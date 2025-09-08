import asyncio
import functools
import httpx
import inspect
import mcp.server.streamable_http
import pickle
from anyio import create_memory_object_stream
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
)
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from mcp import types
from mcp.server import fastmcp
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    EventId,
    StreamableHTTPServerTransport,
)
from mcp.shared.message import SessionMessage
from rbt.mcp.v1.session_rbt import (
    HandleMessageRequest,
    HandleMessageResponse,
    RunRequest,
    RunResponse,
    Session,
    Stream,
)
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import WorkflowContext, WriterContext
from reboot.aio.external import ExternalContext
from reboot.aio.types import StateRef
from reboot.aio.workflows import at_least_once
from reboot.event_store import (
    DurableEventStore,
    StreamServicer,
    get_event_id,
    replay,
)
from reboot.std.collections.v1 import sorted_map
from rebootdev.aio.headers import CONSENSUS_ID_HEADER, STATE_REF_HEADER
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send
from types import MethodType
from typing import Callable, Protocol, cast
from uuid import uuid4, uuid5


class ToolContextProtocol(Protocol):

    _event_aliases: set[str]

    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """Report progress for the current operation.

        Args:
            progress: Current progress value e.g. 24
            total: Optional total value e.g. 100
            message: Optional message e.g. Starting render...
        """
        ...


class ToolContext(WorkflowContext, ToolContextProtocol):

    pass


_context: ContextVar[WorkflowContext | None] = ContextVar(
    "`WorkflowContext` of current message being handled",
    default=None,
)


class DurableMCP(fastmcp.FastMCP):

    _instances: dict[str, "DurableMCP"] = {}

    def __init__(self, *, path: str):
        super().__init__()
        self._path = path
        self._instances[path] = self

    @property
    def path(self):
        return self._path

    def servicers(self):
        return [SessionServicer, StreamServicer] + sorted_map.servicers()

    def add_tool(
        self,
        fn: types.AnyFunction,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: types.ToolAnnotations | None = None,
        structured_output: bool | None = None,
    ) -> None:
        """Overrides `FastMCP.add_tool`."""
        signature = inspect.signature(fn)

        wrapper_parameters = [
            # Always include the `context` parameter so we can access
            # session specific things.
            inspect.Parameter(
                "ctx",
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=fastmcp.Context,
            )
        ]

        context_parameter_names = []

        for parameter_name, parameter in signature.parameters.items():
            annotation = parameter.annotation
            if (
                isinstance(annotation, type) and
                issubclass(annotation, fastmcp.Context)
            ):
                raise TypeError(
                    "`DurableMCP` only injects `ToolContext` not `Context`")
            if (
                isinstance(annotation, type) and
                issubclass(annotation, ToolContext)
            ):
                context_parameter_names.append(parameter_name)
            else:
                wrapper_parameters.append(parameter)

        wrapper_signature = signature.replace(parameters=wrapper_parameters)

        async def wrapper(ctx: fastmcp.Context, *args, **kwargs):

            context: WorkflowContext | None = _context.get()

            assert context is not None

            # To account for the lack of "intersection" types in
            # Python (which is actively being worked on), we instead
            # create a new dynamic `ToolContext` instance that
            # inherits from the instance of `WorkflowContext` that we
            # already have.
            context.__class__ = ToolContext

            context = cast(ToolContext, context)

            # Now we add the `ToolContextProtocol` properties.
            context._event_aliases = set()

            async def report_progress(
                self,
                progress: float,
                total: float | None = None,
                message: str | None = None,
            ) -> None:
                progress_token = (
                    ctx.request_context.meta.progressToken
                    if ctx.request_context.meta else None
                )

                if progress_token is None:
                    return

                # TODO: consider tracking all reported progress and if
                # it has gone "backwards" provide a nice error so
                # developers can fix their bug (presumably they don't
                # ever want the progress to go "backwards").

                event_alias = (
                    f"report_progress(progress={progress}, total={total}, "
                    f"message={message})"
                )

                if event_alias in self._event_aliases:
                    raise TypeError(
                        f"Looks like you're calling `report_progress()` "
                        "more than once with the same arguments"
                    )

                self._event_aliases.add(event_alias)

                assert context is not None

                workflow_id = context.workflow_id

                assert workflow_id is not None

                # Generate a unique but deterministic ID for this
                # event based on the alias and this workflow (which is
                # unique per request).
                event_id = uuid5(workflow_id, event_alias).hex

                await ctx.session.send_notification(
                    types.ServerNotification(
                        types.ProgressNotification(
                            # TODO: figure out why `mypy` requires
                            # passing `method` which has a default.
                            method="notifications/progress",
                            params=types.ProgressNotificationParams(
                                progressToken=progress_token,
                                progress=progress,
                                total=total,
                                message=message,
                                _meta=types.NotificationParams.Meta(
                                    rebootEventId=str(event_id),
                                ),
                            ),
                        ),
                    ),
                    related_request_id=ctx.request_id,
                )

            context.report_progress = MethodType(report_progress, context)  # type: ignore[method-assign]

            for context_parameter_name in context_parameter_names:
                kwargs[context_parameter_name] = context

            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()

            if fastmcp.tools.base._is_async_callable(fn):
                return await fn(**dict(bound.arguments))

            return fn(**dict(bound.arguments))

        setattr(wrapper, "__signature__", wrapper_signature)
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__

        super().add_tool(
            wrapper,
            name,
            title,
            description,
            annotations,
            structured_output,
        )

    @property
    def streamable_http_app_factory(self):
        return functools.partial(_streamable_http_app, self._path)


