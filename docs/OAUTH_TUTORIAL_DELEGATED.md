# OAuth Tutorial: Delegated Access Pattern

This tutorial demonstrates building an MCP server that acts on behalf of
authenticated users. The server uses GitHub OAuth to authenticate users
and creates GitHub gists using the user's credentials. This pattern is
appropriate when the MCP server performs actions as the user rather than
as a service.

## Architecture Overview

The delegated access pattern involves three parties: the user, the MCP
server, and GitHub. The user authenticates with GitHub and grants
permission for the MCP server to act on their behalf. The MCP server
receives an access token representing the user's identity and
authorization. When the user calls MCP tools, the server uses this token
to make GitHub API calls, and GitHub attributes the actions to the user.

```
User                    MCP Server              GitHub
----                    ----------              ------

1. Initiate auth   -->
                        Redirect to GitHub  -->
                                                Display login
                                            <-- User approves

2.                  <-- Authorization code
                        Exchange code       -->
                                            <-- Access token

3. Call MCP tool   -->
   with token           Validate token
                        Create gist         -->
                        with user token
                                            <-- Gist created
                                                (owned by user)
                   <--  Return gist URL
```

The key characteristic of this pattern is that the access token represents
the user's identity. The MCP server validates the token to authenticate
the user, then uses the same token to perform actions on GitHub. GitHub
sees these actions as coming from the user, not from the MCP server.

## Prerequisites

You need a GitHub account to register an OAuth application. Install
Python 3.12 or later and the DurableMCP framework. Understand OAuth 2.1
concepts including authorization flows, access tokens, and scopes. You
should also understand the MCP protocol and how tools are invoked.

## GitHub OAuth Application Setup

Navigate to GitHub Settings, then Developer settings, then OAuth Apps.
Click New OAuth App and configure it with an application name like "MCP
Gist Creator", homepage URL "http://localhost:9991", and authorization
callback URL "http://localhost:9991/oauth/callback". After creation, note
the Client ID and generate a Client Secret. The client secret is shown
only once, so save it securely.

For this tutorial, the required scope is "gist" which allows creating
gists on behalf of the user. You may also request "read:user" to access
the user's profile information. Requesting minimal scopes follows the
principle of least privilege.

## Implementing the OAuth Provider

The OAuth provider validates access tokens by calling GitHub's API. GitHub
does not provide a standard token introspection endpoint, so validation is
performed by attempting to use the token to fetch user information. If the
request succeeds, the token is valid.

```python
import time
from typing import Optional
from mcp.server.auth.provider import (
    AccessToken,
    OAuthAuthorizationServerProvider,
)
import httpx


class GitHubOAuthProvider(OAuthAuthorizationServerProvider):
    """
    OAuth provider for GitHub that validates tokens by fetching
    user information. The token represents a GitHub user who has
    granted our application permission to act on their behalf.
    """

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = httpx.AsyncClient()

    async def load_access_token(
        self,
        token: str,
    ) -> Optional[AccessToken]:
        """
        Validate a GitHub access token by fetching user info.

        Returns an AccessToken with the user's login as client_id
        and the scopes granted by the user. Returns None if the
        token is invalid or the request fails.
        """
        try:
            response = await self.client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )

            if response.status_code != 200:
                return None

            user_data = response.json()

            # GitHub tokens do not typically expire, but we set
            # a far-future expiry for compatibility with the
            # AccessToken model.
            return AccessToken(
                token=token,
                client_id=user_data["login"],
                scopes=["gist", "read:user"],
                expires_at=int(time.time()) + (365 * 24 * 60 * 60),
            )

        except Exception:
            return None

    async def close(self):
        """Clean up HTTP client resources."""
        await self.client.aclose()
```

The provider stores the client ID and secret for the OAuth application.
The load_access_token method is called by the authentication middleware
for each MCP request. It validates the token by making a request to
GitHub's user endpoint. If the request succeeds, an AccessToken is
constructed with the user's login as the client_id. The scopes are
hardcoded here but could be extracted from GitHub's API response if
available.

## OAuth Flow Implementation

The OAuth flow requires two HTTP endpoints. The authorization endpoint
redirects the user to GitHub where they log in and grant permissions. The
callback endpoint receives the authorization code from GitHub and
exchanges it for an access token.

