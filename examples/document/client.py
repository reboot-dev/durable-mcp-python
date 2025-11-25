"""
Example client for document processing demonstration.
"""

import asyncio
import json
from reboot.mcp.client import connect

URL = "http://localhost:9991"


async def main():
    """Run document processing example client."""
    async with connect(URL + "/mcp") as (
        session,
        session_id,
        protocol_version,
    ):
        print("Connected to document example server")
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

        # Example 1: Upload files.
        print("=" * 60)
        print("Example 1: Upload files for processing")
        print("=" * 60)

        files = [
            ("file_001", "invoice.pdf", "application/pdf"),
            ("file_002", "contract.pdf", "application/pdf"),
            ("file_003", "report.docx", "application/vnd.openxmlformats"),
        ]

        file_ids = []
        for file_id, filename, content_type in files:
            result = await session.call_tool(
                "upload_file",
                {
                    "file_id": file_id,
                    "content": f"Binary content of {filename}",
                    "metadata": {
                        "filename": filename,
                        "content_type": content_type,
                    },
                },
            )
            print(f"Uploaded: {result.content[0].text}")

            # Extract file_id from result for later use.
            try:
                data = json.loads(result.content[0].text)
                if data.get("status") == "success":
                    file_ids.append(data["file_id"])
            except json.JSONDecodeError:
                print(f"  Error parsing response: {result.content[0].text}")

        print()

        # Example 2: Process documents.
        print("=" * 60)
        print("Example 2: Process documents (OCR + Translation)")
        print("=" * 60)

        job_ids = []
        for file_id in file_ids:
            result = await session.call_tool(
                "process_document",
                {"file_id": file_id, "target_language": "es"},
            )
            print(f"Processing result: {result.content[0].text}")

            # Extract job_id if successful.
            try:
                data = json.loads(result.content[0].text)
                if data.get("status") == "success":
                    job_ids.append(data.get("job_id"))
            except json.JSONDecodeError:
                pass

            print()

        # Example 3: Check job status.
        print("=" * 60)
        print("Example 3: Check processing job status")
        print("=" * 60)

        # Use the job_id from first successful processing.
        if job_ids and job_ids[0]:
            result = await session.call_tool(
                "get_job_status",
                {"job_id": job_ids[0]},
            )
            print(f"Job status: {result.content[0].text}")
            print()

        # Example 4: Process with different language.
        print("=" * 60)
        print("Example 4: Process document to French")
        print("=" * 60)

        if file_ids:
            result = await session.call_tool(
                "process_document",
                {"file_id": file_ids[0], "target_language": "fr"},
            )
            print(f"Processing result: {result.content[0].text}")
            print()

        print("Document example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
