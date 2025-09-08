import mcp.types
import pickle
from contextvars import ContextVar
from anyio import create_memory_object_stream
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
)
from contextlib import contextmanager
from dataclasses import dataclass
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
from reboot.mcp.event_store import get_event_id

# Global of all of the MCP servers for calling `run()`.
_mcp_servers: dict[str, Server] = {}

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

    def authorizer(self):
        return allow()

    @contextmanager
    def _get_request_streams(self, request_id: mcp.types.RequestId):
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

        if isinstance(message.message.root, mcp.types.JSONRPCRequest):
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
                            mcp.types.JSONRPCResponse | mcp.types.JSONRPCError,
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

        assert isinstance(message.message.root, mcp.types.JSONRPCRequest)

        request_id = message.message.root.id

        with self._get_request_streams(
            request_id,
        ) as (read_stream, write_stream):
            _, read_stream_receive = read_stream
            write_stream_send, _ = write_stream

            async def server_run():
                global _mcp_servers
                server = _mcp_servers[path]
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
