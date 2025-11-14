import asyncio
import httpx
import unittest
import uuid
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.server import DurableMCP

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.resource("config://settings")
def get_settings() -> str:
    """Get application settings."""
    return """{
  "theme": "dark",
  "language": "en",
  "debug": false
}"""


# Reboot application that runs everything necessary for `DurableMCP`.
application: Application = mcp.application()


class TestIsVscodeSseBlocking(unittest.IsolatedAsyncioTestCase):
    """
    Test that reproduces the `is_vscode()` blocking timeout issue.

    The issue occurs at the HTTP transport layer when:
    1. A new session is created with a GET request (SSE connection).
    2. The server calls `is_vscode()` in `server.py` at line 1157.
    3. `is_vscode()` polls waiting for `client_info` to be
       populated.
    4. But `client_info` is only populated AFTER the connection is
       established and the `initialize` message is received.
    5. This creates a chicken-and-egg problem causing a timeout.

    This test directly makes a GET request to establish an SSE
    connection for a brand new session, which triggers the blocking
    behavior in the original `is_vscode()` implementation.
    """

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_is_vscode_non_blocking(self) -> None:
        """
        Test that `is_vscode()` does not block on uninitialized
        sessions.

        Without the fix, this test hangs for ~30 seconds waiting
        for `is_vscode()` to finish polling for `client_info`.

        With the fix, `is_vscode()` returns immediately (False)
        since `client_info` is not yet available, and the request
        completes quickly.
        """
        await self.rbt.up(application)

        # Use a unique session ID to ensure fresh session.
        # Critical: if we reuse an existing session that already
        # has `client_info` populated, the test won't trigger the
        # bug.
        session_id = f"test-session-{uuid.uuid4()}"

        # Create HTTP client for raw HTTP requests.
        async with httpx.AsyncClient(timeout=30.0) as client:
            base_url = self.rbt.url() + "/mcp/"

            # Measure how long the GET request takes. This is the
            # initial SSE connection that triggers `is_vscode()` at
            # line 1157 in `server.py`.
            start_time = asyncio.get_event_loop().time()

            # Make GET request to establish SSE connection. This
            # should trigger `is_vscode()` check BEFORE any
            # `initialize` message has been received.
            #
            # Note: We use `stream=True` and immediately close to
            # avoid actually consuming the SSE stream.
            try:
                async with client.stream(
                    "GET",
                    base_url,
                    headers={
                        "Accept": "text/event-stream",
                        "Cache-Control": "no-cache",
                        # Session ID in header (MCP convention).
                        "X-Session-Id": session_id,
                    },
                ) as response:
                    # Check that we got a response quickly.
                    elapsed = (
                        asyncio.get_event_loop().time() - start_time
                    )

                    # With the fix, completes in < 2 seconds. Without
                    # the fix, would take ~30 seconds due to the
                    # `is_vscode()` polling loop with backoff timing
                    # out.
                    self.assertLess(
                        elapsed,
                        2.0,
                        f"GET request took {elapsed:.2f}s - "
                        f"`is_vscode()` may be blocking waiting for "
                        f"`client_info`!",
                    )

                    # The request may succeed (200) or fail (400),
                    # but the important thing is that it returns
                    # quickly without blocking. The fix makes
                    # `is_vscode()` non-blocking.
                    self.assertIn(
                        response.status_code,
                        [200, 400],
                        f"Expected 200 or 400, got "
                        f"{response.status_code}",
                    )
            except httpx.ReadTimeout:
                elapsed = asyncio.get_event_loop().time() - start_time
                self.fail(
                    f"Request timed out after {elapsed:.2f}s - "
                    f"`is_vscode()` is still blocking!"
                )


if __name__ == "__main__":
    unittest.main()
