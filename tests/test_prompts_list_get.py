import asyncio
import unittest
from mcp import types
from mcp.shared.message import ClientMessageMetadata
from pydantic import AnyUrl
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableMCP, ToolContext

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    """Generate a greeting prompt"""
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }

    return f"{styles.get(style, styles['friendly'])} for someone named {name}."


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

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            print(await session.list_prompts())

        print(f"Rebooting application running at {self.rbt.url()}...")

        await self.rbt.down()
        await self.rbt.up(revision=revision)

        print(f"... application now at {self.rbt.url()}")

        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            # MCP bug: need to start using the "next" request ID in
            # the session as required by the spec:
            # modelcontextprotocol.io/specification/2025-06-18/basic#requests
            next_request_id=session._request_id,
        ) as session:
            print(
                await session.get_prompt(
                    "greet_user",
                    arguments={
                        "name": "Alice",
                        "style": "friendly",
                    },
                )
            )


if __name__ == '__main__':
    unittest.main()
