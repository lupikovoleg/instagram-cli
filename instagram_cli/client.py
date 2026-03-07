from __future__ import annotations

import inspect
from copy import deepcopy
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin

from instagram_cli.config import Settings
from instagram_cli.ops import InstagramOps


_TOOL_DESCRIPTIONS: dict[str, str] = {
  "search_instagram": "Search Instagram by topic with optional media and freshness filters.",
  "get_profile_stats": "Get Instagram profile stats by username or profile URL.",
  "get_reel_stats": "Get Instagram media stats by reel or post URL.",
  "get_recent_reels": "Get latest reels for a profile.",
  "get_profile_reels": "Get reels for a profile with an optional date filter.",
  "get_profile_reels_page": "Get one cursor-based page of reels for a profile.",
  "get_profile_publications": "Get main-grid publications for a profile, including reels, posts, and carousels.",
  "get_profile_publications_page": "Get one cursor-based page of main-grid publications for a profile.",
  "get_followers_page": "Get one page of followers for a profile.",
  "get_following_page": "Get one page of accounts that a profile follows.",
  "get_top_followers": "Get an approximate sampled ranking of the profile's followers by follower count.",
  "search_profile_followers": "Search within a profile's followers for a keyword.",
  "search_profile_following": "Search within a profile's following for a keyword.",
  "get_media_comments": "Get a root-comments preview for a reel or post.",
  "get_media_comments_page": "Get one cursor-based page of root comments for a reel or post.",
  "get_comment_replies": "Get nested replies for a specific parent comment.",
  "get_comment_likers": "Get users who liked a comment.",
  "get_media_usertags": "Get tagged users from a reel or post.",
  "get_media_insight": "Get insight metrics for a reel or post.",
  "get_profile_stories": "Get active stories for a profile.",
  "get_profile_highlights": "Get highlight folders for a profile.",
  "get_profile_pinned_publications": "Get pinned publications for a profile.",
  "get_profile_tagged_publications": "Get publications where the profile is tagged.",
  "get_profile_tagged_publications_page": "Get one cursor-based page of publications where the profile is tagged.",
  "get_media_likers": "Get users who liked a reel or post.",
  "get_system_balance": "Get HikerAPI balance and request usage information.",
  "get_hashtag_info": "Get metadata for a hashtag.",
  "get_hashtag_reels": "Get reels for a hashtag.",
  "search_places": "Search places or locations by text query.",
  "get_location_recent_media": "Get recent media for a location.",
  "search_music": "Search tracks and sounds by query.",
  "get_track_media": "Get media that uses a track.",
  "get_profile_suggestions": "Get suggested related profiles for a profile.",
  "rank_media_likers_by_followers": "Rank likers across media URLs by follower count.",
  "download_media_content": "Download a reel or post.",
  "download_media_audio": "Download the audio track from a reel or post.",
  "download_profile_stories": "Download active stories for a profile.",
  "download_profile_highlights": "Download highlights for a profile.",
  "get_last_reel_metric": "Get one metric from the latest reel for a profile.",
}

_PARAMETER_OVERRIDES: dict[str, dict[str, dict[str, Any]]] = {
  "get_profile_publications": {
    "publication_type": {
      "enum": ["all", "reels", "posts", "carousels"],
      "description": "Filter main-grid publications by type.",
    },
  },
  "get_profile_publications_page": {
    "publication_type": {
      "enum": ["all", "reels", "posts", "carousels"],
      "description": "Filter main-grid publications by type.",
    },
  },
  "get_last_reel_metric": {
    "metric": {
      "enum": [
        "likes",
        "views",
        "comments",
        "saves",
        "published_at",
        "engagement_rate",
      ],
      "description": "Metric from the latest reel.",
    },
  },
}

