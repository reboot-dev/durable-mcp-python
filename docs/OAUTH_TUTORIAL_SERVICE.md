# OAuth Tutorial: Service Credentials Pattern

This tutorial demonstrates building an MCP server that uses its own
credentials to access external services. The server authenticates users
with a separate identity provider (Auth0) and uses service credentials to
access GitHub. This pattern separates user identity from service
authorization.

## Architecture Overview

The service credentials pattern involves four parties: the user, the MCP
server, an identity provider (Auth0), and a resource service (GitHub). The
user authenticates with Auth0 to prove their identity to the MCP server.
The MCP server has its own GitHub credentials separate from any user. When
the user calls MCP tools, the server uses its own credentials to access
GitHub. GitHub sees all actions as coming from the service account, not
from individual users.

```
User            MCP Server          Auth0           GitHub
----            ----------          -----           ------

1. Initiate --> Redirect to     -->
   auth         Auth0                Display login
                                 <-- User approves
                Auth code        <--

2.              Exchange code    -->
                for token            Validate
                                 <-- Access token
                                     (user identity)

3. Call MCP --> Validate user   -->
   tool with    token                Check token
   user token                    <-- Valid

                Use service      -->
                credentials to       Authenticate
                access GitHub        service
                                 <-- Data returned
                                     (as service)
   Result   <--
```

The critical distinction is that the user's access token proves their
identity to the MCP server but is never sent to GitHub. The MCP server has
its own GitHub credentials (personal access token or OAuth app) that it
uses for all GitHub operations. User authorization is enforced by the MCP
server, not by GitHub.

## Prerequisites

You need an Auth0 account for user authentication and a GitHub account for
creating a personal access token or OAuth app. Install Python 3.12 or
later and the DurableMCP framework. Understand OAuth 2.1 concepts and the
difference between authentication (proving identity) and authorization
(granting permissions).

## Auth0 Setup for User Authentication

Auth0 provides managed authentication services. Create an Auth0 account at
auth0.com and create a new application. Choose "Regular Web Application"
as the application type. Note the Domain, Client ID, and Client Secret
from the application settings.

Configure the allowed callback URL to
"http://localhost:9991/auth/callback" for development. Configure the
allowed logout URL to "http://localhost:9991" if implementing logout. In
the API section, create an API representing your MCP server with an
identifier like "https://mcp.example.com". Define permissions (scopes)
such as "read:gists", "write:gists", and "admin:server".

## GitHub Service Credentials

The MCP server needs its own GitHub credentials. Create a personal access
token by navigating to GitHub Settings, then Developer settings, then
Personal access tokens, then Tokens (classic). Click Generate new token
and select the "gist" scope to allow creating gists. Set an expiration
time appropriate for your use case (30 days, 90 days, or no expiration for
development). Copy the generated token and store it securely.

Alternatively, register an OAuth application for the service account. This
is more complex but allows using OAuth flows instead of personal access
tokens. For this tutorial, a personal access token is simpler and
sufficient.

## Implementing the Auth0 Provider

The Auth0 provider validates user tokens by calling Auth0's token
introspection endpoint. This confirms that the token is valid and extracts
the user's identity and granted scopes.

```python
import time
from typing import Optional
from mcp.server.auth.provider import (
    AccessToken,
    OAuthAuthorizationServerProvider,
)
import httpx


class Auth0Provider(OAuthAuthorizationServerProvider):
    """
    OAuth provider for Auth0 that validates user identity tokens.

    These tokens prove the user's identity to the MCP server but
    are not used to access external services. The MCP server uses
    separate service credentials for that purpose.
    """

    def __init__(
        self,
        domain: str,
        client_id: str,
        client_secret: str,
    ):
        self.domain = domain
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = httpx.AsyncClient()

    async def load_access_token(
        self,
        token: str,
    ) -> Optional[AccessToken]:
        """
        Validate a user's Auth0 access token.

        Returns an AccessToken with the user's identifier and
        scopes granted by Auth0. The scopes represent what the
        user can do on the MCP server, not on external services.
        """
        try:
            # Call Auth0's token introspection endpoint.
            response = await self.client.post(
                f"https://{self.domain}/oauth/token/introspect",
                data={
                    "token": token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )

            if response.status_code != 200:
                return None

            data = response.json()

            # Check if token is active.
            if not data.get("active"):
                return None

            # Extract user identifier and scopes.
            return AccessToken(
                token=token,
                client_id=data.get("sub", "unknown"),
                scopes=data.get("scope", "").split(),
                expires_at=data.get("exp"),
            )

        except Exception:
            return None

    async def close(self):
        """Clean up HTTP client resources."""
        await self.client.aclose()
```

