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


@mcp.resource("config://settings")
def get_settings() -> str:
    """Get application settings."""
    return """{
  "theme": "dark",
  "language": "en",
  "debug": false
}"""


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

        session_id = None
        protocol_version = None

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, get_session_id):
            result = await session.initialize()
            assert isinstance(result, types.InitializeResult)
            session_id = get_session_id()
            protocol_version = result.protocolVersion

            result = await session.list_resources()
            print(result)

        print(f"Rebooting application running at {self.rbt.url()}...")

        await self.rbt.down()
        await self.rbt.up(revision=revision)

        print(f"... application now at {self.rbt.url()}")

        assert session_id is not None
        assert protocol_version is not None

        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            # MCP bug: need to start using the "next" request ID in
            # the session as required by the spec:
            # modelcontextprotocol.io/specification/2025-06-18/basic#requests
            next_request_id=session._request_id,
        ) as session:
            result = await session.read_resource(AnyUrl("config://settings"))
            print(result)


if __name__ == '__main__':
    unittest.main()
