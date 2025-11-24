import unittest
from pydantic import AnyUrl
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect
from reboot.mcp.server import DurableContext, DurableMCP

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.resource("template://with-context")
def template_with_context(context: DurableContext) -> str:
    """Test resource registered as template due to context param."""
    assert context is not None
    return "with-context-data"


@mcp.resource("template://no-params")
def template_no_params() -> str:
    """Test resource with no params (should be regular resource, not template)."""
    return "no-params-data"


# Reboot application that runs everything necessary for `DurableMCP`.
application: Application = mcp.application()


class TestTemplateReading(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_template_list_and_read(self) -> None:
        """Verify that resources with context-only params work as templates."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Check resources/list (should be empty).
            resources_result = await session.list_resources()
            print(f"Resources: {resources_result}")

            # Check resources/templates/list (should have our template).
            templates_result = await session.list_resource_templates()
            print(f"Templates: {templates_result}")
            if templates_result.resourceTemplates:
                for template in templates_result.resourceTemplates:
                    print(
                        f"Template: name={template.name}, uriTemplate={template.uriTemplate}"
                    )

            # Try to read the resource with no params (should work as regular resource).
            print("\nReading template://no-params...")
            try:
                read_result = await session.read_resource(
                    AnyUrl("template://no-params")
                )
                print(f"Read result (no-params): {read_result}")
                assert len(read_result.contents) == 1
                assert "no-params-data" in read_result.contents[0].text
            except Exception as e:
                print(f"Failed to read no-params: {e}")

            # Try to read the template with context param.
            print("\nReading template://with-context...")
            try:
                read_result = await session.read_resource(
                    AnyUrl("template://with-context")
                )
                print(f"Read result (with-context): {read_result}")
                assert len(read_result.contents) == 1
                assert "with-context-data" in read_result.contents[0].text
            except Exception as e:
                print(f"Failed to read with-context: {e}")


if __name__ == '__main__':
    unittest.main()
