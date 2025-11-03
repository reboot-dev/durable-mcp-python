import anyio
import asyncio
import mcp.types
import pickle
from contextvars import ContextVar
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
)
from contextlib import contextmanager
from dataclasses import dataclass
from log.log import get_logger
from mcp.server.lowlevel.server import Server
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from rbt.mcp.v1.session_rbt import (
    GetRequest,
    GetResponse,
    HandleMessageRequest,
    HandleMessageResponse,
    RunRequest,
    RunResponse,
    Session,
)
from rbt.mcp.v1.stream_rbt import Stream
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WorkflowContext, WriterContext
from reboot.aio.workflows import at_least_once
from reboot.mcp.event_store import (
    get_event_id,
    qualified_stream_id,
    replace_whole_floats_with_ints,
)
from reboot.protobuf import as_dict, from_model
from rebootdev.aio.backoff import Backoff

logger = get_logger(__name__)

# Dictionary from path to MCP server for calling `run()`.
_servers: dict[str, Server] = {}

# Python asyncio context variable for the `WorkflowContext` of the
# current message being handled.
_context: ContextVar[WorkflowContext | None] = ContextVar(
    "`WorkflowContext` of current message being handled",
    default=None,
)


@dataclass(kw_only=True)
class Streams:
    refs: int
    read_stream: tuple[MemoryObjectSendStream[SessionMessage | Exception],
                       MemoryObjectReceiveStream[SessionMessage | Exception]]
    write_stream: tuple[MemoryObjectSendStream[SessionMessage],
                        MemoryObjectReceiveStream[SessionMessage]]


