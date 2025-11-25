"""
Example client for multi-step operations demonstration.
"""

import asyncio
import json
from reboot.mcp.client import connect

URL = "http://localhost:9991"


async def main():
    """Run multi-step operations example client."""
    async with connect(URL + "/mcp") as (
        session,
        session_id,
        protocol_version,
    ):
        print("Connected to steps example server")
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

        # Example 1: Create user with profile.
        print("=" * 60)
        print("Example 1: Create user with profile (two-step)")
        print("=" * 60)

        result = await session.call_tool(
            "create_user_with_profile",
            {
                "username": "alice",
                "email": "alice@example.com",
                "bio": "Software engineer interested in distributed systems",
            },
        )
        print(f"Created: {result.content[0].text}")

        # Parse the result to get actual user_id and profile_id.
        alice_data = json.loads(result.content[0].text)
        alice_user_id = alice_data.get("user_id")
        alice_profile_id = alice_data.get("profile_id")
        print()

        # Example 2: Create another user.
        result = await session.call_tool(
            "create_user_with_profile",
            {
                "username": "bob",
                "email": "bob@example.com",
                "bio": "Data scientist working on ML infrastructure",
            },
        )
        print(f"Created: {result.content[0].text}")
        print()

        # Example 3: Retrieve user data.
        print("=" * 60)
        print("Example 2: Retrieve user and profile data")
        print("=" * 60)

        if alice_user_id:
            result = await session.call_tool(
                "get_user",
                {"user_id": alice_user_id},
            )
            print(f"User data: {result.content[0].text}")
            print()

        if alice_profile_id:
            result = await session.call_tool(
                "get_profile",
                {"profile_id": alice_profile_id},
            )
            print(f"Profile data: {result.content[0].text}")
            print()

        print("Steps example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
