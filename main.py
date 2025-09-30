import asyncio
from reboot.aio.applications import Application
from reboot.mcp.server import DurableContext, DurableMCP
from reboot.std.collections.v1.sorted_map import SortedMap
from pydantic import BaseModel, Field

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp", log_level="DEBUG")


@mcp.tool()
async def addNumbersAndInsertIntoSortedMap(a: int, b: int,
                                           context: DurableContext) -> int:
    """Add two numbers and also store result in `SortedMap`."""
    await context.report_progress(0.1)
    result = a + b

    await SortedMap.ref("what").Insert(
        context,
        entries={f"{a} + {b}": f"{result}".encode()},
    )

    await context.report_progress(1.0)
    return result


async def main():
    # Reboot application that runs everything necessary for `DurableMCP`.
    await mcp.application().run()


if __name__ == '__main__':
    asyncio.run(main())