def _streamable_http_app(
    path: str,
    external_context_from_request: Callable[[Request], ExternalContext],
):
    return Starlette(
        routes=[
            Route(
                "/{path:path}",
                endpoint=StreamableHTTPASGIApp(
                    path,
                    external_context_from_request,
                ),
            ),
        ],
    )


class StreamableHTTPASGIApp:
    """
    ASGI application for Streamable HTTP server transport.
    """

    def __init__(
        self,
        path: str,
        external_context_from_request: Callable[[Request], ExternalContext],
    ):
        self._path = path
        self._external_context_from_request = external_context_from_request
        self._http_transports: dict[str, StreamableHTTPServerTransport] = {}
        self._connect_tasks: dict[str, asyncio.Task] = {}

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        request = Request(scope, receive)

        if request.headers.get(STATE_REF_HEADER) is None:
            mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

            # If this is a new session, i.e., we don't have an ID,
            # then generate one which we'll use as the session ID.
            mcp_session_id = mcp_session_id or uuid4().hex

            headers = dict(request.headers)
            headers[STATE_REF_HEADER] = f"rbt.mcp.v1.Session:{mcp_session_id}"

            # Need to delete consensus ID header so that we'll
            # properly get routed.
            del headers[CONSENSUS_ID_HEADER]

            response: StreamingResponse | Response

            try:
                async with httpx.AsyncClient() as client:
                    # Too simplify we always perform a streaming
                    # request even if the response is not streaming.
                    async with client.stream(
                        request.method,
                        str(request.url),
                        headers=headers,
                        content=await request.body(),
                    ) as upstream:
                        # Create a generator to yield chunks from the
                        # upstream response.
                        async def streamer():
                            async for chunk in upstream.aiter_bytes():
                                yield chunk

                        response = StreamingResponse(
                            content=streamer(),
                            status_code=upstream.status_code,
                            headers=upstream.headers,
                        )
                        await response(scope, receive, send)
                        return
            except Exception as e:
                response = Response(
                    f"Proxy request failed: {e}",
                    status_code=500,
                )
                await response(scope, receive, send)
                return

        # This request has properly been forwarded to the consensus
        # responsible for this session.
        context = self._external_context_from_request(request)

        mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        session_ref = request.headers.get(STATE_REF_HEADER)

        assert session_ref is not None

        session_id = StateRef.from_maybe_readable(session_ref).id

        if mcp_session_id is not None:
            assert mcp_session_id == session_id
            assert mcp_session_id in self._http_transports
            transport = self._http_transports[mcp_session_id]
            await transport.handle_request(scope, receive, send)
            return

        # This is a new session but we need to use the session ID we
        # already generated so all requests for it will get routed to
        # this consensus.
        mcp_session_id = session_id

        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=mcp_session_id,
            is_json_response_enabled=False,
            event_store=DurableEventStore(context),
            security_settings=None,
        )

        session = Session.ref(mcp_session_id)

        self._http_transports[mcp_session_id] = http_transport

        started = asyncio.Event()

        async def connect():

            async with http_transport.connect() as streams:
                started.set()
                read_stream, write_stream = streams

                writer_tasks: list[asyncio.Task] = []

                async def reader():
                    async for message in read_stream:
                        # TODO: we can't pickle `request_context`
                        # which is a `starlette.requests.Request`,
                        # but it looks like it is only for
                        # _advanced_ use cases, not really
                        # documented
                        # (https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md?plain=1#L948),
                        # and if we really want we could probably
                        # grab what is necessary and send if along
                        # in a picklable way.
                        message.metadata.request_context = None  # type: ignore
                        # TODO: ideally we spawn `HandleMessage`
                        # _before_ a 202 Accepted is sent.
                        await session.spawn().HandleMessage(
                            context,
                            path=self._path,
                            message_bytes=pickle.dumps(message),
                        )

                        if not isinstance(message, Exception) and isinstance(
                            message.message.root,
                            types.JSONRPCRequest,
                        ):
                            request_id = message.message.root.id

                            async def writer():
                                async for message, _ in replay(
                                    context,
                                    stream_id=str(request_id),
                                ):
                                    await write_stream.send(message)

                            writer_tasks.append(asyncio.create_task(writer()))

                reader_task = asyncio.create_task(reader())

                try:
                    # Await the reader first, since it will be
                    # finished once the session is finished, then
                    # we can cancel any writers.
                    await reader_task
                finally:
                    reader_task.cancel()
                    for writer_task in writer_tasks:
                        writer_task.cancel()
                    await asyncio.wait(
                        [reader_task] + writer_tasks,
                        return_when=asyncio.ALL_COMPLETED,
                    )

        self._connect_tasks[mcp_session_id] = asyncio.create_task(connect())

        def done(task):
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"Session {mcp_session_id} crashed: {e}")
            finally:
                if http_transport.is_terminated:
                    assert mcp_session_id in self._connect_tasks
                    del self._connect_tasks[mcp_session_id]
                    assert mcp_session_id in self._http_transports
                    del self._http_transports[mcp_session_id]

        self._connect_tasks[mcp_session_id].add_done_callback(done)

        await started.wait()

        await http_transport.handle_request(scope, receive, send)


