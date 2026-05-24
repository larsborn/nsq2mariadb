# Notes for Claude

Project-specific context for working in this repo. Read alongside `README.md`.

## Test framework: stdlib `unittest` only

- Do not introduce `pytest`.
- All tests live in `tests/` and subclass `unittest.TestCase`.
- File convention (matches `tests/test_nsq2mariadb.py`):

  ```python
  #!/usr/bin/env python3
  # -*- coding: utf-8 -*-
  import unittest
  ...
  if __name__ == "__main__":
      unittest.main()
  ```

- Run via `make test` or `python -m unittest discover -s tests -v`.

## Packaging notes

- `tests/` is excluded from the built wheel via
  `find_packages(exclude=["tests", "tests.*"])` in `setup.py`. Without that
  exclusion, `setuptools.find_packages()` picks up `tests/` and ships it as a
  top-level package, which then **shadows the consumer project's own `tests/`
  package** once `nsq2mariadb` is installed. (We hit this in v0.1.0 — fixed
  in v0.1.1.) When adding new top-level directories that contain
  `__init__.py`, check whether they should be in the exclude list.
- `pyproject.toml` is intentionally minimal — only declares the build-system.
  Metadata still lives in `setup.py`.

## Releasing

This project is published to PyPI via GitHub Actions on every `v*` tag using
PyPI's Trusted Publishers (OIDC — no stored API token).

### Cutting a release

The Makefile owns the release flow. From a clean `main`:

```bash
make release-patch   # X.Y.Z -> X.Y.Z+1
make release-minor   # X.Y.Z -> X.Y+1.0
make release-major   # X.Y.Z -> X+1.0.0
```

Each target invokes `tools/release.py`, which:

1. Verifies the branch is `main`, the working tree is clean, and the local
   commit matches `origin/main`. (Aborts loudly if any check fails.)
2. Verifies the target tag doesn't already exist.
3. Bumps `version="..."` in `setup.py`.
4. Commits the bump with message `chore: bump <new-version>`.
5. Creates an annotated tag `v<new-version>` and pushes both the commit and
   the tag to `origin/main`.

The push triggers `.github/workflows/publish.yml`, which builds an sdist +
wheel and uploads them to PyPI via the configured Trusted Publisher.

### Dry-run

To preview a release without touching files or git state:

```bash
make dry-release-patch   # or dry-release-minor / dry-release-major
```

Prints the commands that would run and the version that would be cut.

### What needs to be true on PyPI

- The project must have a Trusted Publisher configured pointing at
  `larsborn / nsq2mariadb / publish.yml` with environment `pypi`. Configure at
  https://pypi.org/manage/project/nsq2mariadb/settings/publishing/.
- The GitHub repo must have an environment named `pypi` at
  https://github.com/larsborn/nsq2mariadb/settings/environments. No protection
  rules are required.

### Manual fallback

If GHA is down or Trusted Publisher is misconfigured, you can publish manually
from a clean checkout of the tagged commit (requires a PyPI API token):

```bash
.venv/Scripts/python -m build
.venv/Scripts/twine upload --username __token__ dist/*
```

This skips Trusted Publishers entirely and uses an API token instead. Prefer
the automated path — only fall back to this in emergencies.

## Local environment

- Use a project-local `.venv` (see `make` `PYTHON` variable default).
- On Windows the venv's Python is at `.venv/Scripts/python`. On Linux/macOS
  override the Makefile: `make test PYTHON=.venv/bin/python`.
- The `.venv` directory is `.gitignore`'d.

## Git workflow

- `main` is the only long-lived branch. Releases tag commits on `main`.
- Use `git -C <path> <command>` instead of `cd <path> && git ...` on Windows
  bash to avoid interactive approval prompts.
- Never `--no-verify`; if a hook fails, fix the underlying issue.

## When changing the release script

`tools/release.py`'s `bump_version()` and `format_version()` are pure
functions covered by `tests/test_release.py`. If you change the bump logic
(e.g. supporting pre-release suffixes), update those tests first.
