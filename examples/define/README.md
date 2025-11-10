# Technical Glossary

Complete SortedMap CRUD reference using a technical glossary.

## Overview

Demonstrates all SortedMap operations through a practical use case:
maintaining a technical glossary with both alphabetical and
chronological indexes.

## SortedMap Operations

| Operation | Method | Use Case |
|-----------|--------|----------|
| Insert | `insert(context, entries={...})` | Add terms |
| Get | `get(context, key="...")` | Look up term |
| Range | `range(context, start_key=..., limit=...)` | Browse alphabetically |
| Range (bounded) | `range(context, start_key=..., end_key=..., limit=...)` | Prefix search |
| Reverse Range | `reverse_range(context, limit=...)` | Recent additions |
| Remove | `remove(context, keys=[...])` | Delete terms |

## Architecture

Two SortedMaps for different access patterns:

```python
# Map 1: Alphabetical index (keyed by term name).
terms_map = SortedMap.ref("terms")
# Key: "api" -> Value: {"term": "API", "definition": "...", ...}

# Map 2: Chronological index (keyed by UUIDv7).
recent_map = SortedMap.ref("recent")
# Key: "018c1234-..." -> Value: {"term": "API", "definition": "...", ...}
```

## Usage

### Insert

Add terms to both indexes:

```python
@mcp.tool()
async def add_term(
    term: str,
    definition: str,
    category: str = "general",
    context: DurableContext = None,
) -> dict:
    """Add a technical term to the glossary."""
    term_data = {
        "term": term,
        "definition": definition,
        "category": category,
        "timestamp": int(time.time() * 1000),
    }

    # Insert into alphabetical map (keyed by term).
    await terms_map.insert(
        context,
        entries={term.lower(): json.dumps(term_data).encode("utf-8")},
    )

    # Insert into chronological map (keyed by UUIDv7).
    recent_key = str(uuid7())
    await recent_map.insert(
        context,
        entries={recent_key: json.dumps(term_data).encode("utf-8")},
    )

    return {"status": "success", "term": term}
```

### Get

Point lookup for term definition:

```python
@mcp.tool()
async def define(
    term: str,
    context: DurableContext = None,
) -> dict:
    """Look up a term's definition."""
    response = await terms_map.get(context, key=term.lower())

    if not response.HasField("value"):
        return {"status": "error", "message": "Term not found"}

    term_data = json.loads(response.value.decode("utf-8"))
    return {"status": "success", "term": term_data}
```

### Range

Browse terms alphabetically:

```python
@mcp.tool()
async def list_terms(
    start_with: str = "",
    limit: int = 50,
    context: DurableContext = None,
) -> dict:
    """List terms alphabetically."""
    if start_with:
        # Range starting from prefix.
        response = await terms_map.range(
            context,
            start_key=start_with.lower(),
            limit=limit,
        )
    else:
        # Range from beginning.
        response = await terms_map.range(
            context,
            limit=limit,
        )

    # Parse and return entries.
    # ...
```

### Range (Bounded)

Prefix search with start and end boundaries:

```python
@mcp.tool()
async def search_terms(
    prefix: str,
    limit: int = 20,
    context: DurableContext = None,
) -> dict:
    """Search for terms by prefix."""
    # Calculate end key for prefix range.
    start_key = prefix.lower()
    # Increment last character for upper bound.
    end_key = prefix[:-1] + chr(ord(prefix[-1]) + 1)

    response = await terms_map.range(
        context,
        start_key=start_key,
        end_key=end_key.lower(),
        limit=limit,
    )

    # Parse and return entries.
    # ...
```

### Reverse Range

Get recently added terms (UUIDv7 keys):

```python
@mcp.tool()
async def recent_terms(
    limit: int = 20,
    context: DurableContext = None,
) -> dict:
    """Get recently added terms."""
    response = await recent_map.reverse_range(
        context,
        limit=limit,
    )

    # Parse and return entries (newest first).
    # ...
```

### Remove

Delete terms from glossary:

```python
@mcp.tool()
async def remove_term(
    term: str,
    context: DurableContext = None,
) -> dict:
    """Remove a term from the glossary."""
    # Check if term exists first.
    response = await terms_map.get(context, key=term.lower())

    if not response.HasField("value"):
        return {"status": "error", "message": "Term not found"}

    # Remove from alphabetical map.
    await terms_map.remove(
        context,
        keys=[term.lower()],
    )

    return {"status": "success", "message": f"Removed '{term}'"}
```

## Key Concepts

### Point Lookup with get()

Single key retrieval:

```python
response = await terms_map.get(context, key="api")

if not response.HasField("value"):
    # Key not found.
    return {"error": "Not found"}

# Key found.
data = json.loads(response.value.decode("utf-8"))
```

Returns `GetResponse` with optional `value` field.

### Range Queries

Ascending order traversal:

