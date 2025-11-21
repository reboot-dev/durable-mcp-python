# Technical Glossary

Complete OrderedMap CRUD reference using a technical glossary with Pydantic models.

## Overview

Demonstrates all OrderedMap operations with type-safe Pydantic models through a practical use case: maintaining a technical glossary with both alphabetical and chronological indexes.

## OrderedMap + Pydantic Pattern

This example shows the **OrderedMap with protobuf Values** pattern:
- Uses `OrderedMap` for durable key-value storage
- Pydantic models for type safety and validation
- `from_model()` / `as_model()` helpers for serialization

## OrderedMap Operations

| Operation | Method | Use Case |
|-----------|--------|----------|
| Insert | `insert(context, key="...", value=...)` | Add terms |
| Search | `search(context, key="...")` | Look up term |
| Range | `range(context, start_key=..., limit=...)` | Browse alphabetically |
| Reverse Range | `reverse_range(context, limit=...)` | Recent additions |
| Remove | `remove(context, key="...")` | Delete terms |

## Architecture

### Pydantic Model

```python
from pydantic import BaseModel

class TermEntry(BaseModel):
    """Type-safe term entry."""
    term: str
    definition: str
    category: str = "general"
    examples: List[str] = []
    timestamp: int
```

### Two OrderedMaps for Different Access Patterns

```python
# Map 1: Alphabetical index (keyed by term name).
terms_map = OrderedMap.ref("terms")
# Key: "api" -> Value: `protobuf.Value(TermEntry)`.

# Map 2: Chronological index (keyed by `UUIDv7`).
recent_map = OrderedMap.ref("recent")
# Key: "018c1234-..." -> Value: `protobuf.Value(TermEntry)`.
```

## Usage Examples

### Insert with Pydantic

Add terms with type validation:

```python
from rebootdev.protobuf import from_model

@mcp.tool()
async def add_term(
    term: str,
    definition: str,
    category: str = "general",
    examples: List[str] = None,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """Add a technical term to the glossary."""
    timestamp = int(time.time() * 1000)

    # Create Pydantic model instance.
    term_entry = TermEntry(
        term=term,
        definition=definition,
        category=category,
        examples=examples or [],
        timestamp=timestamp,
    )

    # Insert into alphabetical map using `from_model()`.
    await terms_map.insert(
        context,
        key=term.lower(),
        value=from_model(term_entry),
    )

    # Insert into chronological map.
    recent_key = str(uuid7())
    await recent_map.insert(
        context,
        key=recent_key,
        value=from_model(term_entry),
    )

    return {"status": "success", "term": term}
```

### Search with Pydantic

Point lookup with type-safe deserialization:

```python
from rebootdev.protobuf import as_model

@mcp.tool()
async def define(
    term: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """Look up a term's definition."""
    response = await terms_map.search(context, key=term.lower())

    if not response.found:
        return {"status": "error", "message": "Term not found"}

    # Convert protobuf `Value` to Pydantic model.
    term_entry = as_model(response.value, TermEntry)

    return {"status": "success", "term": term_entry.model_dump()}
```

### Range Query

Browse terms alphabetically:

```python
@mcp.tool()
async def list_terms(
    start_with: str = "",
    limit: int = 50,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """List terms alphabetically."""
    response = await terms_map.range(
        context,
        start_key=start_with.lower() if start_with else None,
        limit=limit,
    )

    terms = []
    for entry in response.entries:
        # Deserialize each entry using `as_model()`.
        term_entry = as_model(entry.value, TermEntry)
        terms.append({
            "term": term_entry.term,
            "definition": term_entry.definition[:100] + "..."
                if len(term_entry.definition) > 100
                else term_entry.definition,
            "category": term_entry.category,
        })

    return {"status": "success", "count": len(terms), "terms": terms}
```

### Reverse Range

Get recently added terms:

```python
@mcp.tool()
async def recent_terms(
    limit: int = 20,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """Get recently added terms (newest first)."""
    response = await recent_map.reverse_range(
        context,
        limit=limit,
    )

    terms = []
    for entry in response.entries:
        term_entry = as_model(entry.value, TermEntry)
        terms.append({
            "term": term_entry.term,
            "definition": term_entry.definition[:100] + "...",
            "category": term_entry.category,
            "added_at": term_entry.timestamp,
        })

    return {"status": "success", "count": len(terms), "recent_terms": terms}
```

### Remove

Delete a term:

```python
@mcp.tool()
async def remove_term(
    term: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """Remove a term from the glossary."""
    # Check if term exists.
    response = await terms_map.search(context, key=term.lower())

    if not response.found:
        return {"status": "error", "message": "Term not found"}

    # Remove from alphabetical map.
    await terms_map.remove(context, key=term.lower())

    return {"status": "success", "message": f"Removed '{term}'"}
```

## Registering OrderedMap Servicers

**Important**: OrderedMap requires servicer registration:

```python
from reboot.std.collections.ordered_map.v1.ordered_map import (
    OrderedMap,
    servicers as ordered_map_servicers,
)

async def main():
    await mcp.application(servicers=ordered_map_servicers()).run()
```

## Benefits of OrderedMap + Pydantic

- Type Safety: Pydantic validates all data structures
- Clean API: `from_model()` / `as_model()` are explicit and readable
- IDE Support: Full autocomplete with `term_entry.field`
- Protobuf Integration: Works seamlessly with protobuf Values
- Validation: Catch errors at serialization boundaries

## When to Use OrderedMap vs SortedMap

**Use OrderedMap when:**
- You want protobuf Value integration
- Type safety with Pydantic is important
- You need the `from_model` / `as_model` pattern

**Use SortedMap when:**
- You prefer working with raw bytes
- You need batch operations (`entries={...}`)
- Simplicity is preferred over type safety

See other examples for SortedMap + Pydantic pattern (audit, steps, processing).