@dataclass(kw_only=True)
class Streams:
    refs: int
    read_stream: tuple[MemoryObjectSendStream[SessionMessage | Exception],
                       MemoryObjectReceiveStream[SessionMessage | Exception]]
    write_stream: tuple[MemoryObjectSendStream[SessionMessage],
                        MemoryObjectReceiveStream[SessionMessage]]


class SessionServicer(Session.Servicer):

    def __init__(self):
        self._request_streams: dict[types.RequestId, Streams] = {}

    def authorizer(self):
        return allow()

    @contextmanager
    def _get_request_streams(self, request_id: types.RequestId):
        try:
            if request_id not in self._request_streams:
                # Create streams for communicating with MCP server.
                self._request_streams[request_id] = Streams(
                    refs=1,  # Initial reference count.
                    read_stream=create_memory_object_stream[
                        SessionMessage | Exception](),
                    write_stream=create_memory_object_stream[SessionMessage](),
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

        if isinstance(message.message.root, types.JSONRPCRequest):
            print(f"Handling ({type(message).__name__}): {message}")

            request_id = message.message.root.id

            stream = Stream.ref(str(request_id))

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

                    await read_stream_send.send(message)

                    async for write_message in write_stream_receive:
                        print(
                            f"Sending message ({type(write_message).__name__}): "
                            f"{write_message}"
                        )

                        event_id = get_event_id(write_message)

                        await stream.per_workflow(event_id).Put(
                            context,
                            event_id=event_id,
                            message_bytes=pickle.dumps(write_message),
                        )

                        if isinstance(
                            write_message.message.root,
                            types.JSONRPCResponse | types.JSONRPCError,
                        ):
                            break

                await at_least_once(
                    "Send and receive",
                    context,
                    send_and_receive,
                )

                await read_stream_send.aclose()

                await run_task

                print(f"Completed ({type(message).__name__}): {message}")
        else:
            print(f"UNHANDLED MESSAGE ({type(message).__name__}): {message}")

        return HandleMessageResponse()

    async def Run(
        self,
        context: WorkflowContext,
        request: RunRequest,
    ) -> RunResponse:
        path = request.path
        message = pickle.loads(request.message_bytes)

        assert isinstance(message.message.root, types.JSONRPCRequest)

        request_id = message.message.root.id

        with self._get_request_streams(
            request_id,
        ) as (read_stream, write_stream):
            _, read_stream_receive = read_stream
            write_stream_send, _ = write_stream

            async def server_run():
                server = DurableMCP._instances[path]._mcp_server
                _context.set(context)
                try:
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
