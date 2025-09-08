import asyncio
import unittest
from mcp import types
from mcp.shared.message import ClientMessageMetadata
from mcp.shared.session import RequestResponder
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp import DurableMCP, ToolContext
from reboot.std.collections.v1.sorted_map import SortedMap
from tests.client import connect, resume

report_progress_event = asyncio.Event()
resume_event = asyncio.Event()

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def add(a: int, b: int, context: ToolContext) -> int:
    """Add two numbers and also store result in `SortedMap`."""
    # `ToolContext` can be used for making Reboot specific calls, can
    # also use `at_least_once`, `at_most_once`, `until`, etc!
    await SortedMap.ref("adds").Insert(
        context,
        entries={f"{a} + {b}": f"{a + b}".encode()},
    )
    await context.report_progress(progress=0.5, total=1.0)
    await resume_event.wait()
    return a + b


@mcp.tool()
async def set_resume() -> None:
    resume_event.set()
    return None


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
        revision = await self.rbt.up(application, local_envoy=True)

        async def progress_callback(
            progress: float,
            total: float | None,
            message: str | None,
        ) -> None:
            assert total is not None
            percentage = (progress / total) * 100
            print(f"Progress: {progress}/{total} ({percentage:.1f}%)")
            report_progress_event.set()

        session_id = None
        protocol_version = None
        last_event_id = None

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, get_session_id):
            result = await session.initialize()
            assert isinstance(result, types.InitializeResult)
            session_id = get_session_id()
            protocol_version = result.protocolVersion

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

            await report_progress_event.wait()

            while last_event_id == None:
                await asyncio.sleep(0.01)

            send_request_task.cancel()
            try:
                await send_request_task
            except:
                pass

        assert session_id is not None
        assert protocol_version is not None

        async with resume(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            # MCP bug: need to start using the "next" request ID in
            # the session as required by the spec:
            # modelcontextprotocol.io/specification/2025-06-18/basic#requests
            next_request_id=session._request_id,
        ) as session:

            await session.send_request(
                types.ClientRequest(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name="set_resume",
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
                # TODO: figure out why `mypy` fails here.
                types.CallToolResult,  # type: ignore[arg-type]
                metadata=ClientMessageMetadata(
                    resumption_token=last_event_id,
                ),
            )

            print(result)

            context = self.rbt.create_external_context(
                name=self.id(),
                app_internal=True,
            )

            response = await SortedMap.ref("adds").Range(context, limit=2)
            print(response)


if __name__ == '__main__':
    unittest.main()
