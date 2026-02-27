from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
  from rich.console import Console
  from rich.live import Live
  from rich.markdown import Markdown
except ImportError:  # pragma: no cover
  Console = None  # type: ignore[assignment]
  Live = None  # type: ignore[assignment]
  Markdown = None  # type: ignore[assignment]

from instagram_cli.config import Settings
from instagram_cli.hiker_api import (
  HikerApiClient,
  HikerApiError,
  extract_profile_username,
  extract_reel_shortcode,
)
from instagram_cli.openrouter_agent import OpenRouterAgent, OpenRouterAgentError


_RICH_CONSOLE = Console() if Console is not None else None


_AGENT_TOOL_SPECS: list[dict[str, Any]] = [
  {
    "type": "function",
    "function": {
      "name": "get_profile_stats",
      "description": "Get Instagram profile stats by username or profile URL.",
      "parameters": {
        "type": "object",
        "properties": {
          "target": {
            "type": "string",
            "description": "Instagram username (with or without @) or full profile URL",
          },
        },
        "required": ["target"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "get_reel_stats",
      "description": "Get Instagram Reel stats by reel URL.",
      "parameters": {
        "type": "object",
        "properties": {
          "reel_url": {
            "type": "string",
            "description": "Full Instagram Reel URL",
          },
        },
        "required": ["reel_url"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "get_recent_reels",
      "description": "Get latest reels for a profile.",
      "parameters": {
        "type": "object",
        "properties": {
          "target": {
            "type": "string",
            "description": "Instagram username or profile URL",
          },
          "limit": {
            "type": "integer",
            "description": "Number of latest reels to fetch (1..20)",
            "minimum": 1,
            "maximum": 20,
          },
        },
        "required": ["target"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "get_last_reel_metric",
      "description": (
        "Get one metric from the latest reel. If target is omitted, use profile from session context."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "metric": {
            "type": "string",
            "enum": [
              "likes",
              "views",
              "comments",
              "saves",
              "engagement_rate",
              "viral_index",
              "published_at_local",
              "published_at_utc",
            ],
            "description": "Metric to read from latest reel",
          },
          "target": {
            "type": "string",
            "description": "Optional username or profile URL",
          },
        },
        "required": ["metric"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "get_session_context",
      "description": "Return current CLI session context with profile/reel memory.",
      "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
      },
    },
  },
]


@dataclass
class SessionState:
  current_model: str
  render_mode: str = "plain"
  last_metrics: dict[str, Any] | None = None
  current_profile: dict[str, Any] | None = None
  current_reel: dict[str, Any] | None = None
  recent_reels: list[dict[str, Any]] | None = None
  chat_history: list[dict[str, str]] = field(default_factory=list)


_ASCII_ART = r"""
 ___ _   _ ____ _____  _    ____ ____      _    __  __      ____ _     ___
|_ _| \ | / ___|_   _|/ \  / ___|  _ \    / \  |  \/  |    / ___| |   |_ _|
 | ||  \| \___ \ | | / _ \| |  _| |_) |  / _ \ | |\/| |   | |   | |    | |
 | || |\  |___) || |/ ___ \ |_| |  _ <  / ___ \| |  | |   | |___| |___ | |
|___|_| \_|____/ |_/_/   \_\____|_| \_\/_/   \_\_|  |_|    \____|_____|___|
                           INSTAGRAM-CLI by @lupikovoleg
"""


def _default_render_mode() -> str:
  if _RICH_CONSOLE is None or Markdown is None:
    return "plain"
  return "rich" if _RICH_CONSOLE.is_terminal else "plain"


def _render_mode_label(mode: str) -> str:
  if mode == "rich":
    return "rich (markdown render)"
  return "plain"


def _print_banner(settings: Settings, state: SessionState) -> None:
  print(_ASCII_ART.rstrip())
  print("Type 'help' for commands. Type 'exit' to quit.\n")
  print(f"- OpenRouter model: {settings.openrouter_chat_model}")
  print(f"- HikerAPI configured: {'yes' if settings.hiker_access_key else 'no'}")
  print(f"- Output mode: {_render_mode_label(state.render_mode)}")
  if settings.loaded_env_files:
    loaded = ", ".join(str(path) for path in settings.loaded_env_files)
    print(f"- Loaded .env: {loaded}")
  print("")


def _format_pct(value: float) -> str:
  return f"{value * 100:.2f}%"


def _print_reel_stats(data: dict[str, Any]) -> None:
  print("\n[Reel stats]")
  print(f"url: {data.get('url')}")
  if data.get("username"):
    print(f"author: @{data.get('username')}")
  print(f"shortcode: {data.get('shortcode')}")
  print(f"published (local): {data.get('published_at_local') or 'unknown'}")
  print(f"published (utc): {data.get('published_at_utc') or 'unknown'}")
  print(f"views: {data.get('views', 0)}")
  print(f"likes: {data.get('likes', 0)}")
  print(f"comments: {data.get('comments', 0)}")
  print(f"saves: {data.get('saves', 0)}")
  print(f"engagement rate: {_format_pct(float(data.get('engagement_rate', 0.0)))}")
  print(f"viral index: {data.get('viral_index', 0)} ({data.get('viral_status', 'unknown')})")
  caption = data.get("caption")
  if caption:
    print(f"caption: {caption[:200]}")
  print("")


def _print_profile_stats(data: dict[str, Any]) -> None:
  print("\n[Profile stats]")
  print(f"username: @{data.get('username')}")
  if data.get("full_name"):
    print(f"name: {data.get('full_name')}")
  print(f"followers: {data.get('followers', 0)}")
  print(f"following: {data.get('following', 0)}")
  print(f"posts: {data.get('posts', 0)}")
  print(f"verified: {data.get('is_verified')}")
  print(f"private: {data.get('is_private')}")
  has_stories = data.get("has_stories")
  stories_count = data.get("stories_count")
  if has_stories is None:
    print("stories: unknown")
  else:
    print(f"stories: {'yes' if has_stories else 'no'} ({stories_count})")
  if data.get("stories_error"):
    print(f"stories note: {data['stories_error']}")
  bio = data.get("biography")
  if bio:
    print(f"bio: {bio[:200]}")
  print("")


def _print_help() -> None:
  print(
    "\nCommands:\n"
    "- help: show this help\n"
    "- actions: show available actions\n"
    "- reel <instagram_reel_url>: fetch reel stats\n"
    "- profile <instagram_profile_url_or_username>: fetch profile stats\n"
    "- stats <url_or_username>: auto detect reel/profile and fetch stats\n"
    "- ask <question>: ask AI agent with tool calling\n"
    "- model: show active AI model\n"
    "- model <openrouter_model_id>: switch model for this session\n"
    "- render: show current output mode\n"
    "- render <rich|plain>: switch output mode\n"
    "- last: print raw JSON for last fetched stats\n"
    "- reload: reload env from files\n"
    "- exit | quit: close CLI\n"
    "\nNatural language works via tool calling (examples):\n"
    "- how many followers does lupikovoleg have?\n"
    "- does @username have stories?\n"
    "- paste a profile or reel link\n"
    "- how many likes does the latest reel have?\n",
  )


def _print_actions() -> None:
  print(
    "\nAvailable actions now:\n"
    "1. Get Reel metrics by URL: views, likes, comments, saves, engagement, publish time.\n"
    "2. Get Profile metrics by URL/@username: followers, following, posts, verified/private, stories.\n"
    "3. Ask natural language questions; agent decides tool calls automatically.\n"
    "4. Follow-ups use session context (current profile/reel).\n"
    "5. Switch OpenRouter model and output render mode (rich/plain).\n"
    "6. View raw payload for debugging.\n",
  )


def _command_arg(text: str) -> str:
  parts = text.split(maxsplit=1)
  return parts[1].strip() if len(parts) > 1 else ""


def _auto_handle_target(target: str, hiker: HikerApiClient) -> dict[str, Any]:
  if extract_reel_shortcode(target):
    return hiker.reel_stats(target)

  username = extract_profile_username(target)
  if username:
    return hiker.profile_stats(username)

  raise HikerApiError("Cannot detect target type. Use 'reel ...' or 'profile ...'.")


def _is_direct_target_input(raw: str) -> bool:
  stripped = raw.strip()
  if not stripped or " " in stripped:
    return False
  if "instagram.com/" in stripped.lower():
    return True
  return bool(extract_profile_username(stripped))


def _without_raw(payload: dict[str, Any] | None) -> dict[str, Any] | None:
  if not isinstance(payload, dict):
    return None
  return {key: value for key, value in payload.items() if key != "raw"}


def _update_context_with_stats(state: SessionState, stats: dict[str, Any]) -> None:
  state.last_metrics = stats
  entity_type = str(stats.get("entity_type") or "")

  if entity_type == "profile":
    previous_username = (state.current_profile or {}).get("username")
    next_username = stats.get("username")
    state.current_profile = stats
    if previous_username != next_username:
      state.recent_reels = None
    return

  if entity_type in {"reel", "reel_preview"}:
    state.current_reel = stats


def _build_agent_context(state: SessionState) -> dict[str, Any]:
  context: dict[str, Any] = {}

  if state.last_metrics is not None:
    context["last_metrics"] = _without_raw(state.last_metrics)
  if state.current_profile is not None:
    context["current_profile"] = _without_raw(state.current_profile)
  if state.current_reel is not None:
    context["current_reel"] = _without_raw(state.current_reel)
  if state.recent_reels:
    context["recent_reels"] = [_without_raw(item) for item in state.recent_reels[:5]]

  return context


def _load_latest_reel_for_username(
  *,
  username: str,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any] | None:
  current_username = (state.current_profile or {}).get("username")
  if current_username == username and state.recent_reels:
    latest = state.recent_reels[0]
    state.current_reel = latest
    state.last_metrics = latest
    return latest

  payload = hiker.recent_reels(username, limit=12)
  profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else None
  reels = payload.get("reels") if isinstance(payload.get("reels"), list) else []

  if profile:
    previous_username = (state.current_profile or {}).get("username")
    next_username = profile.get("username")
    state.current_profile = profile
    if previous_username != next_username:
      state.recent_reels = None

  state.recent_reels = [item for item in reels if isinstance(item, dict)]
  if not state.recent_reels:
    return None

  latest = state.recent_reels[0]
  state.current_reel = latest
  state.last_metrics = latest
  return latest


def _tool_get_profile_stats(
  *,
  target: str,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  profile = hiker.profile_stats(target)
  _update_context_with_stats(state, profile)
  return {
    "ok": True,
    "profile": _without_raw(profile),
  }


def _tool_get_reel_stats(
  *,
  reel_url: str,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  reel = hiker.reel_stats(reel_url)
  _update_context_with_stats(state, reel)
  return {
    "ok": True,
    "reel": _without_raw(reel),
  }


def _tool_get_recent_reels(
  *,
  target: str,
  limit: int,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  payload = hiker.recent_reels(target, limit=limit)
  profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else None
  reels = payload.get("reels") if isinstance(payload.get("reels"), list) else []
  normalized_reels = [item for item in reels if isinstance(item, dict)]

  if profile:
    _update_context_with_stats(state, profile)
  state.recent_reels = normalized_reels

  if normalized_reels:
    state.current_reel = normalized_reels[0]
    state.last_metrics = normalized_reels[0]

  return {
    "ok": True,
    "username": payload.get("username"),
    "count": len(normalized_reels),
    "profile": _without_raw(profile) if profile else None,
    "reels": [_without_raw(item) for item in normalized_reels],
  }


def _tool_get_last_reel_metric(
  *,
  metric: str,
  target: str | None,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  chosen_target = (target or "").strip()
  if not chosen_target:
    chosen_target = (
      str((state.current_profile or {}).get("username") or "")
      or str((state.current_reel or {}).get("username") or "")
    )

  if not chosen_target:
    return {
      "ok": False,
      "error": "target_not_found_in_session",
      "message": "Provide username/profile URL or load a profile first.",
    }

  latest = _load_latest_reel_for_username(username=chosen_target, state=state, hiker=hiker)
  if latest is None:
    return {
      "ok": False,
      "error": "latest_reel_not_found",
      "target": chosen_target,
    }

  value = latest.get(metric)
  return {
    "ok": True,
    "target": chosen_target,
    "metric": metric,
    "value": value,
    "reel": _without_raw(latest),
  }


def _execute_agent_tool(
  tool_name: str,
  args: dict[str, Any],
  *,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  try:
    if tool_name == "get_session_context":
      return {
        "ok": True,
        "context": _build_agent_context(state),
      }

    if tool_name == "get_profile_stats":
      target = str(args.get("target") or "").strip()
      if not target:
        return {"ok": False, "error": "missing_target"}
      return _tool_get_profile_stats(target=target, state=state, hiker=hiker)

    if tool_name == "get_reel_stats":
      reel_url = str(args.get("reel_url") or "").strip()
      if not reel_url:
        return {"ok": False, "error": "missing_reel_url"}
      return _tool_get_reel_stats(reel_url=reel_url, state=state, hiker=hiker)

    if tool_name == "get_recent_reels":
      target = str(args.get("target") or "").strip()
      if not target:
        return {"ok": False, "error": "missing_target"}
      raw_limit = args.get("limit", 12)
      try:
        limit = int(raw_limit)
      except (TypeError, ValueError):
        limit = 12
      limit = max(1, min(limit, 20))
      return _tool_get_recent_reels(target=target, limit=limit, state=state, hiker=hiker)

    if tool_name == "get_last_reel_metric":
      metric = str(args.get("metric") or "").strip()
      if not metric:
        return {"ok": False, "error": "missing_metric"}
      target = args.get("target")
      target_text = str(target).strip() if isinstance(target, str) else None
      return _tool_get_last_reel_metric(metric=metric, target=target_text, state=state, hiker=hiker)

    return {
      "ok": False,
      "error": f"unknown_tool:{tool_name}",
    }
  except HikerApiError as exc:
    return {
      "ok": False,
      "error": str(exc),
    }
  except Exception as exc:  # pragma: no cover
    return {
      "ok": False,
      "error": f"unexpected_tool_error:{exc}",
    }


def _append_history(state: SessionState, role: str, content: str) -> None:
  text = content.strip()
  if not text:
    return
  if role not in {"user", "assistant"}:
    return
  state.chat_history.append({"role": role, "content": text})
  if len(state.chat_history) > 20:
    state.chat_history = state.chat_history[-20:]


def _should_use_rich(state: SessionState) -> bool:
  return (
    state.render_mode == "rich"
    and _RICH_CONSOLE is not None
    and _RICH_CONSOLE.is_terminal
    and Markdown is not None
  )


def _start_plain_typing_indicator(prefix: str = "assistant> ") -> tuple[threading.Event, threading.Event, threading.Thread]:
  first_chunk = threading.Event()
  stop = threading.Event()

  def run() -> None:
    frames = [".", "..", "..."]
    idx = 0
    while not stop.is_set() and not first_chunk.is_set():
      frame = frames[idx % len(frames)]
      print(f"\r{prefix}{frame}   ", end="", flush=True)
      idx += 1
      time.sleep(0.35)

  thread = threading.Thread(target=run, daemon=True)
  thread.start()
  return first_chunk, stop, thread


def _render_assistant_markdown_stream(
  *,
  user_text: str,
  state: SessionState,
  agent: OpenRouterAgent,
  hiker: HikerApiClient,
) -> str:
  if Live is None or Markdown is None or _RICH_CONSOLE is None:
    return ""

  _RICH_CONSOLE.print("assistant>")
  rendered: list[str] = []
  last_rendered_len = 0
  first_chunk = threading.Event()
  stop_indicator = threading.Event()

  with Live(Markdown(""), console=_RICH_CONSOLE, refresh_per_second=20, transient=True) as live:
    def indicator() -> None:
      frames = [".", "..", "..."]
      idx = 0
      while not stop_indicator.is_set() and not first_chunk.is_set():
        live.update(f"[dim]{frames[idx % len(frames)]}[/dim]")
        idx += 1
        time.sleep(0.35)

    indicator_thread = threading.Thread(target=indicator, daemon=True)
    indicator_thread.start()

    def on_chunk(chunk: str) -> None:
      nonlocal last_rendered_len
      first_chunk.set()
      rendered.append(chunk)
      current = "".join(rendered)
      # Avoid re-rendering every single character after initial content appears.
      if (
        len(current) <= 12
        or len(current) - last_rendered_len >= 24
        or chunk.endswith(("\n", ".", "!", "?", ":"))
      ):
        live.update(Markdown(current))
        last_rendered_len = len(current)

    try:
      answer = agent.ask_with_tools(
        question=user_text,
        tool_specs=_AGENT_TOOL_SPECS,
        tool_executor=lambda name, args: _execute_agent_tool(name, args, state=state, hiker=hiker),
        context=_build_agent_context(state),
        history=state.chat_history,
        model=state.current_model,
        on_stream_chunk=on_chunk,
      )
    finally:
      stop_indicator.set()
      indicator_thread.join(timeout=0.2)

  final_text = answer or "".join(rendered)
  if final_text:
    _RICH_CONSOLE.print(Markdown(final_text))
  else:
    _RICH_CONSOLE.print("(empty response)")
  _RICH_CONSOLE.print()
  return final_text


def _run_agent_turn(
  *,
  user_text: str,
  state: SessionState,
  agent: OpenRouterAgent,
  hiker: HikerApiClient,
) -> None:
  if not agent.enabled:
    print("OpenRouter is not configured (OPENROUTER_API_KEY missing).\n")
    return

  _append_history(state, "user", user_text)

  try:
    if _should_use_rich(state):
      answer = _render_assistant_markdown_stream(
        user_text=user_text,
        state=state,
        agent=agent,
        hiker=hiker,
      )
    else:
      first_chunk, stop_indicator, indicator_thread = _start_plain_typing_indicator()
      try:
        def on_chunk(chunk: str) -> None:
          if not first_chunk.is_set():
            first_chunk.set()
            print("\rassistant> ", end="", flush=True)
          print(chunk, end="", flush=True)

        answer = agent.ask_with_tools(
          question=user_text,
          tool_specs=_AGENT_TOOL_SPECS,
          tool_executor=lambda name, args: _execute_agent_tool(name, args, state=state, hiker=hiker),
          context=_build_agent_context(state),
          history=state.chat_history,
          model=state.current_model,
          on_stream_chunk=on_chunk,
        )
      finally:
        stop_indicator.set()
        indicator_thread.join(timeout=0.2)
      if not answer:
        if not first_chunk.is_set():
          print("\rassistant> ", end="", flush=True)
        print("(empty response)", end="")
      print("\n")
    _append_history(state, "assistant", answer)
  except OpenRouterAgentError as exc:
    print(f"\nError: {exc}\n")
  except Exception as exc:  # pragma: no cover
    print(f"\nError: {exc}\n")


def run_repl(settings: Settings) -> int:
  state = SessionState(
    current_model=settings.openrouter_chat_model,
    render_mode=_default_render_mode(),
  )
  hiker = HikerApiClient(settings)
  agent = OpenRouterAgent(settings)

  _print_banner(settings, state)

  while True:
    try:
      raw = input("instagram> ").strip()
    except (KeyboardInterrupt, EOFError):
      print("\nBye.")
      return 0

    if not raw:
      continue

    if raw in {"exit", "quit", "q"}:
      print("Bye.")
      return 0

    if raw in {"help", "?"}:
      _print_help()
      continue

    if raw == "actions":
      _print_actions()
      continue

    if raw == "model":
      print(f"Current model: {state.current_model}\n")
      continue

    if raw.startswith("model "):
      candidate = _command_arg(raw)
      if not candidate:
        print("Usage: model <openrouter_model_id>\n")
        continue
      state.current_model = candidate
      print(f"Model set to: {state.current_model}\n")
      continue

    if raw == "render":
      print(f"Current output mode: {_render_mode_label(state.render_mode)}\n")
      continue

    if raw.startswith("render "):
      candidate = _command_arg(raw).lower()
      if candidate not in {"rich", "plain"}:
        print("Usage: render <rich|plain>\n")
        continue
      if candidate == "rich" and (_RICH_CONSOLE is None or Markdown is None):
        print("Rich is not available. Install dependency and restart CLI.\n")
        continue
      state.render_mode = candidate
      print(f"Output mode set to: {_render_mode_label(state.render_mode)}\n")
      continue

    if raw == "last":
      if state.last_metrics is None:
        print("No stats loaded yet.\n")
      else:
        print(json.dumps(state.last_metrics, ensure_ascii=False, indent=2))
        print("")
      continue

    if raw == "reload":
      new_settings = Settings.load()
      hiker = HikerApiClient(new_settings)
      agent = OpenRouterAgent(new_settings)
      if state.current_model == settings.openrouter_chat_model:
        state.current_model = new_settings.openrouter_chat_model
      settings = new_settings
      print("Environment reloaded.\n")
      continue

    if raw.startswith("reel "):
      target = _command_arg(raw)
      if not target:
        print("Usage: reel <instagram_reel_url>\n")
        continue
      try:
        stats = hiker.reel_stats(target)
        _update_context_with_stats(state, stats)
        _print_reel_stats(stats)
      except HikerApiError as exc:
        print(f"Error: {exc}\n")
      continue

    if raw.startswith("profile "):
      target = _command_arg(raw)
      if not target:
        print("Usage: profile <instagram_profile_url_or_username>\n")
        continue
      try:
        stats = hiker.profile_stats(target)
        _update_context_with_stats(state, stats)
        _print_profile_stats(stats)
      except HikerApiError as exc:
        print(f"Error: {exc}\n")
      continue

    if raw.startswith("stats "):
      target = _command_arg(raw)
      if not target:
        print("Usage: stats <url_or_username>\n")
        continue
      try:
        stats = _auto_handle_target(target, hiker)
        _update_context_with_stats(state, stats)
        if stats.get("entity_type") == "reel":
          _print_reel_stats(stats)
        else:
          _print_profile_stats(stats)
      except HikerApiError as exc:
        print(f"Error: {exc}\n")
      continue

    if raw.startswith("ask "):
      question = _command_arg(raw)
      if not question:
        print("Usage: ask <question>\n")
        continue
      _run_agent_turn(user_text=question, state=state, agent=agent, hiker=hiker)
      continue

    if _is_direct_target_input(raw):
      try:
        stats = _auto_handle_target(raw, hiker)
        _update_context_with_stats(state, stats)
        if stats.get("entity_type") == "reel":
          _print_reel_stats(stats)
        else:
          _print_profile_stats(stats)
      except HikerApiError as exc:
        print(f"Error: {exc}\n")
      continue

    _run_agent_turn(user_text=raw, state=state, agent=agent, hiker=hiker)


def write_shell_wrapper(path: Path, python_bin: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  content = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    f"exec {python_bin} -m instagram_cli.main \"$@\"\n"
  )
  path.write_text(content, encoding="utf-8")
  path.chmod(0o755)
