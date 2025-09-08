from google.protobuf.empty_pb2 import Empty
from rbt.mcp.v1.stream_rbt import (
    Event,
    PutRequest,
    PutResponse,
    ReplayRequest,
    ReplayResponse,
    Stream,
)
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WriterContext
from reboot.mcp.event_store import qualified_event_id


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