class SessionServicer(Session.Servicer):

    def __init__(self):
        self._request_streams: dict[mcp.types.RequestId, Streams] = {}

        # For requests coming from the server, e.g., elicit, sample,
        # etc, this maps the event ID that we generated to a tuple of
        # the server generated request ID and the "related request ID"
        # for looking up the stream to send the response.
        self._write_request_ids: dict[
            str,
            # (server generated request ID, related request ID)
            tuple[mcp.types.RequestId, mcp.types.RequestId]
        ] = {}

    def authorizer(self):
        return allow()

    @contextmanager
    def _get_request_streams(self, request_id: mcp.types.RequestId):
        # `mcp.types.RequestId` is of type `str | int`, and it seems
        # the mcp SDK sometimes uses a `str` and sometimes uses an
        # `int` for the _same_ request ID, e.g., `1`, so we always
        # need to canonicalize it as a `str`.
        request_id = str(request_id)
        try:
            if request_id not in self._request_streams:
                # Create streams for communicating with MCP server.
                self._request_streams[request_id] = Streams(
                    refs=1,  # Initial reference count.
                    read_stream=anyio.create_memory_object_stream[
                        SessionMessage | Exception](),
                    write_stream=anyio.create_memory_object_stream[
                        SessionMessage](),
                )
            else:
                self._request_streams[request_id].refs += 1

            yield (
                self._request_streams[request_id].read_stream,
                self._request_streams[request_id].write_stream,
            )
        finally:
            self._request_streams[request_id].refs -= 1
            if self._request_streams[request_id].refs == 0:
                # TODO: do we also need to close the streams in order
                # for them to get garbage collected?
                del self._request_streams[request_id]

    async def HandleMessage(
        self,
        context: WorkflowContext,
        request: HandleMessageRequest,
    ) -> HandleMessageResponse:
        message = pickle.loads(request.message_bytes)

        if isinstance(message.message.root, mcp.types.JSONRPCRequest):
            logger.debug(f"Handling ({type(message).__name__}): {message}")

            request_id = message.message.root.id

            stream_id = qualified_stream_id(
                session_id=context.state_id,
                request_id=request_id,
            )

            async def store_stream(state):
                """Inline writer that adds this stream to `Session` state."""
                state.stream_ids.append(stream_id)

            await self.ref().per_workflow(
                "Store stream",
            ).write(context, store_stream)

            stream = Stream.ref(stream_id)

            vscode_stream_id = qualified_stream_id(
                session_id=context.state_id,
                request_id="VSCODE_GET",
            )

            vscode_stream = Stream.ref(vscode_stream_id)

            # Store the initial request on the stream for
            # auditing/inspecting/debugging.
            await stream.per_workflow("Store initial request").put(
                context,
                message=from_model(
                    message.message,
                    by_alias=True,
                    mode="json",
                    exclude_none=True,
                ),
            )

            # Store client info on initialize.
            if (
                isinstance(message.message.root, mcp.types.JSONRPCRequest)
                and message.message.root.method == "initialize"
            ):
                async def store_client_info(state):
                    assert not state.HasField("client_info")
                    client_info = message.message.root.params["clientInfo"]
                    if "name" in client_info:
                        state.client_info.name = client_info["name"]
                    if "title" in client_info:
                        state.client_info.title = client_info["title"]
                    assert "version" in client_info
                    state.client_info.version = client_info["version"]

                await self.ref().per_workflow(
                    "Store client info on initialize",
                ).write(context, store_client_info)

            with self._get_request_streams(
                request_id,
            ) as (read_stream, write_stream):
                read_stream_send, _ = read_stream
                _, write_stream_receive = write_stream

                run_task = await self.ref().spawn().Run(
                    context,
                    path=request.path,
                    message_bytes=request.message_bytes,
                )

                async def send_and_receive():
                    try:
                        await read_stream_send.send(message)
                    except anyio.ClosedResourceError:
                        # Stream is closed, we must be re-executing
                        # this function due to effect validation, just
                        # return.
                        return

                    async for write_message in write_stream_receive:
                        logger.debug(
                            f"Sending message ({type(write_message).__name__}): "
                            f"{write_message}"
                        )

                        event_id = get_event_id(write_message)

                        related_request_id = (
                            write_message.metadata.related_request_id
                            if write_message.metadata is not None else None
                        )

                        # If this is a request, we need to grab the
                        # request ID and map it to something else that
                        # we actually send so that we can reconnect it
                        # to the response once we receive that.
                        if isinstance(write_message.message.root, mcp.types.JSONRPCRequest):
                            write_request_id = write_message.message.root.id
                            write_message.message.root.id = event_id
                            assert related_request_id is not None
                            self._write_request_ids[event_id] = (
                                write_request_id, related_request_id
                            )

                        assert (
                            related_request_id is None or
                            type(related_request_id) == str
                        )

                        # Store the _outgoing_ message, i.e., event,
                        # on the stream.
                        await stream.per_workflow(event_id).put(
                            context,
                            message=from_model(
                                write_message.message,
                                by_alias=True,
                                mode="json",
                                exclude_none=True,
                            ),
                            event_id=event_id,
                            related_request_id=related_request_id,
                        )

                        async def check_is_vscode():
                            backoff = Backoff(max_backoff_seconds=2)
                            while True:
                                response = await self.ref().always().get(
                                    context
                                )
                                if not response.HasField("client_info"):
                                    await backoff()
                                    continue
                                # Technically `name` is required but
                                # at least the MCP SDK doesn't
                                # validate it via Pydantic, but Visual
                                # Studio Code always seems to include
                                # its name, so if we don't have a name
                                # it is not Visual Studio Code.
                                if response.client_info.HasField("name"):
                                    return response.client_info.name == "Visual Studio Code"
                                return False

                        is_vscode = await at_least_once(
                            "Check if client is Visual Studio Code",
                            context,
                            check_is_vscode,
                            type=bool,
                        )

                        if is_vscode:
                            # For Visual Studio Code, also store the
                            # _outgoing_ message, i.e., event, on the
                            # aggregated stream.
                            await vscode_stream.per_workflow(event_id).put(
                                context,
                                message=from_model(
                                    write_message.message,
                                    by_alias=True,
                                    mode="json",
                                    exclude_none=True,
                                ),
                                event_id=event_id,
                            )

                        if isinstance(
                            write_message.message.root,
                            mcp.types.JSONRPCResponse | mcp.types.JSONRPCError,
                        ):
                            await read_stream_send.aclose()
                            break

                await at_least_once(
                    "Send and receive",
                    context,
                    send_and_receive,
                )

                # NOTE: need to await `run_task` within the
                # `self._get_request_streams()` context manager so
                # that we continue to use the same streams between
                # this function and `Run()`.
                await run_task

                logger.debug(f"Completed ({type(message).__name__}): {message}")

                return HandleMessageResponse()

        elif isinstance(message.message.root, mcp.types.JSONRPCNotification):
            # Ignore "notifications/initialized" as we run the
            # servers with `stateless=True` here so they are
            # always initialized.
            if message.message.root.method == "notifications/initialized":
                return HandleMessageResponse()

            # TODO: handle notification or route to the
            # appropriate request stream if relevant.

        elif isinstance(message.message.root, mcp.types.JSONRPCResponse):
            # We override outgoing request IDs with our own event IDs
            # to make them unique and routable, and they are always
            # strings so we ensure that here.
            event_id = str(message.message.root.id)

            # Need to put the request ID that the MCP SDK used back on
            # the message so it'll be handled/routed correctly, if it
            # exists, which it might not if we've rebooted.
            if event_id in self._write_request_ids:
                request_id, related_request_id = self._write_request_ids[event_id]

                message.message.root.id = request_id

                stream_id = qualified_stream_id(
                    session_id=context.state_id,
                    request_id=related_request_id,
                )

                stream = Stream.ref(stream_id)

                # We also store the response for
                # auditing/inspecting/debugging.
                await stream.per_workflow(
                    f"Store response for request with event ID '{event_id}'",
                ).put(
                    context,
                    message=from_model(
                        message.message,
                        by_alias=True,
                        mode="json",
                        exclude_none=True,
                    ),
                )

                with self._get_request_streams(
                    related_request_id,
                ) as (read_stream, _):
                    read_stream_send, _ = read_stream

                    await read_stream_send.send(message)
            else:
                logger.info(f"Ignoring client response as server must have rebooted")

            return HandleMessageResponse()

        logger.warning(f"UNIMPLEMENTED ({type(message).__name__}): {message}")

        return HandleMessageResponse()

    async def Run(
        self,
        context: WorkflowContext,
        request: RunRequest,
    ) -> RunResponse:
        path = request.path
        message = pickle.loads(request.message_bytes)

        assert isinstance(message.message.root, mcp.types.JSONRPCRequest)

        request_id = message.message.root.id

        with self._get_request_streams(
            request_id,
        ) as (read_stream, write_stream):
            _, read_stream_receive = read_stream
            write_stream_send, _ = write_stream

            async def cancel_outstanding_requests():
                """
                Helper that sends cancellations after a reboot for
                any outstanding server sent requests, e.g.,
                elicitations, since we'll be retrying them.
                """
                stream_id = qualified_stream_id(
                    session_id=context.state_id,
                    request_id=request_id,
                )

                stream = Stream.ref(stream_id)

                # Need to _always_ get the messages because they
                # likely will have changed since we rebooted!
                response = await stream.always().messages(context)

                outstanding_event_ids: set[str] = set()

                for message in response.messages:
                    json_rpc_message = mcp.types.JSONRPCMessage.model_validate(
                        replace_whole_floats_with_ints(as_dict(message.message))
                    )

                    # Add an outstanding event ID for requests.
                    if (
                        isinstance(json_rpc_message.root, mcp.types.JSONRPCRequest) and
                        # Need to distinguish a request we got from the
                        # client from one sent by the server, the latter
                        # of which will always have an `event_id`.
                        message.HasField("event_id")
                    ):
                        assert message.event_id not in self._write_request_ids
                        outstanding_event_ids.add(message.event_id)

                    # Discard any outstanding event ID for requests that
                    # have a response.
                    if isinstance(json_rpc_message.root, mcp.types.JSONRPCResponse):
                        outstanding_event_ids.discard(str(json_rpc_message.root.id))

                for event_id in outstanding_event_ids:
                    await write_stream_send.send(
                        SessionMessage(
                            message=mcp.types.JSONRPCMessage(
                                mcp.types.JSONRPCNotification(
                                    jsonrpc="2.0",
                                    **mcp.types.ServerNotification(
                                        mcp.types.CancelledNotification(
                                            # TODO: figure out why `mypy`
                                            # requires passing `method`
                                            # which has a default.
                                            method="notifications/cancelled",
                                            params=mcp.types.CancelledNotificationParams(
                                                reason="Server rebooted",
                                                requestId=event_id,
                                                _meta=mcp.types.NotificationParams.Meta(
                                                    rebootEventId=f"cancelled-{event_id}",
                                                ),
                                            ),
                                        ),
                                    ).model_dump(
                                        by_alias=True,
                                        mode="json",
                                        exclude_none=True,
                                    ),
                                ),
                            ),
                            metadata=ServerMessageMetadata(
                                related_request_id=str(request_id),
                            ),
                        )
                    )

            async def server_run():
                assert _context.get() is None
                _context.set(context)
                try:
                    global _servers
                    server = _servers[path]
                    await server.run(
                        read_stream_receive,
                        write_stream_send,
                        server.create_initialization_options(),
                        # Set to False to handle "unknown request ID" errors
                        # gracefully after reboot. MCP SDK v1.19.0's
                        # `_handle_message()` has `case Exception():` that
                        # raises when this is True. v1.13.1 did not raise.
                        # Exceptions are still logged and sent to clients as
                        # error notifications.
                        raise_exceptions=False,
                        # Since we might resume we set `stateless=True`
                        # because we don't want the server to need to do
                        # initialization, but it will happily do it when the
                        # client does it on connect.
                        stateless=True,
                    )
                except:
                    import traceback
                    traceback.print_exc()
                    raise
                finally:
                    _context.set(None)

            # Run this as an asyncio task because it blocks when
            # calling `write_stream_send.send()`.
            cancel_outstanding_requests_task = asyncio.create_task(
                cancel_outstanding_requests()
            )

            try:
                await at_least_once("Server run", context, server_run)
            finally:
                cancel_outstanding_requests_task.cancel()
                try:
                    await cancel_outstanding_requests_task
                except:
                    pass

            return RunResponse()

    async def get(
        self,
        context: ReaderContext,
        request: GetRequest,
    ) -> GetResponse:
        return GetResponse(
            stream_ids=self.state.stream_ids,
            client_info=(
                self.state.client_info
                if self.state.HasField("client_info") else None
            ),
        )
