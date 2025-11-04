# DurableMCP Authentication Architecture

This document describes the OAuth 2.1 authentication architecture for
DurableMCP, including the separation of durable and ephemeral state,
integration patterns, and authorization mechanisms.

## Overview

DurableMCP implements OAuth 2.1 bearer token authentication following the
Model Context Protocol (MCP) specification. The architecture separates
concerns between durable state (session workflows that survive application
reboots), ephemeral state (OAuth tokens validated per-request), and
authorization (contextvar-based access control).

## Core Principles

### Stateless Authentication

OAuth tokens are never stored server-side. The server validates bearer
tokens on each HTTP request but does not persist them. This follows the
OAuth 2.1 specification (tokens are client-side credentials), the MCP
specification (authentication must be per-request), and the Reboot
architecture (only workflow state is durable).

### Durable vs Ephemeral State

Durable state survives reboot and includes session ID (workflow state),
request/response history, application state, and stream IDs for message
routing. Ephemeral state is per-request and includes OAuth bearer tokens
(client-side), authentication context (contextvar), validated user
identity, and access token with scopes.

The server validates tokens per-request, checking expiry and scopes, but
never stores them. The client stores OAuth tokens, includes them in HTTP
headers, and refreshes them when expired. Session ID is durable on both
sides; it survives disconnect and is used for reconnection. Workflow
state is persisted in Reboot and restored after reboot.

## Authentication Flow

### Initial Connection

The client first registers with the auth server (one-time), providing
metadata and receiving client_id and secret. For each authorization
request, the client generates PKCE parameters (code_verifier and
code_challenge), requests authorization with code_challenge, and receives
an authorization code after user authentication. The client then exchanges
the code plus code_verifier for access_token and refresh_token.

When connecting to the MCP server, the client initializes with a bearer
token and receives a session ID representing durable state. For
authenticated requests, the client calls tools with the bearer token, the
server validates the token per-request and executes within authenticated
context, and returns the tool result.

### Reconnection After Reboot

When the application reboots, the server loses in-memory state but the
session ID persists in durable storage. The client manages tokens and does
not rely on server-side storage. On reconnection, the client provides both
session_id and bearer token. The server restores durable session state
from storage and validates the bearer token with fresh validation (no
cached auth state). For subsequent requests, the server validates the
token per-request with no cached auth state.

## Workflow Integration

### The Contextvar Problem

The python-sdk provides get_access_token() which retrieves the
authenticated user's AccessToken from a contextvar. This works in HTTP
handlers because AuthenticationMiddleware validates tokens and
AuthContextMiddleware stores them in a contextvar. However, contextvars do
not propagate across workflow spawn boundaries in Reboot.

When a request spawns HandleMessage which spawns Run which calls a tool,
the contextvar set in the HTTP handler is not available in the spawned
workflow. This means get_access_token() returns None in tools, breaking
per-tool authorization.

### The Solution: AccessToken Serialization

The solution involves extracting the AccessToken at the spawn point,
serializing it through proto messages, and reconstructing it in the
workflow. At the HTTP entry point, external_context_with_access_token()
calls get_access_token() from the middleware contextvar and serializes the
AccessToken to JSON. This JSON is passed through ExternalContext.bearer_token.

When spawning HandleMessage, the server extracts access_token_json from
context.bearer_token and passes it to HandleMessage via the proto field.
HandleMessage deserializes the JSON and sets a workflow-scoped contextvar.
When HandleMessage spawns Run, it passes access_token_json through the
proto field. Run deserializes and sets the workflow contextvar. When Run
calls server_run() in an async task, it captures the access_token from the
parent scope and sets it in the task's contextvar.

### Monkey-Patch for Compatibility

To make get_access_token() work transparently in both HTTP handlers and
workflows, the implementation monkey-patches the function at module load
time. The patched version first tries the workflow contextvar (for spawned
workflows), then falls back to the middleware contextvar (for HTTP
handlers). This allows tools to use the same get_access_token() API
regardless of whether they are called from an HTTP handler or a workflow.

