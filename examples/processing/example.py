"""
Payment Processing with at_most_once.

Demonstrates using at_most_once for operations that call external APIs where
retrying after certain errors could cause unintended side effects.
"""

import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict

# Add api/ to Python path for generated proto code.
api_path = Path(__file__).parent.parent.parent / "api"
if api_path.exists():
    sys.path.insert(0, str(api_path))

from reboot.aio.workflows import at_most_once, AtMostOnceFailedBeforeCompleting
from reboot.mcp.server import DurableMCP, DurableContext
from reboot.std.collections.v1.sorted_map import SortedMap

# Initialize MCP server.
mcp = DurableMCP(path="/mcp")


class NetworkError(Exception):
    """Temporary network error (retryable)."""

    pass


class PaymentRejectedError(Exception):
    """Payment was rejected by payment processor (not retryable)."""

    pass


class InsufficientFundsError(Exception):
    """Insufficient funds (not retryable)."""

    pass


async def simulate_payment_api(
    amount: float,
    currency: str,
    context: DurableContext,
) -> Dict[str, Any]:
    """
    Simulate external payment API call.

    Raises different exception types to demonstrate retry behavior.
    """
    # Check for invalid currency (non-retryable error).
    valid_currencies = ["USD", "EUR", "GBP", "JPY"]
    if currency not in valid_currencies:
        raise PaymentRejectedError(f"Invalid currency: {currency}")

    # Check for insufficient funds (non-retryable error).
    if amount > 100000:
        raise InsufficientFundsError(
            f"Amount {amount} exceeds available balance"
        )

    # For amounts ending in .01, simulate retriable network errors using
    # a SortedMap to track attempts. Fail first attempt, succeed on retry.
    if amount % 1 == 0.01:
        retry_map = SortedMap.ref("retry_attempts")
        attempt_key = f"payment_{amount}_{currency}"

        # Get current attempt count.
        response = await retry_map.get(context, key=attempt_key)

        if response.HasField("value"):
            attempts = int(response.value.decode("utf-8"))
        else:
            attempts = 0

        # Increment attempt count.
        await retry_map.insert(
            context,
            entries={attempt_key: str(attempts + 1).encode("utf-8")},
        )

        # Fail first attempt to demonstrate retry.
        if attempts == 0:
            raise NetworkError("Simulated network timeout for demo (will retry)")

    # Success: Return payment confirmation.
    return {
        "transaction_id": f"txn_{random.randint(100000, 999999)}",
        "amount": amount,
        "currency": currency,
        "status": "completed",
    }


@mcp.tool()
async def process_payment(
    amount: float,
    currency: str = "USD",
    description: str = "",
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Process a payment via external payment API.

    Uses at_most_once to ensure the payment is only attempted once, even if
    the tool is retried. Network errors are retryable, but payment rejections
    are not.

    Args:
        amount: Payment amount.
        currency: Currency code (default: USD).
        description: Payment description.
        context: The durable context.

    Returns:
        Payment result or error information.
    """
    payments_map = SortedMap.ref("payments")

    async def make_payment():
        # Call external payment API.
        result = await simulate_payment_api(amount, currency, context)

        # Store payment record.
        payment_id = result["transaction_id"]
        await payments_map.insert(
            context,
            entries={
                payment_id: json.dumps(
                    {
                        "transaction_id": payment_id,
                        "amount": amount,
                        "currency": currency,
                        "description": description,
                        "status": result["status"],
                    }
                ).encode("utf-8")
            },
        )

        return result

    try:
        # Use at_most_once to ensure payment is attempted at most once.
        # Only retry on network errors - payment rejections are final.
        result = await at_most_once(
            f"payment_{amount}_{currency}_{hash(description)}",
            context,
            make_payment,
            type=dict,
            retryable_exceptions=[NetworkError],
        )

        return {
            "status": "success",
            "payment": result,
        }

    except NetworkError:
        # Network error after retries exhausted.
        return {
            "status": "error",
            "error_type": "network_error",
            "message": "Payment service temporarily unavailable",
            "retryable": True,
        }

    except AtMostOnceFailedBeforeCompleting:
        # Previous attempt failed with non-retryable error.
        # This means payment was rejected or funds were insufficient.
        return {
            "status": "error",
            "error_type": "payment_failed",
            "message": "Payment failed on previous attempt (not retryable)",
            "retryable": False,
        }

    except (PaymentRejectedError, InsufficientFundsError) as e:
        # First attempt with non-retryable error.
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": str(e),
            "retryable": False,
        }


@mcp.tool()
async def get_payment(
    transaction_id: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Retrieve payment record.

    Args:
        transaction_id: The transaction ID to retrieve.
        context: The durable context.

    Returns:
        Payment data or error if not found.
    """
    payments_map = SortedMap.ref("payments")

    response = await payments_map.get(context, key=transaction_id)

    if not response.HasField("value"):
        return {"status": "error", "message": "Payment not found"}

    payment_data = json.loads(response.value.decode("utf-8"))

    return {"status": "success", "payment": payment_data}


@mcp.tool()
async def fetch_exchange_rate(
    from_currency: str,
    to_currency: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Fetch exchange rate from external API.

    Demonstrates at_most_once for read-only API calls where retries are safe
    but we want to avoid redundant network calls.

    Args:
        from_currency: Source currency code.
        to_currency: Target currency code.
        context: The durable context.

    Returns:
        Exchange rate or error.
    """

    async def fetch_rate():
        # Simulate API call with occasional network errors.
        if random.random() < 0.1:
            raise NetworkError("API timeout")

        # Return simulated exchange rate.
        return {
            "from": from_currency,
            "to": to_currency,
            "rate": round(random.uniform(0.5, 2.0), 4),
        }

    try:
        # Retry on network errors only.
        result = await at_most_once(
            f"exchange_rate_{from_currency}_{to_currency}",
            context,
            fetch_rate,
            type=dict,
            retryable_exceptions=[NetworkError],
        )

        return {"status": "success", "data": result}

    except NetworkError:
        return {
            "status": "error",
            "message": "Exchange rate service unavailable",
        }

    except AtMostOnceFailedBeforeCompleting:
        return {
            "status": "error",
            "message": "Previous fetch attempt failed",
        }


async def main():
    """Start the payment processing example server."""
    await mcp.application().run()


if __name__ == "__main__":
    asyncio.run(main())
