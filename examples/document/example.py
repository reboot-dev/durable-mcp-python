"""
Document Processing with Mixed Idempotency Patterns.

Demonstrates combining `at_least_once` and `at_most_once` in a single workflow
for document processing with external API calls and multi-step operations.
"""

import asyncio
import hashlib
import random
import sys
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel

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
from reboot.std.collections.ordered_map.v1.ordered_map import (
    OrderedMap,
    servicers as ordered_map_servicers,
)
from rebootdev.protobuf import from_model, as_model

# Initialize MCP server.
mcp = DurableMCP(path="/mcp")


# Pydantic models for document processing.
class FileData(BaseModel):
    """File data model."""

    file_id: str
    content: str
    metadata: Dict[str, str] = {}


class OCRResult(BaseModel):
    """OCR processing result."""

    job_id: str
    step: str
    text: str


class TranslationResult(BaseModel):
    """Translation processing result."""

    job_id: str
    step: str
    text: str
    language: str


class JobResult(BaseModel):
    """Final job result."""

    job_id: str
    file_id: str
    target_language: str
    status: str
    result: str


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
    files_map = OrderedMap.ref("files")
    results_map = OrderedMap.ref("results")
    jobs_map = OrderedMap.ref("jobs")

    # Generate job ID.
    job_id = f"job_{hashlib.md5(f'{file_id}_{target_language}'.encode()).hexdigest()[:12]}"

    # Step 1: Retrieve file metadata (idempotent read).
    async def get_file_metadata():
        response = await files_map.search(context, key=file_id)

        if not response.found:
            raise ValueError(f"File {file_id} not found")

        file_data = as_model(response.value, FileData)
        return file_data.model_dump()

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

        # Create Pydantic model and store OCR result.
        ocr_result_key = f"{job_id}_ocr"
        ocr_result = OCRResult(
            job_id=job_id,
            step="ocr",
            text=extracted_text,
        )
        await results_map.idempotently(f"store_ocr_{job_id}").insert(
            context,
            key=ocr_result_key,
            value=from_model(ocr_result),
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

        # Create Pydantic model and store translation result.
        translation_result_key = f"{job_id}_translation"
        translation_result = TranslationResult(
            job_id=job_id,
            step="translation",
            text=translated_text,
            language=target_language,
        )
        await results_map.idempotently(f"store_translation_{job_id}").insert(
            context,
            key=translation_result_key,
            value=from_model(translation_result),
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
        job_result = JobResult(
            job_id=job_id,
            file_id=file_id,
            target_language=target_language,
            status="completed",
            result=translated_text,
        )
        await jobs_map.insert(
            context,
            key=job_id,
            value=from_model(job_result),
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
    files_map = OrderedMap.ref("files")

    file_data = FileData(
        file_id=file_id,
        content=content,
        metadata=metadata or {},
    )
    await files_map.insert(
        context,
        key=file_id,
        value=from_model(file_data),
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
    jobs_map = OrderedMap.ref("jobs")

    response = await jobs_map.search(context, key=job_id)

    if not response.found:
        return {"status": "error", "message": "Job not found"}

    job_result = as_model(response.value, JobResult)

    return {"status": "success", "job": job_result.model_dump()}


async def main():
    """Start the document processing example server."""
    await mcp.application(servicers=ordered_map_servicers()).run()


if __name__ == "__main__":
    asyncio.run(main())
