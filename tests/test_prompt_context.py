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


@mcp.prompt()
def basic_prompt(topic: str, context: DurableContext) -> str:
    """Basic prompt with DurableContext."""
    assert context is not None
    return f"Please write about {topic}."


@mcp.prompt()
async def progress_prompt(task: str, context: DurableContext) -> str:
    """Prompt that reports progress."""
    await context.report_progress(0, 100, "Analyzing task")
    await asyncio.sleep(0.01)
    await context.report_progress(50, 100, "Generating prompt")
    await asyncio.sleep(0.01)
    await context.report_progress(100, 100, "Finalizing")
    return f"Please complete this task: {task}."


@mcp.prompt()
async def logging_prompt(level: str, context: DurableContext) -> str:
    """Prompt that uses logging methods."""
    if level == "debug":
        await context.debug(f"Generating debug prompt")
    elif level == "info":
        await context.info(f"Generating info prompt")
    elif level == "warning":
        await context.warning(f"Generating warning prompt")
    elif level == "error":
        await context.error(f"Generating error prompt")

    await context.log(
        "info", f"Custom log for prompt {level}", logger_name="prompts"
    )
    return f"Prompt generated with {level} logging."


class PreferenceSchema(BaseModel):
    style: str
    detail_level: str


@mcp.prompt()
async def elicit_prompt(topic: str, context: DurableContext) -> str:
    """Prompt that elicits user preferences."""
    result = await context.elicit(
        message="What style and detail level do you prefer?",
        schema=PreferenceSchema
    )

    if isinstance(result, AcceptedElicitation):
        return (
            f"Please write about {topic} in {result.data.style} style "
            f"with {result.data.detail_level} detail level."
        )
    else:
        return f"Please write about {topic}."


@mcp.prompt()
def sync_prompt(subject: str, context: DurableContext) -> str:
    """Synchronous prompt with DurableContext."""
    assert context is not None
    return f"Write a detailed analysis of {subject}."


@mcp.prompt()
async def multi_message_prompt(context: DurableContext) -> list[str]:
    """Prompt that returns multiple messages."""
    await context.info("Generating multi-part prompt")
    return [
        "First, analyze the problem.", "Then, propose solutions.",
        "Finally, evaluate trade-offs."
    ]


# Reboot application that runs everything necessary for `DurableMCP`.
application: Application = mcp.application()


class TestPromptContext(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_basic_prompt_with_context(self) -> None:
        """Test that basic prompt can access DurableContext."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.get_prompt(
                "basic_prompt", arguments={"topic": "AI"}
            )
            assert len(result.messages) == 1
            assert "Please write about AI" in result.messages[0].content.text

    async def test_prompt_with_progress(self) -> None:
        """Test that prompt can report progress."""
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
            # Get prompt that reports progress, capturing the progress notification.
            send_request_task = asyncio.create_task(
                session.send_request(
                    types.ClientRequest(
                        types.GetPromptRequest(
                            method="prompts/get",
                            params=types.GetPromptRequestParams(
                                name="progress_prompt",
                                arguments={"task": "analyze data"},
                            ),
                        ),
                    ),
                    types.GetPromptResult,
                    progress_callback=progress_callback,
                )
            )

            # Wait for progress notification to be received.
            await progress_event.wait()

            # Get the result.
            result = await send_request_task
            assert len(result.messages) == 1
            assert "analyze data" in result.messages[0].content.text

    async def test_prompt_with_logging(self) -> None:
        """Test that prompt can use logging methods."""
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
                        types.GetPromptRequest(
                            method="prompts/get",
                            params=types.GetPromptRequestParams(
                                name="logging_prompt",
                                arguments={"level": "debug"},
                            ),
                        ),
                    ),
                    types.GetPromptResult,
                )
            )

            # Wait for log message to be received.
            await log_message_event.wait()

            # Verify the log message.
            assert received_log_message == "Generating debug prompt"

            # Get the result.
            result = await send_request_task
            assert len(result.messages) == 1
            assert "debug logging" in result.messages[0].content.text

    async def test_prompt_with_elicit(self) -> None:
        """Test that prompt can elicit user input."""
        revision = await self.rbt.up(application)

        elicitation_received = asyncio.Event()

        async def elicitation_callback(
            context: RequestContext[ClientSession, None],
            params: types.ElicitRequestParams,
        ):
            assert "What style and detail level" in params.message
            elicitation_received.set()
            # Respond with user preferences.
            return types.ElicitResult(
                action="accept",
                content={"style": "technical", "detail_level": "high"}
            )

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
            elicitation_callback=elicitation_callback,
        ) as (session, session_id, protocol_version):
            # Call prompt that will elicit.
            result = await session.get_prompt("elicit_prompt", arguments={"topic": "AI"})

            # Verify elicitation was received.
            assert elicitation_received.is_set()

            # Verify result includes elicited preferences.
            assert len(result.messages) == 1
            assert "AI" in result.messages[0].content.text
            assert "technical" in result.messages[0].content.text
            assert "high" in result.messages[0].content.text

    async def test_sync_prompt_with_context(self) -> None:
        """Test that synchronous prompts work with DurableContext."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.get_prompt(
                "sync_prompt", arguments={"subject": "quantum computing"}
            )
            assert len(result.messages) == 1
            assert "quantum computing" in result.messages[0].content.text

    async def test_multi_message_prompt(self) -> None:
        """Test prompt that returns multiple messages."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.get_prompt(
                "multi_message_prompt", arguments={}
            )
            assert len(result.messages) == 3
            assert "analyze the problem" in result.messages[0].content.text
            assert "propose solutions" in result.messages[1].content.text
            assert "evaluate trade-offs" in result.messages[2].content.text

    async def test_prompt_survives_reboot(self) -> None:
        """Test that prompt with elicitation survives server reboot."""
        revision = await self.rbt.up(application)

        elicitation_event = asyncio.Event()

        async def elicitation_callback_before_reboot(
            context: RequestContext[ClientSession, None],
            params: types.ElicitRequestParams,
        ):
            assert "What style and detail level" in params.message
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
                        types.GetPromptRequest(
                            method="prompts/get",
                            params=types.GetPromptRequestParams(
                                name="elicit_prompt",
                                arguments={"topic": "quantum computing"},
                            ),
                        ),
                    ),
                    types.GetPromptResult,
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
            assert "What style and detail level" in params.message
            return types.ElicitResult(
                action="accept",
                content={"style": "academic", "detail_level": "comprehensive"}
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
                    types.GetPromptRequest(
                        method="prompts/get",
                        params=types.GetPromptRequestParams(
                            name="elicit_prompt",
                            arguments={"topic": "quantum computing"},
                        ),
                    ),
                ),
                types.GetPromptResult,
                metadata=ClientMessageMetadata(
                    resumption_token=last_event_id,
                ),
            )

            assert len(result.messages) == 1
            assert "quantum computing" in result.messages[0].content.text
            assert "academic" in result.messages[0].content.text
            assert "comprehensive" in result.messages[0].content.text


if __name__ == '__main__':
    unittest.main()
