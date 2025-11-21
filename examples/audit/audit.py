"""
Audit logging to SortedMap for DurableMCP tools.

Provides both decorator and explicit logging for storing audit data in a
durable, chronologically-ordered audit trail using UUIDv7.
"""

import functools
import time
from typing import Any, Callable, Dict, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from reboot.mcp.server import DurableContext
from reboot.std.collections.v1.sorted_map import SortedMap
from uuid7 import create as uuid7  # type: ignore[import-untyped]


# Pydantic model for audit log entries.
class AuditEntry(BaseModel):
    """Audit log entry with structured data."""

    timestamp: int
    tool: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None
    outputs: Optional[Any] = None
    success: Optional[bool] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None

    # Allow extra fields for custom audit data.
    model_config = {"extra": "allow"}


def timestamp_to_uuidv7(timestamp_ms: int) -> UUID:
    """
    Create a UUIDv7 from a Unix timestamp in milliseconds.

    This is useful for creating range boundaries when querying audit logs.
    The UUIDv7 will have the timestamp embedded and minimal random bits.

    Args:
        timestamp_ms: Unix timestamp in milliseconds.

    Returns:
        UUIDv7 with the given timestamp.
    """
    # UUIDv7 format (128 bits):
    # - 48 bits: Unix timestamp in milliseconds
    # - 4 bits: version (0111 = 7)
    # - 12 bits: random
    # - 2 bits: variant (10)
    # - 62 bits: random

    # Create minimal `UUIDv7` with timestamp and zeros for random bits.
    timestamp_48 = timestamp_ms & 0xFFFFFFFFFFFF  # 48 bits.

    # Build the 128-bit `UUID`.
    uuid_int = (timestamp_48 << 80) | (0x7 << 76)  # Timestamp + version.
    uuid_int |= (0x2 << 62)  # Variant bits.

    return UUID(int=uuid_int)


async def _write_audit(
    log_name: str,
    context: DurableContext,
    data: Dict[str, Any],
) -> None:
    """
    Internal function to write audit entry to SortedMap.

    Args:
        log_name: Name of the audit log.
        context: The durable context.
        data: Dictionary of audit data to store.
    """
    timestamp = int(time.time() * 1000)
    # Use `UUIDv7` for time-ordered, unique keys.
    key = str(uuid7())

    # Create Pydantic model with timestamp and provided data.
    audit_entry = AuditEntry(timestamp=timestamp, **data)

    try:
        audit_map = SortedMap.ref(f"audit:{log_name}")
        await audit_map.insert(
            context,
            entries={key: audit_entry.model_dump_json().encode("utf-8")},
        )
    except Exception:
        # Don't fail the original operation if audit fails.
        pass


def audit(
    log_name: str,
    context: Optional[DurableContext] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Union[Callable, None]:
    """
    Audit logging - works as both decorator and explicit function.

    As a decorator:
        @mcp.tool()
        @audit("user_operations")
        async def my_tool(name: str, context: DurableContext = None):
            return {"status": "success"}

    As an explicit function:
        await audit("user_operations", context, {
            "action": "custom_event",
            "user": "alice",
            "result": "success",
        })

    Args:
        log_name: Name of the audit log (creates SortedMap "audit:{log_name}").
        context: The durable context (required for explicit logging).
        data: Freeform dictionary (required for explicit logging).

    Returns:
        Decorator function if used as decorator, coroutine if used explicitly.

    Storage:
        Audit entries are stored in SortedMap with UUIDv7 keys for
        time-ordered, unique identification. Query with reverse_range()
        for chronological order (newest first).

    Decorator behavior:
        - Captures all function arguments (except context)
        - Records function return value or error
        - Measures execution duration
        - Automatically adds: tool, inputs, outputs, success, duration_seconds
    """
    # Explicit logging: `audit(log_name, context, data)`.
    if context is not None and data is not None:
        return _write_audit(log_name, context, data)

    # Decorator mode: `@audit(log_name)`.
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Assume `context` is in `kwargs`.
            ctx = kwargs.get("context")

            # Capture inputs (exclude `context`).
            inputs = {k: v for k, v in kwargs.items() if k != "context"}

            # Call function and capture timing.
            start_time = time.time()
            success = False
            result = None
            error = None

            try:
                result = await func(*args, **kwargs)
                success = True
            except Exception as e:
                error = f"{type(e).__name__}: {str(e)}"
                raise
            finally:
                # Log if we have `context`.
                if ctx:
                    duration = time.time() - start_time
                    audit_data = {
                        "tool": func.__name__,
                        "inputs": inputs,
                        "success": success,
                        "duration_seconds": round(duration, 3),
                    }

                    if success:
                        audit_data["outputs"] = result
                    else:
                        audit_data["error"] = error

                    await _write_audit(log_name, ctx, audit_data)

            return result

        return wrapper

    return decorator
