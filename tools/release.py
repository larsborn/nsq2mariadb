#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bump version in setup.py, commit, tag, and push.

Usage: python tools/release.py {patch|minor|major} [--dry-run]

The actual PyPI publish is triggered by the `v*` tag via
`.github/workflows/publish.yml`. This script only handles the local
bump + tag + push.

Safety checks before bumping:
- Must be on `main`
- Working tree must be clean
- Local `main` must be in sync with `origin/main`
- Target tag must not already exist
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_PY = REPO_ROOT / "setup.py"
VERSION_PATTERN = re.compile(r'version="(\d+)\.(\d+)\.(\d+)"')


def read_current_version() -> Tuple[Tuple[int, int, int], str]:
    text = SETUP_PY.read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(text)
    if not match:
        sys.exit(f"ERROR: could not find version=\"X.Y.Z\" in {SETUP_PY}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))), text


def bump_version(current: Tuple[int, int, int], kind: str) -> Tuple[int, int, int]:
    major, minor, patch = current
    if kind == "major":
        return (major + 1, 0, 0)
    if kind == "minor":
        return (major, minor + 1, 0)
    if kind == "patch":
        return (major, minor, patch + 1)
    raise ValueError(f"unknown bump kind: {kind!r}")


def format_version(version: Tuple[int, int, int]) -> str:
    return ".".join(str(n) for n in version)


def run(cmd, dry_run: bool = False) -> None:
    print(f"+ {' '.join(cmd)}")
    if dry_run:
        return
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def capture(cmd) -> str:
    return subprocess.check_output(cmd, text=True, cwd=REPO_ROOT).strip()


def preflight_checks() -> None:
    branch = capture(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if branch != "main":
        sys.exit(f"ERROR: must be on `main` branch (currently on {branch!r})")

    dirty = capture(["git", "status", "--porcelain"])
    if dirty:
        sys.exit(
            "ERROR: working tree has uncommitted changes — commit or stash first:\n" + dirty
        )

    # Ensure local main matches origin/main so we don't push into divergence.
    subprocess.run(["git", "fetch", "origin", "main", "--quiet"], check=True, cwd=REPO_ROOT)
    local_sha = capture(["git", "rev-parse", "HEAD"])
    remote_sha = capture(["git", "rev-parse", "origin/main"])
    if local_sha != remote_sha:
        sys.exit(
            "ERROR: local `main` is not in sync with `origin/main`. "
            "Pull / push so they match, then retry."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=["patch", "minor", "major"])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the steps that would run, but don't modify files or git state",
    )
    args = parser.parse_args()

    preflight_checks()

    current, text = read_current_version()
    new = bump_version(current, args.kind)
    current_str = format_version(current)
    new_str = format_version(new)
    tag = f"v{new_str}"

    if tag in capture(["git", "tag"]).split():
        sys.exit(f"ERROR: tag {tag} already exists")

    print(f"Bumping {current_str} -> {new_str} ({args.kind})")

    if not args.dry_run:
        new_text = text.replace(f'version="{current_str}"', f'version="{new_str}"', 1)
        SETUP_PY.write_text(new_text, encoding="utf-8")

    run(["git", "add", "setup.py"], dry_run=args.dry_run)
    run(["git", "commit", "-m", f"chore: bump {new_str}"], dry_run=args.dry_run)
    run(["git", "tag", "-a", tag, "-m", tag], dry_run=args.dry_run)
    run(["git", "push", "origin", "main", tag], dry_run=args.dry_run)

    print()
    if args.dry_run:
        print(f"DRY RUN — nothing changed. Would have released {tag}.")
    else:
        print(f"Released {tag}. Watch the workflow:")
        print("  https://github.com/larsborn/nsq2mariadb/actions")


if __name__ == "__main__":
    main()
