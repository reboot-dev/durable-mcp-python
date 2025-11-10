"""
Example client for technical glossary demonstration.
"""

import asyncio
from reboot.mcp.client import connect

URL = "http://localhost:9991"


async def main():
    """Run technical glossary example client."""
    async with connect(URL + "/mcp") as (
        session,
        session_id,
        protocol_version,
    ):
        print("Connected to define example server")
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

        # Example 1: Add technical terms.
        print("=" * 60)
        print("Example 1: Add technical terms to glossary")
        print("=" * 60)

        terms = [
            (
                "API",
                "Application Programming Interface - A set of protocols "
                "for building software",
                "architecture",
                ["REST API", "GraphQL API"],
            ),
            (
                "REST",
                "Representational State Transfer - Architectural style "
                "for distributed systems",
                "architecture",
                ["RESTful services", "HTTP methods"],
            ),
            (
                "gRPC",
                "Google Remote Procedure Call - High-performance RPC "
                "framework",
                "networking",
                ["Protocol Buffers", "HTTP/2"],
            ),
            (
                "Docker",
                "Platform for developing and running containerized "
                "applications",
                "devops",
                ["containers", "images", "Dockerfile"],
            ),
            (
                "Kubernetes",
                "Container orchestration platform for automating "
                "deployment and scaling",
                "devops",
                ["K8s", "pods", "deployments"],
            ),
        ]

        for term, definition, category, examples in terms:
            result = await session.call_tool(
                "add_term",
                {
                    "term": term,
                    "definition": definition,
                    "category": category,
                    "examples": examples,
                },
            )
            print(f"Added: {result.content[0].text}")

        print()

        # Example 2: Look up term definitions.
        print("=" * 60)
        print("Example 2: Look up term definitions")
        print("=" * 60)

        for term in ["API", "gRPC", "Docker"]:
            result = await session.call_tool(
                "define",
                {"term": term},
            )
            print(f"Definition of {term}: {result.content[0].text}")
            print()

        # Example 3: Case-insensitive lookup.
        print("=" * 60)
        print("Example 3: Case-insensitive lookup")
        print("=" * 60)

        # Demonstrate that lookups work regardless of case.
        for query in ["grpc", "GRPC", "GrPc"]:
            result = await session.call_tool(
                "define",
                {"term": query},
            )
            print(f"Lookup '{query}': {result.content[0].text}")
            print()

        # Example 4: List terms alphabetically.
        print("=" * 60)
        print("Example 4: List terms alphabetically")
        print("=" * 60)

        result = await session.call_tool(
            "list_terms",
            {"start_with": "", "limit": 10},
        )
        print(f"Terms (all): {result.content[0].text}")
        print()

        # Example 5: Search by prefix.
        print("=" * 60)
        print("Example 5: Search terms by prefix")
        print("=" * 60)

        result = await session.call_tool(
            "search_terms",
            {"prefix": "gR", "limit": 5},
        )
        print(f"Terms starting with 'gR': {result.content[0].text}")
        print()

        # Example 6: Get recently added terms.
        print("=" * 60)
        print("Example 6: Get recently added terms")
        print("=" * 60)

        result = await session.call_tool(
            "recent_terms",
            {"limit": 3},
        )
        print(f"Recent terms: {result.content[0].text}")
        print()

        # Example 7: Remove a term.
        print("=" * 60)
        print("Example 7: Remove a term")
        print("=" * 60)

        result = await session.call_tool(
            "remove_term",
            {"term": "Docker"},
        )
        print(f"Removed: {result.content[0].text}")
        print()

        # Verify removal.
        result = await session.call_tool(
            "define",
            {"term": "Docker"},
        )
        print(f"Lookup after removal: {result.content[0].text}")
        print()

        print("Define example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
