import asyncio
import unittest
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp import DurableMCP, ToolContext
from reboot.std.collections.v1.sorted_map import SortedMap

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def add(a: int, b: int, context: ToolContext) -> int:
    """Add two numbers and also store result in `SortedMap`."""
    # `ToolContext` can be used for making Reboot specific calls, can
    # also use `at_least_once`, `at_most_once`, `until`, etc!
    await context.report_progress(progress=0.5, total=1.0)
    await SortedMap.ref("adds").Insert(
        context,
        entries={f"{a} + {b}": f"{a + b}".encode()},
    )
    return a + b


# Reboot application that runs everything necessary for `DurableMCP`.
application = Application(servicers=mcp.servicers())

# Mounts the server at the path specified.
application.http.mount(mcp.path, mcp.streamable_http_app())  # type: ignore


class TestSomething(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_mcp(self) -> None:
        await self.rbt.up(application, local_envoy=True)

        async def progress_callback(
            progress: float,
            total: float | None,
            message: str | None,
        ) -> None:
            assert total is not None
            percentage = (progress / total) * 100
            print(f"Progress: {progress}/{total} ({percentage:.1f}%)")

        async with streamablehttp_client(self.rbt.url() + "/mcp") as (
            read_stream,
            write_stream,
            _,
        ):
            # Create a session using the client streams.
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the connection.
                await session.initialize()

                results = await asyncio.gather(
                    session.call_tool(
                        "add",
                        arguments={
                            "a": 5,
                            "b": 3
                        },
                        progress_callback=progress_callback,
                    ),
                    session.call_tool(
                        "add",
                        arguments={
                            "a": 5,
                            "b": 4
                        },
                        progress_callback=progress_callback,
                    ),
                )

                for result in results:
                    result_unstructured = result.content[0]
                    if isinstance(result_unstructured, types.TextContent):
                        print(f"Tool result: {result_unstructured.text}")
                    result_structured = result.structuredContent
                    print(f"Structured tool result: {result_structured}")

        context = self.rbt.create_external_context(
            name=self.id(),
            app_internal=True,
        )

        response = await SortedMap.ref("adds").Range(context, limit=2)
        print(response)


if __name__ == '__main__':
    unittest.main()
