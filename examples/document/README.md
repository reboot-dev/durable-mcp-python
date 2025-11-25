# Document Processing

Document processing pipeline combining `at_least_once` and `at_most_once` patterns with OrderedMap and Pydantic models.

## Overview

Real-world workflows often need both idempotency patterns. Use `at_least_once` for idempotent operations (reads, storage) and `at_most_once` for operations with side effects (external APIs).

This example demonstrates:
- OrderedMap for durable storage
- Pydantic models for type-safe data structures
- `from_model()` / `as_model()` for serialization
- Mixed idempotency patterns in a single workflow

## Workflow

```
Upload File -> Process Document
               |- Step 1: Get file metadata (at_least_once)
               |- Step 2: OCR extraction (at_most_once)
               |- Step 3: Translation (at_most_once)
               |- Step 4: Store result (at_least_once)
```

## Pydantic Models

```python
from pydantic import BaseModel

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
```

## Pattern with OrderedMap + Pydantic

```python
from rebootdev.protobuf import from_model, as_model
from reboot.std.collections.ordered_map.v1.ordered_map import OrderedMap

@mcp.tool()
async def process_document(
    file_id: str,
    target_language: str = "en",
    context: DurableContext = None,
) -> dict:
    """Process document through OCR and translation pipeline."""

    files_map = OrderedMap.ref("files")
    results_map = OrderedMap.ref("results")
    jobs_map = OrderedMap.ref("jobs")

    # Step 1: Idempotent file lookup.
    async def get_file_metadata():
        response = await files_map.search(context, key=file_id)
        if not response.found:
            raise ValueError(f"File {file_id} not found")

        # Deserialize with Pydantic.
        file_data = as_model(response.value, FileData)
        return file_data.model_dump()

    file_metadata = await at_least_once(
        f"get_file_{file_id}",
        context,
        get_file_metadata,
        type=dict,
    )

    # Step 2: OCR (external API, at most once).
    async def perform_ocr():
        extracted_text = await simulate_ocr_api(file_metadata["content"])

        # Create Pydantic model and store with from_model().
        ocr_result = OCRResult(
            job_id=job_id,
            step="ocr",
            text=extracted_text,
        )
        await results_map.idempotently(f"store_ocr_{job_id}").insert(
            context,
            key=f"{job_id}_ocr",
            value=from_model(ocr_result),
        )
        return extracted_text

    try:
        ocr_text = await at_most_once(
            f"ocr_{job_id}",
            context,
            perform_ocr,
            type=str,
            retryable_exceptions=[NetworkError],
        )
    except NetworkError:
        return {"status": "error", "step": "ocr", "error": "..."}
    except AtMostOnceFailedBeforeCompleting:
        return {"status": "error", "step": "ocr", "error": "..."}
    except InvalidDocumentError as e:
        return {"status": "error", "step": "ocr", "error": str(e)}

    # Step 3: Translation (external API, at most once).
    async def perform_translation():
        translated_text = await simulate_translation_api(
            ocr_text,
            target_language,
        )

        # Create Pydantic model and store.
        translation_result = TranslationResult(
            job_id=job_id,
            step="translation",
            text=translated_text,
            language=target_language,
        )
        await results_map.idempotently(f"store_translation_{job_id}").insert(
            context,
            key=f"{job_id}_translation",
            value=from_model(translation_result),
        )
        return translated_text

    try:
        translated_text = await at_most_once(
            f"translate_{job_id}",
            context,
            perform_translation,
            type=str,
            retryable_exceptions=[NetworkError],
        )
    except NetworkError:
        return {"status": "error", "step": "translation", "error": "..."}
    except AtMostOnceFailedBeforeCompleting:
        return {"status": "error", "step": "translation", "error": "..."}
    except QuotaExceededError as e:
        return {"status": "error", "step": "translation", "error": str(e)}

    # Step 4: Store final result (idempotent write).
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

    final_job_id = await at_least_once(
        f"store_job_{job_id}",
        context,
        store_job_result,
        type=str,
    )

    return {"status": "success", "job_id": final_job_id}
```

## Error Handling

### Retryable Errors
- `NetworkError`: Temporary network issues (API timeouts)
- Handled by `at_most_once` with automatic retry

### Non-Retryable Errors
- `InvalidDocumentError`: Document format not supported
- `QuotaExceededError`: API quota exceeded
- Caught and returned as error responses

## Idempotency Guards

### at_least_once
- Used for: File reads, result storage
- Behavior: Caches return value, retries until success
- Ideal for: Idempotent operations that should eventually complete

### at_most_once
- Used for: External API calls (OCR, translation)
- Behavior: Executes at most once, even if retried
- Ideal for: Operations with side effects (charges, state changes)

### Combined Pattern
The `.idempotently()` modifier on `insert()` ensures intermediate results are stored exactly once, even if the enclosing `at_most_once` block retries.

## Registering Servicers

OrderedMap requires servicer registration:

```python
from reboot.std.collections.ordered_map.v1.ordered_map import (
    OrderedMap,
    servicers as ordered_map_servicers,
)

async def main():
    await mcp.application(servicers=ordered_map_servicers()).run()
```

## Benefits

- Type Safety: Pydantic validates all intermediate results
- Clear Errors: Each step has specific error types
- Resumable: If translation fails, OCR doesn't re-run
- Protobuf Integration: OrderedMap with `from_model` / `as_model`
- Audit Trail: Intermediate results stored for debugging

## Use Case

Perfect for workflows that:
- Call external APIs with charges or side effects
- Need to resume after partial failures
- Require validation of intermediate results
- Want type-safe data structures throughout
