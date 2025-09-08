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
pytest tests/test.py
```

### TODO client --> server _requests_:
- [x] `initialize`
- [x] `tools/call`
- [x] `tools/list`
- [ ] `prompts/get`
- [ ] `prompts/list`
- [ ] `resources/list`
- [ ] `resources/read`
- [ ] `resources/subscribe`
- [ ] `resources/unsubscribe`
- [ ] `resources/templates/list`
- [ ] `completion/complete`
- [ ] `logging/setLevel`

### TODO client --> server _notifications_:
- [ ] `notifications/initialized`

### TODO client <-- server _requests_:
- [ ] `elicitation/create`
- [ ] `roots/list`
- [ ] `sampling/createMessage`

### TODO client <-- server _notifications_:
- [x] `notifications/progress`
- [ ] `notifications/message`
- [ ] `notifications/prompts/list_changed`
- [ ] `notifications/resources/list_changed`
- [ ] `notifications/resources/updated`
- [ ] `notifications/roots/list_changed`
- [ ] `notifications/tools/list_changed`

### TODO client <--> server _notifications_:
- [ ] `notifications/cancelled`

### TODO miscellaneous:
- [x] `EventStore` support for resumability
- [ ] Docs
- [ ] `yapf`
- [ ] Push to `reboot-mcp` in pypi.org
- [ ] Pydantic `state` for each session