The provider calls Auth0's introspection endpoint for each request. The
endpoint returns whether the token is active and what scopes it has. The
client_id field contains the user's unique identifier (subject claim). The
scopes represent permissions defined in Auth0, such as "read:gists" or
"write:gists". These scopes control what the user can ask the MCP server
to do, not what the server can do on GitHub.

## Auth0 OAuth Flow

The OAuth flow for user authentication uses Auth0 as the authorization
server. The user logs in to Auth0 and grants the MCP server permission to
access their identity.

```python
from starlette.responses import RedirectResponse, JSONResponse
from starlette.routing import Route
import urllib.parse
import secrets


async def auth_authorize(request):
    """
    Redirect the user to Auth0 for authentication.

    The user proves their identity to Auth0. Auth0 then issues
    a token that the MCP server can validate. This token is not
    used to access GitHub.
    """
    state = secrets.token_urlsafe(32)

    params = {
        "response_type": "code",
        "client_id": auth0_provider.client_id,
        "redirect_uri": "http://localhost:9991/auth/callback",
        "scope": "openid profile read:gists write:gists",
        "audience": "https://mcp.example.com",
        "state": state,
    }

    auth_url = (
        f"https://{auth0_provider.domain}/authorize?"
        + urllib.parse.urlencode(params)
    )

    return RedirectResponse(auth_url)


async def auth_callback(request):
    """
    Handle the OAuth callback from Auth0.

    Auth0 redirects here with an authorization code. We exchange
    the code for an access token that proves the user's identity.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return JSONResponse(
            {"error": "No authorization code received"},
            status_code=400,
        )

    # Exchange authorization code for access token.
    token_response = await auth0_provider.client.post(
        f"https://{auth0_provider.domain}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": auth0_provider.client_id,
            "client_secret": auth0_provider.client_secret,
            "code": code,
            "redirect_uri": "http://localhost:9991/auth/callback",
        },
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

    return JSONResponse({
        "access_token": access_token,
        "instructions": (
            "Use this token to authenticate with the MCP server. "
            "Include it in the Authorization header: Bearer <token>"
        ),
    })
```

The authorization endpoint redirects to Auth0 with the requested scopes.
The audience parameter identifies the MCP server API. The callback
endpoint exchanges the authorization code for an access token. This token
represents the user's identity and their granted permissions on the MCP
server. It is not used to access GitHub.

## GitHub Service Client

The MCP server needs a client for accessing GitHub using service
credentials. This client is separate from the OAuth provider and uses the
service account's personal access token.

```python
class GitHubServiceClient:
    """
    Client for accessing GitHub using service credentials.

    All GitHub operations use the service account's credentials,
    not user credentials. Users are authenticated separately via
    Auth0.
    """

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.client = httpx.AsyncClient()

    async def create_gist(
        self,
        description: str,
        filename: str,
        content: str,
        public: bool = True,
    ) -> dict:
        """
        Create a gist using the service account.

        The gist is created as the service account, not as any
        individual user. The calling user must be authenticated
        to the MCP server, but their identity is not used for
        GitHub authorization.
        """
        response = await self.client.post(
            "https://api.github.com/gists",
            headers={
                "Authorization": f"Bearer {self.access_token}",
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

        return response.json()

    async def list_gists(self) -> list:
        """
        List gists created by the service account.

        Returns gists owned by the service account, not by
        individual users.
        """
        response = await self.client.get(
            "https://api.github.com/gists",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/vnd.github+json",
            },
        )

        if response.status_code != 200:
            raise Exception("Failed to list gists")

        return response.json()

    async def close(self):
        """Clean up HTTP client resources."""
        await self.client.aclose()
```

The GitHubServiceClient always uses the service account's access token. It
never uses user credentials. All gists created through this client appear
under the service account on GitHub. User authentication happens
separately through Auth0 and only controls access to the MCP server.

## Building the MCP Server

The MCP server is configured with the Auth0 provider for user
authentication. The GitHub service client is initialized separately with
the service account credentials.

