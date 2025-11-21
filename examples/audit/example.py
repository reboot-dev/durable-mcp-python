"""
Example DurableMCP server with audit logging.

Demonstrates both decorator and explicit audit logging patterns.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Add api/ to Python path for generated proto code.
api_path = Path(__file__).parent.parent.parent / "api"
if api_path.exists():
    sys.path.insert(0, str(api_path))

from audit import AuditEntry, audit, timestamp_to_uuidv7
from reboot.mcp.server import DurableMCP, DurableContext
from reboot.std.collections.v1.sorted_map import SortedMap

# Initialize MCP server.
mcp = DurableMCP(path="/mcp")


# Example 1: Using @audit decorator
@mcp.tool()
@audit("user_operations")
async def create_user(
    name: str,
    email: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Create a new user.

    This tool is decorated with @audit, so all invocations are automatically
    logged with inputs, outputs, duration, and success/failure.
    """
    # Simulate user creation.
    user_id = f"user_{hash(name) % 10000}"

    return {
        "status": "success",
        "user_id": user_id,
        "name": name,
        "email": email,
    }


# Example 2: Using explicit audit logging
@mcp.tool()
async def delete_user(
    user_id: str,
    reason: Optional[str] = None,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Delete a user.

    This tool uses explicit audit logging to record additional context
    beyond what the decorator would capture.
    """
    # Perform deletion logic here.
    # ...

    # Explicit audit with custom fields.
    await audit(
        "user_operations",
        context,
        {
            "action": "delete_user",
            "user_id": user_id,
            "reason": reason or "no reason provided",
            "severity": "high",
            "status": "success",
        },
    )

    return {"status": "success", "user_id": user_id}


# Example 3: Tool to query audit logs
@mcp.tool()
async def get_audit_log(
    log_name: str,
    begin: Optional[int] = None,
    end: Optional[int] = None,
    limit: int = 100,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Query audit log entries by time range.

    Args:
        log_name: Name of the audit log to query.
        begin: Start timestamp in milliseconds (Unix epoch). Optional.
        end: End timestamp in milliseconds (Unix epoch). Optional.
        limit: Maximum number of entries to return (default 100).
        context: The durable context.

    Returns:
        Dictionary with count and entries list.

    Examples:
        # Get last 50 entries.
        get_audit_log("user_operations", limit=50)

        # Get entries from last hour.
        get_audit_log("user_operations", begin=time.time()*1000 - 3600000)

        # Get entries in specific range.
        get_audit_log("user_operations", begin=1699000000000, end=1699100000000)
    """
    audit_map = SortedMap.ref(f"audit:{log_name}")

    # Build range query using `UUIDv7` boundaries.
    if begin is not None and end is not None:
        # Range query: begin to end.
        begin_key = str(timestamp_to_uuidv7(begin))
        end_key = str(timestamp_to_uuidv7(end))

        response = await audit_map.range(
            context,
            start_key=begin_key,
            end_key=end_key,
            limit=limit,
        )
    elif begin is not None:
        # Query from begin onwards.
        begin_key = str(timestamp_to_uuidv7(begin))

        response = await audit_map.range(
            context,
            start_key=begin_key,
            limit=limit,
        )
    elif end is not None:
        # Query up to end (newest first, then filter).
        end_key = str(timestamp_to_uuidv7(end))

        response = await audit_map.reverse_range(
            context,
            end_key=end_key,
            limit=limit,
        )
    else:
        # No time bounds - get most recent entries.
        response = await audit_map.reverse_range(
            context,
            limit=limit,
        )

    # Parse entries using Pydantic.
    entries = []
    for entry in response.entries:
        audit_entry = AuditEntry.model_validate_json(entry.value)
        entries.append(audit_entry.model_dump())

    return {
        "log_name": log_name,
        "count": len(entries),
        "entries": entries,
    }


# Example 4: Mixed pattern - decorator + explicit logging
@mcp.tool()
@audit("user_operations")
async def update_user(
    user_id: str,
    updates: Dict[str, Any],
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Update user information.

    Uses both decorator (for automatic capture) and explicit logging
    (for additional context).
    """
    # Perform update.
    # ...

    # The decorator will log this automatically, but we can add
    # additional entries for specific events.
    if "role" in updates:
        await audit(
            "security_events",
            context,
            {
                "action": "role_change",
                "user_id": user_id,
                "old_role": "user",
                "new_role": updates["role"],
                "severity": "medium",
            },
        )

    return {
        "status": "success",
        "user_id": user_id,
        "updated_fields": list(updates.keys()),
    }


async def main():
    """Start the example audit server."""
    # Reboot application that runs everything necessary for `DurableMCP`.
    await mcp.application().run()


if __name__ == "__main__":
    asyncio.run(main())
