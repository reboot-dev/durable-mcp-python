# Multi-Step Operations

Multi-step operations with independent idempotency guards using
`at_least_once`.

## Overview

When a tool performs multiple sequential operations, each step should
be independently idempotent. If the tool is retried after step 1
succeeds but before step 2 completes, step 1 returns its cached result
and only step 2 retries.

## Pattern

```python
@mcp.tool()
async def create_user_with_profile(
    username: str,
    email: str,
    bio: str = "",
    context: DurableContext = None,
) -> dict:
    """Create user and profile in separate steps."""

    # Step 1: Create user (cached on success).
    async def create_user():
        user_id = f"user_{hash(username) % 100000}"
        await users_map.insert(
            context,
            entries={user_id: json.dumps({...}).encode("utf-8")},
        )
        return user_id

    user_id = await at_least_once(
        f"create_user_{username}",
        context,
        create_user,
        type=str,
    )

    # Step 2: Create profile (cached independently).
    async def create_profile():
        profile_id = f"profile_{user_id}"
        await profiles_map.insert(
            context,
            entries={profile_id: json.dumps({...}).encode("utf-8")},
        )
        return profile_id

    profile_id = await at_least_once(
        f"create_profile_{user_id}",
        context,
        create_profile,
        type=str,
    )

    return {"user_id": user_id, "profile_id": profile_id}
```

## How It Works

Each step has its own `at_least_once` guard with a unique alias.

### Retry After Step 1 Success

1. Initial call: Step 1 creates user, succeeds
2. Crash before step 2
3. Retry: Step 1 returns cached `user_id`, step 2 executes

Result: User created once, profile created on retry.

### Retry After Both Steps

1. Initial call: Step 1 succeeds, step 2 succeeds
2. Network error prevents response delivery
3. Retry: Both steps return cached results

Result: Both operations return immediately without re-execution.

### Retry After Step 1 Failure

1. Initial call: Step 1 raises exception
2. Retry: Step 1 executes again

Result: Step 1 retries until success, then step 2 executes.

## Key Concepts

### Independent Guards

Each step has its own guard with distinct alias:

```python
# Step 1 alias.
await at_least_once(f"create_user_{username}", ...)

# Step 2 alias.
await at_least_once(f"create_profile_{user_id}", ...)
```

This ensures each step caches independently.

### Sequential Dependencies

Later steps can depend on earlier step results:

```python
# Step 1: Get data.
user_id = await at_least_once("create_user", context, ...)

# Step 2: Use result from step 1.
profile_id = await at_least_once(
    f"create_profile_{user_id}",  # Uses `user_id`.
    context,
    ...,
)
```

### Function References

Pass function references directly (no lambda):

```python
# Correct.
async def create_user():
    return await create_user_record(...)

user_id = await at_least_once(
    "create_user",
    context,
    create_user,  # Function reference.
    type=str,
)

# Wrong (don't use lambda unless needed for arguments).
user_id = await at_least_once(
    "create_user",
    context,
    lambda: create_user(),
    type=str,
)
```

## Best Practices

Use distinct aliases:

```python
# Good: Different aliases.
await at_least_once(f"create_user_{username}", ...)
await at_least_once(f"create_profile_{user_id}", ...)

# Bad: Same alias.
await at_least_once("create", ...)
await at_least_once("create", ...)
```

Make each step atomic:

```python
# Good: Each step is complete operation.
user_id = await at_least_once("create_user", ...)
profile_id = await at_least_once("create_profile", ...)

# Bad: Steps too granular.
await at_least_once("validate_username", ...)
await at_least_once("hash_password", ...)
await at_least_once("insert_database", ...)
```

Let exceptions propagate:

```python
# Good: `at_least_once` handles retries.
user_id = await at_least_once("create_user", context, create_user, ...)

# Bad: Catching exceptions defeats retry.
try:
    user_id = await at_least_once("create_user", ...)
except Exception:
    return {"error": "failed"}  # Operation won't retry.
```

## Running

```bash
cd examples/steps
uv run python example.py
```