```python
from starlette.responses import RedirectResponse, JSONResponse
from starlette.routing import Route
import urllib.parse
import secrets


async def oauth_authorize(request):
    """
    Redirect the user to GitHub's authorization page.

    The user will see what permissions our application is
    requesting and can approve or deny. GitHub redirects back
    to our callback with an authorization code.
    """
    # Generate random state to prevent CSRF attacks.
    state = secrets.token_urlsafe(32)

    params = {
        "client_id": github_provider.client_id,
        "redirect_uri": "http://localhost:9991/oauth/callback",
        "scope": "gist read:user",
        "state": state,
    }

    auth_url = (
        "https://github.com/login/oauth/authorize?"
        + urllib.parse.urlencode(params)
    )

    # In production, store state in session to validate callback.
    return RedirectResponse(auth_url)


async def oauth_callback(request):
    """
    Handle the OAuth callback from GitHub.

    GitHub redirects here with an authorization code. We exchange
    the code for an access token that represents the user's grant
    of permission to our application.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return JSONResponse(
            {"error": "No authorization code received"},
            status_code=400,
        )

    # In production, validate state parameter against session.

    # Exchange authorization code for access token.
    token_response = await github_provider.client.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": github_provider.client_id,
            "client_secret": github_provider.client_secret,
            "code": code,
            "redirect_uri": "http://localhost:9991/oauth/callback",
        },
        headers={"Accept": "application/json"},
    )

    if token_response.status_code != 200:
        return JSONResponse(
            {"error": "Failed to exchange authorization code"},
            status_code=400,
        )

    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return JSONResponse(
            {"error": "No access token in response"},
            status_code=400,
        )

    # Return the token to the user. In production, this might
    # be stored in a session or returned via a secure mechanism.
    return JSONResponse({
        "access_token": access_token,
        "instructions": (
            "Include this token in MCP requests using the "
            "Authorization header: Bearer <token>"
        ),
    })
```

The authorization endpoint constructs a URL pointing to GitHub's OAuth
authorization page. The scope parameter specifies what permissions the
application requests. The state parameter is a random value used to
prevent CSRF attacks. In production, this value should be stored in the
session and validated in the callback.

The callback endpoint receives the authorization code from GitHub. This
code is short-lived and single-use. The endpoint exchanges the code for an
access token by making a POST request to GitHub's token endpoint. The
client secret proves that the request comes from the registered
application. The access token returned represents the user's authorization
for the application to act on their behalf.

## Building the MCP Server

The MCP server is configured with the GitHub OAuth provider. When a
request arrives with a bearer token, the authentication middleware calls
load_access_token to validate it. If valid, the token is made available to
tools via get_access_token.

```python
from reboot.mcp.server import DurableMCP
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl


# Initialize the OAuth provider with credentials.
github_provider = GitHubOAuthProvider(
    client_id="your_github_client_id",
    client_secret="your_github_client_secret",
)

# Create the MCP server with authentication enabled.
mcp = DurableMCP(
    path="/mcp",
    auth_server_provider=github_provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://github.com"),
        resource_server_url=AnyHttpUrl("http://localhost:9991"),
    ),
)
```

The auth_server_provider parameter enables authentication. The server
automatically configures middleware to validate bearer tokens on each
request. The auth parameter provides metadata about the OAuth
configuration, though it is primarily informational in this case.

## Implementing MCP Tools

Tools use get_access_token to retrieve the authenticated user's token.
This token is then used to make GitHub API calls on behalf of the user.
The key insight is that the same token used for authentication is used for
authorization to GitHub.

```python
from mcp.server.auth.middleware.auth_context import get_access_token


@mcp.tool()
async def create_gist(
    description: str,
    filename: str,
    content: str,
    public: bool = True,
) -> dict:
    """
    Create a GitHub gist on behalf of the authenticated user.

    The gist will appear under the user's GitHub account. The
    user must have granted the 'gist' scope during OAuth.
    """
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    if "gist" not in token.scopes:
        raise Exception("Requires 'gist' scope")

    # Use the user's token to create the gist as them.
    response = await github_provider.client.post(
        "https://api.github.com/gists",
        headers={
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "description": description,
            "public": public,
            "files": {
                filename: {
                    "content": content,
                },
            },
        },
    )

    if response.status_code != 201:
        raise Exception(f"Failed to create gist: {response.text}")

    gist_data = response.json()
    return {
        "id": gist_data["id"],
        "url": gist_data["html_url"],
        "created_by": token.client_id,
    }


@mcp.tool()
async def list_my_gists() -> dict:
    """
    List gists created by the authenticated user.

    Returns the user's public and private gists. Requires
    authentication but uses the implicit 'gist' scope.
    """
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    response = await github_provider.client.get(
        "https://api.github.com/gists",
        headers={
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/vnd.github+json",
        },
    )

    if response.status_code != 200:
        raise Exception("Failed to list gists")

    gists = response.json()
    return {
        "count": len(gists),
        "gists": [
            {
                "id": gist["id"],
                "description": gist.get("description", "No description"),
                "url": gist["html_url"],
                "public": gist["public"],
                "files": list(gist["files"].keys()),
            }
            for gist in gists[:10]
        ],
    }


@mcp.tool()
async def get_my_profile() -> dict:
    """
    Get the authenticated user's GitHub profile.

    This demonstrates that the token represents the user's
    identity and can be used to access user-specific data.
    """
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    response = await github_provider.client.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/vnd.github+json",
        },
    )

    if response.status_code != 200:
        raise Exception("Failed to fetch profile")

    user = response.json()
    return {
        "login": user["login"],
        "name": user.get("name"),
        "bio": user.get("bio"),
        "public_gists": user["public_gists"],
        "followers": user["followers"],
    }
```

