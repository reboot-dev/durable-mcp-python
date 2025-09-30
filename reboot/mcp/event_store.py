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
from mcp.types import RequestId
from rbt.mcp.v1.session_rbt import Session
from rbt.mcp.v1.stream_rbt import Stream
from reboot.aio.external import ExternalContext
from reboot.protobuf import as_dict
from uuid import uuid4


def get_event_id(message: SessionMessage) -> EventId:
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


def qualified_stream_id(*, session_id: str, request_id: RequestId) -> str:
    return f"{session_id}/{request_id}"


def qualified_event_id(*, request_id: RequestId, event_id: EventId) -> EventId:
    return f"{request_id}/{event_id}"


class DurableEventStore(EventStore):

    def __init__(self, context: ExternalContext, session_id: str):
        self._context = context
        self._session_id = session_id

    async def store_event(
        self,
        # MCP SDK uses request IDs for the stream ID, which does not
        # work across sessions as most clients use incrementing
        # request IDs for each session. Hence, we call this
        # `request_id` to differentiate it from our `stream_id` which
        # we use to get a `Stream` reference.
        request_id: StreamId,
        message: mcp.types.JSONRPCMessage,
    ) -> EventId:
        event_id = get_event_id(SessionMessage(message=message))
        # Need to qualify event ID to include the request ID which is
        # used to distinguish streams.
        return qualified_event_id(request_id=request_id, event_id=event_id)

    async def replay_events_after(
        self,
        qualified_last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        request_id, last_event_id = qualified_last_event_id.split("/")

        async for message, event_id in replay(
            self._context,
            session_id=self._session_id,
            request_id=request_id,
            last_event_id=last_event_id,
        ):
            await send_callback(
                EventMessage(
                    message.message,
                    # Need to qualify event ID to include the request
                    # ID which is used to distinguish streams.
                    qualified_event_id(
                        request_id=request_id,
                        event_id=event_id,
                    ),
                )
            )

        return request_id


def replace_whole_floats_with_ints(d: dict):
    """
    Iterates through all values in a dictionary, including nested
    values, replacing floats that are whole numbers with their integer
    equivalant.

    This is necessary because according to JSON `1.0` and `1` are
    considered the _same_ value, but Pydantic does not consider `1.0`
    a valid `int` when using strict mode. In our case, protobuf always
    renders the value `1.0` even if it was originally passed `1` and
    thus Pydantic fails. *sigh*
    """
    result: dict = {}

    for key, value in d.items():
        if isinstance(value, float):
            if value == int(value):
                result[key] = int(value)
                continue

        if isinstance(value, dict):
            result[key] = replace_whole_floats_with_ints(value)
            continue

        result[key] = value

    return result


async def replay(
    context: ExternalContext,
    *,
    session_id: str,
    request_id: RequestId,
    last_event_id: EventId | None = None,
) -> tuple[SessionMessage, EventId]:
    stream_id = qualified_stream_id(
        session_id=session_id,
        request_id=request_id,
    )

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
                message = mcp.types.JSONRPCMessage.model_validate(
                    replace_whole_floats_with_ints(as_dict(event.message))
                )

                metadata = None

                if event.HasField("related_request_id"):
                    metadata = ServerMessageMetadata()
                    metadata.related_request_id = event.related_request_id

                yield SessionMessage(message, metadata=metadata), event.id

                if isinstance(
                    message.root,
                    mcp.types.JSONRPCResponse | mcp.types.JSONRPCError,
                ):
                    return

            last_event_id = replay.events[-1].id
            break
