from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    """Resolve repository root with git first, then a stable monorepo fallback."""
    scripts_dir = Path(__file__).resolve().parent
    fallback_root = scripts_dir.parents[1]

    try:
        root = subprocess.check_output(
            ["git", "-C", str(fallback_root), "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    except Exception:
        return fallback_root

    return Path(root)


def _resolve_repo_from_remote() -> str | None:
    root = _repo_root()
    try:
        remote = subprocess.check_output(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            text=True,
        ).strip()
    except Exception:
        return None

    if remote.endswith(".git"):
        remote = remote[:-4]

    if remote.startswith("git@github.com:"):
        return remote.split("git@github.com:", 1)[1]

    if "github.com/" in remote:
        return remote.split("github.com/", 1)[1]

    return None


def resolve_github_repository(default: str | None = None) -> str:
    """Resolve owner/repo consistently across local and CI runs."""
    env_repo = os.getenv("GITHUB_REPOSITORY")
    if env_repo:
        return env_repo

    remote_repo = _resolve_repo_from_remote()
    if remote_repo:
        return remote_repo

    if default:
        return default

    raise RuntimeError(
        "Unable to resolve GitHub repository. Set GITHUB_REPOSITORY or configure remote.origin.url."
    )