Each tool calls get_access_token to retrieve the user's token. The token
object includes the token string, the user's client_id (GitHub login), and
the granted scopes. Tools check that required scopes are present before
making API calls. The token is then used in the Authorization header for
GitHub API requests. GitHub sees these requests as coming from the
authenticated user, not from the MCP server.

## Complete Application

The complete application combines the OAuth flow endpoints with the MCP
server.

```python
from starlette.applications import Starlette
from reboot.aio.applications import Application


# Define routes for the OAuth flow.
oauth_routes = [
    Route("/oauth/authorize", oauth_authorize),
    Route("/oauth/callback", oauth_callback),
]

# Get the MCP application with authentication middleware.
mcp_app = mcp.application()

# Combine OAuth routes with MCP routes.
app = Starlette(
    routes=oauth_routes + mcp_app.routes,
    middleware=mcp_app.middleware,
)

# Wrap in Reboot application for workflow durability.
application = Application(
    name="github-gist-mcp",
    starlette=app,
)
```

The OAuth routes handle the authorization flow. The MCP application
provides the /mcp endpoint with authentication middleware. The middleware
validates bearer tokens on each request. The Reboot application wrapper
provides workflow durability so the MCP session state survives server
restarts.

## Client Usage Flow

The client must first obtain an access token through the OAuth flow. The
flow proceeds as follows.

```
Client                         Server                 GitHub
------                         ------                 ------

1. User visits
   /oauth/authorize
                           --> Redirect to GitHub
                                                  --> Show login page
                                                      User authenticates
                                                      User approves scopes
                                                  <-- Redirect with code

2. Browser redirected to
   /oauth/callback?code=X
                           --> Exchange code
                               for token          -->
                                                  <-- Return access_token

3. Display token to user
   User copies token

4. MCP client connects
   with Authorization:
   Bearer <token>         --> Validate token     -->
                                                  <-- Token valid
                          <-- Session established

5. Call create_gist tool
   with bearer token      --> Validate token
                              Create gist         -->
                              with user token
                                                  <-- Gist created
                          <-- Return gist URL
```

The user initiates the OAuth flow by visiting the authorization endpoint.
After GitHub redirects back with the code, the callback endpoint exchanges
it for an access token. The user copies this token and provides it to
their MCP client. Each MCP request includes the token in the Authorization
header. The server validates the token and uses it to make GitHub API
calls as the user.

## Example MCP Client Code

```python
from reboot.mcp.client import connect


async def main():
    # Token obtained from OAuth flow (user copies from callback).
    access_token = "gho_xxxxxxxxxxxxxxxxxxxx"

    async with connect(
        "http://localhost:9991/mcp",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (session, session_id, protocol_version):
        # Create a gist as the authenticated user.
        result = await session.call_tool(
            "create_gist",
            arguments={
                "description": "My MCP-created gist",
                "filename": "example.py",
                "content": "print('Hello from MCP')",
                "public": True,
            },
        )
        print("Gist created:", result.content[0].text)

        # List the user's gists.
        result = await session.call_tool(
            "list_my_gists",
            arguments={},
        )
        print("My gists:", result.content[0].text)

        # Get user profile.
        result = await session.call_tool(
            "get_my_profile",
            arguments={},
        )
        print("Profile:", result.content[0].text)
```

The client includes the access token in every request. The server
validates the token and makes GitHub API calls using it. The created gist
appears under the user's GitHub account, not under any MCP server account.

## Security Considerations

### Token Storage

