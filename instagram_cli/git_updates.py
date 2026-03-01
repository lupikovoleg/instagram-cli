from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path


@dataclass
class GitUpdateStatus:
  available: bool
  repo_root: Path | None = None
  branch: str | None = None
  upstream: str | None = None
  behind: int = 0
  ahead: int = 0
  is_dirty: bool = False
  fetch_attempted: bool = False
  fetch_error: str | None = None
  check_error: str | None = None

  @property
  def has_updates(self) -> bool:
    return self.behind > 0

  @property
  def is_diverged(self) -> bool:
    return self.behind > 0 and self.ahead > 0


def _run_git(args: list[str], *, cwd: Path, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
  return subprocess.run(
    ["git", *args],
    cwd=str(cwd),
    capture_output=True,
    text=True,
    timeout=timeout,
    check=False,
  )


def _git_ok(args: list[str], *, cwd: Path, timeout: float = 8.0) -> tuple[bool, str]:
  try:
    result = _run_git(args, cwd=cwd, timeout=timeout)
  except (OSError, subprocess.SubprocessError) as exc:
    return False, str(exc)
  if result.returncode != 0:
    detail = result.stderr.strip() or result.stdout.strip() or f"git exited with {result.returncode}"
    return False, detail
  return True, result.stdout.strip()


def check_for_updates(project_root: Path) -> GitUpdateStatus:
  status = GitUpdateStatus(available=False)

  ok, output = _git_ok(["rev-parse", "--show-toplevel"], cwd=project_root)
  if not ok:
    status.check_error = output
    return status

  repo_root = Path(output).resolve()
  status.available = True
  status.repo_root = repo_root

  ok, output = _git_ok(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
  if not ok:
    status.check_error = output
    return status
  status.branch = output

  ok, output = _git_ok(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=repo_root)
  if not ok:
    status.check_error = output
    return status
  status.upstream = output

  status.fetch_attempted = True
  ok, output = _git_ok(["fetch", "--quiet", "--prune"], cwd=repo_root, timeout=15.0)
  if not ok:
    status.fetch_error = output

  ok, output = _git_ok(["rev-list", "--left-right", "--count", "HEAD...@{u}"], cwd=repo_root)
  if not ok:
    status.check_error = output
    return status

  try:
    ahead_text, behind_text = output.split()
    status.ahead = int(ahead_text)
    status.behind = int(behind_text)
  except (ValueError, TypeError):
    status.check_error = f"Unexpected rev-list output: {output}"
    return status

  ok, output = _git_ok(["status", "--porcelain"], cwd=repo_root)
  if ok:
    status.is_dirty = bool(output.strip())

  return status


def fast_forward_update(project_root: Path) -> tuple[bool, str, GitUpdateStatus]:
  status = check_for_updates(project_root)
  if not status.available or status.repo_root is None:
    return False, status.check_error or "Git repository is unavailable.", status

  if status.is_dirty:
    return False, "Working tree is dirty. Commit or stash changes before updating.", status

  if status.is_diverged:
    return False, "Local branch diverged from upstream. Update manually with git.", status

  if not status.has_updates:
    return True, "Already up to date.", status

  ok, output = _git_ok(["pull", "--ff-only"], cwd=status.repo_root, timeout=30.0)
  if not ok:
    return False, output, status

  refreshed = check_for_updates(project_root)
  message = output or f"Updated from {status.upstream}."
  return True, message, refreshed
