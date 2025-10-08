import asyncio
from reboot.mcp.server import DurableContext, DurableMCP
from reboot.std.collections.v1.sorted_map import SortedMap
from pydantic import BaseModel, Field

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp", log_level="DEBUG")

# class SortedMapPreference(BaseModel):
#     """Preference for storing results in a `SortedMap`."""

#     store_in_sorted_map: bool = Field(
#         default=True,
#         description="Would you like to store the result in a SortedMap.",
#     )


@mcp.tool()
async def addNumbersAndInsertIntoSortedMap(
    a: int, b: int, context: DurableContext
) -> int:
    """Add two numbers and also store result in `SortedMap`."""
    # await context.report_progress(0.1)
    result = a + b

    # elicit_result = await context.elicit(
    #     message=
    #     f"Computed {a} + {b}, result is {result}. Should I add this your records?",
    #     schema=SortedMapPreference
    # )
    # print("elicit_result:")
    # print(elicit_result)

    # if elicit_result.action == "accept" and elicit_result.data:
    #     if not elicit_result.data.store_in_sorted_map:
    #         await context.report_progress(1.0)
    #         return result

    await SortedMap.ref("adds").Insert(
        context,
        entries={f"{a} + {b}": f"{result}".encode()},
    )

    # await context.report_progress(1.0)
    return result


async def main():
    # Reboot application that runs everything necessary for `DurableMCP`.
    await mcp.application().run()


if __name__ == '__main__':
    asyncio.run(main())
