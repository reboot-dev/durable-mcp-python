#!/usr/bin/env python3
"""
Harness for running DurableMCP examples.

Lets user select an example, starts the server, and runs the client.
"""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import aiohttp


EXAMPLES = {
    "1": {
        "name": "audit",
        "description": "Audit logging with decorator and explicit patterns",
    },
    "2": {
        "name": "steps",
        "description": "Multi-step operations with independent idempotency",
    },
    "3": {
        "name": "processing",
        "description": "Payment processing with at_most_once",
    },
    "4": {
        "name": "document",
        "description": "Document pipeline combining both patterns",
    },
    "5": {
        "name": "define",
        "description": "Technical glossary with SortedMap CRUD",
    },
}


def print_menu():
    """Print the example selection menu."""
    print("\nDurableMCP Examples")
    print("=" * 60)
    for key, example in sorted(EXAMPLES.items()):
        print(f"{key}. {example['name']:12} - {example['description']}")
    print("=" * 60)


def get_selection():
    """Get user's example selection."""
    while True:
        choice = input("\nSelect example (1-5, or 'q' to quit): ").strip()
        if choice.lower() == "q":
            return None
        if choice in EXAMPLES:
            return EXAMPLES[choice]["name"]
        print(f"Invalid selection: {choice}")


def check_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


async def wait_for_server(url: str, timeout: int = 30):
    """Wait for server to be ready."""
    start = time.time()
    port = 9991

    # First, wait for port to be open.
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", port)) == 0:
                print(f"Port {port} is open, checking MCP endpoint...")
                break
        await asyncio.sleep(0.5)
    else:
        print(f"Timeout: Port {port} never opened")
        return False

    # Port is open, now wait for MCP to respond.
    # Give it a moment to fully initialize.
    await asyncio.sleep(2)

    while time.time() - start < timeout:
        try:
            async with aiohttp.ClientSession() as session:
                # Try to list tools via MCP protocol.
                async with session.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                    },
                ) as resp:
                    # Any response means server is up.
                    print(f"MCP responded with status {resp.status}")
                    if resp.status in (200, 400, 405, 406):
                        return True
        except (aiohttp.ClientError, ConnectionError) as e:
            print(f"MCP check failed: {e.__class__.__name__}")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Unexpected error: {e}")
            await asyncio.sleep(0.5)

    print("Timeout: MCP endpoint never responded")
    return False


async def run_example(example_name: str):
    """Run the selected example."""
    example_dir = Path(__file__).parent / example_name
    server_path = example_dir / "example.py"
    client_path = example_dir / "client.py"

    if not server_path.exists():
        print(f"Error: Server not found at {server_path}")
        return

    if not client_path.exists():
        print(f"Error: Client not found at {client_path}")
        return

    print(f"\nStarting {example_name} example...")
    print(f"Server: {server_path}")
    print(f"Client: {client_path}")

    # Check if port 9991 is already in use.
    if check_port_in_use(9991):
        print("\nWarning: Port 9991 is already in use!")
        print("Please stop the existing server before continuing.")
        return

    # Start the server with rbt dev run in a new process group.
    print("\nStarting server (output below)...")
    print("-" * 60)
    server_process = subprocess.Popen(
        [
            "uv",
            "run",
            "rbt",
            "dev",
            "run",
            "--python",
            f"--application={server_path.name}",
            "--working-directory=.",
            "--no-generate-watch",
        ],
        cwd=example_dir,
        stdin=subprocess.PIPE,  # Provide a pipe for stdin.
        preexec_fn=os.setsid,  # Create new process group.
    )

    try:
        # Wait for server to be ready.
        print("\nWaiting for server to be ready on port 9991...")
        if not await wait_for_server("http://localhost:9991/mcp"):
            print("Error: Server did not start in time")
            print("Check server output above for errors")
            return

        print("Server ready!")
        print("\n" + "=" * 60)

        # Run the client.
        client_process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(client_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        stdout, stderr = await client_process.communicate()

        print(stdout.decode())
        if stderr:
            print("Errors:", stderr.decode(), file=sys.stderr)

        print("=" * 60)

    finally:
        # Clean up - send SIGINT (Ctrl-C) to allow rbt to cleanup properly.
        print("\nShutting down server...")
        try:
            # Send SIGINT (like Ctrl-C) to the entire process group.
            # This gives rbt a chance to cleanup docker containers.
            os.killpg(os.getpgid(server_process.pid), signal.SIGINT)
            # Wait longer for graceful shutdown (docker cleanup takes time).
            try:
                server_process.wait(timeout=10)
                print("Server stopped cleanly")
            except subprocess.TimeoutExpired:
                print("Server didn't stop in time, forcing shutdown...")
                # Force kill if necessary.
                os.killpg(os.getpgid(server_process.pid), signal.SIGKILL)
                server_process.wait()
        except ProcessLookupError:
            # Process already terminated.
            pass


async def main():
    """Main harness loop."""
    while True:
        print_menu()
        example = get_selection()

        if example is None:
            print("\nExiting...")
            break

        try:
            await run_example(example)
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            break
        except Exception as e:
            print(f"\nError running example: {e}", file=sys.stderr)

        input("\nPress Enter to continue...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nExiting...")
        sys.exit(0)
