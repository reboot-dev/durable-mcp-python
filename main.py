import asyncio
import mcp.types as types
from typing import Any, Dict, List
from dataclasses import dataclass

from reboot.mcp.server import DurableContext, DurableMCP
from reboot.std.collections.v1.sorted_map import SortedMap
from pydantic import BaseModel, Field, ConfigDict, ValidationError

MIME_TYPE = "text/html+skybridge"


@dataclass(frozen=True)
class CounterWidget:
    identifier: str
    title: str
    template_uri: str
    invoking: str
    invoked: str
    html: str
    response_text: str


WIDGET = CounterWidget(
    identifier="counter",
    title="Keep a count with a counter widget",
    template_uri="ui://widget/counter.html",
    invoking="Start counting",
    invoked="Your counter is ready",
    html=(
        "<div id=\"counter-root\"></div>\n"
        "<link rel=\"stylesheet\" href=\"https://persistent.oaistatic.com/"
        "ecosystem-built-assets/solar-system-0038.css\">\n"
        "<script type=\"module\" src=\"https://persistent.oaistatic.com/"
        "ecosystem-built-assets/solar-system-0038.js\"></script>"
    ),
    response_text="Your counter is ready",
)


def _embedded_widget_resource(widget: CounterWidget) -> types.EmbeddedResource:
    return types.EmbeddedResource(
        type="resource",
        resource=types.TextResourceContents(
            uri=widget.template_uri,
            mimeType=MIME_TYPE,
            text=widget.html,
            title=widget.title,
        ),
    )


async def _call_tool_request(req: types.CallToolRequest) -> types.ServerResult:
    arguments = req.params.arguments or {}
    try:
        model_validate(arguments)
    except ValidationError as exc:
        return types.ServerResult(
            types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Input validation error: {exc.errors()}",
                    )
                ],
                isError=True,
            )
        )

    widget_resource = _embedded_widget_resource(WIDGET)
    meta: Dict[str, Any] = {
        "openai.com/widget": widget_resource.model_dump(mode="json"),
        "openai/outputTemplate": WIDGET.template_uri,
        "openai/toolInvocation/invoking": WIDGET.invoking,
        "openai/toolInvocation/invoked": WIDGET.invoked,
        "openai/widgetAccessible": True,
        "openai/resultCanProduceWidget": True,
    }

    return types.ServerResult(
        types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=widget.response_text,
                )
            ],
            _meta=meta,
        )
    )


mcp = DurableMCP(path="/mcp", log_level="DEBUG")


async def main():
    # Reboot application that runs everything necessary for `DurableMCP`.
    await mcp.application().run()


if __name__ == '__main__':
    asyncio.run(main())
