from __future__ import annotations

import json
import csv
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
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
      "description": "Get Instagram media stats by reel or post URL.",
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
      "name": "get_profile_reels",
      "description": (
        "Get reels for a profile with optional date and trial-mode filters. "
        "If target is omitted, use the current profile from session context."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "target": {
            "type": "string",
            "description": "Optional Instagram username or profile URL",
          },
          "limit": {
            "type": "integer",
            "description": "How many reels to return (1..20)",
            "minimum": 1,
            "maximum": 20,
          },
          "days_back": {
            "type": "integer",
            "description": "Only include reels published in the last N days (1..30)",
            "minimum": 1,
            "maximum": 30,
          },
          "mode": {
            "type": "string",
            "enum": ["all", "trial", "main"],
            "description": "Return all reels, only trial reels, or only main reels",
          },
        },
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "get_followers_page",
      "description": "Get one page of followers for a profile with low API cost.",
      "parameters": {
        "type": "object",
        "properties": {
          "target": {
            "type": "string",
            "description": "Instagram username or profile URL",
          },
          "limit": {
            "type": "integer",
            "description": "Number of followers to return from the page (1..50)",
            "minimum": 1,
            "maximum": 50,
          },
          "page_id": {
            "type": "string",
            "description": "Optional next_page_id from a previous followers page",
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
      "name": "get_top_followers",
      "description": (
        "Get an approximate ranking of the biggest followers by follower count using a limited sampled subset."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "target": {
            "type": "string",
            "description": "Instagram username or profile URL",
          },
          "sample_size": {
            "type": "integer",
            "description": "How many followers to sample before ranking. Keep this small unless the user explicitly asks for a deeper crawl (5..20).",
            "minimum": 5,
            "maximum": 20,
          },
          "top_n": {
            "type": "integer",
            "description": "How many ranked followers to return (1..10)",
            "minimum": 1,
            "maximum": 10,
          },
          "max_pages": {
            "type": "integer",
            "description": "How many followers pages may be scanned. Default to 1 unless the user explicitly asks for a deeper crawl (1..2).",
            "minimum": 1,
            "maximum": 2,
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
      "name": "get_media_comments",
      "description": (
        "Get comments for an Instagram reel or post URL. "
        "If media_url is omitted, use the current reel or post from session context."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "media_url": {
            "type": "string",
            "description": "Optional Instagram reel or post URL",
          },
          "limit": {
            "type": "integer",
            "description": "How many comments to return (1..50)",
            "minimum": 1,
            "maximum": 50,
          },
        },
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "get_media_likers",
      "description": (
        "Get users who liked an Instagram reel or post URL. "
        "If media_url is omitted, use the current reel or post from session context."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "media_url": {
            "type": "string",
            "description": "Optional Instagram reel or post URL",
          },
          "limit": {
            "type": "integer",
            "description": "How many liker previews to return (1..50)",
            "minimum": 1,
            "maximum": 50,
          },
        },
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "rank_media_likers_by_followers",
      "description": (
        "Build a top ranking of users who liked one or more media URLs, sorted by follower count. "
        "Use this only when the user explicitly asks for ranked/top likers or wants to export them."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "media_urls": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One or more Instagram reel/post URLs. If omitted, use current media from session context.",
          },
          "top_n": {
            "type": "integer",
            "description": "How many ranked rows to return (1..100)",
            "minimum": 1,
            "maximum": 100,
          },
        },
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
      "name": "export_session_data",
      "description": "Export the most recent collection in session to CSV or JSON.",
      "parameters": {
        "type": "object",
        "properties": {
          "format": {
            "type": "string",
            "enum": ["csv", "json"],
            "description": "Export file format",
          },
          "filename_hint": {
            "type": "string",
            "description": "Optional filename hint without extension",
          },
        },
        "required": ["format"],
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
  current_media: dict[str, Any] | None = None
  current_reel: dict[str, Any] | None = None
  recent_reels: list[dict[str, Any]] | None = None
  current_profile_reels: dict[str, Any] | None = None
  current_followers_page: dict[str, Any] | None = None
  current_top_followers: dict[str, Any] | None = None
  current_media_comments: dict[str, Any] | None = None
  current_media_likers: dict[str, Any] | None = None
  last_collection: dict[str, Any] | None = None
  last_export: dict[str, Any] | None = None
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
  if data.get("product_type"):
    print(f"product type: {data.get('product_type')}")
  if data.get("product_type") == "clips":
    print(f"reel mode: {'trial' if data.get('is_trial_mode') else 'main'}")
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


def _print_followers_page(data: dict[str, Any]) -> None:
  print("\n[Followers page]")
  print(f"target: @{data.get('target_username')}")
  print(f"returned: {data.get('count', 0)}")
  print(f"source: {data.get('source_endpoint')}")
  print(f"next page id: {data.get('next_page_id') or 'none'}")
  followers = data.get("followers") if isinstance(data.get("followers"), list) else []
  for index, item in enumerate(followers[:50], start=1):
    if not isinstance(item, dict):
      continue
    username = item.get("username") or "unknown"
    flags: list[str] = []
    if item.get("is_verified"):
      flags.append("verified")
    if item.get("is_private"):
      flags.append("private")
    if item.get("has_story_ring"):
      flags.append("story")
    suffix = f" [{' '.join(flags)}]" if flags else ""
    print(f"{index}. @{username}{suffix}")
  print("")


def _print_top_followers(data: dict[str, Any]) -> None:
  print("\n[Top followers]")
  print(f"target: @{data.get('target_username')}")
  print(
    "sample: "
    f"{data.get('sample_size_collected', 0)}/{data.get('sample_size_requested', 0)} "
    f"followers across {data.get('pages_used', 0)} page(s)"
  )
  budget = data.get("api_budget") if isinstance(data.get("api_budget"), dict) else {}
  print(
    "api budget: "
    f"pages={budget.get('page_requests', 0)}, "
    f"profile lookups={budget.get('profile_lookups', 0)}, "
    f"cache hits={budget.get('profile_cache_hits', 0)}"
  )
  if data.get("approximation_note"):
    print(f"note: {data.get('approximation_note')}")

  followers = data.get("followers") if isinstance(data.get("followers"), list) else []
  for index, item in enumerate(followers, start=1):
    if not isinstance(item, dict):
      continue
    username = item.get("username") or "unknown"
    follower_count = item.get("followers", 0)
    flags: list[str] = []
    if item.get("is_verified"):
      flags.append("verified")
    if item.get("is_private"):
      flags.append("private")
    suffix = f" [{' '.join(flags)}]" if flags else ""
    print(f"{index}. @{username} - {follower_count} followers{suffix}")
  print("")


def _print_profile_reels(data: dict[str, Any]) -> None:
  print("\n[Profile reels]")
  print(f"target: @{data.get('username')}")
  filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
  print(
    "filters: "
    f"mode={filters.get('mode', 'all')}, "
    f"days_back={filters.get('days_back') or 'any'}, "
    f"limit={filters.get('limit') or 0}"
  )
  print(f"pages used: {data.get('pages_used', 0)}")
  print(f"scanned reels: {data.get('scanned_reels', 0)}")
  reels = data.get("reels") if isinstance(data.get("reels"), list) else []
  for index, item in enumerate(reels, start=1):
    if not isinstance(item, dict):
      continue
    username = item.get("username") or data.get("username") or "unknown"
    label = "trial" if item.get("is_trial_mode") else "main"
    print(
      f"{index}. @{username} {item.get('url') or ''}\n"
      f"   {label} | {item.get('published_at_local') or 'unknown'} | "
      f"views={item.get('views', 0)} likes={item.get('likes', 0)} comments={item.get('comments', 0)}"
    )
  print("")


def _print_media_comments(data: dict[str, Any]) -> None:
  media = data.get("media") if isinstance(data.get("media"), dict) else {}
  print("\n[Media comments]")
  print(f"url: {media.get('url')}")
  print(f"returned: {data.get('returned_count', 0)}")
  if data.get("cap_note"):
    print(f"note: {data.get('cap_note')}")
  comments = data.get("comments") if isinstance(data.get("comments"), list) else []
  for index, item in enumerate(comments, start=1):
    if not isinstance(item, dict):
      continue
    username = item.get("username") or "unknown"
    print(
      f"{index}. @{username} ({item.get('like_count', 0)} likes) "
      f"{item.get('created_at_local') or item.get('created_at_utc') or ''}\n"
      f"   {item.get('text') or ''}"
    )
  print("")


def _print_media_likers(data: dict[str, Any]) -> None:
  media = data.get("media") if isinstance(data.get("media"), dict) else {}
  print("\n[Media likers]")
  print(f"url: {media.get('url')}")
  print(f"returned: {data.get('returned_count', 0)}")
  if data.get("cap_note"):
    print(f"note: {data.get('cap_note')}")
  likers = data.get("likers") if isinstance(data.get("likers"), list) else []
  for index, item in enumerate(likers, start=1):
    if not isinstance(item, dict):
      continue
    username = item.get("username") or "unknown"
    flags: list[str] = []
    if item.get("is_verified"):
      flags.append("verified")
    if item.get("is_private"):
      flags.append("private")
    suffix = f" [{' '.join(flags)}]" if flags else ""
    print(f"{index}. @{username}{suffix}")
  print("")


def _print_ranked_media_likers(data: dict[str, Any]) -> None:
  print("\n[Top media likers by followers]")
  source_media = data.get("source_media") if isinstance(data.get("source_media"), list) else []
  print(f"source media: {len(source_media)}")
  budget = data.get("api_budget") if isinstance(data.get("api_budget"), dict) else {}
  print(
    "api budget: "
    f"media info={budget.get('media_info_requests', 0)}, "
    f"likers={budget.get('liker_requests', 0)}, "
    f"profile lookups={budget.get('profile_lookups', 0)}"
  )
  limitations = data.get("limitations") if isinstance(data.get("limitations"), list) else []
  for note in limitations:
    print(f"note: {note}")
  rows = data.get("rows") if isinstance(data.get("rows"), list) else []
  for row in rows[:20]:
    if not isinstance(row, dict):
      continue
    print(
      f"{row.get('rank')}. @{row.get('username') or 'unknown'} - "
      f"{row.get('followers', 0)} followers | liked {row.get('liked_count', 0)} source posts"
    )
  print("")


def _print_export_result(data: dict[str, Any]) -> None:
  print("\n[Export]")
  print(f"collection: {data.get('collection_name')}")
  print(f"rows: {data.get('row_count')}")
  print(f"format: {data.get('format')}")
  print(f"path: {data.get('path')}")
  print("")


def _print_help() -> None:
  print(
    "\nCommands:\n"
    "- help: show this help\n"
    "- actions: show available actions\n"
    "- reel <instagram_reel_url>: fetch reel stats\n"
    "- profile <instagram_profile_url_or_username>: fetch profile stats\n"
    "- reels <instagram_profile_url_or_username> [limit] [days_back] [all|trial|main]: fetch filtered reels\n"
    "- comments <instagram_media_url> [limit]: fetch media comments\n"
    "- likers <instagram_media_url> [limit]: fetch media likers\n"
    "- followers <instagram_profile_url_or_username> [limit]: fetch one follower page\n"
    "- top-followers <instagram_profile_url_or_username> [sample_size] [top_n]: approximate biggest followers\n"
    "- export <csv|json> [filename_hint]: export the most recent collection in session\n"
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
    "- how many likes does the latest reel have?\n"
    "- show the last 5 trial reels from this profile from the last week\n"
    "- export that to csv\n",
  )


def _print_actions() -> None:
  print(
    "\nAvailable actions now:\n"
    "1. Get Reel metrics by URL: views, likes, comments, saves, engagement, publish time.\n"
    "2. Get Profile metrics by URL/@username: followers, following, posts, verified/private, stories.\n"
    "3. Fetch filtered profile reels, including trial-mode detection from chunk payloads.\n"
    "4. Fetch media comments and media likers.\n"
    "5. Fetch follower pages with low API cost.\n"
    "6. Estimate top followers from a bounded sampled subset to control API spend.\n"
    "7. Rank likers by follower count when explicitly requested.\n"
    "8. Export the current collection to CSV or JSON.\n"
    "9. Ask natural language questions; agent decides tool calls automatically.\n"
    "10. Follow-ups use session context (current profile/reel/media/collection).\n",
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


def _slugify(value: str, *, default: str = "export") -> str:
  slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
  return slug or default


def _json_safe_value(value: Any) -> Any:
  if isinstance(value, (str, int, float, bool)) or value is None:
    return value
  if isinstance(value, list):
    return [_json_safe_value(item) for item in value]
  if isinstance(value, dict):
    return {str(key): _json_safe_value(item) for key, item in value.items()}
  return str(value)


def _csv_cell(value: Any) -> str:
  safe = _json_safe_value(value)
  if isinstance(safe, (str, int, float, bool)) or safe is None:
    return "" if safe is None else str(safe)
  return json.dumps(safe, ensure_ascii=False)


def _output_dir() -> Path:
  path = Path(__file__).resolve().parent.parent / "output"
  path.mkdir(parents=True, exist_ok=True)
  return path


def _set_last_collection(
  state: SessionState,
  *,
  name: str,
  rows: list[dict[str, Any]],
  metadata: dict[str, Any] | None = None,
  filename_hint: str | None = None,
) -> None:
  state.last_collection = {
    "name": name,
    "row_count": len(rows),
    "rows": rows,
    "metadata": metadata or {},
    "filename_hint": filename_hint or name,
  }


def _collection_context(collection: dict[str, Any] | None) -> dict[str, Any] | None:
  if not isinstance(collection, dict):
    return None
  rows = collection.get("rows") if isinstance(collection.get("rows"), list) else []
  return {
    "name": collection.get("name"),
    "row_count": collection.get("row_count", len(rows)),
    "filename_hint": collection.get("filename_hint"),
    "metadata": collection.get("metadata"),
    "sample_rows": [_json_safe_value(item) for item in rows[:5] if isinstance(item, dict)],
  }


def _resolve_profile_target(target: str | None, state: SessionState) -> str | None:
  candidate = (target or "").strip()
  if candidate:
    return candidate

  for source in (
    state.current_profile,
    state.current_media,
    state.current_reel,
    state.current_profile_reels.get("profile") if isinstance(state.current_profile_reels, dict) else None,
  ):
    if not isinstance(source, dict):
      continue
    username = str(source.get("username") or "").strip()
    if username:
      return username
  return None


def _resolve_media_url(media_url: str | None, state: SessionState) -> str | None:
  candidate = (media_url or "").strip()
  if candidate:
    return candidate

  for source in (
    state.current_media,
    state.current_reel,
    state.last_metrics,
  ):
    if not isinstance(source, dict):
      continue
    url = str(source.get("url") or "").strip()
    if url and extract_reel_shortcode(url):
      return url
  return None


def _export_last_collection(
  *,
  fmt: str,
  state: SessionState,
  filename_hint: str | None = None,
) -> dict[str, Any]:
  collection = state.last_collection
  if not isinstance(collection, dict):
    return {
      "ok": False,
      "error": "no_collection_available",
      "message": "Load a list or ranking first, then export it.",
    }

  rows = collection.get("rows") if isinstance(collection.get("rows"), list) else []
  safe_rows = [
    {str(key): _json_safe_value(value) for key, value in item.items()}
    for item in rows
    if isinstance(item, dict)
  ]
  timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
  hint = filename_hint or str(collection.get("filename_hint") or collection.get("name") or "export")
  slug = _slugify(hint)
  output_path = _output_dir() / f"{slug}_{timestamp}.{fmt}"

  if fmt == "csv":
    fieldnames: list[str] = []
    seen_fields: set[str] = set()
    for row in safe_rows:
      for key in row.keys():
        if key in seen_fields:
          continue
        seen_fields.add(key)
        fieldnames.append(key)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
      writer = csv.DictWriter(handle, fieldnames=fieldnames)
      writer.writeheader()
      for row in safe_rows:
        writer.writerow({key: _csv_cell(row.get(key)) for key in fieldnames})
  else:
    output_path.write_text(
      json.dumps(
        {
          "generated_at": datetime.now().isoformat(timespec="seconds"),
          "collection": {
            "name": collection.get("name"),
            "row_count": len(safe_rows),
            "filename_hint": collection.get("filename_hint"),
          },
          "metadata": _json_safe_value(collection.get("metadata")),
          "rows": safe_rows,
        },
        ensure_ascii=False,
        indent=2,
      ),
      encoding="utf-8",
    )

  state.last_export = {
    "format": fmt,
    "path": str(output_path),
    "row_count": len(safe_rows),
    "collection_name": collection.get("name"),
  }
  return {
    "ok": True,
    "format": fmt,
    "path": str(output_path),
    "row_count": len(safe_rows),
    "collection_name": collection.get("name"),
  }


def _update_context_with_stats(state: SessionState, stats: dict[str, Any]) -> None:
  state.last_metrics = stats
  entity_type = str(stats.get("entity_type") or "")

  if entity_type == "profile":
    previous_username = (state.current_profile or {}).get("username")
    next_username = stats.get("username")
    state.current_profile = stats
    if previous_username != next_username:
      state.recent_reels = None
      state.current_profile_reels = None
      state.current_followers_page = None
      state.current_top_followers = None
      state.current_media = None
      state.current_reel = None
      state.current_media_comments = None
      state.current_media_likers = None
    return

  if entity_type == "media":
    state.current_media = stats
    return

  if entity_type in {"reel", "reel_preview"}:
    state.current_media = {
      "entity_type": "media",
      "url": stats.get("url"),
      "shortcode": stats.get("shortcode"),
      "username": stats.get("username"),
      "product_type": stats.get("product_type"),
      "published_at_utc": stats.get("published_at_utc"),
      "published_at_local": stats.get("published_at_local"),
    }
    state.current_reel = stats
    return

  if entity_type == "profile_reels":
    profile = stats.get("profile")
    reels = stats.get("reels") if isinstance(stats.get("reels"), list) else []
    if isinstance(profile, dict):
      previous_username = (state.current_profile or {}).get("username")
      state.current_profile = profile
      if previous_username != profile.get("username"):
        state.current_followers_page = None
        state.current_top_followers = None
    state.current_profile_reels = stats
    state.recent_reels = [item for item in reels if isinstance(item, dict)]
    if state.recent_reels:
      state.current_reel = state.recent_reels[0]
    return

  if entity_type == "followers_page":
    profile = stats.get("profile")
    if isinstance(profile, dict):
      previous_username = (state.current_profile or {}).get("username")
      next_username = profile.get("username")
      state.current_profile = profile
      if previous_username != next_username:
        state.recent_reels = None
        state.current_top_followers = None
    state.current_followers_page = stats
    return

  if entity_type == "top_followers_sample":
    profile = stats.get("profile")
    if isinstance(profile, dict):
      previous_username = (state.current_profile or {}).get("username")
      next_username = profile.get("username")
      state.current_profile = profile
      if previous_username != next_username:
        state.recent_reels = None
      state.current_followers_page = None
    state.current_top_followers = stats
    return

  if entity_type == "media_comments":
    media = stats.get("media")
    if isinstance(media, dict):
      state.current_media = media
    state.current_media_comments = stats
    return

  if entity_type == "media_likers":
    media = stats.get("media")
    if isinstance(media, dict):
      state.current_media = media
    state.current_media_likers = stats
    return

  if entity_type == "media_likers_ranked":
    state.current_media_likers = stats


def _build_agent_context(state: SessionState) -> dict[str, Any]:
  context: dict[str, Any] = {}

  if state.last_metrics is not None:
    context["last_metrics"] = _without_raw(state.last_metrics)
  if state.current_profile is not None:
    context["current_profile"] = _without_raw(state.current_profile)
  if state.current_media is not None:
    context["current_media"] = _without_raw(state.current_media)
  if state.current_reel is not None:
    context["current_reel"] = _without_raw(state.current_reel)
  if state.recent_reels:
    context["recent_reels"] = [_without_raw(item) for item in state.recent_reels[:5]]
  if state.current_profile_reels is not None:
    profile_reels = _without_raw(state.current_profile_reels) or {}
    reels = profile_reels.get("reels")
    if isinstance(reels, list):
      profile_reels["reels"] = [_without_raw(item) for item in reels[:5] if isinstance(item, dict)]
    context["current_profile_reels"] = profile_reels
  if state.current_followers_page is not None:
    followers_page = _without_raw(state.current_followers_page) or {}
    followers = followers_page.get("followers")
    if isinstance(followers, list):
      followers_page["followers"] = [_without_raw(item) for item in followers[:10] if isinstance(item, dict)]
    context["current_followers_page"] = followers_page
  if state.current_top_followers is not None:
    top_followers = _without_raw(state.current_top_followers) or {}
    followers = top_followers.get("followers")
    if isinstance(followers, list):
      top_followers["followers"] = [_without_raw(item) for item in followers[:10] if isinstance(item, dict)]
    context["current_top_followers"] = top_followers
  if state.current_media_comments is not None:
    media_comments = _without_raw(state.current_media_comments) or {}
    comments = media_comments.get("comments")
    if isinstance(comments, list):
      media_comments["comments"] = [_without_raw(item) for item in comments[:10] if isinstance(item, dict)]
    context["current_media_comments"] = media_comments
  if state.current_media_likers is not None:
    media_likers = _without_raw(state.current_media_likers) or {}
    likers = media_likers.get("likers")
    rows = media_likers.get("rows")
    if isinstance(likers, list):
      media_likers["likers"] = [_without_raw(item) for item in likers[:10] if isinstance(item, dict)]
    if isinstance(rows, list):
      media_likers["rows"] = [_without_raw(item) for item in rows[:10] if isinstance(item, dict)]
    context["current_media_likers"] = media_likers
  collection_context = _collection_context(state.last_collection)
  if collection_context is not None:
    context["last_collection"] = collection_context
  if state.last_export is not None:
    context["last_export"] = state.last_export

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
  _update_context_with_stats(state, payload)
  profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else None
  reels = payload.get("reels") if isinstance(payload.get("reels"), list) else []
  normalized_reels = [item for item in reels if isinstance(item, dict)]
  safe_reels = [_without_raw(item) for item in normalized_reels]
  _set_last_collection(
    state,
    name="profile_reels",
    rows=[item for item in safe_reels if isinstance(item, dict)],
    metadata={
      "username": payload.get("username"),
      "pages_used": payload.get("pages_used"),
      "filters": payload.get("filters"),
      "source_endpoint": payload.get("source_endpoint"),
    },
    filename_hint=f"{payload.get('username') or 'profile'}-recent-reels",
  )

  return {
    "ok": True,
    "username": payload.get("username"),
    "count": len(normalized_reels),
    "profile": _without_raw(profile) if profile else None,
    "reels": safe_reels,
  }


def _tool_get_profile_reels(
  *,
  target: str | None,
  limit: int,
  days_back: int | None,
  mode: str,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  chosen_target = _resolve_profile_target(target, state)
  if not chosen_target:
    return {
      "ok": False,
      "error": "target_not_found_in_session",
      "message": "Provide username/profile URL or load a profile first.",
    }

  payload = hiker.profile_reels(
    chosen_target,
    limit=limit,
    days_back=days_back,
    mode=mode,
  )
  _update_context_with_stats(state, payload)
  reels = payload.get("reels") if isinstance(payload.get("reels"), list) else []
  safe_reels = [_without_raw(item) for item in reels if isinstance(item, dict)]
  _set_last_collection(
    state,
    name="profile_reels",
    rows=[item for item in safe_reels if isinstance(item, dict)],
    metadata={
      "username": payload.get("username"),
      "filters": payload.get("filters"),
      "pages_used": payload.get("pages_used"),
      "source_endpoint": payload.get("source_endpoint"),
    },
    filename_hint=f"{payload.get('username') or 'profile'}-{mode}-reels",
  )
  return {
    "ok": True,
    "username": payload.get("username"),
    "count": len(safe_reels),
    "filters": payload.get("filters"),
    "pages_used": payload.get("pages_used"),
    "source_endpoint": payload.get("source_endpoint"),
    "profile": _without_raw(payload.get("profile")) if isinstance(payload.get("profile"), dict) else None,
    "reels": safe_reels,
  }


def _tool_get_followers_page(
  *,
  target: str,
  limit: int,
  page_id: str | None,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  payload = hiker.followers_page(target, limit=limit, page_id=page_id)
  _update_context_with_stats(state, payload)
  followers = payload.get("followers") if isinstance(payload.get("followers"), list) else []
  safe_followers = [_without_raw(item) for item in followers if isinstance(item, dict)]
  _set_last_collection(
    state,
    name="followers_page",
    rows=[item for item in safe_followers if isinstance(item, dict)],
    metadata={
      "target_username": payload.get("target_username"),
      "next_page_id": payload.get("next_page_id"),
      "source_endpoint": payload.get("source_endpoint"),
    },
    filename_hint=f"{payload.get('target_username') or 'profile'}-followers-page",
  )
  return {
    "ok": True,
    "target_username": payload.get("target_username"),
    "count": len(followers),
    "next_page_id": payload.get("next_page_id"),
    "source_endpoint": payload.get("source_endpoint"),
    "profile": _without_raw(payload.get("profile")) if isinstance(payload.get("profile"), dict) else None,
    "followers": safe_followers,
  }


def _tool_get_top_followers(
  *,
  target: str,
  sample_size: int,
  top_n: int,
  max_pages: int,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  payload = hiker.top_followers(target, sample_size=sample_size, top_n=top_n, max_pages=max_pages)
  _update_context_with_stats(state, payload)
  followers = payload.get("followers") if isinstance(payload.get("followers"), list) else []
  safe_followers = [_without_raw(item) for item in followers if isinstance(item, dict)]
  _set_last_collection(
    state,
    name="top_followers",
    rows=[item for item in safe_followers if isinstance(item, dict)],
    metadata={
      "target_username": payload.get("target_username"),
      "approximation_note": payload.get("approximation_note"),
      "api_budget": payload.get("api_budget"),
    },
    filename_hint=f"{payload.get('target_username') or 'profile'}-top-followers",
  )
  return {
    "ok": True,
    "target_username": payload.get("target_username"),
    "approximate": payload.get("approximate"),
    "approximation_note": payload.get("approximation_note"),
    "sample_size_requested": payload.get("sample_size_requested"),
    "sample_size_collected": payload.get("sample_size_collected"),
    "pages_used": payload.get("pages_used"),
    "api_budget": payload.get("api_budget"),
    "followers": safe_followers,
  }


def _tool_get_media_comments(
  *,
  media_url: str | None,
  limit: int,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  chosen_media_url = _resolve_media_url(media_url, state)
  if not chosen_media_url:
    return {
      "ok": False,
      "error": "media_not_found_in_session",
      "message": "Provide a reel/post URL or load a reel/post first.",
    }

  payload = hiker.media_comments(chosen_media_url, limit=limit)
  _update_context_with_stats(state, payload)
  comments = payload.get("comments") if isinstance(payload.get("comments"), list) else []
  safe_comments = [_without_raw(item) for item in comments if isinstance(item, dict)]
  media = payload.get("media") if isinstance(payload.get("media"), dict) else None
  _set_last_collection(
    state,
    name="media_comments",
    rows=[item for item in safe_comments if isinstance(item, dict)],
    metadata={
      "media_url": (media or {}).get("url"),
      "shortcode": (media or {}).get("shortcode"),
      "available_comment_count": payload.get("available_comment_count"),
      "cap_note": payload.get("cap_note"),
    },
    filename_hint=f"{(media or {}).get('shortcode') or 'media'}-comments",
  )
  return {
    "ok": True,
    "media": _without_raw(media) if media else None,
    "returned_count": payload.get("returned_count"),
    "available_comment_count": payload.get("available_comment_count"),
    "cap_note": payload.get("cap_note"),
    "comments": safe_comments,
  }


def _tool_get_media_likers(
  *,
  media_url: str | None,
  limit: int,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  chosen_media_url = _resolve_media_url(media_url, state)
  if not chosen_media_url:
    return {
      "ok": False,
      "error": "media_not_found_in_session",
      "message": "Provide a reel/post URL or load a reel/post first.",
    }

  payload = hiker.media_likers(chosen_media_url)
  _update_context_with_stats(state, payload)
  likers = payload.get("likers") if isinstance(payload.get("likers"), list) else []
  safe_likers = [_without_raw(item) for item in likers[:limit] if isinstance(item, dict)]
  media = payload.get("media") if isinstance(payload.get("media"), dict) else None
  _set_last_collection(
    state,
    name="media_likers",
    rows=[item for item in safe_likers if isinstance(item, dict)],
    metadata={
      "media_url": (media or {}).get("url"),
      "shortcode": (media or {}).get("shortcode"),
      "available_like_count": payload.get("available_like_count"),
      "returned_count": payload.get("returned_count"),
      "cap_note": payload.get("cap_note"),
    },
    filename_hint=f"{(media or {}).get('shortcode') or 'media'}-likers",
  )
  return {
    "ok": True,
    "media": _without_raw(media) if media else None,
    "returned_count": len(safe_likers),
    "available_like_count": payload.get("available_like_count"),
    "cap_note": payload.get("cap_note"),
    "likers": safe_likers,
  }


def _tool_rank_media_likers_by_followers(
  *,
  media_urls: list[str] | None,
  top_n: int,
  state: SessionState,
  hiker: HikerApiClient,
) -> dict[str, Any]:
  urls = [str(item).strip() for item in (media_urls or []) if str(item).strip()]
  if not urls:
    current_url = _resolve_media_url(None, state)
    if current_url:
      urls = [current_url]
  if not urls:
    return {
      "ok": False,
      "error": "media_not_found_in_session",
      "message": "Provide one or more reel/post URLs or load a media item first.",
    }

  payload = hiker.top_media_likers_by_followers(urls, top_n=top_n)
  _update_context_with_stats(state, payload)
  rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
  safe_rows = [_without_raw(item) for item in rows if isinstance(item, dict)]
  _set_last_collection(
    state,
    name="ranked_media_likers",
    rows=[item for item in safe_rows if isinstance(item, dict)],
    metadata={
      "source_media": payload.get("source_media"),
      "limitations": payload.get("limitations"),
      "api_budget": payload.get("api_budget"),
    },
    filename_hint="top-media-likers-by-followers",
  )
  return {
    "ok": True,
    "source_media": payload.get("source_media"),
    "unique_likers": payload.get("unique_likers"),
    "enriched_profiles": payload.get("enriched_profiles"),
    "top_n": payload.get("top_n"),
    "limitations": payload.get("limitations"),
    "api_budget": payload.get("api_budget"),
    "rows": safe_rows,
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

    if tool_name == "get_profile_reels":
      target = args.get("target")
      target_text = str(target).strip() if isinstance(target, str) else None
      try:
        limit = int(args.get("limit", 12))
      except (TypeError, ValueError):
        limit = 12
      days_back_raw = args.get("days_back")
      if days_back_raw in {None, ""}:
        days_back = None
      else:
        try:
          days_back = int(days_back_raw)
        except (TypeError, ValueError):
          days_back = None
      mode = str(args.get("mode") or "all").strip().lower() or "all"
      return _tool_get_profile_reels(
        target=target_text,
        limit=max(1, min(limit, 20)),
        days_back=max(1, min(days_back, 30)) if isinstance(days_back, int) else None,
        mode=mode if mode in {"all", "trial", "main"} else "all",
        state=state,
        hiker=hiker,
      )

    if tool_name == "get_followers_page":
      target = str(args.get("target") or "").strip()
      if not target:
        return {"ok": False, "error": "missing_target"}
      raw_limit = args.get("limit", 25)
      try:
        limit = int(raw_limit)
      except (TypeError, ValueError):
        limit = 25
      limit = max(1, min(limit, 50))
      page_id = args.get("page_id")
      page_text = str(page_id).strip() if isinstance(page_id, str) and page_id.strip() else None
      return _tool_get_followers_page(
        target=target,
        limit=limit,
        page_id=page_text,
        state=state,
        hiker=hiker,
      )

    if tool_name == "get_top_followers":
      target = str(args.get("target") or "").strip()
      if not target:
        return {"ok": False, "error": "missing_target"}
      try:
        sample_size = int(args.get("sample_size", 5))
      except (TypeError, ValueError):
        sample_size = 5
      try:
        top_n = int(args.get("top_n", 5))
      except (TypeError, ValueError):
        top_n = 5
      try:
        max_pages = int(args.get("max_pages", 1))
      except (TypeError, ValueError):
        max_pages = 1
      return _tool_get_top_followers(
        target=target,
        sample_size=max(5, min(sample_size, 20)),
        top_n=max(1, min(top_n, 10)),
        max_pages=max(1, min(max_pages, 2)),
        state=state,
        hiker=hiker,
      )

    if tool_name == "get_media_comments":
      media_url = args.get("media_url")
      media_url_text = str(media_url).strip() if isinstance(media_url, str) else None
      try:
        limit = int(args.get("limit", 20))
      except (TypeError, ValueError):
        limit = 20
      return _tool_get_media_comments(
        media_url=media_url_text,
        limit=max(1, min(limit, 50)),
        state=state,
        hiker=hiker,
      )

    if tool_name == "get_media_likers":
      media_url = args.get("media_url")
      media_url_text = str(media_url).strip() if isinstance(media_url, str) else None
      try:
        limit = int(args.get("limit", 20))
      except (TypeError, ValueError):
        limit = 20
      return _tool_get_media_likers(
        media_url=media_url_text,
        limit=max(1, min(limit, 50)),
        state=state,
        hiker=hiker,
      )

    if tool_name == "rank_media_likers_by_followers":
      media_urls_raw = args.get("media_urls")
      media_urls = [str(item).strip() for item in media_urls_raw] if isinstance(media_urls_raw, list) else None
      try:
        top_n = int(args.get("top_n", 100))
      except (TypeError, ValueError):
        top_n = 100
      return _tool_rank_media_likers_by_followers(
        media_urls=media_urls,
        top_n=max(1, min(top_n, 100)),
        state=state,
        hiker=hiker,
      )

    if tool_name == "get_last_reel_metric":
      metric = str(args.get("metric") or "").strip()
      if not metric:
        return {"ok": False, "error": "missing_metric"}
      target = args.get("target")
      target_text = str(target).strip() if isinstance(target, str) else None
      return _tool_get_last_reel_metric(metric=metric, target=target_text, state=state, hiker=hiker)

    if tool_name == "export_session_data":
      fmt = str(args.get("format") or "").strip().lower()
      if fmt not in {"csv", "json"}:
        return {"ok": False, "error": "invalid_format"}
      filename_hint = args.get("filename_hint")
      hint_text = str(filename_hint).strip() if isinstance(filename_hint, str) and filename_hint.strip() else None
      return _export_last_collection(fmt=fmt, state=state, filename_hint=hint_text)

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

    if raw.startswith("reels "):
      parts = raw.split()
      if len(parts) < 2:
        print("Usage: reels <instagram_profile_url_or_username> [limit] [days_back] [all|trial|main]\n")
        continue
      target = parts[1]
      try:
        limit = int(parts[2]) if len(parts) >= 3 else 12
      except ValueError:
        print("Usage: reels <instagram_profile_url_or_username> [limit] [days_back] [all|trial|main]\n")
        continue
      days_back: int | None = None
      mode = "all"
      if len(parts) >= 4:
        if parts[3].isdigit():
          days_back = int(parts[3])
          if len(parts) >= 5:
            mode = parts[4].lower()
        else:
          mode = parts[3].lower()
      try:
        payload = hiker.profile_reels(
          target,
          limit=max(1, min(limit, 20)),
          days_back=max(1, min(days_back, 30)) if isinstance(days_back, int) else None,
          mode=mode if mode in {"all", "trial", "main"} else "all",
        )
        _update_context_with_stats(state, payload)
        reels = payload.get("reels") if isinstance(payload.get("reels"), list) else []
        safe_reels = [_without_raw(item) for item in reels if isinstance(item, dict)]
        _set_last_collection(
          state,
          name="profile_reels",
          rows=[item for item in safe_reels if isinstance(item, dict)],
          metadata={
            "username": payload.get("username"),
            "filters": payload.get("filters"),
            "pages_used": payload.get("pages_used"),
          },
          filename_hint=f"{payload.get('username') or 'profile'}-{mode}-reels",
        )
        _print_profile_reels(payload)
      except HikerApiError as exc:
        print(f"Error: {exc}\n")
      continue

    if raw.startswith("comments "):
      parts = raw.split(maxsplit=2)
      if len(parts) < 2:
        print("Usage: comments <instagram_media_url> [limit]\n")
        continue
      target = parts[1]
      try:
        limit = int(parts[2]) if len(parts) >= 3 else 20
      except ValueError:
        print("Usage: comments <instagram_media_url> [limit]\n")
        continue
      try:
        result = _tool_get_media_comments(
          media_url=target,
          limit=max(1, min(limit, 50)),
          state=state,
          hiker=hiker,
        )
        if not result.get("ok"):
          print(f"Error: {result.get('message') or result.get('error')}\n")
          continue
        _print_media_comments(
          {
            "media": result.get("media"),
            "returned_count": result.get("returned_count"),
            "available_comment_count": result.get("available_comment_count"),
            "cap_note": result.get("cap_note"),
            "comments": result.get("comments"),
          },
        )
      except HikerApiError as exc:
        print(f"Error: {exc}\n")
      continue

    if raw.startswith("likers "):
      parts = raw.split(maxsplit=2)
      if len(parts) < 2:
        print("Usage: likers <instagram_media_url> [limit]\n")
        continue
      target = parts[1]
      try:
        limit = int(parts[2]) if len(parts) >= 3 else 20
      except ValueError:
        print("Usage: likers <instagram_media_url> [limit]\n")
        continue
      try:
        result = _tool_get_media_likers(
          media_url=target,
          limit=max(1, min(limit, 50)),
          state=state,
          hiker=hiker,
        )
        if not result.get("ok"):
          print(f"Error: {result.get('message') or result.get('error')}\n")
          continue
        _print_media_likers(
          {
            "media": result.get("media"),
            "returned_count": result.get("returned_count"),
            "available_like_count": result.get("available_like_count"),
            "cap_note": result.get("cap_note"),
            "likers": result.get("likers"),
          },
        )
      except HikerApiError as exc:
        print(f"Error: {exc}\n")
      continue

    if raw.startswith("followers "):
      parts = raw.split()
      if len(parts) < 2:
        print("Usage: followers <instagram_profile_url_or_username> [limit]\n")
        continue
      target = parts[1]
      try:
        limit = int(parts[2]) if len(parts) >= 3 else 25
      except ValueError:
        print("Usage: followers <instagram_profile_url_or_username> [limit]\n")
        continue
      limit = max(1, min(limit, 50))
      try:
        payload = hiker.followers_page(target, limit=limit)
        _update_context_with_stats(state, payload)
        _print_followers_page(payload)
      except HikerApiError as exc:
        print(f"Error: {exc}\n")
      continue

    if raw.startswith("top-followers "):
      parts = raw.split()
      if len(parts) < 2:
        print("Usage: top-followers <instagram_profile_url_or_username> [sample_size] [top_n]\n")
        continue
      target = parts[1]
      try:
        sample_size = int(parts[2]) if len(parts) >= 3 else 5
        top_n = int(parts[3]) if len(parts) >= 4 else 5
      except ValueError:
        print("Usage: top-followers <instagram_profile_url_or_username> [sample_size] [top_n]\n")
        continue
      try:
        payload = hiker.top_followers(
          target,
          sample_size=max(5, min(sample_size, 20)),
          top_n=max(1, min(top_n, 10)),
        )
        _update_context_with_stats(state, payload)
        _print_top_followers(payload)
      except HikerApiError as exc:
        print(f"Error: {exc}\n")
      continue

    if raw.startswith("export "):
      parts = raw.split(maxsplit=2)
      if len(parts) < 2 or parts[1].lower() not in {"csv", "json"}:
        print("Usage: export <csv|json> [filename_hint]\n")
        continue
      fmt = parts[1].lower()
      filename_hint = parts[2].strip() if len(parts) >= 3 else None
      result = _export_last_collection(fmt=fmt, state=state, filename_hint=filename_hint)
      if not result.get("ok"):
        print(f"Error: {result.get('message') or result.get('error')}\n")
        continue
      _print_export_result(result)
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
