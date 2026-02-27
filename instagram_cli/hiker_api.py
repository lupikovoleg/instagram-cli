from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
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
      response = requests.get(
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

  def reel_stats(self, reel_url: str) -> dict[str, Any]:
    shortcode = extract_reel_shortcode(reel_url)
    if not shortcode:
      raise HikerApiError("Invalid Instagram Reel URL.")

    media = self._request("/v1/media/by/code", {"code": shortcode})
    if not isinstance(media, dict):
      raise HikerApiError("Unexpected HikerAPI response format for reel.")
    return _normalize_reel_payload(media, reel_url=reel_url)

  def recent_reels(self, target: str, limit: int = 12) -> dict[str, Any]:
    username = extract_profile_username(target)
    if not username:
      raise HikerApiError("Invalid Instagram profile URL or username.")

    user = self._request("/v1/user/by/username", {"username": username})
    if not isinstance(user, dict):
      raise HikerApiError("Unexpected HikerAPI response format for profile.")

    user_id = user.get("pk") or user.get("id")
    if user_id is None:
      raise HikerApiError("Profile has no user_id in HikerAPI response.")

    clips = self._request("/v1/user/clips", {"user_id": str(user_id)})
    if not isinstance(clips, list):
      raise HikerApiError("Unexpected HikerAPI response format for user clips.")

    reels: list[dict[str, Any]] = []
    for item in clips:
      if not isinstance(item, dict):
        continue
      normalized = _normalize_reel_payload(item)
      normalized["entity_type"] = "reel_preview"
      reels.append(normalized)

    reels.sort(key=lambda item: int(item.get("taken_at_ts") or 0), reverse=True)
    if limit > 0:
      reels = reels[:limit]

    return {
      "entity_type": "profile_reels",
      "username": _as_str(user.get("username")) or username,
      "user_id": str(user_id),
      "profile": {
        "entity_type": "profile",
        "username": _as_str(user.get("username")) or username,
        "user_id": str(user_id),
        "full_name": _as_str(user.get("full_name")),
        "is_private": bool(user.get("is_private")),
        "is_verified": bool(user.get("is_verified")),
        "followers": _as_int(user.get("follower_count") or user.get("followers")),
        "following": _as_int(user.get("following_count") or user.get("following")),
        "posts": _as_int(user.get("media_count") or user.get("posts")),
        "biography": _as_str(user.get("biography")),
        "external_url": _as_str(user.get("external_url")),
      },
      "reels": reels,
    }

  def profile_stats(self, target: str) -> dict[str, Any]:
    username = extract_profile_username(target)
    if not username:
      raise HikerApiError("Invalid Instagram profile URL or username.")

    user = self._request("/v1/user/by/username", {"username": username})
    if not isinstance(user, dict):
      raise HikerApiError("Unexpected HikerAPI response format for profile.")

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

    return {
      "entity_type": "profile",
      "input": target,
      "username": _as_str(user.get("username")) or username,
      "user_id": str(user_id) if user_id is not None else None,
      "full_name": _as_str(user.get("full_name")),
      "is_private": bool(user.get("is_private")),
      "is_verified": bool(user.get("is_verified")),
      "followers": _as_int(user.get("follower_count") or user.get("followers")),
      "following": _as_int(user.get("following_count") or user.get("following")),
      "posts": _as_int(user.get("media_count") or user.get("posts")),
      "biography": _as_str(user.get("biography")),
      "external_url": _as_str(user.get("external_url")),
      "stories_count": stories_count,
      "has_stories": (stories_count or 0) > 0 if stories_count is not None else None,
      "stories_error": stories_error,
      "raw": user,
    }
