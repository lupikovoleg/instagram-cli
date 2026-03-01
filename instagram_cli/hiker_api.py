from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from instagram_cli.config import Settings


class HikerApiError(RuntimeError):
  """Raised for HikerAPI related errors."""


def _as_int(value: Any) -> int:
  try:
    return int(float(value))
  except (TypeError, ValueError):
    return 0


def _as_str(value: Any) -> str | None:
  if isinstance(value, str):
    stripped = value.strip()
    return stripped or None
  return None


def _timestamp_from_any(value: Any) -> float | None:
  if value is None:
    return None
  if isinstance(value, (int, float)):
    ts = float(value)
    if ts > 1_000_000_000_000:
      ts /= 1000.0
    return ts
  if isinstance(value, str):
    stripped = value.strip()
    if not stripped:
      return None
    try:
      ts = float(stripped)
      if ts > 1_000_000_000_000:
        ts /= 1000.0
      return ts
    except ValueError:
      pass
    try:
      dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
      return dt.timestamp()
    except ValueError:
      return None
  return None


def _format_datetime(ts: float | None) -> tuple[str | None, str | None]:
  if ts is None:
    return None, None
  dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
  local_tz = datetime.now().astimezone().tzinfo
  dt_local = dt_utc.astimezone(local_tz) if local_tz is not None else dt_utc
  return (
    dt_utc.isoformat(timespec="seconds"),
    dt_local.isoformat(timespec="seconds"),
  )


def _calculate_virality(views: int, likes: int, comments: int, saves: int) -> dict[str, Any]:
  if views < 1000:
    return {
      "viral_index": 0.0,
      "viral_status": "unknown",
      "viral_label": "insufficient_data",
      "virality_engagement_raw": 0,
    }

  weighted_engagement_raw = likes + (3 * comments) + (4 * saves)
  viral_index = round((100.0 * weighted_engagement_raw) / max(views, 1), 2)

  if viral_index >= 10:
    status = "viral"
  elif viral_index >= 6:
    status = "strong"
  elif viral_index >= 3:
    status = "normal"
  elif viral_index >= 1:
    status = "weak"
  else:
    status = "non_viral"

  return {
    "viral_index": viral_index,
    "viral_status": status,
    "viral_label": status,
    "virality_engagement_raw": weighted_engagement_raw,
  }


def _normalize_reel_payload(media: dict[str, Any], *, reel_url: str | None = None) -> dict[str, Any]:
  product_type = _as_str(media.get("product_type"))

  views = _as_int(
    media.get("play_count")
    or media.get("video_view_count")
    or media.get("view_count")
    or media.get("content_views_count"),
  )
  likes = _as_int(media.get("like_count") or media.get("likes"))
  comments = _as_int(media.get("comment_count") or media.get("comments"))
  saves = _as_int(
    media.get("save_count")
    or media.get("saved_count")
    or media.get("saves_count")
    or media.get("bookmark_count"),
  )
  engagement_raw = likes + comments + saves
  engagement_rate = round((engagement_raw / views), 4) if views > 0 else 0.0

  owner = media.get("user") if isinstance(media.get("user"), dict) else {}
  if not owner:
    owner = media.get("owner") if isinstance(media.get("owner"), dict) else {}
  username = _as_str(owner.get("username")) or _as_str(media.get("username"))

  caption = None
  if isinstance(media.get("caption"), dict):
    caption = _as_str(media.get("caption", {}).get("text"))
  caption = caption or _as_str(media.get("caption_text")) or _as_str(media.get("title"))

  timestamp = _timestamp_from_any(
    media.get("taken_at")
    or media.get("taken_at_ts")
    or media.get("created_time")
    or media.get("timestamp"),
  )
  published_at_utc, published_at_local = _format_datetime(timestamp)
  shortcode = _as_str(media.get("code")) or (extract_reel_shortcode(reel_url or "") if reel_url else None)
  url = reel_url or (f"https://www.instagram.com/reel/{shortcode}/" if shortcode else None)
  virality = _calculate_virality(views, likes, comments, saves)

  return {
    "entity_type": "reel",
    "url": url,
    "shortcode": shortcode,
    "username": username,
    "media_type": media.get("media_type"),
    "product_type": product_type,
    "caption": caption,
    "published_at_utc": published_at_utc,
    "published_at_local": published_at_local,
    "taken_at_ts": int(timestamp) if timestamp is not None else None,
    "views": views,
    "likes": likes,
    "comments": comments,
    "saves": saves,
    "engagement_raw": engagement_raw,
    "engagement_rate": engagement_rate,
    "viral_index": virality["viral_index"],
    "viral_status": virality["viral_status"],
    "viral_label": virality["viral_label"],
    "virality_engagement_raw": virality["virality_engagement_raw"],
    "raw": media,
  }


def _normalize_media_comment_payload(comment: dict[str, Any]) -> dict[str, Any]:
  user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
  timestamp = _timestamp_from_any(
    comment.get("created_at_utc")
    or comment.get("created_at")
    or comment.get("created_at_ts"),
  )
  created_at_utc, created_at_local = _format_datetime(timestamp)
  comment_id = _as_str(comment.get("pk") or comment.get("id"))
  user_id = _as_str(user.get("pk") or user.get("id"))

  return {
    "entity_type": "media_comment",
    "comment_id": comment_id,
    "text": _as_str(comment.get("text")),
    "like_count": _as_int(comment.get("comment_like_count") or comment.get("like_count")),
    "created_at_utc": created_at_utc,
    "created_at_local": created_at_local,
    "user_id": user_id,
    "username": _as_str(user.get("username")),
    "full_name": _as_str(user.get("full_name")),
    "is_private": bool(user.get("is_private")),
    "is_verified": bool(user.get("is_verified")),
    "parent_comment_id": _as_str(comment.get("parent_comment_id")),
    "raw": comment,
  }


def _normalize_topsearch_item(item: dict[str, Any]) -> dict[str, Any]:
  typename = _as_str(item.get("__typename"))
  username = _as_str(item.get("username"))
  full_name = _as_str(item.get("full_name"))
  shortcode = _as_str(item.get("code"))
  owner = item.get("user") if isinstance(item.get("user"), dict) else {}
  owner_username = _as_str(owner.get("username"))
  thumbnail_url = (
    _as_str(item.get("thumbnail_url"))
    or _as_str(item.get("profile_pic_url"))
    or _best_image_url(item.get("image_versions"))
  )

  result_type = "unknown"
  if typename == "XDTUserDict" or username:
    result_type = "profile"
  elif typename == "XDTMediaDict" or shortcode:
    result_type = "media"

  media_url = None
  if shortcode:
    media_url = f"https://www.instagram.com/reel/{shortcode}/"

  return {
    "entity_type": "search_result",
    "result_type": result_type,
    "typename": typename,
    "username": username or owner_username,
    "full_name": full_name,
    "is_private": bool(item.get("is_private")),
    "is_verified": bool(item.get("is_verified")),
    "profile_pic_url": _as_str(item.get("profile_pic_url")),
    "thumbnail_url": thumbnail_url,
    "shortcode": shortcode,
    "media_url": media_url,
    "caption": _as_str(item.get("caption_text")) or _as_str(item.get("title")),
    "search_subtitle": _as_str(item.get("search_subtitle")),
    "search_secondary_subtitle": _as_str(item.get("search_secondary_subtitle")),
    "search_serp_type": item.get("search_serp_type"),
    "id": _as_str(item.get("id") or item.get("pk") or item.get("strong_id__")),
    "raw": item,
  }


