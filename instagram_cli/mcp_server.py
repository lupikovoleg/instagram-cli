from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from instagram_cli.config import Settings
from instagram_cli.ops import InstagramOps


@dataclass
class StoredResult:
  result_id: str
  created_at: str
  payload: dict[str, Any]
  summary: dict[str, Any]


class ResultStore:
  def __init__(self, *, max_items: int = 200) -> None:
    self._max_items = max(10, max_items)
    self._items: OrderedDict[str, StoredResult] = OrderedDict()

  def put(self, payload: dict[str, Any], *, summary: dict[str, Any]) -> StoredResult:
    result_id = uuid4().hex[:12]
    item = StoredResult(
      result_id=result_id,
      created_at=datetime.now().isoformat(timespec="seconds"),
      payload=payload,
      summary=summary,
    )
    self._items[result_id] = item
    self._items.move_to_end(result_id)
    while len(self._items) > self._max_items:
      self._items.popitem(last=False)
    return item

  def get(self, result_id: str) -> StoredResult | None:
    return self._items.get(result_id.strip())

  def list(self, *, limit: int = 20) -> list[StoredResult]:
    safe_limit = max(1, min(limit, 100))
    items = list(self._items.values())
    return list(reversed(items[-safe_limit:]))


def _mcp_instructions() -> str:
  return (
    "Instagram CLI MCP server. "
    "Use these tools for Instagram discovery, stats, audience analysis, downloads, and exports. "
    "This server is stateless for targets: pass explicit usernames or media URLs to tools. "
    "For search_instagram, the MCP client may supply query_variants with translations or synonyms. "
    "The server does not use OpenRouter internally for MCP search expansion. "
    "Most tools return a result_id. Use read_result or export_result for follow-up actions on that stored result."
  )


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
  runtime_settings = settings or Settings.load()
  ops = InstagramOps(runtime_settings)
  store = ResultStore()
  server = FastMCP(
    name="instagram-cli",
    instructions=_mcp_instructions(),
    json_response=True,
  )

  def record(payload: dict[str, Any]) -> dict[str, Any]:
    summary = ops.summarize_result(payload)
    stored = store.put(payload, summary=summary)
    return {
      **payload,
      "result_id": stored.result_id,
      "created_at": stored.created_at,
      "summary": stored.summary,
    }

  def safe_tool(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
      try:
        payload = fn(*args, **kwargs)
      except Exception as exc:
        return {
          "ok": False,
          "error": str(exc),
        }
      if not isinstance(payload, dict):
        return {"ok": False, "error": "Tool returned non-dict payload."}
      return record(payload)

    return wrapped

  @server.tool(description="Describe the MCP server, configured models, and main capabilities.")
  def server_info() -> dict[str, Any]:
    return {
      "ok": True,
      "server_name": "instagram-cli",
      "transport": "stdio by default",
      "openrouter_model": runtime_settings.openrouter_chat_model,
      "hikerapi_configured": bool(runtime_settings.hiker_access_key),
      "openrouter_configured": bool(runtime_settings.openrouter_api_key),
      "mcp_search_uses_openrouter": False,
      "capabilities": {
        "search": True,
        "profile_stats": True,
        "reel_stats": True,
        "profile_reels": True,
        "stories": True,
        "highlights": True,
        "comments": True,
        "likers": True,
        "followers": True,
        "downloads": True,
        "exports": True,
      },
      "notes": [
        "Pass explicit usernames or media URLs to tools.",
        "Use result_id from any tool response with read_result or export_result.",
      ],
    }

  @server.tool(description="List recent stored MCP results so a client can choose a result_id for export or follow-up.")
  def list_results(limit: int = 20) -> dict[str, Any]:
    items = store.list(limit=limit)
    return {
      "ok": True,
      "count": len(items),
      "results": [
        {
          "result_id": item.result_id,
          "created_at": item.created_at,
          "summary": item.summary,
        }
        for item in items
      ],
    }

  @server.tool(description="Read a stored MCP result by result_id.")
  def read_result(result_id: str) -> dict[str, Any]:
    item = store.get(result_id)
    if item is None:
      return {"ok": False, "error": "unknown_result_id"}
    return {
      "ok": True,
      "result_id": item.result_id,
      "created_at": item.created_at,
      "summary": item.summary,
      "payload": item.payload,
    }

  @server.tool(description="Export a stored result by result_id to CSV or JSON.")
  def export_result(result_id: str, format: str, filename_hint: str | None = None) -> dict[str, Any]:
    item = store.get(result_id)
    if item is None:
      return {"ok": False, "error": "unknown_result_id"}
    return ops.export_collection(
      result=item.payload,
      fmt=format,
      filename_hint=filename_hint,
    )

  @server.tool(
    description=(
      "Search Instagram by topic with optional client-supplied query_variants, media filtering, and freshness filters. "
      "In MCP mode this tool is deterministic and does not call OpenRouter internally."
    ),
  )
  def search_instagram(
    query: str,
    limit: int = 10,
    media_only: bool = False,
    today_only: bool = False,
    days_back: int | None = None,
    query_variants: list[str] | None = None,
  ) -> dict[str, Any]:
    return safe_tool(ops.search_instagram)(
      query=query,
      limit=limit,
      media_only=media_only,
      today_only=today_only,
      days_back=days_back,
      query_variants=query_variants,
      use_llm_expansion=False,
    )

  @server.tool(description="Get Instagram profile stats by username or profile URL.")
  def get_profile_stats(target: str) -> dict[str, Any]:
    return safe_tool(ops.get_profile_stats)(target=target)

  @server.tool(description="Get Instagram reel or post stats by media URL.")
  def get_reel_stats(media_url: str) -> dict[str, Any]:
    return safe_tool(ops.get_reel_stats)(media_url=media_url)

  @server.tool(description="Get latest reels for a profile.")
  def get_recent_reels(target: str, limit: int = 12) -> dict[str, Any]:
    return safe_tool(ops.get_recent_reels)(target=target, limit=limit)

  @server.tool(description="Get reels for a profile with an optional days_back filter.")
  def get_profile_reels(target: str, limit: int = 12, days_back: int | None = None) -> dict[str, Any]:
    return safe_tool(ops.get_profile_reels)(target=target, limit=limit, days_back=days_back)

  @server.tool(description="Get one low-cost followers page for a profile.")
  def get_followers_page(target: str, limit: int = 25, page_id: str | None = None) -> dict[str, Any]:
    return safe_tool(ops.get_followers_page)(target=target, limit=limit, page_id=page_id)

  @server.tool(description="Get an approximate sampled ranking of the biggest followers by follower count.")
  def get_top_followers(
    target: str,
    sample_size: int = 5,
    top_n: int = 5,
    max_pages: int = 1,
  ) -> dict[str, Any]:
    return safe_tool(ops.get_top_followers)(
      target=target,
      sample_size=sample_size,
      top_n=top_n,
      max_pages=max_pages,
    )

  @server.tool(description="Get comments for an Instagram reel or post URL.")
  def get_media_comments(media_url: str, limit: int = 20) -> dict[str, Any]:
    return safe_tool(ops.get_media_comments)(media_url=media_url, limit=limit)

  @server.tool(description="List active stories for a profile.")
  def get_profile_stories(target: str, limit: int = 0) -> dict[str, Any]:
    return safe_tool(ops.get_profile_stories)(target=target, limit=limit)

  @server.tool(description="List highlight folders for a profile.")
  def get_profile_highlights(target: str, limit: int = 0) -> dict[str, Any]:
    return safe_tool(ops.get_profile_highlights)(target=target, limit=limit)

  @server.tool(description="Get a preview list of users who liked an Instagram reel or post.")
  def get_media_likers(media_url: str, limit: int = 20) -> dict[str, Any]:
    return safe_tool(ops.get_media_likers)(media_url=media_url, limit=limit)

  @server.tool(description="Build a ranking of media likers sorted by follower count.")
  def rank_media_likers_by_followers(media_urls: list[str], top_n: int = 100) -> dict[str, Any]:
    return safe_tool(ops.rank_media_likers_by_followers)(media_urls=media_urls, top_n=top_n)

  @server.tool(description="Get one metric from the latest reel of a profile.")
  def get_last_reel_metric(
    target: str,
    metric: str,
  ) -> dict[str, Any]:
    return safe_tool(ops.get_last_reel_metric)(target=target, metric=metric)

  @server.tool(description="Download a reel or post to local files.")
  def download_media_content(media_url: str) -> dict[str, Any]:
    return safe_tool(ops.download_media_content)(media_url=media_url)

  @server.tool(description="Download the audio track from a reel or post.")
  def download_media_audio(media_url: str) -> dict[str, Any]:
    return safe_tool(ops.download_media_audio)(media_url=media_url)

  @server.tool(description="Download active stories for a profile.")
  def download_profile_stories(target: str, limit: int = 0) -> dict[str, Any]:
    return safe_tool(ops.download_profile_stories)(target=target, limit=limit)

  @server.tool(description="Download highlights for a profile, optionally filtered by title.")
  def download_profile_highlights(
    target: str,
    title_filter: str | None = None,
    limit_highlights: int = 0,
  ) -> dict[str, Any]:
    return safe_tool(ops.download_profile_highlights)(
      target=target,
      title_filter=title_filter,
      limit_highlights=limit_highlights,
    )

  return server


def main() -> int:
  server = create_mcp_server()
  server.run(transport="stdio")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
