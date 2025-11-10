"""
Document Processing with Mixed Idempotency Patterns.

Demonstrates combining `at_least_once` and `at_most_once` in a single workflow
for document processing with external API calls and multi-step operations.
"""

import asyncio
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict

# Add api/ to Python path for generated proto code.
api_path = Path(__file__).parent.parent.parent / "api"
if api_path.exists():
    sys.path.insert(0, str(api_path))

from reboot.aio.workflows import (
    at_least_once,
    at_most_once,
    AtMostOnceFailedBeforeCompleting,
)
from reboot.mcp.server import DurableMCP, DurableContext
from reboot.std.collections.v1.sorted_map import SortedMap

# Initialize MCP server.
mcp = DurableMCP(path="/mcp")


class NetworkError(Exception):
    """Temporary network error (retryable)."""

    pass


class InvalidDocumentError(Exception):
    """Document format is invalid (not retryable)."""

    pass


class QuotaExceededError(Exception):
    """API quota exceeded (not retryable)."""

    pass


async def simulate_ocr_api(content: str) -> str:
    """
    Simulate external OCR API call.

    May raise `NetworkError` (retryable) or `InvalidDocumentError` (not
    retryable).
    """
    # Simulate network issues.
    if random.random() < 0.15:
        raise NetworkError("OCR service timeout")

    # Simulate invalid documents.
    if random.random() < 0.05:
        raise InvalidDocumentError("Unsupported document format")

    # Return simulated OCR text.
    return f"Extracted text from document: {content[:50]}..."


async def simulate_translation_api(text: str, target_lang: str) -> str:
    """
    Simulate external translation API call.

    May raise `NetworkError` (retryable) or `QuotaExceededError` (not
    retryable).
    """
    # Simulate network issues.
    if random.random() < 0.1:
        raise NetworkError("Translation service timeout")

    # Simulate quota exceeded.
    if random.random() < 0.03:
        raise QuotaExceededError("Daily translation quota exceeded")

    # Return simulated translation.
    return f"[{target_lang}] {text}"


