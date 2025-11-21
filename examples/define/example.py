"""
Technical Glossary with OrderedMap CRUD Operations.

Demonstrates OrderedMap operations using Pydantic models and
from_model/as_model helpers: Insert, Search, Range, ReverseRange, and
Remove, using a technical terms glossary as an example.
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel

# Add api/ to Python path for generated proto code.
api_path = Path(__file__).parent.parent.parent / "api"
if api_path.exists():
    sys.path.insert(0, str(api_path))

from reboot.mcp.server import DurableMCP, DurableContext
from reboot.std.collections.ordered_map.v1.ordered_map import (
    OrderedMap,
    servicers as ordered_map_servicers,
)
from rebootdev.protobuf import from_model, as_model
from uuid7 import create as uuid7  # type: ignore[import-untyped]

# Initialize MCP server.
mcp = DurableMCP(path="/mcp")


# Pydantic model for term entries.
class TermEntry(BaseModel):
    term: str
    definition: str
    category: str = "general"
    examples: List[str] = []
    timestamp: int


@mcp.tool()
async def add_term(
    term: str,
    definition: str,
    category: str = "general",
    examples: List[str] = None,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Add a technical term to the glossary.

    Stores the term in two OrderedMaps:
    - Alphabetically by term name (for lookup and browsing).
    - Chronologically by UUIDv7 (for recent additions).

    Args:
        term: The technical term to define.
        definition: Definition of the term.
        category: Category (e.g., "programming", "architecture").
        examples: Optional list of usage examples.
        context: The durable context.

    Returns:
        Confirmation with the term and timestamp.
    """
    terms_map = OrderedMap.ref("terms")
    recent_map = OrderedMap.ref("recent")

    timestamp = int(time.time() * 1000)

    # Create Pydantic model instance.
    term_entry = TermEntry(
        term=term,
        definition=definition,
        category=category,
        examples=examples or [],
        timestamp=timestamp,
    )

    # Insert into alphabetical map (keyed by `term`).
    await terms_map.insert(
        context,
        key=term.lower(),
        value=from_model(term_entry),
    )

    # Insert into chronological map (keyed by `UUIDv7`).
    recent_key = str(uuid7())
    await recent_map.insert(
        context,
        key=recent_key,
        value=from_model(term_entry),
    )

    return {
        "status": "success",
        "term": term,
        "timestamp": timestamp,
    }


@mcp.tool()
async def define(
    term: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Look up a term's definition.

    Uses the `search` method for point lookup.

    Args:
        term: The term to look up.
        context: The durable context.

    Returns:
        Term definition or error if not found.
    """
    terms_map = OrderedMap.ref("terms")

    response = await terms_map.search(context, key=term.lower())

    if not response.found:
        return {
            "status": "error",
            "message": f"Term '{term}' not found in glossary",
        }

    term_entry = as_model(response.value, TermEntry)

    return {
        "status": "success",
        "term": term_entry.model_dump(),
    }


@mcp.tool()
async def remove_term(
    term: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Remove a term from the glossary.

    Demonstrates the `remove` method. Note: Only removes from alphabetical
    map. The recent map entry remains (showing historical additions).

    Args:
        term: The term to remove.
        context: The durable context.

    Returns:
        Confirmation of removal.
    """
    terms_map = OrderedMap.ref("terms")

    # Check if term exists first.
    response = await terms_map.search(context, key=term.lower())

    if not response.found:
        return {
            "status": "error",
            "message": f"Term '{term}' not found",
        }

    # Remove from alphabetical map.
    await terms_map.remove(
        context,
        key=term.lower(),
    )

    return {
        "status": "success",
        "message": f"Removed '{term}' from glossary",
    }


@mcp.tool()
async def list_terms(
    start_with: str = "",
    limit: int = 50,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    List terms alphabetically.

    Demonstrates the `range` method with optional start key.

    Args:
        start_with: Optional prefix to start listing from.
        limit: Maximum number of terms to return.
        context: The durable context.

    Returns:
        List of terms in alphabetical order.
    """
    terms_map = OrderedMap.ref("terms")

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

    terms = []
    for entry in response.entries:
        term_entry = as_model(entry.value, TermEntry)
        terms.append({
            "term": term_entry.term,
            "definition": term_entry.definition[:100] + "..."
                if len(term_entry.definition) > 100
                else term_entry.definition,
            "category": term_entry.category,
        })

    return {
        "status": "success",
        "count": len(terms),
        "terms": terms,
    }


@mcp.tool()
async def browse_category(
    category: str,
    limit: int = 50,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Browse terms by category.

    Uses prefix-based range query on category-prefixed keys.

    Args:
        category: Category to browse.
        limit: Maximum number of terms.
        context: The durable context.

    Returns:
        Terms in the specified category.
    """
    terms_map = OrderedMap.ref("terms")

    # Get all terms and filter by category.
    # Note: In production, you'd use a separate category-indexed map.
    response = await terms_map.range(
        context,
        limit=1000,  # Fetch more to filter.
    )

    terms = []
    for entry in response.entries:
        term_entry = as_model(entry.value, TermEntry)
        if term_entry.category == category:
            terms.append({
                "term": term_entry.term,
                "definition": term_entry.definition,
                "examples": term_entry.examples,
            })
            if len(terms) >= limit:
                break

    return {
        "status": "success",
        "category": category,
        "count": len(terms),
        "terms": terms,
    }


@mcp.tool()
async def recent_terms(
    limit: int = 20,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Get recently added terms.

    Demonstrates `reverse_range` on UUIDv7-keyed map to get chronological
    order (newest first).

    Args:
        limit: Maximum number of recent terms.
        context: The durable context.

    Returns:
        Recently added terms in reverse chronological order.
    """
    recent_map = OrderedMap.ref("recent")

    response = await recent_map.reverse_range(
        context,
        limit=limit,
    )

    terms = []
    for entry in response.entries:
        term_entry = as_model(entry.value, TermEntry)
        terms.append({
            "term": term_entry.term,
            "definition": term_entry.definition[:100] + "..."
                if len(term_entry.definition) > 100
                else term_entry.definition,
            "category": term_entry.category,
            "added_at": term_entry.timestamp,
        })

    return {
        "status": "success",
        "count": len(terms),
        "recent_terms": terms,
    }


@mcp.tool()
async def search_terms(
    prefix: str,
    limit: int = 20,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Search for terms by prefix.

    Demonstrates range query with client-side prefix filtering.
    Note: OrderedMap.range() only supports start_key, not end_key.

    Args:
        prefix: Search prefix.
        limit: Maximum results.
        context: The durable context.

    Returns:
        Terms matching the prefix.
    """
    terms_map = OrderedMap.ref("terms")

    start_key = prefix.lower()

    # Fetch more than limit to account for client-side filtering.
    response = await terms_map.range(
        context,
        start_key=start_key,
        limit=limit * 2,
    )

    terms = []
    for entry in response.entries:
        # Check if key still matches prefix.
        if not entry.key.startswith(start_key):
            break

        term_entry = as_model(entry.value, TermEntry)
        terms.append({
            "term": term_entry.term,
            "definition": term_entry.definition,
            "category": term_entry.category,
        })

        if len(terms) >= limit:
            break

    return {
        "status": "success",
        "prefix": prefix,
        "count": len(terms),
        "terms": terms,
    }


async def main():
    """Start the technical glossary server."""
    await mcp.application(servicers=ordered_map_servicers()).run()


if __name__ == "__main__":
    asyncio.run(main())