The access token represents the user's authority to act on GitHub. It must
be stored securely by the client. Never log access tokens or include them
in error messages. The server should not store user tokens in durable
state. Token validation happens per-request by calling GitHub's API.

### Scope Limitation

Request only the scopes your application needs. This example requests
"gist" and "read:user". Avoid requesting broad scopes like "repo" unless
you need repository access. Document clearly what scopes are required and
why.

### State Parameter

The state parameter in the OAuth flow prevents CSRF attacks. Generate a
random value when redirecting to GitHub. Store it in the session. Validate
that the state parameter in the callback matches the stored value. This
ensures the callback originated from a redirect you initiated.

### HTTPS in Production

Use HTTPS for all OAuth flows in production. GitHub requires HTTPS for
OAuth callbacks except for localhost during development. Configure proper
TLS certificates before deploying to production.

### Token Refresh

GitHub personal access tokens do not expire by default. However, OAuth
tokens may have expiry times. Implement token refresh logic using refresh
tokens if your OAuth provider supports it. The MCP client is responsible
for refreshing tokens before they expire.

## Advantages and Disadvantages

### Advantages

The delegated access pattern has several advantages. Actions are
attributed to the correct user. GitHub shows the user as the creator of
gists, not a service account. Permissions are scoped per user. Each user
grants only the permissions they want. No service credentials are needed.
The MCP server does not need its own GitHub account or API key. Audit
trails are accurate. GitHub's audit logs show which user performed each
action.

### Disadvantages

The pattern also has disadvantages. Users must complete the OAuth flow.
This adds friction compared to unauthenticated access. Token management is
complex. Clients must obtain, store, and provide tokens. Rate limits are
per user. Each user has their own GitHub rate limit which may be lower
than service limits. Revocation affects the user. If a user revokes the
OAuth grant, they lose access to the MCP server.

## When to Use This Pattern

Use the delegated access pattern when actions should be attributed to
users, when users need different permissions, when compliance requires
accurate audit trails, or when you want to avoid managing service
credentials. This pattern is appropriate for personal tools, collaborative
applications, and user-specific automation.

Do not use this pattern when you need consistent service identity, when
user authentication adds too much friction, when you need higher rate
limits than individual users have, or when the service needs to act
independently of any user. For these cases, consider the service
credentials pattern described in the companion tutorial.

## Appendix: Using Google Gemini CLI with Delegated OAuth

Google's Gemini CLI provides an example of a client that supports OAuth
flows for MCP servers. This appendix demonstrates configuring Gemini to
connect to an MCP server using GitHub OAuth for delegated access.

### Installing Gemini CLI

Install the Gemini CLI using pip. The CLI requires Python 3.10 or later.

```bash
pip install google-generativeai
```

Configure your Google API key for Gemini access. Obtain a key from
https://makersuite.google.com/app/apikey and set it in your environment.

```bash
export GOOGLE_API_KEY="your-api-key"
```

### MCP Server Configuration for Gemini

Gemini CLI reads MCP server configurations from a JSON file. Create a
configuration file at ~/.config/gemini/mcp-servers.json with your server
details.

```json
{
  "github-gist-mcp": {
    "url": "http://localhost:9991/mcp",
    "auth": {
      "type": "oauth",
      "authorization_url": "http://localhost:9991/oauth/authorize",
      "token_url": "http://localhost:9991/oauth/callback",
      "scopes": ["gist", "read:user"]
    }
  }
}
```

The configuration specifies the MCP server URL and OAuth endpoints. The
authorization_url points to the endpoint that redirects to GitHub. The
token_url points to the callback endpoint that exchanges the code for a
token. The scopes specify what permissions to request from GitHub.

### OAuth Flow with Gemini CLI

When Gemini CLI connects to the MCP server, it initiates the OAuth flow
automatically. The process follows these steps.

```
Gemini CLI              MCP Server              GitHub
----------              ----------              ------

1. gemini connect
   github-gist-mcp  --> GET /oauth/authorize
                        Redirect to GitHub  -->
                                                Browser opens
                                                User logs in
                                                User approves
                                            <-- Redirect w/code

2. CLI detects
   redirect         --> POST /oauth/callback
                        with code
                        Exchange for token  -->
                                            <-- Access token
                    <-- Return token

3. Store token in
   ~/.config/gemini/tokens/github-gist-mcp.json

4. MCP requests  --> Include token in
   include token     Authorization header
```

The CLI opens a browser window for the GitHub authorization page. The user
logs in and approves the requested scopes. GitHub redirects to the
callback URL with an authorization code. The CLI captures this code and
exchanges it for an access token. The token is stored locally in the
Gemini configuration directory. Subsequent MCP requests include the token
in the Authorization header.

