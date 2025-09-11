import asyncio
import unittest
from mcp import ClientSession, types
from mcp.shared.context import RequestContext
from mcp.shared.message import ClientMessageMetadata
from pydantic import BaseModel, Field
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableMCP, ToolContext

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


class BookingPreferences(BaseModel):
    """Schema for collecting user preferences."""

    checkAlternative: bool = Field(
        description="Would you like to check another date?"
    )
    alternativeDate: str = Field(
        default="2024-12-26",
        description="Alternative date (YYYY-MM-DD)",
    )


@mcp.tool()
async def book_table(
    date: str,
    time: str,
    party_size: int,
    context: ToolContext,
) -> str:
    result = await context.elicit(
        message=(
            f"No tables available for {party_size} on {date}. "
            "Would you like to try another date?"
        ),
        schema=BookingPreferences,
    )

    if result.action == "accept" and result.data:
        if result.data.checkAlternative:
            return f"[SUCCESS] Booked for {result.data.alternativeDate}"
        return "[CANCELLED] No booking made"
    return "[CANCELLED] Booking cancelled"


# Reboot application that runs everything necessary for `DurableMCP`.
application = Application(servicers=mcp.servicers())

# Mounts the server at the path specified.
application.http.mount(mcp.path, factory=mcp.streamable_http_app_factory)


class TestSomething(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_mcp(self) -> None:
        revision = await self.rbt.up(application)

        elicitation_event = asyncio.Event()

        async def elicitation_callback_before_reboot(
            context: RequestContext[ClientSession, None],
            params: types.ElicitRequestParams,
        ):
            assert "No tables available" in params.message
            elicitation_event.set()
            # Wait until we get cancelled because of the reboot.
            await asyncio.Event().wait()

        last_event_id = None

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
            elicitation_callback=elicitation_callback_before_reboot,
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
                                name="book_table",
                                arguments={
                                    "date": "2024-12-25",
                                    "time": "19:00",
                                    "party_size": 4,
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

            await elicitation_event.wait()

            while last_event_id == None:
                await asyncio.sleep(0.01)

            send_request_task.cancel()
            try:
                await send_request_task
            except:
                pass

        print(f"Rebooting application running at {self.rbt.url()}...")

        await self.rbt.down()
        await self.rbt.up(revision=revision)

        print(f"... application now at {self.rbt.url()}")

        async def elicitation_callback_after_reboot(
            context: RequestContext[ClientSession, None],
            params: types.ElicitRequestParams,
        ):
            assert "Sorry, we got disconnected" in params.message
            assert "No tables available" in params.message
            return types.ElicitResult(
                action="accept",
                content={"checkAlternative": True, "alternativeDate": "2024-12-26"},
            )

        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            # MCP bug: in this case we should specify that the request
            # ID to start with is the _last_ ID that was used so that
            # it is correctly routed on the server.
            next_request_id=session._request_id - 1,
            elicitation_callback=elicitation_callback_after_reboot,
        ) as session:

            assert last_event_id is not None

            result = await session.send_request(
                types.ClientRequest(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name="book_table",
                            arguments={
                                "date": "2024-12-25",
                                "time": "19:00",
                                "party_size": 4,
                            },
                        ),
                    ),
                ),
                types.CallToolResult,
                metadata=ClientMessageMetadata(
                    resumption_token=last_event_id,
                ),
            )

            print(result)


if __name__ == '__main__':
    unittest.main()
