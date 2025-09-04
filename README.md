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

### TODO
- [ ] Pydantic `state` for each session
- [ ] `EventStore` support for resumability
- [ ] `elicit`
- [ ] `sampling`
- [ ] `progress`
- [ ] Enable calling `resource` and `prompt` using Reboot workflows
- [ ] Upgrade to latest Reboot and remove some of the monkey patches
- [ ] Replace `print()` with `logger`