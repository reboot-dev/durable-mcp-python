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
PYTHONPATH=.:api python tests/test.py
```

NOTE: currently `pytest` is NOT supported.
