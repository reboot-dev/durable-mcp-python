from google.protobuf.empty_pb2 import Empty
from rbt.mcp.v1.stream_rbt import (
    Event,
    Message,
    MessagesResponse,
    PutRequest,
    PutResponse,
    ReplayRequest,
    ReplayResponse,
    Stream,
)
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WriterContext


class StreamServicer(Stream.Servicer):

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
        self.state.messages.append(
            Message(
                message=request.message,
                event_id=(
                    request.event_id if request.HasField("event_id") else None
                ),
                related_request_id=(
                    request.related_request_id
                    if request.HasField("related_request_id") else None
                ),
            )
        )
        return PutResponse()

    async def Replay(
        self,
        context: ReaderContext,
        request: ReplayRequest,
    ) -> ReplayResponse:
        # TODO: don't construct _all_ the events every time!
        events = [
            Event(
                id=message.event_id,
                message=message.message,
                related_request_id=(
                    message.related_request_id
                    if message.HasField("related_request_id") else None
                ),
            )
            for message in self.state.messages
            if message.HasField("event_id")
        ]

        if not request.HasField("last_event_id"):
            return ReplayResponse(events=events)

        for i, event in enumerate(events):
            if event.id == request.last_event_id:
                return ReplayResponse(events=events[i + 1:])

        return ReplayResponse()

    async def Messages(
        self,
        context: ReaderContext,
        request: Empty,
    ) -> MessagesResponse:
        return MessagesResponse(messages=self.state.messages)