```python
from reboot.mcp.server import DurableMCP
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl


# Initialize Auth0 provider for user authentication.
auth0_provider = Auth0Provider(
    domain="your-tenant.auth0.com",
    client_id="your_auth0_client_id",
    client_secret="your_auth0_client_secret",
)

# Initialize GitHub service client with service credentials.
github_service = GitHubServiceClient(
    access_token="ghp_xxxxxxxxxxxxxxxxxxxx",
)

# Create MCP server with user authentication.
mcp = DurableMCP(
    path="/mcp",
    auth_server_provider=auth0_provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://your-tenant.auth0.com"),
        resource_server_url=AnyHttpUrl("http://localhost:9991"),
    ),
)
```

The auth_server_provider validates user tokens from Auth0. The GitHub
service client is separate and uses the service account's personal access
token. User authentication and GitHub authorization are completely
decoupled.

## Implementing MCP Tools with Service Credentials

Tools validate the user's identity through Auth0 but use service
credentials to access GitHub. User permissions are checked against the
scopes granted by Auth0, not against GitHub permissions.

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
    Create a gist using the service account.

    The user must be authenticated and have 'write:gists' scope
    from Auth0. The gist is created as the service account on
    GitHub, not as the user.
    """
    # Validate user authentication.
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    # Check user has permission to create gists.
    if "write:gists" not in token.scopes:
        raise Exception(
            f"Insufficient permissions: requires 'write:gists', "
            f"user has: {token.scopes}"
        )

    # Use service credentials to create gist on GitHub.
    gist_data = await github_service.create_gist(
        description=f"{description} (created by {token.client_id})",
        filename=filename,
        content=content,
        public=public,
    )

    return {
        "id": gist_data["id"],
        "url": gist_data["html_url"],
        "created_by_service": True,
        "requested_by": token.client_id,
    }


@mcp.tool()
async def list_service_gists() -> dict:
    """
    List gists created by the service account.

    The user must be authenticated and have 'read:gists' scope.
    Returns gists owned by the service account, not by users.
    """
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    if "read:gists" not in token.scopes:
        raise Exception("Requires 'read:gists' scope")

    # Use service credentials to list gists.
    gists = await github_service.list_gists()

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
async def get_my_permissions() -> dict:
    """
    Get the authenticated user's permissions.

    Shows what scopes the user has been granted by Auth0. These
    scopes control what the user can do on the MCP server, not
    what the service can do on GitHub.
    """
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    return {
        "user_id": token.client_id,
        "scopes": token.scopes,
        "expires_at": token.expires_at,
    }
```

Each tool first validates the user's Auth0 token to confirm
authentication. The token's scopes determine what the user can request the
server to do. For example, "write:gists" allows requesting gist creation.
The server then uses its own GitHub credentials to fulfill the request.
GitHub sees all actions as coming from the service account.

## Complete Application

```python
from starlette.applications import Starlette
from reboot.aio.applications import Application


# Define routes for Auth0 authentication flow.
auth_routes = [
    Route("/auth/authorize", auth_authorize),
    Route("/auth/callback", auth_callback),
]

# Get MCP application with authentication middleware.
mcp_app = mcp.application()

# Combine authentication routes with MCP routes.
app = Starlette(
    routes=auth_routes + mcp_app.routes,
    middleware=mcp_app.middleware,
)

# Wrap in Reboot application for durability.
application = Application(
    name="github-service-mcp",
    starlette=app,
)
```

The application provides endpoints for Auth0 authentication and the MCP
protocol. Users authenticate with Auth0 to obtain a token proving their
identity. They use this token to call MCP tools. The server validates the
token with Auth0 and uses service credentials for GitHub access.

## Client Usage Flow

```
Client          MCP Server      Auth0           GitHub
------          ----------      -----           ------

1. Visit auth
   endpoint --> Redirect to  -->
                Auth0            User logs in
                             <-- Redirect w/code

2. Callback  --> Exchange    -->
                 code             Validate
                             <-- User token

3. Copy token

4. MCP request
   with user --> Validate    -->
   token         token            Check active
                             <-- Valid
                 Use service -->
                 token            Create gist
                 for GitHub       as service
                             <-- Gist created
   Result    <--
```

The user authenticates with Auth0 to prove their identity. The MCP server
validates this identity on each request. GitHub operations use the service
account's credentials. The user never directly authenticates to GitHub.

## Example MCP Client Code

```python
from reboot.mcp.client import connect


async def main():
    # Token obtained from Auth0 flow (proves user identity).
    user_token = "eyJ0eXAiOiJKV1QiLCJhbGc..."

    async with connect(
        "http://localhost:9991/mcp",
        headers={"Authorization": f"Bearer {user_token}"},
    ) as (session, session_id, protocol_version):
        # User's token is validated by Auth0.
        # GitHub operations use service credentials.

        result = await session.call_tool(
            "create_gist",
            arguments={
                "description": "Created via MCP service",
                "filename": "example.py",
                "content": "print('Hello from service')",
                "public": True,
            },
        )
        print("Gist created:", result.content[0].text)

        result = await session.call_tool(
            "list_service_gists",
            arguments={},
        )
        print("Service gists:", result.content[0].text)

        result = await session.call_tool(
            "get_my_permissions",
            arguments={},
        )
        print("My permissions:", result.content[0].text)
```

The client uses the Auth0 token for all requests. This token proves the
user's identity and permissions on the MCP server. The server uses its own
GitHub credentials internally. The user never sees or handles GitHub
credentials.

## Security Considerations

### Separation of Concerns

Keep user authentication separate from service authorization. User tokens
from Auth0 prove identity to the MCP server. Service credentials for
GitHub are managed by the server and never exposed to users. This
separation limits the blast radius if user tokens are compromised.

### Service Token Security

Protect the GitHub service token carefully. Store it in environment
variables or a secrets manager, never in source code. Rotate the token
periodically according to your security policy. Monitor GitHub's audit log
for unexpected activity from the service account.

### Scope Design

Design Auth0 scopes to match your application's authorization model. For
example, "read:gists" allows viewing gists, "write:gists" allows creating
them, and "admin:server" allows administrative operations. Users are
granted only the scopes they need. The MCP server enforces these scopes
independently of GitHub's permissions.

### Audit Trail

Log all operations with both the user identifier and the action performed.
Since GitHub sees all actions as coming from the service account, your
application logs are the only record of which user requested each action.
Include timestamps, user identifiers, and operation details in logs.

### Rate Limiting

The service account has a single GitHub rate limit shared by all users.
Implement application-level rate limiting to prevent any single user from
exhausting the service's quota. Consider implementing per-user quotas
based on their subscription tier or usage patterns.

## Advantages and Disadvantages

### Advantages

The service credentials pattern has several advantages. Consistent service
identity means all GitHub actions appear under one account, simplifying
management. Higher rate limits are available because enterprise or
organization accounts have higher limits than personal accounts. No user
OAuth flow is needed for GitHub, reducing complexity. Credential
management is centralized in one place. Service continuity is maintained
even if users revoke Auth0 access.

### Disadvantages

The pattern also has disadvantages. Attribution is lost on GitHub because
all actions appear as the service account, not individual users. A single
credential compromise affects all users since the service token grants
access for everyone. Audit trails require application logs since GitHub
logs do not show individual users. Resource quotas are shared across all
users. The service account needs broad permissions to serve all users.

## When to Use This Pattern

Use the service credentials pattern when you need consistent service
identity on external services, when user OAuth flows add too much
complexity, when you need higher rate limits than individual users have,
when the service should act independently of users, or when you want
centralized credential management. This pattern is appropriate for
multi-tenant SaaS applications, enterprise integrations, and services that
aggregate data from external sources.

Do not use this pattern when you need user attribution on external
services, when compliance requires individual user credentials, when users
should control their own permissions on external services, or when the
service should not have broad access on behalf of all users. For these
cases, consider the delegated access pattern described in the companion
tutorial.

## Hybrid Approaches

Some applications use both patterns. User authentication happens through
Auth0 for identity and MCP access control. Users can optionally connect
their own GitHub accounts for delegated access. If a user has connected
their account, their token is used for GitHub operations. Otherwise, the
service account is used as a fallback. This provides user attribution when
possible while maintaining service availability when users have not
connected accounts.

The implementation stores optional user GitHub tokens in the application
database. Tools check if the current user has a connected GitHub account.
If yes, the user's token is used. If no, the service account token is
used. This requires careful scope management to ensure both paths have
appropriate permissions.
