## Publishing to PyPI

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
sed -i "s/^version = \".*\"/version = \"$TAG\"/" pyproject.toml
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

4. Build sdist and wheel:

```console
python -m build
```

5. Validate artifacts:

```console
twine check dist/*
```

6. Upload to PyPI:

```console
twine upload dist/*
```

7. Push tag:

```console
git push --follow-tags origin main
```
