import asyncio
import functools
import httpx
import inspect
import logging
import mcp.types
import pickle
from dataclasses import dataclass
from log.log import get_logger, set_log_level
from mcp.server import fastmcp
from mcp.server.auth.middleware.auth_context import (
    AuthContextMiddleware,
    get_access_token,
)
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.provider import (
    OAuthAuthorizationServerProvider,
    ProviderTokenVerifier,
    TokenVerifier,
)
from mcp.server.auth.settings import AuthSettings
from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    ElicitationResult,
    ElicitSchemaModelT,
    _validate_elicitation_schema,
)
from mcp.server.session import ServerSession
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    StreamableHTTPServerTransport,
)
from mcp.shared.message import ServerMessageMetadata
from rbt.mcp.v1.session_rbt import Session
from rbt.v1alpha1.errors_pb2 import StateNotConstructed
from reboot.aio.applications import Application
from rebootdev.aio.servicers import Servicer
from reboot.aio.contexts import EffectValidation, WorkflowContext
from reboot.aio.external import ExternalContext, InitializeContext
from reboot.aio.types import StateRef
from reboot.aio.workflows import at_least_once
from reboot.mcp.event_store import (
    DurableEventStore,
    replay,
    qualified_stream_id,
)
from reboot.protobuf import from_model
from google.protobuf import struct_pb2
from reboot.mcp.servicers.session import (
    SessionServicer,
    _servers,
    _context,
)
from reboot.mcp.servicers.stream import StreamServicer
from reboot.std.collections.v1 import sorted_map
from rebootdev.aio.headers import SERVER_ID_HEADER, STATE_REF_HEADER
from rebootdev.aio.backoff import Backoff
from rebootdev.memoize.v1.memoize_rbt import Memoize
from rebootdev.settings import DOCS_BASE_URL
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send
from types import MethodType
from typing import Any, Awaitable, Callable, Literal, Protocol, TypeAlias, cast
from uuid import uuid4, uuid5
from uuid7 import create as uuid7  # type: ignore[import-untyped]

logger = get_logger(__name__)


class DurableSession:

    _session: ServerSession
    _context: WorkflowContext
    _event_aliases: set[str]

    def __init__(self, session: ServerSession, context: WorkflowContext):
        self._session = session
        self._context = context
        self._event_aliases = set()

    def _event_id(self, function_name: str, why: str):
        event_alias = f"{function_name}: {why}"

        assert self._context is not None

        if self._context.within_loop():
            event_alias += f" #{self._context.task.iteration}"

        if event_alias in self._event_aliases:
            raise TypeError(
                f"Looks like you're calling `{function_name}()` "
                "more than once with the same `why`"
            )

        self._event_aliases.add(event_alias)

        workflow_id = self._context.workflow_id

        assert workflow_id is not None

        # Generate a unique but deterministic ID for this event based
        # on the alias and this workflow (which is unique per
        # request).
        return uuid5(workflow_id, event_alias).hex

    async def send_resource_list_changed(self, why: str) -> None:
        """
        Send a resource list changed notification.

        Args:
            why: Description of why the resource list changed,
                 used to durably differentiate resource list
                 changed events that are sent to client
        """
        event_id = self._event_id("send_resource_list_changed", why)

        await self._session.send_notification(
            mcp.types.ServerNotification(
                mcp.types.ResourceListChangedNotification(
                    # TODO: figure out why `mypy` requires
                    # passing `method` which has a default.
                    method="notifications/resources/list_changed",
                    params=mcp.types.NotificationParams(
                        _meta=mcp.types.NotificationParams.Meta(
                            rebootEventId=str(event_id),
                        ),
                    ),
                ),
            ),
        )

    async def send_tool_list_changed(self, why: str) -> None:
        """
        Send a tool list changed notification.

        Args:
            why: Description of why the resource list changed,
                 used to durably differentiate resource list
                 changed events that are sent to client
        """
        event_id = self._event_id("send_tool_list_changed", why)

        await self._session.send_notification(
            mcp.types.ServerNotification(
                mcp.types.ToolListChangedNotification(
                    # TODO: figure out why `mypy` requires
                    # passing `method` which has a default.
                    method="notifications/tools/list_changed",
                    params=mcp.types.NotificationParams(
                        _meta=mcp.types.NotificationParams.Meta(
                            rebootEventId=str(event_id),
                        ),
                    ),
                ),
            ),
        )

    async def send_prompt_list_changed(self, why: str) -> None:
        """
        Send a prompt list changed notification.

        Args:
            why: Description of why the resource list changed,
                 used to durably differentiate resource list
                 changed events that are sent to client
        """
        event_id = self._event_id("send_prompt_list_changed", why)

        await self._session.send_notification(
            mcp.types.ServerNotification(
                mcp.types.PromptListChangedNotification(
                    # TODO: figure out why `mypy` requires
                    # passing `method` which has a default.
                    method="notifications/prompts/list_changed",
                    params=mcp.types.NotificationParams(
                        _meta=mcp.types.NotificationParams.Meta(
                            rebootEventId=str(event_id),
                        ),
                    ),
                ),
            ),
        )


