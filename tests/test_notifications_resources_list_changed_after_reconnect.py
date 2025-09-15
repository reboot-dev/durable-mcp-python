import asyncio
import unittest
from mcp import types
from mcp.shared.message import ClientMessageMetadata
from mcp.shared.session import RequestResponder
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableContext, DurableMCP
from reboot.std.collections.v1.sorted_map import SortedMap

finish_event = asyncio.Event()

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def add(a: int, b: int, context: DurableContext) -> int:
    """Add two numbers and also store result in `SortedMap`."""
    # `ToolContext` can be used for making Reboot specific calls, can
    # also use `at_least_once`, `at_most_once`, `until`, etc!
    await SortedMap.ref("adds").Insert(
        context,
        entries={f"{a} + {b}": f"{a + b}".encode()},
    )
    # Need to also send at least one progress report so we have a
    # last-event-id.
    await context.report_progress(progress=0.5, total=1.0)
    await finish_event.wait()
    await context.session.send_resource_list_changed("For testing")
    return a + b


@mcp.tool()
async def finish() -> None:
    finish_event.set()


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

        async def message_handler_expecting_no_messages(
            message: RequestResponder[
                types.ServerRequest, types.ClientResult
            ] | types.ServerNotification | Exception,
        ) -> None:
            raise RuntimeError(f"Not expecting to get a message, got: {message}")

        report_progress_event = asyncio.Event()

        async def progress_callback(
            progress: float,
            total: float | None,
            message: str | None,
        ) -> None:
            report_progress_event.set()

        last_event_id = None

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
            message_handler=message_handler_expecting_no_messages,
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
                    progress_callback=progress_callback,
                )
            )

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

        received_notification_event = asyncio.Event()

        async def message_handler(
            message: RequestResponder[
                types.ServerRequest, types.ClientResult
            ] | types.ServerNotification | Exception,
        ) -> None:
            if isinstance(message, types.ServerNotification):
                if isinstance(message.root, types.ResourceListChangedNotification):
                    received_notification_event.set()

        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            # MCP bug: need to start using the "next" request ID in
            # the session as required by the spec:
            # modelcontextprotocol.io/specification/2025-06-18/basic#requests
            next_request_id=session._request_id,
            message_handler=message_handler,
        ) as session:

            await session.send_request(
                types.ClientRequest(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name="finish",
                            arguments={},
                        ),
                    ),
                ),
                types.CallToolResult,
            )

            assert last_event_id is not None

            result = await session.send_request(
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
                    resumption_token=last_event_id,
                ),
            )

            print(result)

            await received_notification_event.wait()

            context = self.rbt.create_external_context(
                name=self.id(),
                app_internal=True,
            )

            response = await SortedMap.ref("adds").Range(context, limit=2)
            print(response)


if __name__ == '__main__':
    unittest.main()