## Authorization Mechanisms

DurableMCP provides context-based authorization through get_access_token()
and per-tool authorization where individual tools check scopes.

### Context-Based Authorization

Tools access authenticated user information within request handlers by
calling get_access_token(). This requires AuthenticationMiddleware to
validate the token and set request.user, AuthContextMiddleware to store
the user in a contextvar for HTTP handlers, and the workflow integration
described above to propagate tokens through spawned workflows.

The function returns an AccessToken object with client_id, scopes, and
expires_at, or None if no authenticated user is present. The token is
available throughout the request lifecycle via contextvar. This is used
for accessing user information for logging, auditing, or conditional
logic.

```python
from mcp.server.auth.middleware.auth_context import get_access_token

@mcp.tool()
async def get_user_info() -> dict:
    """Get information about the authenticated user."""
    token = get_access_token()
    if token is None:
        raise Exception("Not authenticated")

    return {
        "client_id": token.client_id,
        "scopes": token.scopes,
        "expires_at": token.expires_at,
    }
```

### Per-Tool Authorization

Individual tools check scopes and enforce authorization rules. Each tool
independently checks required scopes and raises exceptions with
descriptive error messages. This allows different tools to require
different scopes and enables fine-grained access control per operation.

```python
from mcp.server.auth.middleware.auth_context import get_access_token

@mcp.tool()
async def admin_only_operation(operation: str) -> str:
    """Perform an admin-only operation."""
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    if "admin" not in token.scopes:
        raise Exception(
            f"Insufficient permissions: 'admin' scope required, "
            f"but user has: {token.scopes}"
        )

    return f"Admin operation '{operation}' performed"

@mcp.tool()
async def read_data(resource_id: str) -> dict:
    """Read data requiring 'read' scope."""
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    if "read" not in token.scopes:
        raise Exception(
            f"Insufficient permissions: 'read' scope required"
        )

    return {"resource_id": resource_id, "data": "Protected data"}
```

## Integration with DurableMCP

DurableMCP integrates with FastMCP's auth system. The server is configured
with an auth_server_provider and optional token_verifier. This
automatically configures AuthenticationMiddleware for token validation and
AuthContextMiddleware for contextvar storage.

```python
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from reboot.mcp.server import DurableMCP

# Create OAuth provider.
oauth_provider = OAuthAuthorizationServerProvider(...)

# Configure DurableMCP with auth.
mcp = DurableMCP(
    path="/mcp",
    auth_server_provider=oauth_provider,
)

# Define tools with auth checks.
@mcp.tool()
async def protected_operation(param: str) -> str:
    token = get_access_token()
    if token is None or "write" not in token.scopes:
        raise Exception("Insufficient permissions")
    return f"Operation performed: {param}"

application = mcp.application()
```

## Token Storage Considerations

### Client-Side Storage

Tokens must be stored client-side. Common approaches include in-memory
storage (simple but lost on client restart), keychain or credential
manager (secure OS-level storage), and encrypted file (cross-platform
persistent storage). The MCP SDK provides storage interfaces for token
persistence.

### Server-Side Anti-Pattern

Do not store tokens in server-side durable storage. This violates OAuth
2.1 (servers should not store client tokens), the MCP specification
(authentication must be stateless and per-request), and security
principles (tokens are client credentials, not server state).

### What Is Durable

Only session workflow state is durable, including session ID for routing,
request/response history for auditing, stream IDs for message ordering,
and application state (user-defined). Authentication context is not
durable and must be provided per-request.

## Testing Strategy

### Test Files

The test suite includes test_auth_end_to_end.py (5 tests) for complete
auth flow with reboot, session persistence vs token ephemeral,
reconnection with fresh token validation, notifications with auth context,
and concurrent authenticated sessions. The test_auth_integration.py file
(6 tests) covers OAuth 2.1 integration with DurableMCP, auth survival
through reboot, and requests with and without authentication. The
test_auth_per_tool.py file (5 tests) validates get_access_token() function
usage, per-tool scope checking, authorization errors, and fine-grained
access control.

