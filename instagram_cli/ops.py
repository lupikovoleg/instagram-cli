from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from instagram_cli.config import Settings
from instagram_cli.hiker_api import HikerApiClient
from instagram_cli.limits import (
  MAX_MEDIA_COMMENTS,
  MAX_DAYS_BACK,
  MAX_PROFILE_COLLECTION_ITEMS,
  MAX_PROFILE_COLLECTION_PAGE_SIZE,
  MAX_SEARCH_RESULTS,
)
from instagram_cli.openrouter_agent import OpenRouterAgent
from instagram_cli.repl import (
  SessionState,
  _csv_cell,
  _json_safe_value,
  _output_dir,
  _slugify,
  _tool_download_media_audio,
  _tool_download_media_content,
  _tool_download_profile_highlights,
  _tool_download_profile_stories,
  _tool_get_comment_likers,
  _tool_get_comment_replies,
  _tool_get_followers_page,
  _tool_get_following_page,
  _tool_get_hashtag_info,
  _tool_get_hashtag_reels,
  _tool_get_last_reel_metric,
  _tool_get_media_comments,
  _tool_get_media_comments_page,
  _tool_get_media_insight,
  _tool_get_media_likers,
  _tool_get_media_usertags,
  _tool_get_location_recent_media,
  _tool_get_profile_highlights,
  _tool_get_profile_pinned_publications,
  _tool_get_profile_publications_page,
  _tool_get_profile_publications,
  _tool_get_profile_reels_page,
  _tool_get_profile_reels,
  _tool_get_profile_suggestions,
  _tool_get_profile_stats,
  _tool_get_profile_stories,
  _tool_get_profile_tagged_publications_page,
  _tool_get_profile_tagged_publications,
  _tool_get_recent_reels,
  _tool_get_reel_stats,
  _tool_get_system_balance,
  _tool_get_track_media,
  _tool_get_top_followers,
  _tool_rank_media_likers_by_followers,
  _tool_search_music,
  _tool_search_places,
  _tool_search_profile_followers,
  _tool_search_profile_following,
  _tool_search_instagram,
)


def _default_output_dir() -> Path:
  path = _output_dir()
  path.mkdir(parents=True, exist_ok=True)
  return path


def _collection_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
  for key in (
    "rows",
    "items",
    "reels",
    "publications",
    "followers",
    "following",
    "comments",
    "replies",
    "stories",
    "highlights",
    "likers",
    "profiles",
    "tracks",
    "tags",
  ):
    value = result.get(key)
    if isinstance(value, list):
      return [item for item in value if isinstance(item, dict)]

  for key in ("profile", "reel", "media"):
    value = result.get(key)
    if isinstance(value, dict):
      return [value]

  return []


def _collection_name(result: dict[str, Any]) -> str:
  for key in ("collection_name", "entity_type", "download_kind"):
    value = result.get(key)
    if isinstance(value, str) and value.strip():
      return value.strip()
  for key, name in (
    ("items", "search_results"),
    ("reels", "profile_reels"),
    ("publications", "profile_publications"),
    ("followers", "followers"),
    ("following", "following"),
    ("comments", "media_comments"),
    ("replies", "comment_replies"),
    ("stories", "profile_stories"),
    ("highlights", "profile_highlights"),
    ("likers", "media_likers"),
    ("profiles", "profiles"),
    ("tracks", "tracks"),
    ("tags", "tags"),
    ("rows", "rows"),
    ("profile", "profile"),
    ("reel", "reel"),
    ("media", "media"),
  ):
    value = result.get(key)
    if isinstance(value, list) and value:
      return name
    if isinstance(value, dict):
      return name
  return "result"


def _collection_filename_hint(result: dict[str, Any], *, default: str | None = None) -> str:
  for key in ("filename_hint", "target_username", "username", "shortcode", "query", "normalized_query", "hashtag", "track_id", "location_pk"):
    value = result.get(key)
    if isinstance(value, str) and value.strip():
      return value.strip()
  for key in ("profile", "reel", "media"):
    value = result.get(key)
    if not isinstance(value, dict):
      continue
    for nested_key in ("username", "shortcode", "url"):
      nested = value.get(nested_key)
      if isinstance(nested, str) and nested.strip():
        return nested.strip()
  return default or _collection_name(result)


