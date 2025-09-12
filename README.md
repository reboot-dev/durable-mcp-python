# Reboot *Durable* MCP

A framework for building _durable_ MCP servers.

* Takes advantage of the protocols ability to resume after
  disconnection, e.g., due to the server getting rebooted.

* Any existing requests will be retried safely using Reboot workflows.

* Using Reboot you can run multiple replicas of your server, and
  session messages will always be routed to the same replica.

### Requirements
- Linux and macOS
- Python >= 3.12
- Docker

### Install

Using `uv`:

```console
uv add durable-mcp
```

Using `pip`:

```
pip install durable-mcp
```

### Run your application

Activate the `venv` (set up either via `uv` or `python -m venv venv`):

```console
source .venv/bin/activate
```

Make sure you have Docker running:

```console
docker ps
```

And run your app:

```console
rbt dev run --python --application=path/to/your/main.py
```

If you want the application to be restarted when you modify your files
you can add one or more `--watch=path/to/**/*.py` to the above command
line.

To simplify you can move all command line args to a `.rbtrc`.

```
# This file will aggregate all of the command line args
# into a single command line that will be run when you
# use `rbt`.
#
# For example, to add args for running `rbt dev run`
# you can add lines that start with `dev run`. You can add
# one or more args to each line.

dev run --python
dev run --application=path/to/your/main.py
dev run --watch=path/to/**/*.py --watch=different/path/to/**/*.py
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
- [x] `EventStore` support for resumability
- [ ] Auth
- [ ] Docs
- [ ] `yapf`
- [x] Push to `durable-mcp` in pypi.org
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