```python
# All keys from "api" onwards.
response = await terms_map.range(
    context,
    start_key="api",
    limit=50,
)

# Keys from "api" to "apz" (exclusive).
response = await terms_map.range(
    context,
    start_key="api",
    end_key="apz",
    limit=50,
)

# First 50 keys in map.
response = await terms_map.range(
    context,
    limit=50,
)
```

Parameters:

- `start_key`: Inclusive lower bound (optional)
- `end_key`: Exclusive upper bound (optional)
- `limit`: Maximum entries to return (required)

Returns `RangeResponse` with `entries` list.

### Reverse Range

Descending order traversal (largest to smallest keys):

```python
# Get 20 most recent entries (UUIDv7 keys are time-ordered).
response = await recent_map.reverse_range(
    context,
    limit=20,
)

# Keys from "z" down to "m" (exclusive).
response = await terms_map.reverse_range(
    context,
    start_key="z",
    end_key="m",
    limit=50,
)
```

Use cases: Recent items, reverse alphabetical browsing.

### UUIDv7 for Time Ordering

UUIDv7 embeds timestamp in first 48 bits:

```python
from uuid7 import create as uuid7

# Generate time-ordered key.
key = str(uuid7())  # "018c1234-5678-7abc-9012-3456789abcdef"

# Later keys sort after earlier keys.
key1 = str(uuid7())  # At time T1.
time.sleep(0.1)
key2 = str(uuid7())  # At time T2.
# key1 < key2 (lexicographically)
```

Benefits: Natural chronological sorting, no collisions, works with
`reverse_range()` for recent items.

### Prefix Search Pattern

Find all keys starting with prefix "api":

```python
prefix = "api"
start_key = prefix.lower()
# Increment last character to get exclusive upper bound.
end_key = prefix[:-1] + chr(ord(prefix[-1]) + 1)  # "api" -> "apj"

response = await terms_map.range(
    context,
    start_key=start_key,
    end_key=end_key,
    limit=100,
)
```

Works because SortedMap uses lexicographic ordering.

## Best Practices

Always check `HasField("value")` for `get()`:

```python
# Correct.
response = await map.get(context, key="term")
if not response.HasField("value"):
    return {"error": "Not found"}

# Wrong (will raise AttributeError if value is unset).
if not response.value:
    pass
```

Use `limit` parameter for `range()` queries:

```python
# Required - limit prevents unbounded results.
response = await map.range(context, limit=100)

# Error - limit is required.
response = await map.range(context)
```

Lowercase keys for case-insensitive lookup while preserving original
capitalization:

```python
# Store original term in data, use lowercase for key.
term_data = {
    "term": term,  # Preserves "gRPC", "Kubernetes", etc.
    "definition": definition,
    # ...
}

await terms_map.insert(
    context,
    entries={term.lower(): json.dumps(term_data).encode("utf-8")},
)

# Lookup with lowercase (case-insensitive).
response = await terms_map.get(context, key=term.lower())
# Returns: {"term": "gRPC", ...} regardless of input case
```

This allows lookups like `define("grpc")`, `define("GRPC")`, and
`define("gRPC")` to all return the same term with its original
capitalization.

## Common Patterns

### Recent Items with UUIDv7

```python
# Store with UUIDv7 keys for time ordering.
recent_map = SortedMap.ref("recent")
await recent_map.insert(
    context,
    entries={str(uuid7()): data},
)

# Get N most recent.
response = await recent_map.reverse_range(context, limit=10)
```

### Dual Indexing

```python
# Primary index: optimized for lookups.
terms_map = SortedMap.ref("terms")
await terms_map.insert(context, entries={term.lower(): data})

# Secondary index: optimized for chronological access.
recent_map = SortedMap.ref("recent")
await recent_map.insert(context, entries={str(uuid7()): data})
```

### Batch Operations

```python
# Insert multiple entries at once (single call).
await terms_map.insert(
    context,
    entries={
        "api": json.dumps({...}).encode("utf-8"),
        "rest": json.dumps({...}).encode("utf-8"),
        "grpc": json.dumps({...}).encode("utf-8"),
    },
)

# Remove multiple keys at once (single call).
await terms_map.remove(
    context,
    keys=["api", "rest", "grpc"],
)
```

### Multiple Operations on Same Map

When calling methods on the same named SortedMap multiple times within
the same context, use `.idempotently()` with unique aliases:

```python
# Multiple inserts on same map require idempotency guards.
terms_map = SortedMap.ref("terms")

await terms_map.idempotently("insert_api").insert(
    context,
    entries={"api": data1},
)

await terms_map.idempotently("insert_rest").insert(
    context,
    entries={"rest": data2},
)
```

Different named maps don't require guards:

```python
# These are different maps - no conflict.
terms_map = SortedMap.ref("terms")
recent_map = SortedMap.ref("recent")

await terms_map.insert(context, entries={...})  # Fine
await recent_map.insert(context, entries={...}) # Also fine
```

## Running

```bash
cd examples/define
uv run python example.py
```
