import asyncio
import unittest
from mcp import types
from mcp.shared.message import ClientMessageMetadata
from mcp.shared.session import RequestResponder
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.aio.workflows import at_most_once
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableContext, DurableMCP
from reboot.std.collections.v1.sorted_map import SortedMap

LOGGING_MESSAGE = "Completed side-effect _idempotently_!"

finish_event = asyncio.Event()

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def add(a: int, b: int, context: DurableContext) -> int:
    try:

        async def do_side_effect() -> int:
            """
            Pretend that we are doing a side-effect that we can only
            try to do once because it is not able to be performed
            idempotently, hence using `at_most_once`.
            """
            return a + b

        # NOTE: if we reboot, e.g., due to a hardware failure, within
        # `do_side_effect()` then `at_most_once` will forever raise with
        # `AtMostOnceFailedBeforeCompleting` and you will need to handle
        # appropriately.
        print("Calling at_most_once for side-effect...")
        result = await at_most_once(
            "Do side-effect",
            context,
            do_side_effect,
            type=int,
        )
        print("Side-effect completed.")

        await context.info(LOGGING_MESSAGE)

        return result
    except BaseException as e:
        print(f"Error in add tool: {e}")
        raise


# Reboot application that runs everything necessary for `DurableMCP`.
application: Application = mcp.application()


class TestSomething(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_mcp(self) -> None:
        revision = await self.rbt.up(application)

        received_message_event = asyncio.Event()

        async def message_handler(
            message: RequestResponder[types.ServerRequest, types.ClientResult]
            | types.ServerNotification | Exception,
        ) -> None:
            if isinstance(message, types.ServerNotification):
                if isinstance(message.root, types.LoggingMessageNotification):
                    if message.root.params.data == LOGGING_MESSAGE:
                        received_message_event.set()

        last_event_id = None

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
            message_handler=message_handler,
        ) as (session, session_id, protocol_version):

            async def on_resumption_token_update(token: str) -> None:
                nonlocal last_event_id
                last_event_id = token

            send_request_task = asyncio.create_task(
                session.send_request(
                    types.ClientRequest(
                        types.CallToolRequest(
                            method="tools/call",
                            params=types.CallToolRequestParams(
                                name="add",
                                arguments={
                                    "a": 5,
                                    "b": 3
                                },
                            ),
                        ),
                    ),
                    types.CallToolResult,
                    metadata=ClientMessageMetadata(
                        on_resumption_token_update=on_resumption_token_update,
                    ),
                )
            )

            await received_message_event.wait()

            while last_event_id == None:
                await asyncio.sleep(0.01)

            try:
                await send_request_task
            except BaseException as e:
                print(f"Error occurred while sending request: {e}")


if __name__ == '__main__':
    unittest.main()