class DurableContextProtocol(Protocol):

    _event_aliases: set[str]

    session: DurableSession

    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """Report progress for the current operation.

        Args:
            progress: Current progress value e.g. 24
            total: Optional total value e.g. 100
            message: Optional message e.g. Starting render...
        """
        ...

    async def log(
        self,
        level: Literal["debug", "info", "warning", "error"],
        message: str,
        *,
        logger_name: str | None = None,
    ) -> None:
        """Send a log message to the client.

        Args:
            level: Log level (debug, info, warning, error)
            message: Log message
            logger_name: Optional logger name
            **data: Additional structured data to include
        """
        ...

    async def debug(self, message: str) -> None:
        """Send a debug log message."""
        ...

    async def info(self, message: str) -> None:
        """Send an info log message."""
        ...

    async def warning(self, message: str) -> None:
        """Send a warning log message."""
        ...

    async def error(self, message: str) -> None:
        """Send an error log message."""
        ...

    async def elicit(
        self,
        message: str,
        schema: type[ElicitSchemaModelT],
    ) -> ElicitationResult:
         """
         Elicit information from the client/user.

        This method can be used to interactively ask for additional
        information from the client within a tool's execution. The
        client might display the message to the user and collect a
        response according to the provided schema. Or in case a client
        is an agent, it might decide how to handle the elicitation --
        either by asking the user or automatically generating a
        response.

        Args:
            schema: A Pydantic model class defining the expected
                    response structure, according to the
                    specification, only primive types are allowed.
            message: Optional message to present to the user. If not
                     provided, will use a default message based on the
                     schema

        Returns:
            An ElicitationResult containing the action taken and the
            data if accepted

        Note:
            Check the result.action to determine if the user accepted,
            declined, or cancelled.  The result.data will only be
            populated if action is "accept" and validation succeeded.
         """
         ...


class DurableContext(WorkflowContext, DurableContextProtocol):

    pass


@dataclass(kw_only=True, frozen=True)
class Resource:
    fn: mcp.types.AnyFunction
    uri: str
    name: str | None
    title: str | None
    description: str | None
    mime_type: str | None


@dataclass(kw_only=True, frozen=True)
class Prompt:
    func: mcp.types.AnyFunction
    name: str | None
    title: str | None
    description: str | None


@dataclass(kw_only=True, frozen=True)
class Tool:
    fn: mcp.types.AnyFunction
    name: str | None
    title: str | None
    description: str | None
    annotations: mcp.types.ToolAnnotations | None
    structured_output: bool | None


