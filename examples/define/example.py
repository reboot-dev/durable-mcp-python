"""
Technical Glossary with SortedMap CRUD Operations.

Demonstrates all SortedMap operations: insert, get, range, reverse_range,
and remove, using a technical terms glossary as an example.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add api/ to Python path for generated proto code.
api_path = Path(__file__).parent.parent.parent / "api"
if api_path.exists():
    sys.path.insert(0, str(api_path))

from reboot.mcp.server import DurableMCP, DurableContext
from reboot.std.collections.v1.sorted_map import SortedMap
from uuid7 import create as uuid7  # type: ignore[import-untyped]

# Initialize MCP server.
mcp = DurableMCP(path="/mcp")


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

    Stores the term in two SortedMaps:
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
    terms_map = SortedMap.ref("terms")
    recent_map = SortedMap.ref("recent")

    timestamp = int(time.time() * 1000)

    term_data = {
        "term": term,
        "definition": definition,
        "category": category,
        "examples": examples or [],
        "timestamp": timestamp,
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

    Uses the `get` method for point lookup.

    Args:
        term: The term to look up.
        context: The durable context.

    Returns:
        Term definition or error if not found.
    """
    terms_map = SortedMap.ref("terms")

    response = await terms_map.get(context, key=term.lower())

    if not response.HasField("value"):
        return {
            "status": "error",
            "message": f"Term '{term}' not found in glossary",
        }

    term_data = json.loads(response.value.decode("utf-8"))

    return {
        "status": "success",
        "term": term_data,
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
    terms_map = SortedMap.ref("terms")

    # Check if term exists first.
    response = await terms_map.get(context, key=term.lower())

    if not response.HasField("value"):
        return {
            "status": "error",
            "message": f"Term '{term}' not found",
        }

    # Remove from alphabetical map.
    await terms_map.remove(
        context,
        keys=[term.lower()],
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
    terms_map = SortedMap.ref("terms")

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
        term_data = json.loads(entry.value.decode("utf-8"))
        terms.append({
            "term": term_data["term"],
            "definition": term_data["definition"][:100] + "..."
                if len(term_data["definition"]) > 100
                else term_data["definition"],
            "category": term_data["category"],
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
    terms_map = SortedMap.ref("terms")

    # Get all terms and filter by category.
    # Note: In production, you'd use a separate category-indexed map.
    response = await terms_map.range(
        context,
        limit=1000,  # Fetch more to filter.
    )

    terms = []
    for entry in response.entries:
        term_data = json.loads(entry.value.decode("utf-8"))
        if term_data["category"] == category:
            terms.append({
                "term": term_data["term"],
                "definition": term_data["definition"],
                "examples": term_data["examples"],
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
    recent_map = SortedMap.ref("recent")

    response = await recent_map.reverse_range(
        context,
        limit=limit,
    )

    terms = []
    for entry in response.entries:
        term_data = json.loads(entry.value.decode("utf-8"))
        terms.append({
            "term": term_data["term"],
            "definition": term_data["definition"][:100] + "..."
                if len(term_data["definition"]) > 100
                else term_data["definition"],
            "category": term_data["category"],
            "added_at": term_data["timestamp"],
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

    Demonstrates range query with start and end boundaries.

    Args:
        prefix: Search prefix.
        limit: Maximum results.
        context: The durable context.

    Returns:
        Terms matching the prefix.
    """
    terms_map = SortedMap.ref("terms")

    # Calculate end key for prefix range.
    # For prefix "api", we want keys >= "api" and < "apj".
    start_key = prefix.lower()
    # Increment last character for upper bound.
    end_key = prefix[:-1] + chr(ord(prefix[-1]) + 1) if prefix else None

    if end_key:
        response = await terms_map.range(
            context,
            start_key=start_key,
            end_key=end_key.lower(),
            limit=limit,
        )
    else:
        response = await terms_map.range(
            context,
            start_key=start_key,
            limit=limit,
        )

    terms = []
    for entry in response.entries:
        term_data = json.loads(entry.value.decode("utf-8"))
        terms.append({
            "term": term_data["term"],
            "definition": term_data["definition"],
            "category": term_data["category"],
        })

    return {
        "status": "success",
        "prefix": prefix,
        "count": len(terms),
        "terms": terms,
    }


async def main():
    """Start the technical glossary server."""
    await mcp.application().run()


if __name__ == "__main__":
    asyncio.run(main())
