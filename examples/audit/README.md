# Audit Logging

Durable audit trails for MCP tool invocations using SortedMap and
UUIDv7.

## Overview

Store audit entries with time-ordered UUIDv7 keys for chronological
access. Provides both decorator and explicit logging patterns.

## Features

- Decorator pattern for automatic tool auditing
- Explicit logging with custom data
- Time-range queries via UUIDv7 boundaries
- Non-blocking (audit failures don't break tools)

## Usage

### Decorator Pattern

Automatically log tool invocations:

```python
@mcp.tool()
@audit("user_operations")
async def create_user(
    name: str,
    email: str,
    context: DurableContext = None,
) -> dict:
    """Create a new user."""
    user_id = f"user_{hash(name) % 10000}"
    return {"status": "success", "user_id": user_id}
```

Logged data:

```json
{
  "timestamp": 1699123456789,
  "tool": "create_user",
  "inputs": {"name": "Alice", "email": "alice@example.com"},
  "outputs": {"status": "success", "user_id": "1234"},
  "success": true,
  "duration_seconds": 0.123
}
```

### Explicit Logging

Add custom audit entries:

```python
@mcp.tool()
async def delete_user(
    user_id: str,
    reason: str = None,
    context: DurableContext = None,
) -> dict:
    """Delete a user."""
    # Perform deletion.
    # ...

    # Log with custom fields.
    await audit("user_operations", context, {
        "action": "delete_user",
        "user_id": user_id,
        "reason": reason or "no reason provided",
        "severity": "high",
    })

    return {"status": "success"}
```

### Querying Audit Logs

```python
@mcp.tool()
async def get_audit_log(
    log_name: str,
    begin: int = None,
    end: int = None,
    limit: int = 100,
    context: DurableContext = None,
) -> dict:
    """Query audit logs by time range."""
    audit_map = SortedMap.ref(f"audit:{log_name}")

    if begin and end:
        # Range query with UUIDv7 boundaries.
        response = await audit_map.range(
            context,
            start_key=str(timestamp_to_uuidv7(begin)),
            end_key=str(timestamp_to_uuidv7(end)),
            limit=limit,
        )
    else:
        # Get most recent entries.
        response = await audit_map.reverse_range(context, limit=limit)

    # Parse and return entries.
    # ...
```

## How It Works

### UUIDv7 Keys

UUIDv7 embeds timestamp in first 48 bits, providing natural
chronological sorting:

```python
from uuid7 import create as uuid7

key = str(uuid7())  # "018b8c5a-3f7e-7abc-9012-3456789abcdef"
```

Later keys sort after earlier keys lexicographically.

### Storage Structure

Audit entries stored in SortedMap `audit:{log_name}`:

```
audit:user_operations
├─ 018b8c5a-3f7e-7abc-9012-... → {"tool": "create_user", ...}
├─ 018b8c5b-1234-7abc-9012-... → {"tool": "delete_user", ...}
└─ 018b8c5c-5678-7abc-9012-... → {"tool": "update_user", ...}
```

### Timestamp to UUIDv7 Conversion

Convert timestamps to UUIDv7 for range boundaries:

```python
begin_uuid = timestamp_to_uuidv7(1699000000000)
end_uuid = timestamp_to_uuidv7(1699100000000)

response = await audit_map.range(
    context,
    start_key=str(begin_uuid),
    end_key=str(end_uuid),
    limit=100,
)
```

## Examples

```python
# Get last 50 entries.
get_audit_log("user_operations", limit=50)

# Get entries from last hour.
import time
one_hour_ago = int((time.time() - 3600) * 1000)
get_audit_log("user_operations", begin=one_hour_ago)

# Get entries in specific time range.
get_audit_log(
    "user_operations",
    begin=1699000000000,
    end=1699100000000,
)
```

## API Reference

### `audit(log_name, context=None, data=None)`

Dual-purpose function for audit logging.

**As decorator:**

```python
@audit("log_name")
async def my_tool(arg: str, context: DurableContext = None):
    ...
```

**As function:**

```python
await audit("log_name", context, {
    "action": "example",
    "status": "success",
})
```

### `timestamp_to_uuidv7(timestamp_ms)`

Convert Unix timestamp (milliseconds) to UUIDv7 for range queries.

## Best Practices

Choose meaningful log names:

```python
await audit("user_operations", ...)
await audit("security_events", ...)
await audit("api_calls", ...)
```

Use decorator for standard logging, explicit for custom context:

```python
@mcp.tool()
@audit("user_operations")
async def promote_user(user_id: str, context: DurableContext = None):
    # Decorator logs invocation.

    # Also log security event.
    await audit("security_events", context, {
        "action": "privilege_escalation",
        "user_id": user_id,
        "severity": "critical",
    })
```

## Running

```bash
cd examples/audit
uv run python example.py
```
