"""
Multi-Step Operations with Partial Failure Recovery.

Demonstrates using at_least_once for operations with multiple steps where
each step should be idempotent and cached independently.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel

# Add api/ to Python path for generated proto code.
api_path = Path(__file__).parent.parent.parent / "api"
if api_path.exists():
    sys.path.insert(0, str(api_path))

from reboot.aio.workflows import at_least_once
from reboot.mcp.server import DurableMCP, DurableContext
from reboot.std.collections.v1.sorted_map import SortedMap

# Initialize MCP server.
mcp = DurableMCP(path="/mcp")


# Pydantic models for user and profile data.
class UserData(BaseModel):
    """User data model."""

    username: str
    email: str


class ProfileData(BaseModel):
    """Profile data model."""

    user_id: str
    bio: str = ""
    avatar_url: str = ""


@mcp.tool()
async def create_user_with_profile(
    username: str,
    email: str,
    bio: str = "",
    avatar_url: str = "",
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Create a user and their profile in separate steps.

    This demonstrates multi-step operations where each step is independently
    idempotent. If the tool is retried after the user is created but before
    the profile is created, the user creation will return the cached result
    and only the profile creation will retry.

    Args:
        username: Unique username for the user.
        email: User's email address.
        bio: Optional user bio.
        avatar_url: Optional avatar URL.
        context: The durable context.

    Returns:
        Dictionary with user_id and profile_id.
    """

    # Step 1: Create user (idempotent).
    async def create_user():
        users_map = SortedMap.ref("users")
        user_id = f"user_{hash(username) % 100000}"

        # Create Pydantic model and store user data.
        user_data = UserData(username=username, email=email)
        await users_map.insert(
            context,
            entries={user_id: user_data.model_dump_json().encode("utf-8")},
        )

        return user_id

    # If this tool is retried after user creation succeeds, this will
    # return the cached user_id without re-creating the user.
    user_id = await at_least_once(
        f"create_user_{username}",
        context,
        create_user,
        type=str,
    )

    # Step 2: Create profile (idempotent, separate guard).
    async def create_profile():
        profiles_map = SortedMap.ref("profiles")
        profile_id = f"profile_{user_id}"

        # Create Pydantic model and store profile data.
        profile_data = ProfileData(
            user_id=user_id,
            bio=bio,
            avatar_url=avatar_url,
        )
        await profiles_map.insert(
            context,
            entries={profile_id: profile_data.model_dump_json().encode("utf-8")},
        )

        return profile_id

    # If this tool is retried after step 1 but before step 2 completes,
    # only this step will execute (step 1 returns cached result).
    profile_id = await at_least_once(
        f"create_profile_{user_id}",
        context,
        create_profile,
        type=str,
    )

    return {
        "status": "success",
        "user_id": user_id,
        "profile_id": profile_id,
    }


@mcp.tool()
async def get_user(
    user_id: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Retrieve user data.

    Args:
        user_id: The user ID to retrieve.
        context: The durable context.

    Returns:
        User data or error if not found.
    """
    users_map = SortedMap.ref("users")
    response = await users_map.get(context, key=user_id)

    if not response.HasField("value"):
        return {"status": "error", "message": "User not found"}

    user_data = UserData.model_validate_json(response.value)

    return {"status": "success", "user": user_data.model_dump()}


@mcp.tool()
async def get_profile(
    profile_id: str,
    context: DurableContext = None,
) -> Dict[str, Any]:
    """
    Retrieve profile data.

    Args:
        profile_id: The profile ID to retrieve.
        context: The durable context.

    Returns:
        Profile data or error if not found.
    """
    profiles_map = SortedMap.ref("profiles")
    response = await profiles_map.get(context, key=profile_id)

    if not response.HasField("value"):
        return {"status": "error", "message": "Profile not found"}

    profile_data = ProfileData.model_validate_json(response.value)

    return {"status": "success", "profile": profile_data.model_dump()}


async def main():
    """Start the multi-step example server."""
    await mcp.application().run()


if __name__ == "__main__":
    asyncio.run(main())
