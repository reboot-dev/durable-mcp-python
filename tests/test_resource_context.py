import asyncio
import unittest
from mcp import ClientSession, types
from mcp.server.elicitation import AcceptedElicitation
from mcp.shared.context import RequestContext
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

        progress_event = asyncio.Event()

        async def progress_callback(
            progress: float,
            total: float | None,
            message: str | None,
        ) -> None:
            progress_event.set()

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Read resource that reports progress, capturing the progress notification.
            send_request_task = asyncio.create_task(
                session.send_request(
                    types.ClientRequest(
                        types.ReadResourceRequest(
                            method="resources/read",
                            params=types.ReadResourceRequestParams(
                                uri=AnyUrl("progress://data"),
                            ),
                        ),
                    ),
                    types.ReadResourceResult,
                    progress_callback=progress_callback,
                )
            )

            # Wait for progress notification to be received.
            await progress_event.wait()

            # Get the result.
            result = await send_request_task
            assert len(result.contents) == 1
            assert "Processed data" in result.contents[0].text

    async def test_resource_with_logging(self) -> None:
        """Test that resource can use logging methods."""
        revision = await self.rbt.up(application)

        log_message_event = asyncio.Event()
        received_log_message = None

        async def message_handler(
            message: types.ServerNotification | Exception,
        ) -> None:
            nonlocal received_log_message
            if isinstance(message, types.ServerNotification):
                if isinstance(message.root, types.LoggingMessageNotification):
                    received_log_message = message.root.params.data
                    log_message_event.set()

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
            message_handler=message_handler,
        ) as (session, session_id, protocol_version):
            # Test debug logging - capture the log message.
            send_request_task = asyncio.create_task(
                session.send_request(
                    types.ClientRequest(
                        types.ReadResourceRequest(
                            method="resources/read",
                            params=types.ReadResourceRequestParams(
                                uri=AnyUrl("logging://debug"),
                            ),
                        ),
                    ),
                    types.ReadResourceResult,
                )
            )

            # Wait for log message to be received.
            await log_message_event.wait()

            # Verify the log message.
            assert received_log_message == "Debug message for debug"

            # Get the result.
            result = await send_request_task
            assert len(result.contents) == 1
            assert "Logged at debug" in result.contents[0].text

    async def test_resource_with_elicit(self) -> None:
        """Test that resource can elicit user input."""
        revision = await self.rbt.up(application)

        elicitation_received = asyncio.Event()

        async def elicitation_callback(
            context: RequestContext[ClientSession, None],
            params: types.ElicitRequestParams,
        ):
            assert "Do you want to proceed?" in params.message
            elicitation_received.set()
            # Respond with user confirmation.
            return types.ElicitResult(
                action="accept",
                content={"confirmed": True, "reason": "Testing elicitation"}
            )

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
            elicitation_callback=elicitation_callback,
        ) as (session, session_id, protocol_version):
            # Call resource that will elicit.
            result = await session.read_resource(AnyUrl("elicit://confirm"))

            # Verify elicitation was received.
            assert elicitation_received.is_set()

            # Verify result includes elicited data.
            assert len(result.contents) == 1
            assert "User confirmed: True" in result.contents[0].text
            assert "Testing elicitation" in result.contents[0].text

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
        """Test that resource with elicitation survives server reboot."""
        revision = await self.rbt.up(application)

        elicitation_event = asyncio.Event()

        async def elicitation_callback_before_reboot(
            context: RequestContext[ClientSession, None],
            params: types.ElicitRequestParams,
        ):
            assert "Do you want to proceed?" in params.message
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
                        types.ReadResourceRequest(
                            method="resources/read",
                            params=types.ReadResourceRequestParams(
                                uri=AnyUrl("elicit://confirm"),
                            ),
                        ),
                    ),
                    types.ReadResourceResult,
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
            assert "Do you want to proceed?" in params.message
            return types.ElicitResult(
                action="accept",
                content={"confirmed": True, "reason": "Resumed after reboot"}
            )

        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            next_request_id=session._request_id - 1,
            elicitation_callback=elicitation_callback_after_reboot,
        ) as session:

            assert last_event_id is not None

            result = await session.send_request(
                types.ClientRequest(
                    types.ReadResourceRequest(
                        method="resources/read",
                        params=types.ReadResourceRequestParams(
                            uri=AnyUrl("elicit://confirm"),
                        ),
                    ),
                ),
                types.ReadResourceResult,
                metadata=ClientMessageMetadata(
                    resumption_token=last_event_id,
                ),
            )

            assert len(result.contents) == 1
            assert "User confirmed: True" in result.contents[0].text
            assert "Resumed after reboot" in result.contents[0].text


if __name__ == '__main__':
    unittest.main()
