import asyncio
import unittest
from mcp import types
from mcp.shared.message import ClientMessageMetadata
from pydantic import AnyUrl
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableContext, DurableMCP
from reboot.std.collections.v1.sorted_map import SortedMap

mcp = DurableMCP(path="/mcp")


@mcp.resource("data://simple")
async def get_simple(context: DurableContext) -> str:
    """Get simple data using DurableContext."""
    # Use SortedMap with DurableContext for durable storage
    data_map = SortedMap.ref("test-simple-data")

    # Insert some test data
    await data_map.insert(
        context,
        entries={"test": b"value"},
    )

    # Read back using range
    response = await data_map.range(context, limit=1)

    if response.entries:
        entry = response.entries[0]
        return f"Retrieved: {entry.value.decode()}"
    else:
        return "No data found"


@mcp.resource("data://{key}")
async def get_data(key: str, context: DurableContext) -> str:
    """Get data from SortedMap using DurableContext."""
    # Use SortedMap with DurableContext for durable storage
    data_map = SortedMap.ref("test-data")

    # Insert some test data
    await data_map.insert(
        context,
        entries={key: f"value-{key}".encode()},
    )

    # Read back using range to get the entry
    response = await data_map.range(context, start_key=key, limit=1)

    if response.entries:
        entry = response.entries[0]
        return f"Retrieved: {entry.value.decode()}"
    else:
        return f"No data found for key: {key}"


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

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Test resource without URI parameters
            result = await session.read_resource(AnyUrl("data://simple"))
            print(result)
            assert result.contents is not None
            assert len(result.contents) > 0
            assert "Retrieved: value" in result.contents[0].text

            # Test resource template with URI parameter
            result = await session.read_resource(AnyUrl("data://test-key"))
            print(result)
            assert result.contents is not None
            assert len(result.contents) > 0
            assert "Retrieved: value-test-key" in result.contents[0].text

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
            # Test that resources work after reconnection
            result = await session.read_resource(AnyUrl("data://reconnect-key"))
            print(result)
            assert result.contents is not None
            assert len(result.contents) > 0
            assert "Retrieved: value-reconnect-key" in result.contents[0].text

            # Verify data was persisted using external context
            context = self.rbt.create_external_context(
                name=self.id(),
                app_internal=True,
            )

            response = await SortedMap.ref("test-data").range(context, limit=10)
            print(response)


if __name__ == '__main__':
    unittest.main()
