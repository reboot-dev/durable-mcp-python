"""
Helpers for writing clients.
"""

import asyncio
import httpx
import mcp
import mcp.types
from contextlib import asynccontextmanager
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.streamable_http import (
    MCP_PROTOCOL_VERSION_HEADER,
    MCP_SESSION_ID_HEADER,
)
from typing import AsyncIterator, Any, Callable


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """
    Almost identical implementation to
    `mcp.shared._httpx_utils.create_mcp_http_client`, but we've added
    a transport which does retries.
    """
    kwargs: dict[str, Any] = {
        "follow_redirects": True,
    }

    kwargs["timeout"] = timeout or httpx.Timeout(30.0)

    if headers is not None:
        kwargs["headers"] = headers

    if auth is not None:
        kwargs["auth"] = auth

    return httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(retries=5),
        **kwargs,
    )


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
        httpx_client_factory=create_mcp_http_client,
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
