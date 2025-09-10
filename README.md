# Reboot *Durable* MCP

A framework for building _durable_ MCP servers.

* Takes advantage of the protocols ability to resume after
  disconnection.

* Allows for the server itself to be restarted(!) and any existing
  requests to be retried safely thanks to Reboot workflows.

*THIS IS IN PRE-ALPHA STAGE, EXPECT CHANGES, BUG FIXES, ETC; DO NOT RUN IN PRODUCTION!*

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
And run the test(s):
```console
pytest tests
```

### Supported client --> server _requests_:
- [x] `initialize`
- [x] `tools/call`
- [x] `tools/list`
- [ ] `prompts/get`
- [ ] `prompts/list`
- [x] `resources/list`
- [x] `resources/read`
- [x] `resources/templates/list`
- [ ] `resources/subscribe`
- [ ] `resources/unsubscribe`
- [ ] `completion/complete`
- [ ] `logging/setLevel`

### Supported client --> server _notifications_:
- [x] `notifications/initialized`
- [ ] `notifications/roots/list_changed`

### Supported client <-- server _requests_:
- [ ] `elicitation/create`
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
- [ ] Docs
- [ ] `yapf`
- [x] Push to `durable-mcp` in pypi.org
- [ ] Pydantic `state` for each session
