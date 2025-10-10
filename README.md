# Reboot *Durable* MCP

A framework for building _durable_ MCP servers.

* Takes advantage of the protocols ability to resume after
  disconnection, e.g., due to the server getting rebooted.

* Any existing requests will be retried safely using Reboot workflows.

* Using Reboot you can run multiple replicas of your server, and
  session messages will always be routed to the same replica.

### Requirements
- macOS or Linux
- Python >= 3.12.11
- Docker

### Install

We recommend using `uv`, as it will manage the version of Python for
you. For example, to start a new project in the directory `foo`:

```console
uv init --python 3.12.11 .
uv add durable-mcp
```

Activate the `venv`:

```console
source .venv/bin/activate
```

Make sure you have Docker running:

```console
docker ps
```

### Building an MCP server

Instead of using `FastMCP` from the MCP SDK, you use
`DurableMCP`. Here is a simple server to get you started:

```python
import asyncio
from reboot.aio.applications import Application
from reboot.mcp.server import DurableContext, DurableMCP
from reboot.std.collections.v1.sorted_map import SortedMap

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def add(a: int, b: int, context: DurableContext) -> int:
    """Add two numbers and also store result in `SortedMap`."""
    result = a + b
    await SortedMap.ref("adds").insert(
        context,
        entries={f"{a} + {b}": f"{result}".encode()},
    )
    return result


async def main():
    # Reboot application that runs everything necessary for `DurableMCP`.
    await mcp.application().run()


if __name__ == '__main__':
    asyncio.run(main())
```

You can run the server via:

```console
rbt dev run --python --application=path/to/main.py --working-directory=. --no-generate-watch
```

While developing you can tell `rbt` to restart your server when you
modify files by adding one or more `--watch=path/to/**/*.py` to the
above command line.

We recommend you move all of your command line args to a `.rbtrc`:

```bash
# This file will aggregate all of the command line args
# into a single command line that will be run when you
# use `rbt`.
#
# For example, to add args for running `rbt dev run`
# you can add lines that start with `dev run`. You can add
# one or more args to each line.
dev run --no-generate-watch
dev run --python --application=path/to/your/main.py
dev run --watch=path/to/**/*.py --watch=different/path/to/**/*.py
```

Then you can just run:

```console
rbt dev run
```

### Testing your MCP server

You can use the [MCP
Inspector](https://modelcontextprotocol.io/legacy/tools/inspector) to
test out the server, or create a simple client.

```python
import asyncio
from reboot.mcp.client import connect, reconnect

URL = "http://localhost:9991"


async def main():
    # `connect()` is a helper that creates a streamable HTTP client
    # and session using the MCP SDK. You can also write a client that
    # directly uses the MCP SDK, or use any other MCP client library!
    async with connect(URL + "/mcp") as (
        session, session_id, protocol_version
    ):
        print(await session.list_tools())
        print(await session.call_tool("add", arguments={"a": 5, "b": 3}))


if __name__ == '__main__':
    asyncio.run(main())
```

### Performing a side-effect "at least once"

Within your tools (and soon within your prompts and resources too),
you can perform a side-effect that is safe to try one or more times
until success using `at_least_once`. Usually what makes it safe to
perform one or more times is that you can somehow do it
_idempotently_, e.g., passing an idempotency key as part of an API
call. Use `at_least_once` for this, for example:

```python
from reboot.aio.workflows import at_least_once
from reboot.mcp.server import DurableContext, DurableMCP


# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def add(a: int, b: int, context: DurableContext) -> int:

    async def do_side_effect_idempotently() -> int:
        """
        Pretend that we are doing a side-effect that we can try
        more than once because we can do it idempotently, hence using
        `at_least_once`.
        """
        return a + b

    result = await at_least_once(
        "Do side-effect _idempotently_",
        context,
        do_side_effect_idempotently,
        type=int,
    )

    # ...
```

### Performing a side-effect "at most once"

Within your tools (and soon within your prompts and resources too),
you can perform a side-effect that can _only_ be tried once using
`at_most_once` (if you can perform the side-effect more than once
using safely then always prefer `at_least_once`). Here's an example of
`at_most_once`:

```python
from reboot.aio.workflows import at_least_once
from reboot.mcp.server import DurableContext, DurableMCP


# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def add(a: int, b: int, context: DurableContext) -> int:

    async def do_side_effect() -> int:
        """
        Pretend that we are doing a side-effect that we can only
        try to do once because it is not able to be performed
        idempotently, hence using `at_most_once`.
        """
        return a + b

    # NOTE: if we reboot, e.g., due to a hardware failure, within
    # `do_side_effect()` then `at_most_once` will forever raise with
    # `AtMostOnceFailedBeforeCompleting` and you will need to handle
    # appropriately.
    result = await at_most_once(
        "Do side-effect",
        context,
        do_side_effect,
        type=int,
    )

    # ...
```

### Debugging

Start by enabling debug logging:

```python
mcp = DurableMCP(path="/mcp", log_level="DEBUG")
```

The MCP SDK is aggressive about "swallowing" errors on the server side
and just returning "request failed" so we do our best to log stack
traces on the server. If you find a place where you've needed to add
your own `try`/`catch` please let us know we'd love to log that for
you automatically.

### Supported client --> server _requests_:
- [x] `initialize`
- [x] `tools/call`
- [x] `tools/list`
- [x] `prompts/get`
- [x] `prompts/list`
- [x] `resources/list`
- [x] `resources/read`
- [x] `resources/templates/list`
- [ ] `resources/subscribe`
- [ ] `resources/unsubscribe`
- [ ] `completion/complete`
- [ ] `logging/setLevel`

### Supported client --> server _notifications_:
- [x] `notifications/initialized`
- [ ] `notifications/progress` (for server initiated requests, e.g., elicitation)
- [ ] `notifications/roots/list_changed`

### Supported client <-- server _requests_:
- [x] `elicitation/create`
- [ ] `roots/list`
- [ ] `sampling/createMessage`

### Supported client <-- server _notifications_:
- [x] `notifications/progress`
- [x] `notifications/message`
- [x] `notifications/prompts/list_changed`
- [x] `notifications/resources/list_changed`
- [x] `notifications/tools/list_changed`
- [ ] `notifications/resources/updated`

### Supported client <--> server _notifications_:
- [ ] `notifications/cancelled`

### TODO:
- [ ] Auth pass through to MCP SDK
- [ ] Adding tools, resources, and prompts dynamically
- [ ] Add examples of how to test via `Reboot().start/up/down/stop()`
- [ ] Add example of rebooting server using MCP Inspector version [0.16.7](https://github.com/modelcontextprotocol/inspector/releases/tag/0.16.7) which includes [modelcontextprotocol/inspector#787](https://github.com/modelcontextprotocol/inspector/pull/787)
- [ ] `yapf`
- [ ] Pydantic `state` for each session


### Contributing

First grab all dependencies:

```console
uv sync
```

Activate the `venv`:

```console
source .venv/bin/activate
```

Generate code:

```console
rbt generate
```

Make sure you have Docker running:

```console
docker ps
```

Make your changes and run the tests:

```console
pytest tests
```
