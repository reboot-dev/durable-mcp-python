import mcp.types
import pickle
from mcp.server.streamable_http import (
    GET_STREAM_KEY,
    EventCallback,
    EventId,
    EventMessage,
    StreamId,
)
from mcp.server.streamable_http import EventStore
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from rbt.mcp.v1.stream_rbt import Stream
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
    try:
        if isinstance(
            message.message.root,
            mcp.types.JSONRPCRequest | mcp.types.JSONRPCNotification,
        ):
            assert (
                message.message.root.params is not None and
                "_meta" in message.message.root.params and
                "rebootEventId" in message.message.root.params["_meta"]
            ), f"Missing event ID for {message.message.root}"

            return message.message.root.params["_meta"]["rebootEventId"]

        assert isinstance(
            message.message.root,
            mcp.types.JSONRPCResponse | mcp.types.JSONRPCError,
        )

        # This is the original request ID which is sufficient for
        # differentiation.
        return str(message.message.root.id)
    except:
        # TODO: remove once we've support for all types of `message`s
        import traceback
        traceback.print_exc()
        raise


def qualified_event_id(stream_id: StreamId, event_id: EventId) -> EventId:
    return f"{stream_id}/{event_id}"


def stream_id_from_qualified_event_id(event_id: EventId) -> StreamId:
    index = event_id.rfind("/")
    assert index != -1
    return event_id[:index]


class DurableEventStore(EventStore):

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
                                    

