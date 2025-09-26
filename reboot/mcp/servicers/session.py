import anyio
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
from mcp.shared.message import SessionMessage
from rbt.mcp.v1.session_rbt import (
    HandleMessageRequest,
    HandleMessageResponse,
    RunRequest,
    RunResponse,
    Session,
)
from rbt.mcp.v1.stream_rbt import Stream
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import WorkflowContext, WriterContext
from reboot.aio.workflows import at_least_once
from reboot.mcp.event_store import get_event_id, qualified_stream_id

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

            stream = Stream.ref(stream_id)

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

                        # If this is a request, we need to grab the
                        # request ID and map it to something else that
                        # we actually send so that we can reconnect it
                        # here.
                        if isinstance(write_message.message.root, mcp.types.JSONRPCRequest):
                            write_request_id = write_message.message.root.id
                            write_message.message.root.id = event_id
                            related_request_id = write_message.metadata.related_request_id
                            assert related_request_id is not None
                            self._write_request_ids[event_id] = (
                                write_request_id, related_request_id
                            )

                        await stream.per_workflow(event_id).Put(
                            context,
                            request_id=str(request_id),
                            event_id=event_id,
                            message_bytes=pickle.dumps(write_message),
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

            request_id, related_request_id = self._write_request_ids[event_id]

            message.message.root.id = request_id

            with self._get_request_streams(
                related_request_id,
            ) as (read_stream, _):
                read_stream_send, _ = read_stream

                await read_stream_send.send(message)

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
                        raise_exceptions=True,
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

            await at_least_once("Server run", context, server_run)

            return RunResponse()