@mcp.tool()
async def process_document(
    file_id: str,
    target_language: str = "en",
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Process a document through OCR and translation pipeline.

    This demonstrates a complex workflow combining:
    - `at_least_once` for idempotent steps (file lookup, result storage)
    - `at_most_once` for external API calls with side effects

    Args:
        file_id: The file ID to process.
        target_language: Target language code for translation.
        context: The durable context.

    Returns:
        Processing result with job_id and status.
    """
    files_map = SortedMap.ref("files")
    results_map = SortedMap.ref("results")
    jobs_map = SortedMap.ref("jobs")

    # Generate job ID.
    job_id = f"job_{hashlib.md5(f'{file_id}_{target_language}'.encode()).hexdigest()[:12]}"

    # Step 1: Retrieve file metadata (idempotent read).
    async def get_file_metadata():
        response = await files_map.get(context, key=file_id)

        if not response.HasField("value"):
            raise ValueError(f"File {file_id} not found")

        file_data = json.loads(response.value.decode("utf-8"))
        return file_data

    # Use `at_least_once` for idempotent file lookup.
    file_metadata = await at_least_once(
        f"get_file_{file_id}",
        context,
        get_file_metadata,
        type=dict,
    )

    # Step 2: Perform OCR (external API, at most once).
    async def perform_ocr():
        # Call OCR API.
        extracted_text = await simulate_ocr_api(file_metadata["content"])

        # Store OCR result.
        ocr_result_key = f"{job_id}_ocr"
        await results_map.idempotently(f"store_ocr_{job_id}").insert(
            context,
            entries={
                ocr_result_key: json.dumps(
                    {"job_id": job_id, "step": "ocr", "text": extracted_text}
                ).encode("utf-8")
            },
        )

        return extracted_text

    try:
        # Use `at_most_once` to ensure OCR is called at most once.
        # Retry only on network errors.
        ocr_text = await at_most_once(
            f"ocr_{job_id}",
            context,
            perform_ocr,
            type=str,
            retryable_exceptions=[NetworkError],
        )

    except NetworkError:
        return {
            "status": "error",
            "job_id": job_id,
            "step": "ocr",
            "error": "OCR service unavailable",
            "retryable": True,
        }

    except AtMostOnceFailedBeforeCompleting:
        return {
            "status": "error",
            "job_id": job_id,
            "step": "ocr",
            "error": "OCR failed on previous attempt",
            "retryable": False,
        }

    except InvalidDocumentError as e:
        return {
            "status": "error",
            "job_id": job_id,
            "step": "ocr",
            "error": str(e),
            "retryable": False,
        }

    # Step 3: Translate text (external API, at most once).
    async def perform_translation():
        # Call translation API.
        translated_text = await simulate_translation_api(
            ocr_text, target_language
        )

        # Store translation result.
        translation_result_key = f"{job_id}_translation"
        await results_map.idempotently(f"store_translation_{job_id}").insert(
            context,
            entries={
                translation_result_key: json.dumps(
                    {
                        "job_id": job_id,
                        "step": "translation",
                        "text": translated_text,
                        "language": target_language,
                    }
                ).encode("utf-8")
            },
        )

        return translated_text

    try:
        # Use `at_most_once` for translation.
        translated_text = await at_most_once(
            f"translate_{job_id}",
            context,
            perform_translation,
            type=str,
            retryable_exceptions=[NetworkError],
        )

    except NetworkError:
        return {
            "status": "error",
            "job_id": job_id,
            "step": "translation",
            "error": "Translation service unavailable",
            "retryable": True,
        }

    except AtMostOnceFailedBeforeCompleting:
        return {
            "status": "error",
            "job_id": job_id,
            "step": "translation",
            "error": "Translation failed on previous attempt",
            "retryable": False,
        }

    except QuotaExceededError as e:
        return {
            "status": "error",
            "job_id": job_id,
            "step": "translation",
            "error": str(e),
            "retryable": False,
        }

    # Step 4: Store final job result (idempotent write).
    async def store_job_result():
        await jobs_map.insert(
            context,
            entries={
                job_id: json.dumps(
                    {
                        "job_id": job_id,
                        "file_id": file_id,
                        "target_language": target_language,
                        "status": "completed",
                        "result": translated_text,
                    }
                ).encode("utf-8")
            },
        )
        return job_id

    # Use `at_least_once` for final storage.
    final_job_id = await at_least_once(
        f"store_job_{job_id}",
        context,
        store_job_result,
        type=str,
    )

    return {
        "status": "success",
        "job_id": final_job_id,
        "result": translated_text,
    }


@mcp.tool()
async def upload_file(
    file_id: str,
    content: str,
    metadata: Dict[str, str] = None,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Upload a file for processing.

    Args:
        file_id: Unique file identifier.
        content: File content.
        metadata: Optional metadata dictionary.
        context: The durable context.

    Returns:
        Upload confirmation.
    """
    files_map = SortedMap.ref("files")

    await files_map.insert(
        context,
        entries={
            file_id: json.dumps(
                {
                    "file_id": file_id,
                    "content": content,
                    "metadata": metadata or {},
                }
            ).encode("utf-8")
        },
    )

    return {"status": "success", "file_id": file_id}


@mcp.tool()
async def get_job_status(
    job_id: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Get job processing status and result.

    Args:
        job_id: The job ID to query.
        context: The durable context.

    Returns:
        Job status and result if completed.
    """
    jobs_map = SortedMap.ref("jobs")

    response = await jobs_map.get(context, key=job_id)

    if not response.HasField("value"):
        return {"status": "error", "message": "Job not found"}

    job_data = json.loads(response.value.decode("utf-8"))

    return {"status": "success", "job": job_data}


async def main():
    """Start the document processing example server."""
    await mcp.application().run()


if __name__ == "__main__":
    asyncio.run(main())