def _best_image_url(candidates: Any) -> str | None:
  if not isinstance(candidates, list):
    return None
  best_url: str | None = None
  best_width = -1
  for item in candidates:
    if not isinstance(item, dict):
      continue
    url = _as_str(item.get("url"))
    if not url:
      continue
    width = _as_int(item.get("width"))
    if width >= best_width:
      best_width = width
      best_url = url
  return best_url


def _guess_extension_from_url(url: str, *, default: str) -> str:
  parsed = urlparse(url)
  path = parsed.path or ""
  suffix = Path(path).suffix.lower()
  if suffix in {".mp4", ".jpg", ".jpeg", ".png", ".webp"}:
    return suffix
  return default


def _best_video_url(candidates: Any) -> str | None:
  if not isinstance(candidates, list):
    return None
  best_url: str | None = None
  best_height = -1
  for item in candidates:
    if not isinstance(item, dict):
      continue
    url = _as_str(item.get("url"))
    if not url:
      continue
    height = _as_int(item.get("height"))
    if height >= best_height:
      best_height = height
      best_url = url
  return best_url


def _nested_get(data: Any, *path: str) -> Any:
  current = data
  for key in path:
    if not isinstance(current, dict):
      return None
    current = current.get(key)
  return current


_REEL_PATTERNS = [
  r"instagram\.com/reel/([A-Za-z0-9_-]+)",
  r"instagram\.com/p/([A-Za-z0-9_-]+)",
  r"instagram\.com/tv/([A-Za-z0-9_-]+)",
]

_RESERVED_PROFILE_SEGMENTS = {"reel", "reels", "p", "tv", "stories", "explore", "accounts", "developer"}


def extract_reel_shortcode(target: str) -> str | None:
  for pattern in _REEL_PATTERNS:
    match = re.search(pattern, target)
    if match:
      return match.group(1)
  return None


def extract_profile_username(target: str) -> str | None:
  target = target.strip()
  if not target:
    return None

  if target.startswith("@"):
    candidate = target[1:]
    return candidate if re.fullmatch(r"[A-Za-z0-9._]+", candidate) else None

  if "instagram.com" not in target and re.fullmatch(r"[A-Za-z0-9._]+", target):
    return target

  if "instagram.com" not in target:
    return None

  parsed = urlparse(target)
  parts = [part for part in parsed.path.split("/") if part]
  if not parts:
    return None

  if parts[0] == "stories" and len(parts) >= 2:
    return parts[1]

  username = parts[0]
  if username in _RESERVED_PROFILE_SEGMENTS:
    return None
  if not re.fullmatch(r"[A-Za-z0-9._]+", username):
    return None
  return username


