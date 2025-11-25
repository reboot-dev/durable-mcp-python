import unittest
from pydantic import AnyUrl
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect
from reboot.mcp.server import DurableContext, DurableMCP

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.resource("resource://fixed")
def fixed_resource(context: DurableContext) -> str:
    """Fixed URI resource with context (regular resource, not template)."""
    assert context is not None
    return "fixed-resource-data"


@mcp.resource("resource://template/{id}")
def template_resource(id: str, context: DurableContext) -> str:
    """Parameterized URI resource with context (template)."""
    assert context is not None
    return f"template-resource-data-{id}"


# Reboot application that runs everything necessary for `DurableMCP`.
application: Application = mcp.application()


class TestTemplateReading(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_template_list_and_read(self) -> None:
        """Verify that fixed URIs become resources and parameterized URIs become templates."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Check resources/list - should have the fixed URI resource.
            resources_result = await session.list_resources()
            print(f"Resources: {resources_result}")
            assert len(resources_result.resources) == 1
            assert resources_result.resources[0].uri == AnyUrl("resource://fixed")

            # Check resources/templates/list - should have the parameterized resource.
            templates_result = await session.list_resource_templates()
            print(f"Templates: {templates_result}")
            assert len(templates_result.resourceTemplates) == 1
            assert templates_result.resourceTemplates[0].uriTemplate == "resource://template/{id}"

            # Read the fixed resource.
            print("\nReading resource://fixed...")
            read_result = await session.read_resource(AnyUrl("resource://fixed"))
            print(f"Read result (fixed): {read_result}")
            assert len(read_result.contents) == 1
            assert "fixed-resource-data" in read_result.contents[0].text

            # Read the template resource with a parameter.
            print("\nReading resource://template/123...")
            read_result = await session.read_resource(AnyUrl("resource://template/123"))
            print(f"Read result (template): {read_result}")
            assert len(read_result.contents) == 1
            assert "template-resource-data-123" in read_result.contents[0].text


if __name__ == '__main__':
    unittest.main()
