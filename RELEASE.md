## Make a release, publish to PyPI

0. Generate Reboot code

```console
rbt generate
```

1. Tag the release (use semantic versioning):

```console
git tag 0.x.y
```

2. Update the version in `pyproject.toml` to match the tag:

```console
TAG=$(git describe --tags --abbrev=0 | sed 's/^v//')
sed -i "" "s/^version = \".*\"/version = \"$TAG\"/" pyproject.toml
git add pyproject.toml && git commit -m "Set version to $TAG"
```

2. Clean old build artifacts:

```console
rm -rf dist build *.egg-info
```

3. (Ensure deps) Install build + upload tools (if not already in the env):

```console
uv pip install --upgrade build twine
```

4. Build inspect frontend

```console
cd reboot/inspect && npm install && npm run build
```

5. Build sdist and wheel:

```console
python -m build
```

6. Validate artifacts:

```console
twine check dist/*
```

7. Upload to PyPI:

```console
twine upload dist/*
```

8. Push all local tags:

```console
git push --tags origin
```

9. Update GitHub releases

Go to https://github.com/reboot-dev/durable-mcp-python/releases/new
and create a new release for the version just published. See other
examples for what you can put in the release notes.
