from google.protobuf.empty_pb2 import Empty
from rbt.mcp.v1.stream_rbt import (
    CreateRequest,
    Event,
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
        request: CreateRequest,
    ) -> Empty:
        if request.HasField("request"):
            self.state.request.CopyFrom(request.request)
        return Empty()

    async def Put(
        self,
        context: WriterContext,
        request: PutRequest,
    ) -> PutResponse:
        self.state.events.append(
            Event(
                id=request.event_id,
                message=request.message,
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
        if not request.HasField("last_event_id"):
            return ReplayResponse(events=self.state.events)

        for i, event in enumerate(self.state.events):
            if event.id == request.last_event_id:
                return ReplayResponse(events=self.state.events[i+1:])

        return ReplayResponse()
