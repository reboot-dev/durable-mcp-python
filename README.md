# Reboot *Durable* MCP

A framework for building _durable_ MCP servers.

* Takes advantage of the protocols ability to resume after
  disconnection, e.g., due to the server getting rebooted.

* Any existing requests will be retried safely using Reboot workflows.

* Using Reboot you can run multiple replicas of your server, and
  session messages will always be routed to the same replica.

### Requirements
- Linux and macOS
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
from reboot.mcp.server import DurableMCP, ToolContext
from reboot.std.collections.v1.sorted_map import SortedMap

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def add(a: int, b: int, context: ToolContext) -> int:
    """Add two numbers and also store result in `SortedMap`."""
    result = a + b
    await SortedMap.ref("adds").Insert(
        context,
        entries={f"{a} + {b}": f"{result}".encode()},
    )
    return result


async def main():
    # Reboot application that runs everything necessary for `DurableMCP`.
    application = Application(servicers=mcp.servicers())

    # Mounts the server at the path specified.
    application.http.mount(mcp.path, factory=mcp.streamable_http_app_factory)

    await application.run()


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
    # and session using the MCP SDK. You can also write a client the
    # direclty uses the MCP SDK you prefer!
    async with connect(URL + "/mcp") as (
        session, session_id, protocol_version
    ):
        print(await session.list_tools())
        print(await session.call_tool("add", arguments={"a": 5, "b": 3}))


if __name__ == '__main__':
    asyncio.run(main())
```

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
- [ ] Add examples of using `at_least_once` and `at_most_once`
- [ ] Add examples of how to test via `Reboot().start/up/down/stop()`
- [ ] Add example of rebooting server using MCP Inspector version [0.16.7](https://github.com/modelcontextprotocol/inspector/releases/tag/0.16.7) which includes [modelcontextprotocol/inspector#787](https://github.com/modelcontextprotocol/inspector/pull/787)
- [ ] Auth
- [ ] Docs at `docs.reboot.dev`
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
