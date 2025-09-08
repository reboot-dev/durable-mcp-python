import mcp
import mcp.server.streamable_http
import pickle
import rbt.mcp.v1.session_rbt as session_rbt
from google.protobuf.empty_pb2 import Empty
from mcp.server.streamable_http import (
    GET_STREAM_KEY,
    EventCallback,
    EventId,
    EventMessage,
    StreamId,
)
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from rbt.mcp.v1.session_rbt import (
    Event,
    PutRequest,
    PutResponse,
    ReplayRequest,
    ReplayResponse,
    Stream,
)
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WriterContext
from reboot.aio.external import ExternalContext
from uuid import uuid4


def get_stream_id(message: SessionMessage) -> StreamId:
    # Try and extract the ID of the original request.
    request_id = None

    if isinstance(
        message.message.root,
        mcp.types.JSONRPCResponse | mcp.types.JSONRPCError,
    ):
        request_id = str(message.message.root.id)
    elif (
        message.metadata is not None and
        isinstance(message.metadata, ServerMessageMetadata) and
        message.metadata.related_request_id is not None
    ):
        request_id = str(message.metadata.related_request_id)

    stream_id = request_id if request_id is not None else GET_STREAM_KEY

    return stream_id


def get_event_id(message: SessionMessage) -> EventId:
    if isinstance(message.message.root, mcp.types.JSONRPCRequest):
        return str(message.message.root.id)

    if isinstance(message.message.root, mcp.types.JSONRPCNotification):
        if (
            message.message.root.params is not None and
            "_meta" in message.message.root.params and
            "rebootEventId" in message.message.root.params["_meta"]
        ):
            return message.message.root.params["_meta"]["rebootEventId"]

        # TODO: remove this once we've properly added a reboot event
        # ID for all notifications and then assert as much here.
        return uuid4().hex

    assert isinstance(
        message.message.root,
        mcp.types.JSONRPCResponse | mcp.types.JSONRPCError,
    )

    return str(message.message.root.id)


def qualified_event_id(stream_id: StreamId, event_id: EventId) -> EventId:
    return f"{stream_id}/{event_id}"


def stream_id_from_qualified_event_id(event_id: EventId) -> StreamId:
    index = event_id.rfind("/")
    assert index != -1
    return event_id[:index]


class DurableEventStore(mcp.server.streamable_http.EventStore):

    def __init__(self, context: ExternalContext):
        self._context = context

    async def store_event(
        self,
        stream_id: StreamId,
        message: mcp.types.JSONRPCMessage,
    ) -> EventId:
        event_id = get_event_id(SessionMessage(message=message))
        assert event_id is not None
        return qualified_event_id(stream_id, event_id)

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        stream_id = stream_id_from_qualified_event_id(last_event_id)

        async for message, event_id in replay(
            self._context,
            stream_id=stream_id,
            last_event_id=last_event_id,
        ):
            await send_callback(EventMessage(message.message, event_id))

        return stream_id


async def replay(
    context: ExternalContext,
    *,
    stream_id: StreamId,
    last_event_id: EventId | None = None,
):
    stream = Stream.ref(stream_id)

    # Ensure the stream has been created.
    await stream.Create(context)

    # TODO: fix `.reactively()` so we don't need the `while True`.
    while True:
        async for replay in stream.reactively().Replay(
            context,
            last_event_id=last_event_id,
        ):
            if len(replay.events) == 0:
                continue

            for event in replay.events:
                message = pickle.loads(event.message_bytes)
                yield message, event.id
                if isinstance(
                    message.message.root,
                    mcp.types.JSONRPCResponse | mcp.types.JSONRPCError,
                ):
                    return

            last_event_id = replay.events[-1].id
            break
                                    

class StreamServicer(session_rbt.Stream.Servicer):

    def authorizer(self):
        return allow()

    async def Create(
        self,
        context: WriterContext,
        request: Empty,
    ) -> Empty:
        return Empty()

    async def Put(
        self,
        context: WriterContext,
        request: PutRequest,
    ) -> PutResponse:
        self.state.events.append(
            Event(
                id=qualified_event_id(context.state_id, request.event_id),
                message_bytes=request.message_bytes,
            )
        )
        return PutResponse()

    async def Replay(
        self,
        context: ReaderContext,
        request: ReplayRequest,
    ) -> ReplayResponse:
        if not request.HasField("last_event_id"):
            return ReplayResponse(events=self.state.events)

        for i, event in enumerate(self.state.events):
            if event.id == request.last_event_id:
                return ReplayResponse(events=self.state.events[i+1:])

        return ReplayResponse()
