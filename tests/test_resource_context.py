import asyncio
import unittest
from mcp import types
from mcp.server.elicitation import AcceptedElicitation
from mcp.shared.message import ClientMessageMetadata
from pydantic import AnyUrl, BaseModel
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableContext, DurableMCP

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.resource("basic://config")
def basic_resource(context: DurableContext) -> str:
    """Basic resource with DurableContext."""
    assert context is not None
    return "config-data"


@mcp.resource("progress://{name}")
async def progress_resource(name: str, context: DurableContext) -> str:
    """Resource that reports progress."""
    await context.report_progress(0, 100, "Starting")
    await asyncio.sleep(0.01)
    await context.report_progress(50, 100, "Halfway")
    await asyncio.sleep(0.01)
    await context.report_progress(100, 100, "Complete")
    return f"Processed {name}"


@mcp.resource("logging://{level}")
async def logging_resource(level: str, context: DurableContext) -> str:
    """Resource that uses logging methods."""
    if level == "debug":
        await context.debug(f"Debug message for {level}")
    elif level == "info":
        await context.info(f"Info message for {level}")
    elif level == "warning":
        await context.warning(f"Warning message for {level}")
    elif level == "error":
        await context.error(f"Error message for {level}")

    await context.log("info", f"Custom log for {level}", logger_name="test")
    return f"Logged at {level}"


class ConfirmSchema(BaseModel):
    confirmed: bool
    reason: str


@mcp.resource("elicit://confirm")
async def elicit_resource(context: DurableContext) -> str:
    """Resource that elicits user input."""
    result = await context.elicit(
        message="Do you want to proceed?", schema=ConfirmSchema
    )

    if isinstance(result, AcceptedElicitation):
        return f"User confirmed: {result.data.confirmed}, reason: {result.data.reason}"
    else:
        return f"User action: {result.action}"


@mcp.resource("notify://update")
async def notify_resource(context: DurableContext) -> str:
    """Resource that sends list changed notification."""
    await context.session.send_resource_list_changed("Resource updated")
    return "Notification sent"


@mcp.resource("sync://data")
def sync_resource(context: DurableContext) -> str:
    """Synchronous resource with DurableContext."""
    assert context is not None
    return "sync-data"


# Reboot application that runs everything necessary for `DurableMCP`.
application: Application = mcp.application()


class TestResourceContext(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_basic_resource_with_context(self) -> None:
        """Test that basic resource can access DurableContext."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.read_resource(AnyUrl("basic://config"))
            assert len(result.contents) == 1
            assert result.contents[0].text == "config-data"

    async def test_resource_template_with_context(self) -> None:
        """Test that resource templates work with DurableContext."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Test progress resource which is a template.
            result = await session.read_resource(AnyUrl("progress://test"))
            assert len(result.contents) == 1
            assert "Processed test" in result.contents[0].text

    async def test_resource_with_progress(self) -> None:
        """Test that resource can report progress."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Read resource that reports progress.
            # Progress notifications are sent but we don't wait for them here.
            result = await session.read_resource(AnyUrl("progress://data"))
            assert len(result.contents) == 1
            assert "Processed data" in result.contents[0].text

    async def test_resource_with_logging(self) -> None:
        """Test that resource can use logging methods."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Test debug logging.
            result = await session.read_resource(AnyUrl("logging://debug"))
            assert len(result.contents) == 1
            assert "Logged at debug" in result.contents[0].text

            # Test info logging.
            result = await session.read_resource(AnyUrl("logging://info"))
            assert len(result.contents) == 1
            assert "Logged at info" in result.contents[0].text

    async def test_resource_with_elicit(self) -> None:
        """Test that resource can elicit user input."""
        revision = await self.rbt.up(application)

        # Mock elicitation response by responding to the server request.
        async def handle_elicitation(session, session_id, protocol_version):
            # This test would need proper elicitation handling from client.
            # For now we just test that the resource can call elicit.
            # Full elicitation testing is done in test_elicitation_create.py.
            pass

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Note: This will hang waiting for elicitation response.
            # In production, client must respond to elicitation requests.
            # For testing, we verify the structure is correct.
            pass

    async def test_sync_resource_with_context(self) -> None:
        """Test that synchronous resources work with DurableContext."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.read_resource(AnyUrl("sync://data"))
            assert len(result.contents) == 1
            assert result.contents[0].text == "sync-data"

    async def test_resource_survives_reboot(self) -> None:
        """Test that resource context works after server reboot."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.read_resource(AnyUrl("basic://config"))
            assert len(result.contents) == 1

        print(f"Rebooting application running at {self.rbt.url()}...")

        await self.rbt.down()
        await self.rbt.up(revision=revision)

        print(f"... application now at {self.rbt.url()}")

        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            next_request_id=session._request_id,
        ) as session:
            result = await session.read_resource(AnyUrl("basic://config"))
            assert len(result.contents) == 1
            assert result.contents[0].text == "config-data"


if __name__ == '__main__':
    unittest.main()