LogLevel: TypeAlias = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class DurableMCP:
    """
    Proxy for `fastmcp.FastMCP`, but wrapping tools, prompts, and
    resources appropriately to make them durable.

    NOTE: this class explicitly does NOT extend from `fastmcp.FastMCP`
    so that we don't mislead users into thinking some features are
    implemented that are not.
    """

    _log_level: LogLevel
    _resources: list[Resource]
    _prompts: list[Prompt]
    _tools: list[Tool]
    _auth: AuthSettings | None
    _auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None
    _token_verifier: TokenVerifier | None

    def __init__(
        self,
        *,
        path: str,
        log_level: LogLevel = "WARNING",
        auth: AuthSettings | None = None,
        auth_server_provider: (
            OAuthAuthorizationServerProvider[Any, Any, Any] | None
        ) = None,
        token_verifier: TokenVerifier | None = None,
    ):
        self._log_level = log_level
        self._path = path
        self._resources = []
        self._prompts = []
        self._tools = []
        self._auth = auth
        self._auth_server_provider = auth_server_provider
        self._token_verifier = token_verifier

        # Validate auth configuration (same as `FastMCP`).
        if self._auth is not None:
            if auth_server_provider and token_verifier:
                raise ValueError(
                    "Cannot specify both auth_server_provider and "
                    "token_verifier"
                )
            if not auth_server_provider and not token_verifier:
                raise ValueError(
                    "Must specify either auth_server_provider or "
                    "token_verifier when auth is enabled"
                )
        elif auth_server_provider or token_verifier:
            raise ValueError(
                "Cannot specify auth_server_provider or token_verifier "
                "without auth settings"
            )

        set_log_level(logging.getLevelNamesMapping()[log_level])

    @property
    def path(self):
        return self._path

    def servicers(self):
        return [SessionServicer, StreamServicer] + sorted_map.servicers()

    def resource(
        self,
        uri: str,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
    ) -> Callable[[mcp.types.AnyFunction], mcp.types.AnyFunction]:
        """Decorator to register a function as a resource.

        The function will be called when the resource is read to generate its content.
        The function can return:
        - str for text content
        - bytes for binary content
        - other types will be converted to JSON

        If the URI contains parameters (e.g. "resource://{param}") or the function
        has parameters, it will be registered as a template resource.

        Args:
            uri: URI for the resource (e.g. "resource://my-resource" or "resource://{param}")
            name: Optional name for the resource
            title: Optional human-readable title for the resource
            description: Optional description of the resource
            mime_type: Optional MIME type for the resource

        Example:
            @server.resource("resource://my-resource")
            def get_data() -> str:
                return "Hello, world!"

            @server.resource("resource://my-resource")
            async get_data() -> str:
                data = await fetch_data()
                return f"Hello, world! {data}"

            @server.resource("resource://{city}/weather")
            def get_weather(city: str) -> str:
                return f"Weather for {city}"

            @server.resource("resource://{city}/weather")
            async def get_weather(city: str) -> str:
                data = await fetch_weather(city)
                return f"Weather for {city}: {data}"
        """
        # Check if user passed function directly instead of calling decorator.
        if callable(uri):
            raise TypeError(
                "The @resource decorator was used incorrectly. "
                "Did you forget to call it? Use @resource('uri') instead of @resource"
            )

        def decorator(fn: mcp.types.AnyFunction) -> mcp.types.AnyFunction:
            self._resources.append(
                Resource(
                    fn=fn,
                    uri=uri,
                    name=name,
                    title=title,
                    description=description,
                    mime_type=mime_type,
                )
            )
            return fn

        return decorator

    def add_resource(self, resource: fastmcp.resources.Resource) -> None:
        # Where as `add_tool()` is a great insertion point,
        # `add_resource` gives us an already modified function which
        # does not pickle to the child process by default. This
        # probably isn't an issue as mostly folks will just use the
        # decorator, but if it is, we can try extracting everything
        # from `resource`? We also have to override the `resource()`
        # decorator anyway to get templates.
        raise NotImplementedError("Use `resource()` decorator instead")


    def prompt(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> Callable[[mcp.types.AnyFunction], mcp.types.AnyFunction]:
        """Decorator to register a prompt.

        Args:
            name: Optional name for the prompt (defaults to function name)
            title: Optional human-readable title for the prompt
            description: Optional description of what the prompt does

        Example:
            @server.prompt()
            def analyze_table(table_name: str) -> list[Message]:
                schema = read_table_schema(table_name)
                return [
                    {
                        "role": "user",
                        "content": f"Analyze this schema:\n{schema}"
                    }
                ]

            @server.prompt()
            async def analyze_file(path: str) -> list[Message]:
                content = await read_file(path)
                return [
                    {
                        "role": "user",
                        "content": {
                            "type": "resource",
                            "resource": {
                                "uri": f"file://{path}",
                                "text": content
                            }
                        }
                    }
                ]
        """
        # Check if user passed function directly instead of calling decorator.
        if callable(name):
            raise TypeError(
                "The @prompt decorator was used incorrectly. "
                "Did you forget to call it? Use @prompt() instead of @prompt"
            )

        def decorator(func: mcp.types.AnyFunction) -> mcp.types.AnyFunction:
            self._prompts.append(
                Prompt(
                    func=func,
                    name=name,
                    title=title,
                    description=description,
                ),
            )
            return func

        return decorator

    def add_prompt(self, prompt: fastmcp.prompts.Prompt) -> None:
        # Where as `add_tool()` is a great insertion point,
        # `add_prompt` gives us an already modified function which
        # does not pickle to the child process by default. This
        # probably isn't an issue as mostly folks will just use the
        # decorator, but if it is, we can try extracting everything
        # from `prompt`?
        raise NotImplementedError("Use `prompt()` decorator instead")

    def tool(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: mcp.types.ToolAnnotations | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[mcp.types.AnyFunction], mcp.types.AnyFunction]:
        """Decorator to register a tool.

        Tools can optionally request a Context object by adding a parameter with the
        Context type annotation. The context provides access to MCP capabilities like
        logging, progress reporting, and resource access.

        Args:
            name: Optional name for the tool (defaults to function name)
            title: Optional human-readable title for the tool
            description: Optional description of what the tool does
            annotations: Optional ToolAnnotations providing additional tool information
            structured_output: Controls whether the tool's output is structured or unstructured
                - If None, auto-detects based on the function's return type annotation
                - If True, unconditionally creates a structured tool (return type annotation permitting)
                - If False, unconditionally creates an unstructured tool

        Example:
            @server.tool()
            def my_tool(x: int) -> str:
                return str(x)

            @server.tool()
            def tool_with_context(x: int, ctx: Context) -> str:
                ctx.info(f"Processing {x}")
                return str(x)

            @server.tool()
            async def async_tool(x: int, context: Context) -> str:
                await context.report_progress(50, 100)
                return str(x)
        """
        # Check if user passed function directly instead of calling decorator
        if callable(name):
            raise TypeError(
                "The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool"
            )

        def decorator(fn: mcp.types.AnyFunction) -> mcp.types.AnyFunction:
            self.add_tool(
                fn,
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                structured_output=structured_output,
            )
            return fn

        return decorator

    def add_tool(
        self,
        fn: mcp.types.AnyFunction,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: mcp.types.ToolAnnotations | None = None,
        structured_output: bool | None = None,
    ) -> None:
        self._tools.append(
            Tool(
                fn=fn,
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                structured_output=structured_output,
            )
        )

    def application(
        self,
        *,
        servicers: list[type[Servicer]] | None = None,
        initialize: Callable[[InitializeContext], Awaitable[None]]
        | None = None,
    ) -> Application:
        """
        :param servicers: (optional) the types of Reboot-powered servicers that
                          this Application will serve.
        
        :param initialize: (optional) will be called after the Application's
                           servicers have started for the first time, so that
                           it can perform initialization logic (e.g.,
                           constructing some well-known durable data structures,
                           loading some data, etc. It must do so in the context
                           of the given InitializeContext.
       
        Returns a Reboot `Application` for running the MCP tools,
        resources, prompts, etc that were defined.
        """

        async def default_initialize(context: InitializeContext) -> None:
            # Do any app internal initialization here.

            if initialize is not None:
                await initialize(context)

        application = Application(
            servicers=(servicers or []) + self.servicers(),
            initialize=default_initialize,
        )

        application.http.mount(
            self._path,
            factory=self.streamable_http_app_factory,
        )

        return application

    @property
    def streamable_http_app_factory(self):
        return functools.partial(
            _streamable_http_app,
            self._log_level,
            self._path,
            self._resources,
            self._prompts,
            self._tools,
            self._auth,
            self._auth_server_provider,
            self._token_verifier,
        )


def _streamable_http_app(
    log_level: LogLevel,
    path: str,
    resources: list[Resource],
    prompts: list[Prompt],
    tools: list[Tool],
    auth: AuthSettings | None,
    auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None,
    token_verifier: TokenVerifier | None,
    external_context_from_request: Callable[[Request], ExternalContext],
):
    # Create token verifier from provider if needed (same as `FastMCP`).
    if auth_server_provider and not token_verifier:
        token_verifier = ProviderTokenVerifier(auth_server_provider)

    mcp = fastmcp.FastMCP(
        log_level=log_level,
        auth=auth,
        auth_server_provider=auth_server_provider,
        token_verifier=token_verifier,
    )

    for resource in resources:
        mcp.resource(
            resource.uri,
            name=resource.name,
            title=resource.title,
            description=resource.description,
            mime_type=resource.mime_type,
        )(resource.fn)

    for prompt in prompts:
        mcp.prompt(
            name=prompt.name,
            title=prompt.title,
            description=prompt.description,
        )(prompt.func)

    for tool in tools:
        mcp.add_tool(
            _wrap_tool(tool.fn),
            name=tool.name,
            title=tool.title,
            description=tool.description,
            annotations=tool.annotations,
            structured_output=tool.structured_output,
        )

    _servers[path] = mcp._mcp_server

    # Create the `endpoint`.
    endpoint = StreamableHTTPASGIApp(
        path,
        external_context_from_request,
    )

    # Add authentication middleware if `token_verifier` is configured.
    middleware = None
    if token_verifier:
        middleware = [
            Middleware(
                AuthenticationMiddleware,
                backend=BearerAuthBackend(token_verifier),
            ),
            Middleware(AuthContextMiddleware),
        ]
        # Wrap `endpoint` with auth requirement middleware.
        required_scopes = (auth.required_scopes if auth else None) or []
        resource_metadata_url = None
        endpoint = RequireAuthMiddleware(
            endpoint, required_scopes, resource_metadata_url
        )

    return Starlette(
        routes=[
            Route(
                "/{path:path}",
                endpoint=endpoint,
            ),
        ],
        middleware=middleware,
    )


def _wrap_tool(fn: mcp.types.AnyFunction) -> mcp.types.AnyFunction:
    signature = inspect.signature(fn)

    wrapper_parameters = [
        # Always include the `context` parameter so we can access
        # session specific things.
        inspect.Parameter(
            "ctx",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=fastmcp.Context,
        )
    ]

    context_parameter_names = []

    for parameter_name, parameter in signature.parameters.items():
        annotation = parameter.annotation
        if (
            isinstance(annotation, type) and
            issubclass(annotation, fastmcp.Context)
        ):
            raise TypeError(
                "`DurableMCP` only injects `DurableContext` not `Context`")
        if (
            isinstance(annotation, type) and
            issubclass(annotation, DurableContext)
        ):
            context_parameter_names.append(parameter_name)
        else:
            wrapper_parameters.append(parameter)

    wrapper_signature = signature.replace(parameters=wrapper_parameters)

    async def wrapper(
        ctx: fastmcp.Context,
        context: WorkflowContext,
        *args,
        **kwargs,
    ):
        # To account for the lack of "intersection" types in
        # Python (which is actively being worked on), we instead
        # create a new dynamic `DurableContext` instance that
        # inherits from the instance of `WorkflowContext` that we
        # already have.
        context.__class__ = DurableContext

        context = cast(DurableContext, context)

        # Now we add the `DurableContextProtocol` properties.
        context._event_aliases = set()

        context.session = DurableSession(ctx.session, context)

        async def report_progress(
            self,
            progress: float,
            total: float | None = None,
            message: str | None = None,
        ) -> None:
            progress_token = (
                ctx.request_context.meta.progressToken
                if ctx.request_context.meta else None
            )

            if progress_token is None:
                return

            # TODO: consider tracking all reported progress and if
            # it has gone "backwards" provide a nice error so
            # developers can fix their bug (presumably they don't
            # ever want the progress to go "backwards").

            event_alias = (
                f"report_progress(progress={progress}, total={total}, "
                f"message={message})"
            )

            assert context is not None

            if context.within_loop():
                event_alias += f" #{context.task.iteration}"

            if event_alias in self._event_aliases:
                raise TypeError(
                    f"Looks like you're calling `report_progress()` "
                    "more than once with the same arguments"
                )

            self._event_aliases.add(event_alias)

            workflow_id = context.workflow_id

            assert workflow_id is not None

            # Generate a unique but deterministic ID for this
            # event based on the alias and this workflow (which is
            # unique per request).
            event_id = uuid5(workflow_id, event_alias).hex

            await ctx.session.send_notification(
                mcp.types.ServerNotification(
                    mcp.types.ProgressNotification(
                        # TODO: figure out why `mypy` requires
                        # passing `method` which has a default.
                        method="notifications/progress",
                        params=mcp.types.ProgressNotificationParams(
                            progressToken=progress_token,
                            progress=progress,
                            total=total,
                            message=message,
                            _meta=mcp.types.NotificationParams.Meta(
                                rebootEventId=str(event_id),
                            ),
                        ),
                    ),
                ),
                related_request_id=ctx.request_id,
            )

        context.report_progress = MethodType(report_progress, context)  # type: ignore[method-assign]

        async def log(
            self,
            level: Literal["debug", "info", "warning", "error"],
            message: str,
            *,
            logger_name: str | None = None,
        ) -> None:
            event_alias = (
                f"log(level='{level}', message='{message}', logger_name={logger_name})"
            )

            assert context is not None

            if context.within_loop():
                event_alias += f" #{context.task.iteration}"

            if event_alias in self._event_aliases:
                raise TypeError(
                    "Looks like you're trying to `log()` "
                    "more than once with the same arguments"
                )

            self._event_aliases.add(event_alias)

            workflow_id = context.workflow_id

            assert workflow_id is not None

            # Generate a unique but deterministic ID for this
            # event based on the alias and this workflow (which is
            # unique per request).
            event_id = uuid5(workflow_id, event_alias).hex

            await ctx.session.send_notification(
                mcp.types.ServerNotification(
                    mcp.types.LoggingMessageNotification(
                        # TODO: figure out why `mypy` requires
                        # passing `method` which has a default.
                        method="notifications/message",
                        params=mcp.types.LoggingMessageNotificationParams(
                            level=level,
                            data=message,
                            logger=logger_name,
                            _meta=mcp.types.NotificationParams.Meta(
                                rebootEventId=str(event_id),
                            ),
                        ),
                    )
                ),
                related_request_id=ctx.request_id,
            )

        context.log = MethodType(log, context)  # type: ignore[method-assign]

        async def debug(self, message: str) -> None:
            await self.log("debug", message)

        context.debug = MethodType(debug, context)  # type: ignore[method-assign]

        async def info(self, message: str) -> None:
            await self.log("info", message)

        context.info = MethodType(info, context)  # type: ignore[method-assign]

        async def warning(self, message: str) -> None:
            await self.log("warning", message)

        context.warning = MethodType(warning, context)  # type: ignore[method-assign]

        async def error(self, message: str) -> None:
            await self.log("error", message)

        context.error = MethodType(error, context)  # type: ignore[method-assign]

        async def elicit(
            self,
            message: str,
            schema: type[ElicitSchemaModelT],
        ) -> ElicitationResult:
            event_alias = (
                f"elicit(message='{message}', schema={type(schema).__name__})"
            )

            assert context is not None

            if context.within_loop():
                event_alias += f" #{context.task.iteration}"

            if event_alias in self._event_aliases:
                raise TypeError(
                    "Looks like you're trying to `elicit()` "
                    "more than once with the same arguments"
                )

            self._event_aliases.add(event_alias)

            workflow_id = context.workflow_id

            assert workflow_id is not None

            memoize = Memoize.ref(uuid5(workflow_id, event_alias).hex)

            # Initial reset, only done once per workflow, we've
            # already accounted for a possible loop iteration in
            # the `event_alias` above.
            await memoize.per_workflow(event_alias).Reset(context)

            status = await memoize.always().Status(context)

            if not status.started:
                await memoize.always().Start(context)
            else:
                message = (
                    f"Sorry, we got disconnected and need to try again: {message}"
                )

            async def send_request_and_wait_for_result():
                # Generate a unique and _random_ ID for this event because
                # we want to send it _everytime_ since the client is not
                # also durable.
                event_id = uuid4().hex

                # THIS CODE IS MORE OR LESS COPIED FROM
                # `mcp.server.elicitation.elicit_with_validation()`
                # because there was not a good way to override that
                # functionality.
                #
                # Validate that schema only contains primitive types and
                # fail loudly if not.
                _validate_elicitation_schema(schema)

                json_schema = schema.model_json_schema()

                return await ctx.session.send_request(
                    mcp.types.ServerRequest(
                        mcp.types.ElicitRequest(
                            method="elicitation/create",
                            params=mcp.types.ElicitRequestParams(
                                message=message,
                                requestedSchema=json_schema,
                                _meta=mcp.types.RequestParams.Meta(
                                    rebootEventId=str(event_id),
                                ),
                            ),
                        )
                    ),
                    mcp.types.ElicitResult,
                    metadata=ServerMessageMetadata(
                        related_request_id=ctx.request_id,
                    ),
                )

            result = await at_least_once(
                "Send request, wait for result",
                context,
                send_request_and_wait_for_result,
                type=mcp.types.ElicitResult,
            )

            if result.action == "accept" and result.content:
                # Validate and parse the content using the schema.
                validated_data = schema.model_validate(result.content)
                return AcceptedElicitation(data=validated_data)
            elif result.action == "decline":
                return DeclinedElicitation()
            elif result.action == "cancel":
                return CancelledElicitation()
            else:
                # This should never happen, but handle it just in case.
                raise ValueError(
                    f"Unexpected elicitation action: {result.action}"
                )

        context.elicit = MethodType(elicit, context)  # type: ignore[method-assign]

        for context_parameter_name in context_parameter_names:
            kwargs[context_parameter_name] = context

        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()

        try:
            if fastmcp.tools.base._is_async_callable(fn):
                return await fn(**dict(bound.arguments))

            return fn(**dict(bound.arguments))
        except PermissionError as e:
            # Log authorization failures at `INFO` level without traceback.
            logger.info(
                f"Authorization denied in tool {fn.__name__}: {e}"
            )
            raise
        except:
            import traceback
            traceback.print_exc()
            raise

    async def wrapper_validating_effects(
        ctx: fastmcp.Context,
        *args,
        **kwargs,
    ):
        context: WorkflowContext | None = _context.get()

        assert context is not None

        # Checkpoint the context since it is the `IdempotencyManager`.
        checkpoint = context.checkpoint()

        result = await wrapper(ctx, context, *args, **kwargs)

        if context._effect_validation == EffectValidation.DISABLED:
            return result

        # Effect validation is enabled.
        logger.info(
            f"Re-running tool '{fn.__name__}' "
            f"to validate effects. See {DOCS_BASE_URL}/develop/side_effects "
            "for more information."
        )

        # Restore the context to the checkpoint we took above so we
        # can re-execute `callable` as though it is being retried from
        # scratch.
        context.restore(checkpoint)

        # TODO: check if `result` is different (we don't do this for
        # other effect validation so we're also not doing it now).

        return await wrapper(ctx, context, *args, **kwargs)

    setattr(wrapper_validating_effects, "__signature__", wrapper_signature)
    wrapper_validating_effects.__name__ = fn.__name__
    wrapper_validating_effects.__doc__ = fn.__doc__

    return wrapper_validating_effects


class StreamableHTTPASGIApp:
    """
    ASGI application for Streamable HTTP server transport.
    """

    def __init__(
        self,
        path: str,
        external_context_from_request: Callable[[Request], ExternalContext],
    ):
        self._path = path
        self._external_context_from_request = external_context_from_request
        self._http_transports: dict[str, StreamableHTTPServerTransport] = {}
        self._connect_tasks: dict[str, asyncio.Task] = {}

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        request = Request(scope, receive)

        if request.headers.get(STATE_REF_HEADER) is None:
            mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

            # If this is a new session, i.e., we don't have an ID,
            # then generate one which we'll use as the session ID.
            mcp_session_id = mcp_session_id or uuid7().hex

            headers = dict(request.headers)
            headers[STATE_REF_HEADER] = f"rbt.mcp.v1.Session:{mcp_session_id}"

            # Need to delete consensus ID header so that we'll
            # properly get routed.
            del headers[SERVER_ID_HEADER]

            response: StreamingResponse | Response

            try:
                async with httpx.AsyncClient() as client:
                    # Too simplify we always perform a streaming
                    # request even if the response is not streaming.
                    async with client.stream(
                        request.method,
                        str(request.url),
                        headers=headers,
                        content=await request.body(),
                        # Don't worry about timing out, this might be
                        # a long-lived `GET` for server sent events
                        # streaming.
                        timeout=None,
                    ) as upstream:
                        # Create a generator to yield chunks from the
                        # upstream response.
                        async def streamer():
                            async for chunk in upstream.aiter_bytes():
                                yield chunk

                        response = StreamingResponse(
                            content=streamer(),
                            status_code=upstream.status_code,
                            headers=upstream.headers,
                        )
                        await response(scope, receive, send)
                        return
            except Exception as e:
                response = Response(
                    f"Proxy request failed: {e}",
                    status_code=500,
                )
                await response(scope, receive, send)
                return

        # This request has properly been forwarded to the consensus
        # responsible for this session.
        context = self._external_context_from_request(request)

        mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        # If this is a new session, i.e., `mcp_session_id is None`, we
        # need to use the session ID we already generated so all
        # requests for it will get routed to this consensus.
        if mcp_session_id is None:
            session_ref = request.headers.get(STATE_REF_HEADER)
            assert session_ref is not None
            session_id = StateRef.from_maybe_readable(session_ref).id
            mcp_session_id = session_id

        session = Session.ref(mcp_session_id)

        _is_vscode: bool | None = None

        async def is_vscode():
            """Returns true if this session client is Visual Studio Code."""
            nonlocal _is_vscode
            if _is_vscode is None:
                backoff = Backoff(max_backoff_seconds=2)
                while _is_vscode is None:
                    try:
                        # TODO: not using `session.reactively().get()`
                        # because it doesn't properly propagate
                        # `Session.GetAborted`.
                        response = await session.get(context)

                        # Need to wait until session has been initialized,
                        # which is once `client_info` is populated.
                        if not response.HasField("client_info"):
                            await backoff()
                            continue

                        # Technically `name` is required but at least the
                        # MCP SDK doesn't validate it via Pydantic, but
                        # Visual Studio Code always seems to include its
                        # name, so if we don't have a name it is not
                        # Visual Studio Code.
                        if response.client_info.HasField("name"):
                            _is_vscode = (
                                response.client_info.name == "Visual Studio Code"
                            )
                        else:
                            _is_vscode = False
                    except Session.GetAborted as aborted:
                        if type(aborted.error) == StateNotConstructed:
                            await backoff()
                            continue
                        raise
            assert _is_vscode is not None
            return _is_vscode

        # If this is a GET and the client is Visual Studio Code always
        # ensure it has a 'last-event-id' so that it always replays
        # from the aggregate stream.
        if request.method == "GET":
            if "last-event-id" not in request.headers:
                if await is_vscode():
                    # Modify headers to always include a
                    # 'last-event-id' so that we'll always
                    # replay from the aggregate stream.
                    mutable_headers = MutableHeaders(scope=scope)
                    mutable_headers[
                        "last-event-id"
                    ] = "VSCODE_INITIAL_GET_LAST_EVENT_ID"
                    scope["headers"] = mutable_headers.raw
                    request = Request(scope, receive)

        drop = False
        async def post_send(message) -> None:
            """
            Helper that drops Visual Studio Code events from POST
            requests since we send all events over GET.

            We do this here so that the events are still sent
            through the MCP SDK so everything gets cleaned up
            correctly.
            """
            nonlocal drop
            if message["type"] == "http.response.start":
                if message["status"] == 200:
                    for key, value in message["headers"]:
                        if (
                            key == b"content-type" and
                            value == b"text/event-stream" and
                            await is_vscode()
                        ):
                            # We want to drop Visual Studio Code
                            # streams because we send everything
                            # through the GET.
                            drop = True
                            break
                # But always send "http.response.start" so Visual
                # Studio Code at least gets the initial 200.
                await send(message)
            elif not drop:
                # Send on messages for things like 202 Accepted.
                await send(message)

        if mcp_session_id in self._http_transports:
            transport = self._http_transports[mcp_session_id]
            await transport.handle_request(
                scope,
                receive,
                send if request.method == "GET" else post_send,
            )
            return

        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=mcp_session_id,
            is_json_response_enabled=False,
            event_store=DurableEventStore(context, mcp_session_id),
            security_settings=None,
        )

        self._http_transports[mcp_session_id] = http_transport

        started = asyncio.Event()

        async def connect():

            async with http_transport.connect() as streams:
                started.set()
                read_stream, write_stream = streams

                writer_tasks: list[asyncio.Task] = []

                async def reader():

                    async for message in read_stream:
                        # TODO: we can't pickle `request_context`
                        # which is a `starlette.requests.Request`,
                        # but it looks like it is only for
                        # _advanced_ use cases, not really
                        # documented
                        # (https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md?plain=1#L948),
                        # and if we really want we could probably
                        # grab what is necessary and send if along
                        # in a picklable way.
                        message.metadata.request_context = None  # type: ignore

                        # Extract `AccessToken` from `contextvar` and serialize
                        # to protobuf `Value` (`contextvars` don't survive
                        # across subprocess boundaries).
                        access_token = get_access_token()
                        if access_token is not None:
                            access_token_value = from_model(
                                access_token,
                                by_alias=True,
                                mode="json",
                                exclude_none=True,
                            )
                        else:
                            access_token_value = None

                        # TODO: ideally we spawn `HandleMessage`
                        # _before_ a 202 Accepted is sent.
                        await session.spawn().HandleMessage(
                            context,
                            path=self._path,
                            message_bytes=pickle.dumps(message),
                            access_token=access_token_value,
                        )

                        if not isinstance(message, Exception) and isinstance(
                            message.message.root,
                            mcp.types.JSONRPCRequest,
                        ):
                            request_id = message.message.root.id

                            async def writer():
                                async for message, _ in replay(
                                    context,
                                    session_id=session.state_id,
                                    request_id=request_id,
                                ):
                                    await write_stream.send(message)

                            writer_task = asyncio.create_task(writer())

                            writer_tasks.append(writer_task)

                            def done(task):
                                writer_tasks.remove(task)

                            writer_task.add_done_callback(done)

                reader_task = asyncio.create_task(reader())

                try:
                    # Await the reader first, since it will be
                    # finished once the session is finished, then
                    # we can cancel any writers.
                    await reader_task
                finally:
                    reader_task.cancel()
                    for writer_task in writer_tasks:
                        writer_task.cancel()
                    await asyncio.wait(
                        [reader_task] + writer_tasks,
                        return_when=asyncio.ALL_COMPLETED,
                    )

        self._connect_tasks[mcp_session_id] = asyncio.create_task(connect())

        def done(task):
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Session {mcp_session_id} crashed: {e}")
            finally:
                if http_transport.is_terminated:
                    assert mcp_session_id in self._connect_tasks
                    del self._connect_tasks[mcp_session_id]
                    assert mcp_session_id in self._http_transports
                    del self._http_transports[mcp_session_id]

        self._connect_tasks[mcp_session_id].add_done_callback(done)

        await started.wait()

        await http_transport.handle_request(
            scope,
            receive,
            send if request.method == "GET" else post_send,
        )
