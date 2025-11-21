"""
Example client for payment processing demonstration.
"""

import asyncio
import json
from reboot.mcp.client import connect

URL = "http://localhost:9991"


async def main():
    """Run payment processing example client."""
    async with connect(URL + "/mcp") as (
        session,
        session_id,
        protocol_version,
    ):
        print("Connected to processing example server")
        print(f"Session ID: {session_id}")
        print()

        # List available tools.
        tools = await session.list_tools()
        print(f"Available tools: {len(tools.tools)}")
        for tool in tools.tools:
            print(f"  - {tool.name}")
            # Print description with proper indentation.
            if tool.description:
                for line in tool.description.split("\n"):
                    print(f"    {line}")
        print()

        # Example 1: Successful payment.
        print("=" * 60)
        print("Example 1: Successful payment")
        print("=" * 60)

        result = await session.call_tool(
            "process_payment",
            {"amount": 99.99, "currency": "USD"},
        )
        print(f"Payment result: {result.content[0].text}")

        # Extract transaction ID from result.
        payment1_data = json.loads(result.content[0].text)
        txn1_id = payment1_data.get("payment", {}).get("transaction_id")
        print()

        # Example 2: Another successful payment.
        result = await session.call_tool(
            "process_payment",
            {"amount": 49.99, "currency": "USD"},
        )
        print(f"Payment result: {result.content[0].text}")

        # Extract transaction ID from result.
        payment2_data = json.loads(result.content[0].text)
        txn2_id = payment2_data.get("payment", {}).get("transaction_id")
        print()

        # Example 3: Retriable network error (will retry and succeed).
        print("=" * 60)
        print("Example 3: Retriable network error (retries and succeeds)")
        print("=" * 60)

        result = await session.call_tool(
            "process_payment",
            {"amount": 75.01, "currency": "USD"},
        )
        print(f"Payment result: {result.content[0].text}")
        print()

        # Example 4: Retrieve payment records.
        print("=" * 60)
        print("Example 4: Retrieve payment records")
        print("=" * 60)

        # Try first payment.
        if txn1_id:
            result = await session.call_tool(
                "get_payment",
                {"transaction_id": txn1_id},
            )
            print(f"Payment record 1: {result.content[0].text}")
            print()

        # Try second payment.
        if txn2_id:
            result = await session.call_tool(
                "get_payment",
                {"transaction_id": txn2_id},
            )
            print(f"Payment record 2: {result.content[0].text}")
            print()

        # Example 5: Payment that will fail (insufficient funds).
        print("=" * 60)
        print("Example 5: Failed payment (insufficient funds)")
        print("=" * 60)

        result = await session.call_tool(
            "process_payment",
            {"amount": 999999.99, "currency": "USD"},
        )
        print(f"Payment result: {result.content[0].text}")
        print()

        # Example 6: Payment that will fail (invalid currency).
        print("=" * 60)
        print("Example 6: Failed payment (invalid currency)")
        print("=" * 60)

        result = await session.call_tool(
            "process_payment",
            {"amount": 50.00, "currency": "INVALID"},
        )
        print(f"Payment result: {result.content[0].text}")
        print()

        print("Processing example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