### Token Storage and Refresh

Gemini CLI stores tokens in JSON files under ~/.config/gemini/tokens/.
Each MCP server has a separate token file. The file contains the access
token, refresh token (if provided), expiry time, and scopes.

```json
{
  "access_token": "gho_xxxxxxxxxxxxxxxxxxxx",
  "refresh_token": null,
  "expires_at": 1735689600,
  "scopes": ["gist", "read:user"]
}
```

The CLI checks the expiry time before each request. If the token is
expired or expiring soon, the CLI attempts to refresh it using the refresh
token. GitHub OAuth tokens typically do not expire, so the refresh_token
field may be null. If refresh fails or is not available, the CLI
re-initiates the OAuth flow.

### Using the Authenticated Connection

Once authenticated, Gemini CLI can invoke MCP tools using the user's
GitHub credentials. The interaction looks like standard Gemini usage but
with MCP tool calls.

```bash
gemini connect github-gist-mcp

> Create a gist with the code for a hello world program in Python
```

Gemini invokes the create_gist tool with appropriate arguments. The MCP
server validates the token from the CLI and uses it to create a gist on
GitHub. The gist appears under the user's GitHub account. Gemini receives
the gist URL and incorporates it into the response.

```
Creating a gist for you...

I've created a public gist with your Python hello world program:
https://gist.github.com/username/abc123

The gist contains:
- filename: hello.py
- content: print('Hello, world!')
```

The user can verify the gist was created by visiting their GitHub profile.
The gist appears in their list of gists with their username as the author.

### Token Revocation and Re-authentication

Users can revoke OAuth access at any time through GitHub settings. Visit
https://github.com/settings/applications and find the MCP application in
the authorized OAuth apps list. Click Revoke to remove access.

When Gemini CLI next attempts to use the MCP server, the token validation
fails. The server returns a 401 Unauthorized response. The CLI detects
this and automatically re-initiates the OAuth flow. The user is prompted
to re-authorize the application in their browser. Once re-authorized, a
new token is obtained and stored.

### Security Considerations for Gemini CLI

The Gemini CLI stores tokens in plaintext JSON files in the user's home
directory. On Unix systems, ensure the ~/.config/gemini directory has
restrictive permissions (700) so other users cannot read token files. On
multi-user systems, consider using encrypted storage or a credential
manager instead.

The CLI trusts the MCP server to handle OAuth correctly. Verify the server
URL before connecting. Only connect to MCP servers you control or trust.
Malicious servers could capture OAuth tokens during the flow.

Review the requested scopes before approving OAuth requests. Only grant
the minimum scopes needed for the MCP server's functionality. For example,
if the server only creates gists, do not approve requests for "repo"
scope which grants full repository access.

### Limitations and Compatibility

Not all MCP clients support OAuth flows. The Gemini CLI demonstrates one
approach but other clients may differ. Claude Code, as of the current
version, does not support OAuth flows for MCP servers. Users must obtain
tokens manually through a web browser and configure them in the client.

The OAuth flow requires a browser for user interaction. Headless
environments or automated systems cannot complete the flow without
additional tooling. For automated use cases, consider generating personal
access tokens or using the service credentials pattern instead.

MCP server implementations must correctly handle OAuth callbacks. The
server must be accessible from the browser for the redirect to work. When
running locally, localhost URLs work for development. In production,
configure proper DNS and HTTPS for the callback URL.

### Alternative: Manual Token Configuration

If the Gemini CLI does not support automatic OAuth flows, tokens can be
configured manually. Complete the OAuth flow in a web browser to obtain an
access token. Copy the token from the callback response. Create the token
file manually at ~/.config/gemini/tokens/github-gist-mcp.json.

```json
{
  "access_token": "gho_xxxxxxxxxxxxxxxxxxxx",
  "refresh_token": null,
  "expires_at": null,
  "scopes": ["gist", "read:user"]
}
```

Update the MCP server configuration to indicate the token is
pre-configured.

```json
{
  "github-gist-mcp": {
    "url": "http://localhost:9991/mcp",
    "auth": {
      "type": "bearer",
      "token_file": "~/.config/gemini/tokens/github-gist-mcp.json"
    }
  }
}
```

The CLI reads the token from the file and includes it in the Authorization
header. This approach bypasses the OAuth flow but requires manual token
management. Users must manually refresh tokens when they expire and update
the file accordingly.