class InstagramOps:
  def __init__(self, settings: Settings | None = None) -> None:
    self.settings = settings or Settings.load()
    self.hiker = HikerApiClient(self.settings)
    self.agent = OpenRouterAgent(self.settings)

  def _state(self) -> SessionState:
    return SessionState(current_model=self.settings.openrouter_chat_model)

  def search_instagram(
    self,
    *,
    query: str,
    limit: int | None = None,
    media_only: bool = False,
    today_only: bool = False,
    days_back: int | None = None,
    query_variants: list[str] | None = None,
    use_llm_expansion: bool = True,
  ) -> dict[str, Any]:
    state = self._state()
    return _tool_search_instagram(
      query=query,
      limit=max(1, min(limit, MAX_SEARCH_RESULTS)) if isinstance(limit, int) else None,
      media_only=media_only,
      today_only=today_only,
      days_back=max(1, min(days_back, MAX_DAYS_BACK)) if isinstance(days_back, int) else None,
      query_variants=query_variants,
      state=state,
      hiker=self.hiker,
      agent=self.agent if self.agent.enabled and use_llm_expansion else None,
    )

  def get_profile_stats(self, *, target: str) -> dict[str, Any]:
    return _tool_get_profile_stats(target=target, state=self._state(), hiker=self.hiker)

  def get_reel_stats(self, *, media_url: str) -> dict[str, Any]:
    return _tool_get_reel_stats(reel_url=media_url, state=self._state(), hiker=self.hiker)

  def get_recent_reels(self, *, target: str, limit: int = 12) -> dict[str, Any]:
    return _tool_get_recent_reels(
      target=target,
      limit=max(1, min(limit, MAX_PROFILE_COLLECTION_ITEMS)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_reels(
    self,
    *,
    target: str,
    limit: int = 12,
    days_back: int | None = None,
  ) -> dict[str, Any]:
    return _tool_get_profile_reels(
      target=target,
      limit=max(1, min(limit, MAX_PROFILE_COLLECTION_ITEMS)),
      days_back=max(1, min(days_back, MAX_DAYS_BACK)) if isinstance(days_back, int) else None,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_reels_page(
    self,
    *,
    target: str,
    page_id: str | None = None,
    page_size: int = MAX_PROFILE_COLLECTION_PAGE_SIZE,
    days_back: int | None = None,
  ) -> dict[str, Any]:
    return _tool_get_profile_reels_page(
      target=target,
      page_id=page_id,
      page_size=max(1, min(page_size, MAX_PROFILE_COLLECTION_PAGE_SIZE)),
      days_back=max(1, min(days_back, MAX_DAYS_BACK)) if isinstance(days_back, int) else None,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_publications(
    self,
    *,
    target: str,
    limit: int = 12,
    days_back: int | None = None,
    publication_type: str = "all",
  ) -> dict[str, Any]:
    return _tool_get_profile_publications(
      target=target,
      limit=max(1, min(limit, MAX_PROFILE_COLLECTION_ITEMS)),
      days_back=max(1, min(days_back, MAX_DAYS_BACK)) if isinstance(days_back, int) else None,
      publication_type=publication_type,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_publications_page(
    self,
    *,
    target: str,
    page_id: str | None = None,
    page_size: int = MAX_PROFILE_COLLECTION_PAGE_SIZE,
    days_back: int | None = None,
    publication_type: str = "all",
  ) -> dict[str, Any]:
    return _tool_get_profile_publications_page(
      target=target,
      page_id=page_id,
      page_size=max(1, min(page_size, MAX_PROFILE_COLLECTION_PAGE_SIZE)),
      days_back=max(1, min(days_back, MAX_DAYS_BACK)) if isinstance(days_back, int) else None,
      publication_type=publication_type,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_followers_page(
    self,
    *,
    target: str,
    limit: int = 25,
    page_id: str | None = None,
  ) -> dict[str, Any]:
    return _tool_get_followers_page(
      target=target,
      limit=max(1, min(limit, 50)),
      page_id=page_id,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_following_page(
    self,
    *,
    target: str,
    limit: int = 25,
    page_id: str | None = None,
  ) -> dict[str, Any]:
    return _tool_get_following_page(
      target=target,
      limit=max(1, min(limit, 50)),
      page_id=page_id,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_top_followers(
    self,
    *,
    target: str,
    sample_size: int = 5,
    top_n: int = 5,
    max_pages: int = 1,
  ) -> dict[str, Any]:
    return _tool_get_top_followers(
      target=target,
      sample_size=max(5, min(sample_size, 20)),
      top_n=max(1, min(top_n, 10)),
      max_pages=max(1, min(max_pages, 2)),
      state=self._state(),
      hiker=self.hiker,
    )

  def search_profile_followers(
    self,
    *,
    target: str,
    query: str,
    force: bool | None = None,
  ) -> dict[str, Any]:
    return _tool_search_profile_followers(
      target=target,
      query=query,
      force=force,
      state=self._state(),
      hiker=self.hiker,
    )

  def search_profile_following(
    self,
    *,
    target: str,
    query: str,
    force: bool | None = None,
  ) -> dict[str, Any]:
    return _tool_search_profile_following(
      target=target,
      query=query,
      force=force,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_media_comments(self, *, media_url: str, limit: int = 20) -> dict[str, Any]:
    return _tool_get_media_comments(
      media_url=media_url,
      limit=max(1, min(limit, MAX_MEDIA_COMMENTS)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_media_comments_page(
    self,
    *,
    media_url: str,
    page_id: str | None = None,
    page_size: int = 15,
  ) -> dict[str, Any]:
    return _tool_get_media_comments_page(
      media_url=media_url,
      page_id=page_id,
      page_size=max(1, min(page_size, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_comment_replies(
    self,
    *,
    comment_id: str,
    media_url: str,
    page_id: str | None = None,
  ) -> dict[str, Any]:
    return _tool_get_comment_replies(
      comment_id=comment_id,
      media_url=media_url,
      page_id=page_id,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_comment_likers(
    self,
    *,
    comment_id: str,
    media_id: str | None = None,
    page_id: str | None = None,
    limit: int = 20,
  ) -> dict[str, Any]:
    return _tool_get_comment_likers(
      comment_id=comment_id,
      media_id=media_id,
      page_id=page_id,
      limit=max(1, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_media_usertags(self, *, media_url: str) -> dict[str, Any]:
    return _tool_get_media_usertags(
      media_url=media_url,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_media_insight(self, *, media_url: str) -> dict[str, Any]:
    return _tool_get_media_insight(
      media_url=media_url,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_stories(self, *, target: str, limit: int = 0) -> dict[str, Any]:
    return _tool_get_profile_stories(
      target=target,
      limit=max(0, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_highlights(self, *, target: str, limit: int = 0) -> dict[str, Any]:
    return _tool_get_profile_highlights(
      target=target,
      limit=max(0, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_pinned_publications(self, *, target: str, limit: int = 12) -> dict[str, Any]:
    return _tool_get_profile_pinned_publications(
      target=target,
      limit=max(1, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_tagged_publications(self, *, target: str, limit: int = 12) -> dict[str, Any]:
    return _tool_get_profile_tagged_publications(
      target=target,
      limit=max(1, min(limit, MAX_PROFILE_COLLECTION_ITEMS)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_tagged_publications_page(
    self,
    *,
    target: str,
    page_id: str | None = None,
    page_size: int = MAX_PROFILE_COLLECTION_PAGE_SIZE,
  ) -> dict[str, Any]:
    return _tool_get_profile_tagged_publications_page(
      target=target,
      page_id=page_id,
      page_size=max(1, min(page_size, MAX_PROFILE_COLLECTION_PAGE_SIZE)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_media_likers(self, *, media_url: str, limit: int = 20) -> dict[str, Any]:
    return _tool_get_media_likers(
      media_url=media_url,
      limit=max(1, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_system_balance(self) -> dict[str, Any]:
    return _tool_get_system_balance(state=self._state(), hiker=self.hiker)

  def get_hashtag_info(self, *, name: str) -> dict[str, Any]:
    return _tool_get_hashtag_info(name=name, state=self._state(), hiker=self.hiker)

  def get_hashtag_reels(self, *, name: str, limit: int = 12) -> dict[str, Any]:
    return _tool_get_hashtag_reels(
      name=name,
      limit=max(1, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def search_places(
    self,
    *,
    query: str,
    lat: float | None = None,
    lng: float | None = None,
    limit: int = 20,
  ) -> dict[str, Any]:
    return _tool_search_places(
      query=query,
      lat=lat,
      lng=lng,
      limit=max(1, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_location_recent_media(self, *, location_pk: int, limit: int = 12) -> dict[str, Any]:
    return _tool_get_location_recent_media(
      location_pk=location_pk,
      limit=max(1, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def search_music(self, *, query: str, limit: int = 10) -> dict[str, Any]:
    return _tool_search_music(
      query=query,
      limit=max(1, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_track_media(
    self,
    *,
    track_id: str,
    page_id: str | None = None,
    limit: int = 12,
    stream: bool = False,
  ) -> dict[str, Any]:
    return _tool_get_track_media(
      track_id=track_id,
      page_id=page_id,
      limit=max(1, min(limit, 50)),
      stream=stream,
      state=self._state(),
      hiker=self.hiker,
    )

  def get_profile_suggestions(
    self,
    *,
    target: str,
    expand_suggestion: bool = False,
    limit: int = 20,
  ) -> dict[str, Any]:
    return _tool_get_profile_suggestions(
      target=target,
      expand_suggestion=expand_suggestion,
      limit=max(1, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def rank_media_likers_by_followers(
    self,
    *,
    media_urls: list[str],
    top_n: int = 100,
  ) -> dict[str, Any]:
    return _tool_rank_media_likers_by_followers(
      media_urls=media_urls,
      top_n=max(1, min(top_n, 100)),
      state=self._state(),
      hiker=self.hiker,
    )

  def download_media_content(self, *, media_url: str) -> dict[str, Any]:
    return _tool_download_media_content(media_url=media_url, state=self._state(), hiker=self.hiker)

  def download_media_audio(self, *, media_url: str) -> dict[str, Any]:
    return _tool_download_media_audio(media_url=media_url, state=self._state(), hiker=self.hiker)

  def download_profile_stories(self, *, target: str, limit: int = 0) -> dict[str, Any]:
    return _tool_download_profile_stories(
      target=target,
      limit=max(0, min(limit, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def download_profile_highlights(
    self,
    *,
    target: str,
    title_filter: str | None = None,
    limit_highlights: int = 0,
  ) -> dict[str, Any]:
    return _tool_download_profile_highlights(
      target=target,
      title_filter=title_filter,
      limit_highlights=max(0, min(limit_highlights, 50)),
      state=self._state(),
      hiker=self.hiker,
    )

  def get_last_reel_metric(self, *, target: str, metric: str) -> dict[str, Any]:
    return _tool_get_last_reel_metric(
      target=target,
      metric=metric,
      state=self._state(),
      hiker=self.hiker,
    )

  @staticmethod
  def collection_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return _collection_rows(result)

  @staticmethod
  def export_collection(
    *,
    result: dict[str, Any],
    fmt: str,
    filename_hint: str | None = None,
    output_dir: Path | None = None,
  ) -> dict[str, Any]:
    fmt_text = fmt.strip().lower()
    if fmt_text not in {"csv", "json"}:
      return {"ok": False, "error": "invalid_format", "message": "Use csv or json."}

    rows = _collection_rows(result)
    safe_rows = [
      {str(key): _json_safe_value(value) for key, value in row.items()}
      for row in rows
      if isinstance(row, dict)
    ]
    metadata = {
      key: _json_safe_value(value)
      for key, value in result.items()
      if key not in {
        "rows",
        "items",
        "reels",
        "publications",
        "followers",
        "following",
        "comments",
        "replies",
        "stories",
        "highlights",
        "likers",
        "profiles",
        "tracks",
        "tags",
      }
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = output_dir or _default_output_dir()
    root.mkdir(parents=True, exist_ok=True)
    hint = filename_hint or _collection_filename_hint(result)
    slug = _slugify(hint, default="export")
    output_path = root / f"{slug}_{timestamp}.{fmt_text}"

    if fmt_text == "csv":
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
            "collection_name": _collection_name(result),
            "metadata": metadata,
            "rows": safe_rows,
          },
          ensure_ascii=False,
          indent=2,
        ),
        encoding="utf-8",
      )

    return {
      "ok": True,
      "format": fmt_text,
      "path": str(output_path),
      "row_count": len(safe_rows),
      "collection_name": _collection_name(result),
      "filename_hint": hint,
    }

  @staticmethod
  def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    summary = {
      "ok": bool(result.get("ok", True)),
      "collection_name": _collection_name(result),
      "filename_hint": _collection_filename_hint(result),
      "row_count": len(_collection_rows(result)),
    }
    if "api_budget" in result:
      summary["api_budget"] = _json_safe_value(result.get("api_budget"))
    if "count" in result:
      summary["count"] = result.get("count")
    if "target_username" in result:
      summary["target_username"] = result.get("target_username")
    if "username" in result:
      summary["username"] = result.get("username")
    return summary
