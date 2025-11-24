"""Monkey patches for FastMCP to support DurableMCP features.

This module contains patches to FastMCP that enable context injection for
regular resources (not just templates) and fix bugs in template matching.
These patches should be removed when upgrading to a FastMCP version that
includes these fixes natively.
"""

import inspect
from typing import Any

from mcp.server.fastmcp.resources.resource_manager import ResourceManager
from mcp.server.fastmcp.resources.types import FunctionResource
from mcp.server.fastmcp.utilities.context_injection import inject_context
from mcp.server.fastmcp.utilities.context_injection import find_context_parameter
from mcp.server.fastmcp.utilities.logging import get_logger
from pydantic import AnyUrl

logger = get_logger(__name__)


class DurableFunctionResource(FunctionResource):
    """A `FunctionResource` that supports context injection.

    FastMCP's regular `FunctionResource` is typed as `Callable[[], Any]` and
    cannot receive context. Only `ResourceTemplate` supports context injection
    via the `context_kwarg` field. This custom resource class stores the
    original function and context parameter name so that
    `ResourceManager.get_resource()` can execute it with context injection,
    similar to how templates work but for fixed URIs.

    The `context_kwarg` field is automatically detected from the `fn` parameter
    using FastMCP's `find_context_parameter()` utility.
    """

    context_kwarg: str | None = None

    def __init__(self, **data):
        super().__init__(**data)
        # Auto-detect context parameter from function.
        if self.context_kwarg is None and self.fn is not None:
            self.context_kwarg = find_context_parameter(self.fn)


def patch_get_resource() -> None:
    """Patch `ResourceManager.get_resource()` for context injection and bug fixes.

    This function should be called once at module initialization time before
    any FastMCP instances are created.
    """
    _patch_resource_manager_get_resource()


def _patch_resource_manager_get_resource() -> None:
    """Patch `ResourceManager.get_resource()` for context injection and bug fixes.

    This patch serves two purposes:
    1. Enable context injection for regular resources via `DurableFunctionResource`
    2. Fix FastMCP bug where `if params := template.matches(uri)` evaluates to
       `False` when `params` is an empty dict for fixed URIs with no URI
       parameters, since empty dicts are falsy in Python.
    """
    original_get_resource = ResourceManager.get_resource

    async def patched_get_resource(
        self,
        uri: AnyUrl | str,
        context: Any | None = None,
    ) -> Any:
        """Patched version supporting `DurableFunctionResource` and fixing empty dict bug."""
        uri_str = str(uri)
        logger.debug("Getting resource", extra={"uri": uri_str})

        # Check concrete resources.
        if resource := self._resources.get(uri_str):
            # Handle our custom `DurableFunctionResource` with context injection.
            if isinstance(
                resource, DurableFunctionResource
            ) and resource.context_kwarg:
                # Execute function with context injected, similar to templates.
                params = inject_context(
                    resource.fn, {}, context, resource.context_kwarg
                )
                result = resource.fn(**params)
                if inspect.iscoroutine(result):
                    result = await result

                # Return a new resource with the result captured.
                return FunctionResource(
                    uri=resource.uri,
                    name=resource.name,
                    title=resource.title,
                    description=resource.description,
                    mime_type=resource.mime_type,
                    icons=resource.icons,
                    annotations=resource.annotations,
                    fn=lambda: result,
                )
            return resource

        # Check templates. Fixed to check `is not None` instead of truthiness
        # to handle empty dict `{}` for fixed URIs with only context parameters.
        for template in self._templates.values():
            params = template.matches(uri_str)
            if params is not None:
                try:
                    return await template.create_resource(
                        uri_str, params, context=context
                    )
                except Exception as e:
                    raise ValueError(
                        f"Error creating resource from template: {e}"
                    )

        raise ValueError(f"Unknown resource: {uri}")

    ResourceManager.get_resource = patched_get_resource