_SCHEMA_EXCLUDED_PARAMETERS: dict[str, set[str]] = {
  "search_instagram": {"use_llm_expansion"},
}


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
  origin = get_origin(annotation)
  if origin in {list, tuple, set}:
    args = get_args(annotation)
    item_schema = _annotation_to_schema(args[0]) if args else {"type": "string"}
    return {"type": "array", "items": item_schema}

  if origin in {dict}:
    return {"type": "object"}

  if origin in {UnionType, Union}:
    args = [value for value in get_args(annotation) if value is not NoneType]
    if len(args) == 1:
      return _annotation_to_schema(args[0])
    return {"type": "string"}

  if annotation in {str, Path}:
    return {"type": "string"}
  if annotation is int:
    return {"type": "integer"}
  if annotation is float:
    return {"type": "number"}
  if annotation is bool:
    return {"type": "boolean"}
  return {"type": "string"}


def _build_tool_schema(name: str, method: Any) -> dict[str, Any]:
  signature = inspect.signature(method)
  properties: dict[str, Any] = {}
  required: list[str] = []

  for parameter in signature.parameters.values():
    if parameter.kind not in {
      inspect.Parameter.POSITIONAL_OR_KEYWORD,
      inspect.Parameter.KEYWORD_ONLY,
    }:
      continue
    if parameter.name in _SCHEMA_EXCLUDED_PARAMETERS.get(name, set()):
      continue
    schema = _annotation_to_schema(parameter.annotation)
    overrides = _PARAMETER_OVERRIDES.get(name, {}).get(parameter.name, {})
    schema.update(deepcopy(overrides))
    properties[parameter.name] = schema
    if parameter.default is inspect.Signature.empty:
      required.append(parameter.name)

  return {
    "type": "function",
    "function": {
      "name": name,
      "description": _TOOL_DESCRIPTIONS[name],
      "parameters": {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
      },
    },
  }


class InstagramClient(InstagramOps):
  """Stable public Python facade for embedding instagram-cli into other agents."""

  def __init__(
    self,
    settings: Settings | None = None,
    *,
    use_openrouter_search_expansion: bool = False,
  ) -> None:
    super().__init__(settings)
    self.use_openrouter_search_expansion = use_openrouter_search_expansion

  @classmethod
  def from_env(
    cls,
    *,
    env_file: str | Path | None = None,
    use_openrouter_search_expansion: bool = False,
  ) -> "InstagramClient":
    settings = Settings.load(env_file=env_file)
    return cls(
      settings,
      use_openrouter_search_expansion=use_openrouter_search_expansion,
    )

  def search_instagram(
    self,
    *,
    query: str,
    limit: int = 10,
    media_only: bool = False,
    today_only: bool = False,
    days_back: int | None = None,
    query_variants: list[str] | None = None,
    use_llm_expansion: bool | None = None,
  ) -> dict[str, Any]:
    enabled = self.use_openrouter_search_expansion if use_llm_expansion is None else use_llm_expansion
    return super().search_instagram(
      query=query,
      limit=limit,
      media_only=media_only,
      today_only=today_only,
      days_back=days_back,
      query_variants=query_variants,
      use_llm_expansion=enabled,
    )

  @classmethod
  def tool_names(cls) -> list[str]:
    return sorted(_TOOL_DESCRIPTIONS)

  def tool_schemas(self, *, names: list[str] | None = None) -> list[dict[str, Any]]:
    selected_names = names or self.tool_names()
    return [
      _build_tool_schema(name, getattr(self, name))
      for name in selected_names
      if name in _TOOL_DESCRIPTIONS and hasattr(self, name)
    ]

  def call_tool(self, name: str, /, **arguments: Any) -> dict[str, Any]:
    if name not in _TOOL_DESCRIPTIONS:
      raise ValueError(f"Unknown instagram-cli tool: {name}")
    handler = getattr(self, name, None)
    if handler is None or not callable(handler):
      raise ValueError(f"Unavailable instagram-cli tool: {name}")
    result = handler(**arguments)
    if not isinstance(result, dict):
      raise TypeError(f"Tool {name} returned non-dict result: {type(result).__name__}")
    return result

  @classmethod
  def tool_catalog(cls) -> list[dict[str, Any]]:
    client = cls(settings=Settings.load())
    return [
      {
        "name": name,
        "description": _TOOL_DESCRIPTIONS[name],
        "schema": _build_tool_schema(name, getattr(client, name)),
      }
      for name in client.tool_names()
    ]
