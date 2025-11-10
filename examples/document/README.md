# Document Processing

Document processing pipeline combining `at_least_once` and
`at_most_once` patterns.

## Overview

Real-world workflows often need both idempotency patterns. Use
`at_least_once` for idempotent operations (reads, storage) and
`at_most_once` for operations with side effects (external APIs).

## Workflow

```
Upload File -> Process Document
               |- Step 1: Get file metadata (at_least_once)
               |- Step 2: OCR extraction (at_most_once)
               |- Step 3: Translation (at_most_once)
               |- Step 4: Store result (at_least_once)
```

## Pattern

```python
@mcp.tool()
async def process_document(
    file_id: str,
    target_language: str = "en",
    context: DurableContext = None,
) -> dict:
    """Process document through OCR and translation pipeline."""

    # Step 1: Idempotent file lookup.
    async def get_file_metadata():
        response = await files_map.get(context, key=file_id)
        if not response.HasField("value"):
            raise ValueError(f"File {file_id} not found")
        return json.loads(response.value.decode("utf-8"))

    file_metadata = await at_least_once(
        f"get_file_{file_id}",
        context,
        get_file_metadata,
        type=dict,
    )

    # Step 2: OCR (external API, at most once).
    async def perform_ocr():
        extracted_text = await simulate_ocr_api(file_metadata["content"])
        # Store intermediate result with idempotency guard.
        await results_map.idempotently(f"store_ocr_{job_id}").insert(
            context,
            entries={...},
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
        # Store intermediate result with idempotency guard.
        await results_map.idempotently(f"store_translation_{job_id}").insert(
            context,
            entries={...},
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

    # Step 4: Idempotent final storage.
    async def store_job_result():
        await jobs_map.insert(context, entries={job_id: ...})
        return job_id

    final_job_id = await at_least_once(
        f"store_job_{job_id}",
        context,
        store_job_result,
        type=str,
    )

    return {"status": "success", "job_id": final_job_id}
```

## Pattern Selection

| Operation | Pattern | Reason |
|-----------|---------|--------|
| File lookup | `at_least_once` | Idempotent read |
| OCR API call | `at_most_once` | External API side effects |
| Translation API | `at_most_once` | External API quota |
| Store result | `at_least_once` | Idempotent write |

## Error Handling

### For at_most_once Steps

Each external API call needs three exception handlers:

```python
try:
    result = await at_most_once(
        "operation",
        context,
        operation_func,
        type=str,
        retryable_exceptions=[NetworkError],
    )
except NetworkError:
    # Retryable error after retries exhausted.
    return {"status": "error", "retryable": True}
except AtMostOnceFailedBeforeCompleting:
    # Previous attempt failed with non-retryable error.
    return {"status": "error", "retryable": False}
except (InvalidDocumentError, QuotaExceededError) as e:
    # First attempt with non-retryable error.
    return {"status": "error", "message": str(e)}
```

### For at_least_once Steps

Let exceptions propagate (they'll cause workflow retry):

```python
# No try/except needed - idempotent operations can safely retry.
result = await at_least_once(
    "operation",
    context,
    operation_func,
    type=dict,
)
```

## Multiple Operations on Same SortedMap

When calling a method on the **same named SortedMap** multiple times
within the same context, use `.idempotently()` with a unique alias for
each call:

```python
# Inside an `at_most_once` or `at_least_once` callable:
async def perform_operation():
    results_map = SortedMap.ref("results")

    # First insert on "results" map.
    await results_map.idempotently("store_step1").insert(
        context,
        entries={key1: value1},
    )

    # Second insert on same "results" map - needs different alias.
    await results_map.idempotently("store_step2").insert(
        context,
        entries={key2: value2},
    )

    return result
```

Without `.idempotently()`, the second call raises:

```
ValueError: To call 'rbt.std.collections.v1.SortedMapMethods.Insert'
of 'results' more than once using the same context an idempotency
alias or key must be specified
```

**Different maps don't need idempotency guards:**

```python
# These are different named maps - no conflict.
results_map = SortedMap.ref("results")
jobs_map = SortedMap.ref("jobs")

await results_map.insert(context, entries={...})  # Fine
await jobs_map.insert(context, entries={...})     # Also fine
```

**For loop operations:**

Use dynamic aliases when calling the same map in loops:

```python
items_map = SortedMap.ref("items")
for i in range(5):
    await items_map.idempotently(f"insert_item_{i}").insert(
        context,
        entries={f"item_{i}": data},
    )
```

This pattern applies to all SortedMap methods (`insert`, `get`,
`range`, `remove`) when called multiple times on the same named map
within the same context.

## Retry Scenarios

### Network Error During OCR

1. Step 1: File lookup succeeds
2. Step 2: OCR API raises `NetworkError`
3. `at_most_once` retries OCR
4. OCR succeeds on retry
5. Steps 3-4 proceed normally

### Invalid Document Error

1. Step 1: File lookup succeeds
2. Step 2: OCR API raises `InvalidDocumentError`
3. Exception propagates (not in `retryable_exceptions`)
4. Tool returns error response

### Tool Retry After OCR Success

1. Initial call: Steps 1-2 succeed, network issue prevents response
2. Tool retried by MCP framework
3. Step 1: `at_least_once` returns cached file metadata
4. Step 2: `at_most_once` returns cached OCR text
5. Step 3: Translation proceeds

## Best Practices

Choose the right pattern for each step:

```python
# Good: Idempotent read uses `at_least_once`.
data = await at_least_once("read", context, read_func, type=dict)

# Good: External API uses `at_most_once`.
result = await at_most_once(
    "api",
    context,
    api_func,
    type=str,
    retryable_exceptions=[...],
)

# Bad: Using `at_most_once` for idempotent read (unnecessary).
data = await at_most_once("read", context, read_func, type=dict)
```

Store intermediate results:

```python
async def expensive_operation():
    result = await external_api()
    # Store immediately so we don't lose it.
    # Use `.idempotently()` if multiple SortedMap operations occur
    # in the same context.
    await results_map.idempotently("store_result").insert(
        context,
        entries={...},
    )
    return result
```

Use distinct aliases:

```python
# Each step has unique alias.
await at_least_once(f"get_file_{file_id}", ...)
await at_most_once(f"ocr_{job_id}", ...)
await at_most_once(f"translate_{job_id}", ...)
await at_least_once(f"store_job_{job_id}", ...)
```

## Running

```bash
cd examples/document
uv run python example.py
```
