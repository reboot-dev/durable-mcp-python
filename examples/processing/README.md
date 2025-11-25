# Payment Processing

Payment processing with `at_most_once` to prevent duplicate charges.

## Overview

Use `at_most_once` with `retryable_exceptions` to distinguish between
temporary failures (network errors) and permanent failures (payment
rejected). This prevents duplicate payments while allowing retries on
transient errors.

## Pattern

```python
@mcp.tool()
async def process_payment(
    amount: float,
    currency: str = "USD",
    context: DurableContext = None,
) -> dict:
    """Process payment via external API."""

    async def make_payment():
        # Call external payment API.
        result = await simulate_payment_api(amount, currency)

        # Store payment record.
        await payments_map.insert(context, entries={...})

        return result

    try:
        # Retry only on network errors.
        result = await at_most_once(
            f"payment_{amount}_{currency}",
            context,
            make_payment,
            type=dict,
            retryable_exceptions=[NetworkError],
        )

        return {"status": "success", "payment": result}

    except NetworkError:
        # Network error after retries exhausted.
        return {"status": "error", "message": "Service unavailable"}

    except AtMostOnceFailedBeforeCompleting:
        # Previous attempt failed with non-retryable error.
        return {"status": "error", "message": "Payment failed previously"}

    except (PaymentRejectedError, InsufficientFundsError) as e:
        # First attempt with non-retryable error.
        return {"status": "error", "message": str(e)}
```

## How It Works

### Retryable vs Non-Retryable

Define clear exception classes:

```python
# Retryable: Temporary failures.
class NetworkError(Exception):
    pass

# Non-retryable: Permanent failures.
class PaymentRejectedError(Exception):
    pass

class InsufficientFundsError(Exception):
    pass
```

Specify which exceptions should trigger retry:

```python
result = await at_most_once(
    "operation",
    context,
    operation_func,
    type=dict,
    retryable_exceptions=[NetworkError],  # Only retry these.
)
```

### Error Scenarios

**Network Error (Retryable)**

1. Initial attempt: `NetworkError` raised
2. `at_most_once` retries the operation
3. Second attempt succeeds
4. Result cached and returned

**Payment Rejected (Non-Retryable)**

1. Initial attempt: `PaymentRejectedError` raised
2. Exception propagates (not in `retryable_exceptions`)
3. Tool returns error response

**Tool Retry After Success**

1. Initial call: Steps succeed, network issue prevents response
2. Tool called again by MCP framework
3. `at_most_once` returns cached result

**Tool Retry After Rejection**

1. Initial call: `PaymentRejectedError` raised
2. Tool returns error response
3. Tool called again
4. `at_most_once` raises `AtMostOnceFailedBeforeCompleting`

### Three Exception Handlers

```python
try:
    result = await at_most_once(...)
    return {"status": "success", ...}

except NetworkError:
    # Retryable error after exhausting retries.
    return {"status": "error", "retryable": True}

except AtMostOnceFailedBeforeCompleting:
    # Previous attempt failed with non-retryable error.
    return {"status": "error", "retryable": False}

except (PaymentRejectedError, InsufficientFundsError) as e:
    # First attempt with non-retryable error.
    return {"status": "error", "message": str(e)}
```

## AtMostOnceFailedBeforeCompleting

Raised when:

1. Previous attempt failed with non-retryable exception
2. Tool is called again (retry by MCP framework)
3. `at_most_once` detects the previous failure

Purpose: Prevent re-executing operations that already failed
permanently.

## Best Practices

Be specific with `retryable_exceptions`:

```python
# Good: Explicit list of retryable exceptions.
retryable_exceptions=[NetworkError, TimeoutError]

# Bad: Too broad (might retry unintended exceptions).
retryable_exceptions=[Exception]
```

Handle all exception cases:

```python
try:
    result = await at_most_once(...)
except RetryableError:
    pass  # Handle exhausted retries.
except AtMostOnceFailedBeforeCompleting:
    pass  # Handle previous failure.
except PermanentError:
    pass  # Handle first-time permanent failure.
```

Use descriptive aliases:

```python
# Include identifying information in alias.
await at_most_once(
    f"payment_{user_id}_{amount}_{timestamp}",
    context,
    make_payment,
    type=dict,
)
```

## Comparison: at_least_once vs at_most_once

| Feature | at_least_once | at_most_once |
|---------|---------------|--------------|
| Guarantee | Completes at least once | Executes at most once |
| Retry | Always retries on failure | Only on `retryable_exceptions` |
| Use case | Idempotent operations | Operations with side effects |
| Exception | None | `AtMostOnceFailedBeforeCompleting` |

## Running

```bash
cd examples/processing
uv run python example.py
```