class HikerApiClient:
  def __init__(self, settings: Settings) -> None:
    self._settings = settings
    self._access_key = settings.hiker_access_key
    self._base_url = settings.hikerapi_base_url.rstrip("/")
    self._session = requests.Session()
    self._user_cache_by_username: dict[str, dict[str, Any]] = {}
    self._user_cache_by_id: dict[str, dict[str, Any]] = {}
    self._followers_page_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    self._media_info_cache: dict[str, dict[str, Any]] = {}
    self._media_likers_cache: dict[str, dict[str, Any]] = {}
    self._media_comments_cache: dict[str, dict[str, Any]] = {}
    self._clips_chunk_cache: dict[tuple[str, str, int], tuple[list[dict[str, Any]], str | None]] = {}
    self._stories_cache: dict[str, list[dict[str, Any]]] = {}
    self._highlights_cache: dict[str, list[dict[str, Any]]] = {}
    self._highlight_detail_cache: dict[str, dict[str, Any]] = {}
    self._topsearch_cache: dict[tuple[str, str, bool], dict[str, Any]] = {}

  @property
  def enabled(self) -> bool:
    return bool(self._access_key)

  def _requests_proxies(self) -> dict[str, str] | None:
    if self._settings.debug:
      return None
    proxy = self._settings.proxy_socks5_url or self._settings.proxy_url
    if not proxy:
      return None
    if proxy.startswith(("socks4://", "socks5://")):
      try:
        import socks  # type: ignore # noqa: F401
      except ImportError:
        fallback_http = self._settings.proxy_url
        if fallback_http and fallback_http.startswith("http://"):
          proxy = fallback_http
        else:
          return None
    return {"http": proxy, "https": proxy}

  def _request(self, path: str, params: dict[str, Any]) -> Any:
    if not self._access_key:
      raise HikerApiError("HIKERAPI_TOKEN or HIKERAPI_KEY is missing.")

    merged_params = dict(params)
    merged_params["access_key"] = self._access_key
    url = f"{self._base_url}{path}"

    try:
      response = self._session.get(
        url,
        params=merged_params,
        timeout=25,
        proxies=self._requests_proxies(),
      )
    except requests.RequestException as exc:
      raise HikerApiError(f"HikerAPI request failed: {exc}") from exc
    if response.status_code != 200:
      detail = None
      try:
        payload = response.json()
        if isinstance(payload, dict):
          detail = payload.get("detail") or payload.get("message")
      except Exception:
        detail = response.text[:200]
      suffix = f" ({detail})" if detail else ""
      raise HikerApiError(f"HikerAPI HTTP {response.status_code}{suffix}")

    try:
      return response.json()
    except Exception as exc:  # pragma: no cover
      raise HikerApiError(f"HikerAPI returned non-JSON response: {exc}") from exc

  @staticmethod
  def _username_cache_key(username: str) -> str:
    return username.strip().lstrip("@").lower()

  @staticmethod
  def _normalize_profile_user(user: dict[str, Any], *, username_input: str | None = None) -> dict[str, Any]:
    user_id = user.get("pk") or user.get("id")
    return {
      "entity_type": "profile",
      "input": username_input,
      "username": _as_str(user.get("username")) or username_input,
      "user_id": str(user_id) if user_id is not None else None,
      "full_name": _as_str(user.get("full_name")),
      "is_private": bool(user.get("is_private")),
      "is_verified": bool(user.get("is_verified")),
      "followers": _as_int(user.get("follower_count") or user.get("followers")),
      "following": _as_int(user.get("following_count") or user.get("following")),
      "posts": _as_int(user.get("media_count") or user.get("posts")),
      "biography": _as_str(user.get("biography")),
      "external_url": _as_str(user.get("external_url")),
      "profile_pic_url": _as_str(user.get("profile_pic_url")),
      "raw": user,
    }

  @staticmethod
  def _normalize_follower_preview(user: dict[str, Any], *, source: str) -> dict[str, Any]:
    user_id = user.get("pk") or user.get("id")
    reel = user.get("reel") if isinstance(user.get("reel"), dict) else None
    return {
      "entity_type": "follower_preview",
      "user_id": str(user_id) if user_id is not None else None,
      "username": _as_str(user.get("username")),
      "full_name": _as_str(user.get("full_name")),
      "is_private": bool(user.get("is_private")),
      "is_verified": bool(user.get("is_verified")),
      "profile_pic_url": _as_str(user.get("profile_pic_url")),
      "has_story_ring": reel is not None,
      "source_endpoint": source,
      "raw": user,
    }

  def _cache_user(self, user: dict[str, Any]) -> dict[str, Any]:
    username = _as_str(user.get("username"))
    user_id = user.get("pk") or user.get("id")
    if username:
      self._user_cache_by_username[self._username_cache_key(username)] = user
    if user_id is not None:
      self._user_cache_by_id[str(user_id)] = user
    return user

  def _get_user_by_id(self, user_id: str) -> dict[str, Any]:
    cache_key = str(user_id).strip()
    if not cache_key:
      raise HikerApiError("User id is required.")
    cached = self._user_cache_by_id.get(cache_key)
    if cached is not None:
      return cached

    primary_error: Exception | None = None
    try:
      user = self._request("/gql/user/web_profile_info", {"user_id": cache_key})
      if isinstance(user, dict) and user:
        return self._cache_user(user)
    except Exception as exc:  # pragma: no cover
      primary_error = exc

    user = self._request("/v1/user/by/id", {"id": cache_key})
    if not isinstance(user, dict):
      if primary_error is not None:
        raise HikerApiError(f"Unexpected user by id response after gql fallback: {primary_error}")
      raise HikerApiError("Unexpected HikerAPI response format for user by id.")
    return self._cache_user(user)

  def _get_user_by_username(self, username: str) -> dict[str, Any]:
    cache_key = self._username_cache_key(username)
    cached = self._user_cache_by_username.get(cache_key)
    if cached is not None:
      return cached

    user = self._request("/v1/user/by/username", {"username": username})
    if not isinstance(user, dict):
      raise HikerApiError("Unexpected HikerAPI response format for profile.")
    return self._cache_user(user)

  def _get_user_by_target(self, target: str) -> tuple[str, dict[str, Any]]:
    username = extract_profile_username(target)
    if not username:
      raise HikerApiError("Invalid Instagram profile URL or username.")
    user = self._get_user_by_username(username)
    return username, user

  @staticmethod
  def _extract_page_users(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, dict):
      raise HikerApiError("Unexpected HikerAPI response format for followers page.")

    response = payload.get("response")
    if not isinstance(response, dict):
      raise HikerApiError("Unexpected HikerAPI page payload format.")

    users = response.get("users")
    if not isinstance(users, list):
      users = []
    next_page_id = _as_str(payload.get("next_page_id")) or _as_str(response.get("next_max_id"))
    normalized_users = [item for item in users if isinstance(item, dict)]
    return normalized_users, next_page_id

  def reel_stats(self, reel_url: str) -> dict[str, Any]:
    shortcode = extract_reel_shortcode(reel_url)
    if not shortcode:
      raise HikerApiError("Invalid Instagram Reel URL.")

    media = self._request("/v1/media/by/code", {"code": shortcode})
    if not isinstance(media, dict):
      raise HikerApiError("Unexpected HikerAPI response format for reel.")
    return _normalize_reel_payload(media, reel_url=reel_url)

  def media_info(self, media_url: str) -> dict[str, Any]:
    shortcode = extract_reel_shortcode(media_url)
    if not shortcode:
      raise HikerApiError("Invalid Instagram media URL.")

    cached = self._media_info_cache.get(shortcode)
    if cached is not None:
      media = cached
    else:
      media = self._request("/v1/media/by/code", {"code": shortcode})
      if not isinstance(media, dict):
        raise HikerApiError("Unexpected HikerAPI response format for media.")
      self._media_info_cache[shortcode] = media

    owner = media.get("user") if isinstance(media.get("user"), dict) else {}
    numeric_id = _as_str(media.get("pk")) or _as_str(media.get("id"))
    composite_id = _as_str(media.get("id"))
    timestamp = _timestamp_from_any(
      media.get("taken_at")
      or media.get("taken_at_ts")
      or media.get("created_time")
      or media.get("timestamp"),
    )
    published_at_utc, published_at_local = _format_datetime(timestamp)
    return {
      "entity_type": "media",
      "url": media_url,
      "shortcode": _as_str(media.get("code")) or shortcode,
      "media_pk": numeric_id,
      "media_id": composite_id,
      "media_type": media.get("media_type"),
      "product_type": _as_str(media.get("product_type")),
      "username": _as_str(owner.get("username")),
      "owner_user_id": _as_str(owner.get("pk") or owner.get("id")),
      "published_at_utc": published_at_utc,
      "published_at_local": published_at_local,
      "like_count": _as_int(media.get("like_count")),
      "comment_count": _as_int(media.get("comment_count")),
      "view_count": _as_int(
        media.get("play_count")
        or media.get("view_count")
        or media.get("video_view_count"),
      ),
      "raw": media,
    }

  def media_likers(self, media_url: str) -> dict[str, Any]:
    media = self.media_info(media_url)
    media_pk = _as_str(media.get("media_pk"))
    if not media_pk:
      raise HikerApiError("Media has no numeric id for likers lookup.")

    cached = self._media_likers_cache.get(media_pk)
    if cached is not None:
      return cached

    likers = self._request("/v1/media/likers", {"id": media_pk})
    if not isinstance(likers, list):
      raise HikerApiError("Unexpected HikerAPI response format for media likers.")

    users: list[dict[str, Any]] = []
    for item in likers:
      if not isinstance(item, dict):
        continue
      user_id = _as_str(item.get("pk") or item.get("id"))
      username = _as_str(item.get("username"))
      if not user_id or not username:
        continue
      users.append(
        {
          "entity_type": "media_liker_preview",
          "user_id": user_id,
          "username": username,
          "full_name": _as_str(item.get("full_name")),
          "is_private": bool(item.get("is_private")),
          "is_verified": bool(item.get("is_verified")),
          "profile_pic_url": _as_str(item.get("profile_pic_url")),
          "raw": item,
        },
      )

    payload = {
      "entity_type": "media_likers",
      "media": media,
      "likers": users,
      "returned_count": len(users),
      "available_like_count": _as_int(media.get("like_count")),
      "is_capped": len(users) < _as_int(media.get("like_count")),
      "cap_note": (
        "HikerAPI media likers endpoint may return a capped list instead of all likes."
        if len(users) < _as_int(media.get("like_count")) else None
      ),
    }
    self._media_likers_cache[media_pk] = payload
    return payload

  def media_comments(self, media_url: str, *, limit: int = 20) -> dict[str, Any]:
    media = self.media_info(media_url)
    media_pk = _as_str(media.get("media_pk"))
    if not media_pk:
      raise HikerApiError("Media has no numeric id for comments lookup.")

    cached = self._media_comments_cache.get(media_pk)
    if cached is not None:
      comments_payload = cached
    else:
      raw_comments = self._request("/v1/media/comments", {"id": media_pk})
      if not isinstance(raw_comments, list):
        raise HikerApiError("Unexpected HikerAPI response format for media comments.")
      normalized_comments = [
        _normalize_media_comment_payload(item)
        for item in raw_comments
        if isinstance(item, dict)
      ]
      comments_payload = {
        "entity_type": "media_comments",
        "media": media,
        "comments": normalized_comments,
        "returned_count": len(normalized_comments),
        "available_comment_count": _as_int(media.get("comment_count")),
        "is_capped": len(normalized_comments) < _as_int(media.get("comment_count")),
        "cap_note": (
          "HikerAPI media comments endpoint may return a capped list instead of all comments."
          if len(normalized_comments) < _as_int(media.get("comment_count")) else None
        ),
      }
      self._media_comments_cache[media_pk] = comments_payload

    requested_limit = max(1, min(limit, 50))
    comments = comments_payload.get("comments") if isinstance(comments_payload.get("comments"), list) else []
    return {
      **comments_payload,
      "comments": comments[:requested_limit],
      "returned_count": min(len(comments), requested_limit),
    }

  @staticmethod
  def _normalize_story_payload(story: dict[str, Any]) -> dict[str, Any]:
    timestamp = _timestamp_from_any(story.get("taken_at"))
    published_at_utc, published_at_local = _format_datetime(timestamp)
    thumbnail_url = _as_str(story.get("thumbnail_url"))
    video_url = _as_str(story.get("video_url"))
    image_url = thumbnail_url
    return {
      "entity_type": "story",
      "story_id": _as_str(story.get("pk") or story.get("id")),
      "id": _as_str(story.get("id")),
      "code": _as_str(story.get("code")),
      "media_type": story.get("media_type"),
      "product_type": _as_str(story.get("product_type")),
      "username": _as_str((story.get("user") or {}).get("username")) if isinstance(story.get("user"), dict) else None,
      "published_at_utc": published_at_utc,
      "published_at_local": published_at_local,
      "video_url": video_url,
      "image_url": image_url,
      "thumbnail_url": thumbnail_url,
      "is_video": bool(video_url),
      "raw": story,
    }

  @staticmethod
  def _normalize_highlight_payload(highlight: dict[str, Any]) -> dict[str, Any]:
    user = highlight.get("user") if isinstance(highlight.get("user"), dict) else {}
    timestamp = _timestamp_from_any(highlight.get("created_at"))
    created_at_utc, created_at_local = _format_datetime(timestamp)
    return {
      "entity_type": "highlight",
      "highlight_id": _as_str(highlight.get("pk") or highlight.get("id")),
      "id": _as_str(highlight.get("id")),
      "title": _as_str(highlight.get("title")),
      "username": _as_str(user.get("username")),
      "media_count": _as_int(highlight.get("media_count")),
      "created_at_utc": created_at_utc,
      "created_at_local": created_at_local,
      "is_pinned_highlight": bool(highlight.get("is_pinned_highlight")),
      "raw": highlight,
    }

  @staticmethod
  def _extract_media_assets(media: dict[str, Any]) -> list[dict[str, Any]]:
    shortcode = _as_str(media.get("code"))
    assets: list[dict[str, Any]] = []

    def append_asset(
      *,
      asset_url: str | None,
      asset_kind: str,
      asset_index: int,
      media_type: Any,
      source_label: str,
    ) -> None:
      if not asset_url:
        return
      default_ext = ".mp4" if asset_kind == "video" else ".jpg"
      assets.append(
        {
          "asset_url": asset_url,
          "asset_kind": asset_kind,
          "asset_index": asset_index,
          "media_type": media_type,
          "shortcode": shortcode,
          "source_label": source_label,
          "extension": _guess_extension_from_url(asset_url, default=default_ext),
        },
      )

    direct_video = _as_str(media.get("video_url")) or _best_video_url(media.get("video_versions"))
    direct_image = _best_image_url(media.get("image_versions")) or _as_str(media.get("thumbnail_url"))
    resources = media.get("resources") if isinstance(media.get("resources"), list) else []

    if resources:
      for index, resource in enumerate(resources, start=1):
        if not isinstance(resource, dict):
          continue
        video_url = _as_str(resource.get("video_url")) or _best_video_url(resource.get("video_versions"))
        image_url = _best_image_url(resource.get("image_versions")) or _as_str(resource.get("thumbnail_url"))
        append_asset(
          asset_url=video_url or image_url,
          asset_kind="video" if video_url else "image",
          asset_index=index,
          media_type=resource.get("media_type"),
          source_label="resource",
        )
    else:
      append_asset(
        asset_url=direct_video or direct_image,
        asset_kind="video" if direct_video else "image",
        asset_index=1,
        media_type=media.get("media_type"),
        source_label="media",
      )

    return assets

  def _download_binary(self, url: str, destination: Path) -> None:
    try:
      response = self._session.get(
        url,
        stream=True,
        timeout=60,
        proxies=self._requests_proxies(),
      )
      response.raise_for_status()
    except requests.RequestException as exc:
      raise HikerApiError(f"Content download failed: {exc}") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
      for chunk in response.iter_content(chunk_size=64 * 1024):
        if chunk:
          handle.write(chunk)

  def download_file(self, url: str, destination: Path) -> None:
    self._download_binary(url, destination)

  def enrich_users_by_id(
    self,
    user_ids: list[str],
    *,
    max_workers: int = 8,
    retry_count: int = 2,
    retry_delay_seconds: float = 0.75,
    on_progress: Callable[[int, int], None] | None = None,
  ) -> list[dict[str, Any]]:
    normalized_ids: list[str] = []
    seen_ids: set[str] = set()
    for raw_user_id in user_ids:
      user_id = str(raw_user_id).strip()
      if not user_id or user_id in seen_ids:
        continue
      seen_ids.add(user_id)
      normalized_ids.append(user_id)

    def fetch(user_id: str) -> dict[str, Any]:
      last_error: Exception | None = None
      for attempt in range(retry_count + 1):
        try:
          return self._get_user_by_id(user_id)
        except Exception as exc:  # pragma: no cover
          last_error = exc
          if attempt >= retry_count:
            raise
          time.sleep(retry_delay_seconds * (attempt + 1))
      raise HikerApiError(f"Could not fetch user {user_id}: {last_error}")

    enriched: list[dict[str, Any]] = []
    if not normalized_ids:
      return enriched

    worker_count = min(max_workers, max(1, len(normalized_ids)))
    completed = 0
    total = len(normalized_ids)
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
      future_map = {pool.submit(fetch, user_id): user_id for user_id in normalized_ids}
      for future in as_completed(future_map):
        user = future.result()
        enriched.append(self._normalize_profile_user(user, username_input=_as_str(user.get("username"))))
        completed += 1
        if on_progress is not None:
          on_progress(completed, total)
    return enriched

  def profile_reels(
    self,
    target: str,
    *,
    limit: int = 12,
    days_back: int | None = None,
    max_pages: int = 3,
    page_size: int = 12,
  ) -> dict[str, Any]:
    username, user = self._get_user_by_target(target)

    user_id = user.get("pk") or user.get("id")
    if user_id is None:
      raise HikerApiError("Profile has no user_id in HikerAPI response.")

    requested_limit = max(1, min(limit, 20))
    requested_page_size = max(1, min(page_size, 24))
    requested_max_pages = max(1, min(max_pages, 5))

    cutoff_ts: int | None = None
    if days_back is not None:
      requested_days_back = max(1, min(days_back, 30))
      cutoff_ts = int(time.time() - (requested_days_back * 86400))
    else:
      requested_days_back = None

    page_cursor: str | None = None
    pages_used = 0
    scanned_count = 0
    reels: list[dict[str, Any]] = []
    seen_shortcodes: set[str] = set()

    while pages_used < requested_max_pages and len(reels) < requested_limit:
      cache_key = (str(user_id), page_cursor or "", requested_page_size)
      cached_page = self._clips_chunk_cache.get(cache_key)
      if cached_page is None:
        raw_payload = self._request(
          "/v1/user/clips/chunk",
          {
            "user_id": str(user_id),
            "end_cursor": page_cursor or None,
            "page_size": requested_page_size,
          },
        )
        if not isinstance(raw_payload, list) or len(raw_payload) != 2:
          raise HikerApiError("Unexpected HikerAPI response format for user clips chunk.")
        raw_items = raw_payload[0] if isinstance(raw_payload[0], list) else []
        raw_cursor = _as_str(raw_payload[1])
        cached_page = ([item for item in raw_items if isinstance(item, dict)], raw_cursor)
        self._clips_chunk_cache[cache_key] = cached_page

      page_items, next_cursor = cached_page
      pages_used += 1
      page_cursor = next_cursor
      stop_for_cutoff = False

      for item in page_items:
        normalized = _normalize_reel_payload(item)
        normalized["entity_type"] = "reel_preview"
        scanned_count += 1

        shortcode = _as_str(normalized.get("shortcode"))
        if shortcode and shortcode in seen_shortcodes:
          continue
        if shortcode:
          seen_shortcodes.add(shortcode)

        taken_at_ts = int(normalized.get("taken_at_ts") or 0)
        if cutoff_ts is not None and taken_at_ts and taken_at_ts < cutoff_ts:
          stop_for_cutoff = True
          continue

        reels.append(normalized)
        if len(reels) >= requested_limit:
          break

      if len(reels) >= requested_limit:
        break
      if stop_for_cutoff:
        break
      if not page_cursor:
        break

    reels.sort(key=lambda item: int(item.get("taken_at_ts") or 0), reverse=True)

    return {
      "entity_type": "profile_reels",
      "username": _as_str(user.get("username")) or username,
      "user_id": str(user_id),
      "profile": self._normalize_profile_user(user, username_input=username),
      "reels": reels[:requested_limit],
      "filters": {
        "limit": requested_limit,
        "days_back": requested_days_back,
      },
      "pages_used": pages_used,
      "scanned_reels": scanned_count,
      "next_page_id": page_cursor,
      "source_endpoint": "/v1/user/clips/chunk",
    }

  def recent_reels(self, target: str, limit: int = 12) -> dict[str, Any]:
    return self.profile_reels(target, limit=limit, max_pages=2)

  def top_media_likers_by_followers(
    self,
    media_urls: list[str],
    *,
    top_n: int = 100,
    max_workers: int = 8,
  ) -> dict[str, Any]:
    unique_urls: list[str] = []
    seen_urls: set[str] = set()
    for raw_url in media_urls:
      url = str(raw_url).strip()
      if not url or url in seen_urls:
        continue
      seen_urls.add(url)
      unique_urls.append(url)

    if not unique_urls:
      raise HikerApiError("At least one media URL is required.")

    source_media: list[dict[str, Any]] = []
    liker_map: dict[str, dict[str, Any]] = {}
    media_info_requests = 0
    liker_requests = 0

    for media_url in unique_urls:
      payload = self.media_likers(media_url)
      media_info_requests += 1
      liker_requests += 1
      media = payload.get("media") if isinstance(payload.get("media"), dict) else {}
      source_media.append(
        {
          "url": media.get("url"),
          "shortcode": media.get("shortcode"),
          "media_pk": media.get("media_pk"),
          "username": media.get("username"),
          "like_count": payload.get("available_like_count"),
          "returned_likers": payload.get("returned_count"),
          "is_capped": payload.get("is_capped"),
        },
      )

      likers = payload.get("likers") if isinstance(payload.get("likers"), list) else []
      for liker in likers:
        if not isinstance(liker, dict):
          continue
        user_id = _as_str(liker.get("user_id"))
        if not user_id:
          continue
        entry = liker_map.setdefault(
          user_id,
          {
            "user_id": user_id,
            "username": liker.get("username"),
            "full_name": liker.get("full_name"),
            "liked_shortcodes": [],
            "liked_urls": [],
            "liked_count": 0,
          },
        )
        shortcode = media.get("shortcode")
        url = media.get("url")
        if shortcode and shortcode not in entry["liked_shortcodes"]:
          entry["liked_shortcodes"].append(shortcode)
        if url and url not in entry["liked_urls"]:
          entry["liked_urls"].append(url)
        entry["liked_count"] = len(entry["liked_shortcodes"])

    likers = list(liker_map.values())
    enriched_users = self.enrich_users_by_id(
      [item["user_id"] for item in likers],
      max_workers=max(1, min(max_workers, 12)),
    )
    liker_by_id = {str(item["user_id"]): item for item in likers}

    rows: list[dict[str, Any]] = []
    for user in enriched_users:
      user_id = str(user.get("user_id") or "")
      liker = liker_by_id.get(user_id)
      if liker is None:
        continue
      rows.append(
        {
          "rank": 0,
          "user_id": user_id,
          "username": user.get("username"),
          "full_name": user.get("full_name"),
          "followers": int(user.get("followers") or 0),
          "following": int(user.get("following") or 0),
          "posts": int(user.get("posts") or 0),
          "is_verified": bool(user.get("is_verified")),
          "is_private": bool(user.get("is_private")),
          "liked_count": liker.get("liked_count", 0),
          "liked_shortcodes": liker.get("liked_shortcodes", []),
          "liked_urls": liker.get("liked_urls", []),
        },
      )

    rows.sort(
      key=lambda item: (
        int(item["followers"]),
        int(item["liked_count"]),
        int(item["is_verified"]),
        str(item["username"] or ""),
      ),
      reverse=True,
    )
    limited_rows = rows[:max(1, min(top_n, 100))]
    for index, row in enumerate(limited_rows, start=1):
      row["rank"] = index

    capped_media_count = sum(1 for item in source_media if item.get("is_capped"))
    limitations: list[str] = []
    if capped_media_count:
      limitations.append(
        f"{capped_media_count} media item(s) returned a capped likers list, so the ranking is limited to the available liker sample.",
      )

    return {
      "entity_type": "media_likers_ranked",
      "source_media": source_media,
      "unique_likers": len(likers),
      "enriched_profiles": len(enriched_users),
      "top_n": len(limited_rows),
      "rows": limited_rows,
      "limitations": limitations,
      "api_budget": {
        "media_info_requests": media_info_requests,
        "liker_requests": liker_requests,
        "profile_lookups": len(likers),
        "estimated_total_requests": media_info_requests + liker_requests + len(likers),
      },
    }

  def profile_stats(self, target: str) -> dict[str, Any]:
    username, user = self._get_user_by_target(target)

    user_id = user.get("pk") or user.get("id")
    stories_count: int | None = None
    stories_error: str | None = None
    if user_id:
      try:
        stories_payload = self._request("/v1/user/stories", {"user_id": str(user_id)})
        if isinstance(stories_payload, list):
          stories_count = len(stories_payload)
        elif isinstance(stories_payload, dict) and isinstance(stories_payload.get("items"), list):
          stories_count = len(stories_payload["items"])
        else:
          stories_count = 0
      except HikerApiError as exc:
        stories_error = str(exc)

    profile = self._normalize_profile_user(user, username_input=target)
    profile["stories_count"] = stories_count
    profile["has_stories"] = (stories_count or 0) > 0 if stories_count is not None else None
    profile["stories_error"] = stories_error
    return profile

  def profile_stories(self, target: str, *, limit: int = 0) -> dict[str, Any]:
    username, user = self._get_user_by_target(target)
    user_id = user.get("pk") or user.get("id")
    if user_id is None:
      raise HikerApiError("Profile has no user_id in HikerAPI response.")

    cache_key = str(user_id)
    raw_stories = self._stories_cache.get(cache_key)
    if raw_stories is None:
      raw_payload = self._request("/v1/user/stories", {"user_id": str(user_id), "amount": max(0, limit)})
      if not isinstance(raw_payload, list):
        raise HikerApiError("Unexpected HikerAPI response format for stories.")
      raw_stories = [item for item in raw_payload if isinstance(item, dict)]
      self._stories_cache[cache_key] = raw_stories

    normalized = [self._normalize_story_payload(item) for item in raw_stories]
    requested_limit = max(0, min(limit, 50))
    stories = normalized if requested_limit == 0 else normalized[:requested_limit]
    return {
      "entity_type": "profile_stories",
      "username": _as_str(user.get("username")) or username,
      "user_id": str(user_id),
      "profile": self._normalize_profile_user(user, username_input=username),
      "stories": stories,
      "count": len(stories),
      "available_count": len(normalized),
      "source_endpoint": "/v1/user/stories",
    }

  def profile_highlights(self, target: str, *, limit: int = 0) -> dict[str, Any]:
    username, user = self._get_user_by_target(target)
    user_id = user.get("pk") or user.get("id")
    if user_id is None:
      raise HikerApiError("Profile has no user_id in HikerAPI response.")

    cache_key = str(user_id)
    raw_highlights = self._highlights_cache.get(cache_key)
    if raw_highlights is None:
      raw_payload = self._request("/v1/user/highlights", {"user_id": str(user_id), "amount": max(0, limit)})
      if not isinstance(raw_payload, list):
        raise HikerApiError("Unexpected HikerAPI response format for highlights.")
      raw_highlights = [item for item in raw_payload if isinstance(item, dict)]
      self._highlights_cache[cache_key] = raw_highlights

    normalized = [self._normalize_highlight_payload(item) for item in raw_highlights]
    requested_limit = max(0, min(limit, 50))
    highlights = normalized if requested_limit == 0 else normalized[:requested_limit]
    return {
      "entity_type": "profile_highlights",
      "username": _as_str(user.get("username")) or username,
      "user_id": str(user_id),
      "profile": self._normalize_profile_user(user, username_input=username),
      "highlights": highlights,
      "count": len(highlights),
      "available_count": len(normalized),
      "source_endpoint": "/v1/user/highlights",
    }

  def topsearch(
    self,
    query: str,
    *,
    limit: int = 10,
    end_cursor: str | None = None,
    flat: bool = True,
  ) -> dict[str, Any]:
    query_text = query.strip()
    if not query_text:
      raise HikerApiError("Search query is required.")

    cursor_text = (end_cursor or "").strip()
    cache_key = (query_text.lower(), cursor_text, flat)
    cached = self._topsearch_cache.get(cache_key)
    if cached is None:
      payload = self._request(
        "/gql/topsearch",
        {
          "query": query_text,
          "end_cursor": cursor_text or None,
          "flat": flat,
        },
      )
      if not isinstance(payload, dict):
        raise HikerApiError("Unexpected HikerAPI response format for topsearch.")
      self._topsearch_cache[cache_key] = payload
    else:
      payload = cached

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    normalized = [_normalize_topsearch_item(item) for item in items if isinstance(item, dict)]
    requested_limit = max(1, min(limit, 50))
    return {
      "entity_type": "search_results",
      "query": query_text,
      "count": min(len(normalized), requested_limit),
      "available_count": len(normalized),
      "items": normalized[:requested_limit],
      "end_cursor": _as_str(payload.get("end_cursor")),
      "more_available": bool(payload.get("more_available")),
      "source_endpoint": "/gql/topsearch",
    }

  def highlight_by_id(self, highlight_id: str) -> dict[str, Any]:
    cache_key = str(highlight_id).strip()
    if not cache_key:
      raise HikerApiError("Highlight id is required.")

    cached = self._highlight_detail_cache.get(cache_key)
    if cached is not None:
      return cached

    raw_highlight = self._request("/v1/highlight/by/id", {"id": cache_key})
    if not isinstance(raw_highlight, dict):
      raise HikerApiError("Unexpected HikerAPI response format for highlight.")
    self._highlight_detail_cache[cache_key] = raw_highlight
    return raw_highlight

  def download_media_plan(self, media_url: str) -> dict[str, Any]:
    media = self.media_info(media_url)
    raw_media = media.get("raw") if isinstance(media.get("raw"), dict) else None
    if not raw_media:
      raise HikerApiError("Media payload is missing raw fields for download.")
    assets = self._extract_media_assets(raw_media)
    return {
      "entity_type": "download_plan",
      "download_kind": "media",
      "target_label": media.get("shortcode") or media.get("url"),
      "source_endpoint": "/v1/media/by/code",
      "media": media,
      "assets": assets,
    }

  def download_media_audio_plan(self, media_url: str) -> dict[str, Any]:
    media = self.media_info(media_url)
    raw_media = media.get("raw") if isinstance(media.get("raw"), dict) else None
    if not raw_media:
      raise HikerApiError("Media payload is missing raw fields for audio download.")

    clips_metadata = raw_media.get("clips_metadata") if isinstance(raw_media.get("clips_metadata"), dict) else {}
    original_sound_info = _nested_get(clips_metadata, "original_sound_info")
    music_info = _nested_get(clips_metadata, "music_info")
    music_asset_info = _nested_get(music_info, "music_asset_info")

    audio_url = (
      _as_str(_nested_get(original_sound_info, "progressive_download_url"))
      or _as_str(_nested_get(original_sound_info, "fast_start_progressive_download_url"))
      or _as_str(_nested_get(music_asset_info, "progressive_download_url"))
      or _as_str(_nested_get(music_asset_info, "fast_start_progressive_download_url"))
      or _as_str(_nested_get(music_asset_info, "preview_audio_url"))
    )
    if not audio_url:
      raise HikerApiError("No downloadable audio URL was found in the media payload.")

    title = (
      _as_str(_nested_get(music_asset_info, "title"))
      or _as_str(_nested_get(original_sound_info, "original_audio_title"))
      or _as_str(media.get("shortcode"))
      or "audio"
    )
    artist = (
      _as_str(_nested_get(music_asset_info, "display_artist"))
      or _as_str(_nested_get(music_asset_info, "artist_name"))
      or _as_str(media.get("username"))
    )

    return {
      "entity_type": "download_plan",
      "download_kind": "media_audio",
      "target_label": media.get("shortcode") or media.get("url"),
      "source_endpoint": "/v1/media/by/code",
      "media": media,
      "audio_track": {
        "title": title,
        "artist": artist,
        "audio_url": audio_url,
        "extension": _guess_extension_from_url(audio_url, default=".m4a"),
      },
      "assets": [
        {
          "asset_url": audio_url,
          "asset_kind": "audio",
          "asset_index": 1,
          "shortcode": media.get("shortcode"),
          "title": title,
          "artist": artist,
          "extension": _guess_extension_from_url(audio_url, default=".m4a"),
        },
      ],
    }

  def download_stories_plan(self, target: str, *, limit: int = 0) -> dict[str, Any]:
    payload = self.profile_stories(target, limit=limit)
    stories = payload.get("stories") if isinstance(payload.get("stories"), list) else []
    assets: list[dict[str, Any]] = []
    for index, story in enumerate(stories, start=1):
      if not isinstance(story, dict):
        continue
      asset_url = _as_str(story.get("video_url")) or _as_str(story.get("image_url")) or _as_str(story.get("thumbnail_url"))
      if not asset_url:
        continue
      assets.append(
        {
          "asset_url": asset_url,
          "asset_kind": "video" if story.get("is_video") else "image",
          "asset_index": index,
          "story_id": story.get("story_id"),
          "code": story.get("code"),
          "published_at_utc": story.get("published_at_utc"),
          "extension": _guess_extension_from_url(asset_url, default=".mp4" if story.get("is_video") else ".jpg"),
        },
      )
    return {
      "entity_type": "download_plan",
      "download_kind": "stories",
      "target_label": payload.get("username"),
      "source_endpoint": payload.get("source_endpoint"),
      "profile": payload.get("profile"),
      "stories": stories,
      "assets": assets,
      "count": len(assets),
    }

  def download_highlights_plan(
    self,
    target: str,
    *,
    title_filter: str | None = None,
    limit_highlights: int = 0,
  ) -> dict[str, Any]:
    payload = self.profile_highlights(target, limit=limit_highlights)
    highlights = payload.get("highlights") if isinstance(payload.get("highlights"), list) else []
    selected_highlights: list[dict[str, Any]] = []
    title_filter_text = _as_str(title_filter)
    title_filter_lower = title_filter_text.lower() if title_filter_text else None

    for highlight in highlights:
      if not isinstance(highlight, dict):
        continue
      title = _as_str(highlight.get("title")) or ""
      if title_filter_lower and title_filter_lower not in title.lower():
        continue
      selected_highlights.append(highlight)

    assets: list[dict[str, Any]] = []
    for highlight in selected_highlights:
      highlight_id = _as_str(highlight.get("highlight_id"))
      if not highlight_id:
        continue
      detail = self.highlight_by_id(highlight_id)
      items = detail.get("items") if isinstance(detail.get("items"), list) else []
      for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
          continue
        normalized_story = self._normalize_story_payload(item)
        asset_url = _as_str(normalized_story.get("video_url")) or _as_str(normalized_story.get("image_url")) or _as_str(normalized_story.get("thumbnail_url"))
        if not asset_url:
          continue
        assets.append(
          {
            "asset_url": asset_url,
            "asset_kind": "video" if normalized_story.get("is_video") else "image",
            "asset_index": index,
            "highlight_id": highlight_id,
            "highlight_title": highlight.get("title"),
            "story_id": normalized_story.get("story_id"),
            "code": normalized_story.get("code"),
            "published_at_utc": normalized_story.get("published_at_utc"),
            "extension": _guess_extension_from_url(asset_url, default=".mp4" if normalized_story.get("is_video") else ".jpg"),
          },
        )

    return {
      "entity_type": "download_plan",
      "download_kind": "highlights",
      "target_label": payload.get("username"),
      "source_endpoint": "/v1/user/highlights + /v1/highlight/by/id",
      "profile": payload.get("profile"),
      "highlights": selected_highlights,
      "title_filter": title_filter_text,
      "assets": assets,
      "count": len(assets),
    }

  def followers_page(
    self,
    target: str,
    *,
    page_id: str | None = None,
    limit: int = 25,
    strategy: str = "g2",
  ) -> dict[str, Any]:
    username, user = self._get_user_by_target(target)
    user_id = user.get("pk") or user.get("id")
    if user_id is None:
      raise HikerApiError("Profile has no user_id in HikerAPI response.")

    chosen_strategy = strategy.strip().lower() or "g2"
    page_token = (page_id or "").strip()
    cache_key = (chosen_strategy, str(user_id), page_token)

    if cache_key in self._followers_page_cache:
      payload = self._followers_page_cache[cache_key]
    else:
      if chosen_strategy == "gql_chunk":
        raw_payload = self._request(
          "/gql/user/followers/chunk",
          {"user_id": str(user_id), "end_cursor": page_token or None},
        )
        if not isinstance(raw_payload, list) or len(raw_payload) != 2:
          raise HikerApiError("Unexpected HikerAPI response format for gql followers chunk.")
        users = raw_payload[0] if isinstance(raw_payload[0], list) else []
        next_page_id = _as_str(raw_payload[1])
        payload = {
          "source_endpoint": "/gql/user/followers/chunk",
          "users": [item for item in users if isinstance(item, dict)],
          "next_page_id": next_page_id,
        }
      else:
        endpoint = "/g2/user/followers" if chosen_strategy == "g2" else "/v2/user/followers"
        raw_payload = self._request(
          endpoint,
          {"user_id": str(user_id), "page_id": page_token or None},
        )
        users, next_page_id = self._extract_page_users(raw_payload)
        payload = {
          "source_endpoint": endpoint,
          "users": users,
          "next_page_id": next_page_id,
        }
      self._followers_page_cache[cache_key] = payload

    normalized_followers = [
      self._normalize_follower_preview(item, source=payload["source_endpoint"])
      for item in payload["users"][:max(1, min(limit, 50))]
    ]

    return {
      "entity_type": "followers_page",
      "target_username": _as_str(user.get("username")) or username,
      "user_id": str(user_id),
      "page_id": page_token or None,
      "next_page_id": payload["next_page_id"],
      "count": len(normalized_followers),
      "source_endpoint": payload["source_endpoint"],
      "approximate": False,
      "profile": self._normalize_profile_user(user, username_input=username),
      "followers": normalized_followers,
      "raw": {
        "count": len(payload["users"]),
        "next_page_id": payload["next_page_id"],
      },
    }

  def top_followers(
    self,
    target: str,
    *,
    sample_size: int = 5,
    top_n: int = 5,
    max_pages: int = 1,
    strategy: str = "g2",
  ) -> dict[str, Any]:
    requested_sample_size = max(5, min(sample_size, 50))
    requested_top_n = max(1, min(top_n, 20))
    requested_max_pages = max(1, min(max_pages, 4))

    first_page = self.followers_page(target, page_id=None, limit=50, strategy=strategy)
    profile = first_page.get("profile") if isinstance(first_page.get("profile"), dict) else None
    target_username = str(first_page.get("target_username") or extract_profile_username(target) or "")
    user_id = str(first_page.get("user_id") or "")

    sampled_followers: list[dict[str, Any]] = []
    seen_usernames: set[str] = set()
    next_page_id = first_page.get("next_page_id")
    pages_used = 1
    page_requests = 1

    def extend_followers(items: list[dict[str, Any]]) -> None:
      for item in items:
        username = _as_str(item.get("username"))
        if not username:
          continue
        cache_key = self._username_cache_key(username)
        if cache_key in seen_usernames:
          continue
        seen_usernames.add(cache_key)
        sampled_followers.append(item)
        if len(sampled_followers) >= requested_sample_size:
          break

    initial_followers = first_page.get("followers") if isinstance(first_page.get("followers"), list) else []
    extend_followers([item for item in initial_followers if isinstance(item, dict)])

    while len(sampled_followers) < requested_sample_size and next_page_id and pages_used < requested_max_pages:
      page = self.followers_page(target_username, page_id=str(next_page_id), limit=50, strategy=strategy)
      page_requests += 1
      pages_used += 1
      next_page_id = page.get("next_page_id")
      followers = page.get("followers") if isinstance(page.get("followers"), list) else []
      extend_followers([item for item in followers if isinstance(item, dict)])

    usernames_to_fetch: list[str] = []
    profile_lookups = 0
    cache_hits = 0
    for item in sampled_followers:
      username = _as_str(item.get("username"))
      if not username:
        continue
      cache_key = self._username_cache_key(username)
      if cache_key in self._user_cache_by_username:
        cache_hits += 1
      else:
        profile_lookups += 1
      usernames_to_fetch.append(username)

    enriched: list[dict[str, Any]] = []
    max_workers = min(4, max(1, len(usernames_to_fetch)))
    if usernames_to_fetch:
      with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
          pool.submit(self._get_user_by_username, username): username
          for username in usernames_to_fetch
        }
        for future in as_completed(future_map):
          username = future_map[future]
          user = future.result()
          normalized = self._normalize_profile_user(user, username_input=username)
          normalized["entity_type"] = "follower_profile"
          enriched.append(normalized)

    ranked = sorted(
      enriched,
      key=lambda item: (
        int(item.get("followers") or 0),
        int(bool(item.get("is_verified"))),
        str(item.get("username") or ""),
      ),
      reverse=True,
    )[:requested_top_n]

    return {
      "entity_type": "top_followers_sample",
      "target_username": target_username,
      "user_id": user_id or None,
      "sample_size_requested": requested_sample_size,
      "sample_size_collected": len(sampled_followers),
      "enriched_count": len(enriched),
      "top_n": requested_top_n,
      "pages_used": pages_used,
      "has_more_followers": bool(next_page_id),
      "next_page_id": next_page_id,
      "source_endpoint": "/g2/user/followers" if strategy == "g2" else (
        "/gql/user/followers/chunk" if strategy == "gql_chunk" else "/v2/user/followers"
      ),
      "approximate": True,
      "approximation_note": (
        "This ranking is computed from a limited sampled subset of followers to control API spend. "
        "It is not a full-account ranking."
      ),
      "api_budget": {
        "page_requests": page_requests,
        "profile_lookups": profile_lookups,
        "profile_cache_hits": cache_hits,
        "estimated_total_requests": page_requests + profile_lookups + 1,
      },
      "profile": profile,
      "followers": ranked,
      "raw": {
        "sampled_usernames": [item.get("username") for item in sampled_followers],
      },
    }
