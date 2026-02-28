from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from instagram_cli.config import Settings
from instagram_cli.hiker_api import HikerApiClient, HikerApiError


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="Export top media likers ranked by follower count.",
  )
  parser.add_argument(
    "urls",
    nargs="+",
    help="Instagram media URLs (post or reel).",
  )
  parser.add_argument(
    "--top",
    type=int,
    default=100,
    help="How many ranked rows to export.",
  )
  parser.add_argument(
    "--workers",
    type=int,
    default=8,
    help="Parallel workers for profile enrichment.",
  )
  parser.add_argument(
    "--output-dir",
    default="output",
    help="Directory for CSV/JSON export files.",
  )
  return parser.parse_args()


def _ensure_output_dir(path_text: str) -> Path:
  path = Path(path_text).expanduser().resolve()
  path.mkdir(parents=True, exist_ok=True)
  return path


def _collect_likers(
  client: HikerApiClient,
  urls: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
  source_media: list[dict[str, Any]] = []
  liker_map: dict[str, dict[str, Any]] = {}

  for index, url in enumerate(urls, start=1):
    print(f"[{index}/{len(urls)}] Fetching media likers: {url}", flush=True)
    payload = client.media_likers(url)
    media = payload["media"]
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

    for liker in payload["likers"]:
      user_id = str(liker["user_id"])
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
      media_url = media.get("url")
      if shortcode and shortcode not in entry["liked_shortcodes"]:
        entry["liked_shortcodes"].append(shortcode)
      if media_url and media_url not in entry["liked_urls"]:
        entry["liked_urls"].append(media_url)
      entry["liked_count"] = len(entry["liked_shortcodes"])

  return source_media, list(liker_map.values())


def _rank_rows(
  likers: list[dict[str, Any]],
  enriched_users: list[dict[str, Any]],
  *,
  top_n: int,
) -> list[dict[str, Any]]:
  liker_by_id = {str(item["user_id"]): item for item in likers}
  rows: list[dict[str, Any]] = []

  for user in enriched_users:
    user_id = str(user.get("user_id") or "")
    if not user_id or user_id not in liker_by_id:
      continue
    liker = liker_by_id[user_id]
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
        "liked_shortcodes": ",".join(liker.get("liked_shortcodes", [])),
        "liked_urls": ",".join(liker.get("liked_urls", [])),
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

  limited = rows[:top_n]
  for index, row in enumerate(limited, start=1):
    row["rank"] = index
  return limited


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
  fieldnames = [
    "rank",
    "user_id",
    "username",
    "full_name",
    "followers",
    "following",
    "posts",
    "is_verified",
    "is_private",
    "liked_count",
    "liked_shortcodes",
    "liked_urls",
  ]
  with path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
  path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
  args = parse_args()
  settings = Settings.load()
  client = HikerApiClient(settings)

  try:
    source_media, likers = _collect_likers(client, args.urls)
  except HikerApiError as exc:
    print(f"Error while fetching likers: {exc}")
    return 1

  user_ids = [item["user_id"] for item in likers]
  print(
    f"Collected {len(likers)} unique likers from {len(source_media)} media items. "
    f"Starting enrichment for {len(user_ids)} profiles...",
    flush=True,
  )

  def on_progress(completed: int, total: int) -> None:
    if completed == total or completed % 100 == 0:
      print(f"Enrichment progress: {completed}/{total}", flush=True)

  try:
    enriched = client.enrich_users_by_id(
      user_ids,
      max_workers=max(1, min(args.workers, 12)),
      on_progress=on_progress,
    )
  except HikerApiError as exc:
    print(f"Error while enriching users: {exc}")
    return 1

  ranked_rows = _rank_rows(likers, enriched, top_n=max(1, args.top))
  capped_media_count = sum(1 for item in source_media if item.get("is_capped"))
  limitations: list[str] = []
  if capped_media_count:
    limitations.append(
      f"{capped_media_count} media item(s) returned a capped likers list via HikerAPI, so the ranking is top-{args.top} within the available liker sample, not necessarily all likes.",
    )

  output_dir = _ensure_output_dir(args.output_dir)
  timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
  csv_path = output_dir / f"top_media_likers_by_followers_{timestamp}.csv"
  json_path = output_dir / f"top_media_likers_by_followers_{timestamp}.json"

  _write_csv(csv_path, ranked_rows)
  _write_json(
    json_path,
    {
      "generated_at": datetime.now().isoformat(timespec="seconds"),
      "source_media": source_media,
      "unique_likers": len(likers),
      "enriched_profiles": len(enriched),
      "top_n": len(ranked_rows),
      "limitations": limitations,
      "rows": ranked_rows,
    },
  )

  print(f"CSV: {csv_path}")
  print(f"JSON: {json_path}")
  if limitations:
    print("Limitations:")
    for item in limitations:
      print(f"- {item}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
