"""
Helpers for writing clients.
"""

import asyncio
import mcp
import mcp.types
from contextlib import asynccontextmanager
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.streamable_http import (
    MCP_PROTOCOL_VERSION_HEADER,
    MCP_SESSION_ID_HEADER,
)
from typing import AsyncIterator, Any, Callable


@asynccontextmanager
async def connect(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    terminate_on_close: bool = True,
) -> AsyncIterator[tuple[mcp.ClientSession, Callable[[], str | None]]]:
    async with streamablehttp_client(
        url,
        headers=headers,
        terminate_on_close=terminate_on_close,
    ) as (read_stream, write_stream, get_session_id):
        async with mcp.ClientSession(read_stream, write_stream) as session:
            yield session, get_session_id


@asynccontextmanager
async def reconnect(
    url: str,
    *,
    session_id: str,
    protocol_version: str | int,
    next_request_id: int,
    terminate_on_close: bool = True,
) -> AsyncIterator[mcp.ClientSession]:
    headers: dict[str, Any] = {}
    headers[MCP_SESSION_ID_HEADER] = session_id
    headers[MCP_PROTOCOL_VERSION_HEADER] = protocol_version
    async with connect(
        url,
        headers=headers,
        terminate_on_close=terminate_on_close,
    ) as (session, _):
        session._request_id = next_request_id
        yield session
