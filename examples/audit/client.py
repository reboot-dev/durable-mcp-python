"""
Example client for audit logging demonstration.
"""

import asyncio
import time
from reboot.mcp.client import connect

URL = "http://localhost:9991"


async def main():
    """Run audit logging example client."""
    async with connect(URL + "/mcp") as (
        session,
        session_id,
        protocol_version,
    ):
        print("Connected to audit example server")
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

        # Example 1: Create users (decorator auditing).
        print("=" * 60)
        print("Example 1: Creating users (decorator auditing)")
        print("=" * 60)

        users = [
            ("alice", "alice@example.com"),
            ("bob", "bob@example.com"),
            ("carol", "carol@example.com"),
        ]

        for name, email in users:
            result = await session.call_tool(
                "create_user",
                {"name": name, "email": email},
            )
            print(f"Created: {result.content[0].text}")

        print()

        # Example 2: Delete user (explicit auditing).
        print("=" * 60)
        print("Example 2: Deleting user (explicit auditing)")
        print("=" * 60)

        result = await session.call_tool(
            "delete_user",
            {
                "user_id": "user_1234",
                "reason": "Account inactive for 2 years",
            },
        )
        print(f"Deleted: {result.content[0].text}")
        print()

        # Example 3: Query recent audit logs.
        print("=" * 60)
        print("Example 3: Query recent audit logs")
        print("=" * 60)

        result = await session.call_tool(
            "get_audit_log",
            {"log_name": "user_operations", "limit": 10},
        )
        print(f"Audit log: {result.content[0].text}")
        print()

        # Example 4: Update user (mixed pattern).
        print("=" * 60)
        print("Example 4: Update user role (mixed pattern)")
        print("=" * 60)

        result = await session.call_tool(
            "update_user",
            {
                "user_id": "user_5678",
                "updates": {"role": "admin", "verified": True},
            },
        )
        print(f"Updated: {result.content[0].text}")
        print()

        # Query security events log.
        result = await session.call_tool(
            "get_audit_log",
            {"log_name": "security_events", "limit": 5},
        )
        print(f"Security events: {result.content[0].text}")
        print()

        print("Audit example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
