# DurableMCP Examples

Examples demonstrating idempotency patterns and durable storage
primitives for Model Context Protocol servers.

## Concepts

### Idempotency Guards

**`at_least_once(alias, context, callable, type)`**

Operation completes at least once. Caches result on success. Retries
on all failures.

```python
user_id = await at_least_once(
    "create_user",
    context,
    create_user,
    type=str,
)
```

**`at_most_once(alias, context, callable, type, retryable_exceptions)`**

Operation executes at most once. Only retries on specified exceptions.
Raises `AtMostOnceFailedBeforeCompleting` on subsequent calls after
non-retryable failure.

```python
result = await at_most_once(
    "payment",
    context,
    make_payment,
    type=dict,
    retryable_exceptions=[NetworkError],
)
```

### Storage Primitives

**SortedMap**

Larger-than-memory key-value store with lexicographic ordering.
Supports batch operations and range queries.

```python
map = SortedMap.ref("name")
await map.insert(context, entries={"key": b"value"})
response = await map.get(context, key="key")
response = await map.range(context, start_key="a", limit=100)
response = await map.reverse_range(context, limit=100)
await map.remove(context, keys=["key"])
```

When calling methods on the same named SortedMap multiple times within
the same context, use `.idempotently()` with unique aliases:

```python
map = SortedMap.ref("results")
await map.idempotently("store_step1").insert(context, entries={...})
await map.idempotently("store_step2").insert(context, entries={...})
```

Different named maps don't require idempotency guards.

**UUIDv7**

Time-ordered UUID with embedded timestamp. Sorts chronologically in
SortedMap.

```python
from uuid7 import create as uuid7

key = str(uuid7())  # Embeds current timestamp.
await map.insert(context, entries={key: data})
response = await map.reverse_range(context, limit=10)  # Most recent.
```

### Tool Lifecycle

Each `@mcp.tool()` invocation has its own idempotency manager. Guards
only deduplicate within a single tool call, not across multiple calls.

## Examples

### audit

Audit logging with `@audit()` decorator. Stores tool invocations in
SortedMap with UUIDv7 keys for chronological access.

**Demonstrates**: Decorator pattern, time-range queries, `reverse_range`
for recent entries.

### steps

Multi-step operations where each step is independently idempotent. If
tool is retried after step 1 succeeds but before step 2 completes,
step 1 returns cached result.

**Demonstrates**: Multiple `at_least_once` guards with separate aliases,
sequential dependencies.

### processing

Payment processing with `at_most_once` to prevent duplicate charges.
Distinguishes retryable (network errors) from non-retryable (payment
rejected) failures.

**Demonstrates**: `retryable_exceptions` parameter,
`AtMostOnceFailedBeforeCompleting` exception, error classification.

### document

Document processing pipeline combining `at_least_once` (idempotent
reads/writes) and `at_most_once` (external API calls) in a single
workflow.

**Demonstrates**: Mixed patterns, OCR and translation APIs, multi-step
error handling.

### define

Technical glossary demonstrating all SortedMap CRUD operations.
Maintains dual indexes: alphabetical (by term) and chronological
(by UUIDv7).

**Demonstrates**: `insert`, `get`, `range`, `reverse_range`, `remove`,
prefix search, dual indexing.

## Running Examples

### Interactive Harness (Recommended)

The interactive harness runs examples end-to-end with client
demonstrations:

```bash
cd examples
python run.py
```

**What it does:**

1. Shows menu of available examples
2. Starts selected server on port 9991
3. Waits for server to be ready
4. Runs corresponding client script
5. Shows full client output with examples
6. Cleans up server process on exit

**Exit:** Press `q` at the menu or `Ctrl-C` to exit.

### Client Pattern

All example clients follow this pattern:

```python
from reboot.mcp.client import connect

URL = "http://localhost:9991"

async def main():
    async with connect(URL + "/mcp") as (
        session,
        session_id,
        protocol_version,
    ):
        # List tools.
        tools = await session.list_tools()

        # Call tools.
        result = await session.call_tool("tool_name", {"arg": "value"})
```

### Running Servers Directly

To run servers standalone without the harness:

```bash
cd examples/<example-name>
uv run python example.py
```

Each example is a standalone MCP server exposing tools via the Model
Context Protocol on `http://localhost:9991/mcp`.

## Patterns

### Idempotent Multi-Step Operations

```python
# Step 1: Cached on success.
step1_result = await at_least_once(
    "step1",
    context,
    do_step1,
    type=dict,
)

# Step 2: Uses result from step 1.
step2_result = await at_least_once(
    "step2",
    context,
    do_step2,
    type=dict,
)
```

### External API with Retry Policy

```python
try:
    result = await at_most_once(
        "api_call",
        context,
        call_api,
        type=dict,
        retryable_exceptions=[NetworkError],
    )
except NetworkError:
    # Retries exhausted.
    return {"error": "service unavailable"}
except AtMostOnceFailedBeforeCompleting:
    # Previous attempt failed with non-retryable error.
    return {"error": "operation failed previously"}
```

### Recent Items with UUIDv7

```python
# Store with time-ordered keys.
key = str(uuid7())
await map.insert(context, entries={key: data})

# Query most recent.
response = await map.reverse_range(context, limit=20)
```

### Prefix Search

```python
# Find all keys starting with "api".
start_key = "api"
end_key = "apj"  # Increment last character.
response = await map.range(
    context,
    start_key=start_key,
    end_key=end_key,
    limit=100,
)
```

## Notes

- Idempotency guards are per-tool-invocation, not per-server.
- SortedMap operations are not atomic across multiple maps.
- UUIDv7 provides millisecond precision for time ordering.
- All storage is persistent and survives server restarts.