Tests that only validated FastMCP/python-sdk functionality (such as PKCE
parameter generation, OAuth provider initialization, and bearer token
middleware) were removed because they duplicate coverage already provided
by the python-sdk test suite.

### Running Tests

```bash
# All auth tests.
pytest tests/test_auth_*.py -v

# Specific test file.
pytest tests/test_auth_per_tool.py -v

# Single test.
pytest tests/test_auth_per_tool.py::TestGetAccessToken::test_get_access_token_returns_user_info -v
```

## Security Considerations

### Token Validation

Token validation includes expiry checking (tokens with expires_at in the
past are rejected), scope verification (required scopes must be present in
token), per-request validation (no caching of validation results), and
stateless validation (no server-side token storage).

### Error Handling

Error responses include 401 Unauthorized for missing or invalid tokens,
403 Forbidden for valid tokens with insufficient scopes, descriptive
errors that include required scopes in error messages, and no token
leakage (never include token values in logs or errors).

### Token Refresh

Token refresh is the client's responsibility. The client checks if
token.expires_at is less than current_time plus safety_margin, requests a
new token from the oauth_provider using the refresh_token, and stores the
new tokens. The server never initiates refresh and never stores refresh
tokens.

## Implementation Details

### Proto Definitions

The HandleMessageRequest and RunRequest proto messages include an
access_token_json field (field 3) that carries serialized AccessToken data
as JSON. This field contains token, client_id, scopes, and expires_at,
allowing tools to call get_access_token() in workflows.

### Server Entry Point

The server.py file implements the workflow integration at module load
time. It imports auth_context_module and saves the original
get_access_token function. The _workflow_aware_get_access_token function
first tries get_workflow_access_token() from the workflow contextvar, then
falls back to the original function for HTTP handlers. This replacement is
applied at module load by assigning auth_context_module.get_access_token.

The external_context_with_access_token wrapper extracts the AccessToken
from the middleware contextvar using get_access_token(), serializes it to
JSON with token, client_id, scopes, and expires_at fields, and returns an
ExternalContext with bearer_token set to the JSON string if an
AccessToken is present, otherwise returns the base context unchanged.

When handling requests, the server extracts access_token_json from
context.bearer_token if context is an ExternalContext, then spawns
HandleMessage with path, message_bytes, and access_token_json.

### Workflow Servicers

The session.py file defines a workflow-scoped contextvar
_workflow_access_token that stores the AccessToken for the current
workflow. The get_workflow_access_token function returns this contextvar's
value. The _deserialize_access_token function parses JSON and constructs
an AccessToken, returning None if deserialization fails.

HandleMessage deserializes access_token_json from the proto field and sets
the workflow contextvar, then spawns Run with path, message_bytes, and
access_token_json. Run deserializes access_token_json and sets the
workflow contextvar at the method entry point.

Within Run, the server_run async function captures the access_token
variable from the parent Run method scope and sets the workflow contextvar
in the async task context. This ensures get_access_token() works when
tools are called from within server_run. The contextvar is cleared in the
finally block to prevent leakage.

## References

OAuth 2.1 is defined at https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1.
RFC 7636 (PKCE) is at https://datatracker.ietf.org/doc/html/rfc7636.
RFC 9728 (Protected Resource Metadata) is at
https://datatracker.ietf.org/doc/html/rfc9728. The MCP Specification
describes the Model Context Protocol. The Reboot Documentation describes
the durable workflow framework.

## Implementation Checklist

When implementing auth for a DurableMCP server, choose an OAuth 2.1
provider or implement a mock for testing, configure client registration
with client_id, client_secret, and redirect_uri, implement client-side
token storage using keychain or encrypted file, configure DurableMCP with
auth_server_provider, and add per-tool authorization checks where needed.

Test without auth and expect 401 errors. Test with valid tokens and expect
success. Test with expired tokens and expect 401 errors. Test with
insufficient scopes and expect 403 or tool-level errors. Test reconnection
after reboot to verify tokens are validated fresh. Verify no tokens are
stored in server-side durable state.
