# MCP Guide

This document covers the local `instagram-mcp` server.

## Overview

The MCP server exposes the same capability layer as the CLI, but without terminal UI features such as:

- banners
- `render` modes
- `open`
- interactive session prompts

Instead, MCP clients call deterministic tools and receive structured results.

Transport:

- `stdio`

Entry command:

- `instagram-mcp`

## Installation

Install the project first:

```bash
cd /path/to/instagram-cli
./install.sh
```

Then run:

```bash
instagram-mcp
```

In normal use, MCP clients start this process themselves. You do not keep it running manually in a separate terminal.

## Tool Catalog

Current core tools:

- `search_instagram`
- `get_profile_stats`
- `get_reel_stats`
- `get_recent_reels`
- `get_profile_reels`
- `get_profile_publications`
- `get_profile_pinned_publications`
- `get_profile_tagged_publications`
- `get_profile_tagged_publications_page`
- `get_followers_page`
- `get_following_page`
- `get_top_followers`
- `search_profile_followers`
- `search_profile_following`
- `get_media_comments`
- `get_media_comments_page`
- `get_comment_replies`
- `get_comment_likers`
- `get_media_usertags`
- `get_media_insight`
- `get_profile_stories`
- `get_profile_highlights`
- `get_media_likers`
- `get_system_balance`
- `get_hashtag_info`
- `get_hashtag_reels`
- `search_places`
- `get_location_recent_media`
- `search_music`
- `get_track_media`
- `get_profile_suggestions`
- `rank_media_likers_by_followers`
- `get_last_reel_metric`
- `download_media_content`
- `download_media_audio`
- `download_profile_stories`
- `download_profile_highlights`
- `read_result`
- `export_result`
- `list_results`
- `server_info`

## Result Model

Most data tools return a `result_id`.

Use follow-up tools for persisted results:

- `read_result(result_id)`
- `export_result(result_id, format)`
- `list_results()`

This keeps MCP interactions explicit and avoids depending on terminal session memory.

## Exact vs Approximate in MCP

Treat MCP tool results as exact unless the payload explicitly says otherwise.

- exact examples:
  - `get_followers_page`
  - `get_following_page`
  - `get_profile_pinned_publications`
  - `get_profile_tagged_publications_page`
  - `get_media_comments_page`
- approximate examples:
  - `get_top_followers`
  - ranked liker flows when the payload includes a cap or limitation note

## Comments Completeness

Comments are not one flat dataset.

- `get_media_comments` and `get_media_comments_page` return root comments
- `get_comment_replies` loads nested replies for one root comment
- total media comment count can be greater than the number of returned root comments

If the client needs full thread depth, it should:

1. fetch root comments
2. select root comment ids
3. call `get_comment_replies` for the needed threads

## Search Behavior in MCP

In MCP mode, `search_instagram` does not call OpenRouter internally.

Recommended inputs:

- `query`
- `query_variants`
- `media_only`
- `today_only`
- `days_back`

Best practice:

- let the MCP client do the reasoning
- pass translated variants or synonyms in `query_variants`
- let the server handle paginated retrieval, merge, dedupe, filtering, and bounded freshness enrichment

Defaults and limits:

- if `limit` is omitted, `search_instagram` uses adaptive deep retrieval and targets up to `50` final results
- if `limit` is specified, the one-shot cap is `100`
- the response includes:
  - `deep_search_used`
  - `stop_reason`
  - `api_budget.search_requests`
  - `api_budget.query_page_counts`

Example ideal search payload:

```json
{
  "query": "find today's reels about an attack on Dubai",
  "query_variants": [
    "attack on Dubai",
    "Dubai attack",
    "атака на дубай",
    "взрыв в дубае"
  ],
  "media_only": true,
  "today_only": true,
  "limit": 100
}
```

## Comments Behavior in MCP

`get_media_comments` is now a high-level bulk root-comment tool:

- it paginates internally
- it deduplicates root comments
- it can return up to `100` root comments per media
- it does not include replies unless the client explicitly uses `get_comment_replies`

The response includes:

- `returned_count`
- `available_comment_count`
- `comments_completeness = roots_only`
- `api_budget.page_requests`

Host agents should handle any user confirmation for expensive multi-step workflows themselves. The server does not block those calls interactively.

## Claude Code Setup

Add the server:

```bash
claude mcp add instagram-cli -- /path/to/instagram-cli/.venv/bin/instagram-mcp
```

If the command is already in `PATH`, this also works:

```bash
claude mcp add instagram-cli -- instagram-mcp
```

Verify:

```bash
claude mcp list
claude mcp get instagram-cli
```

## Claude Desktop Setup

On macOS, Claude Desktop reads MCP config from:

```text
~/Library/Application Support/Claude/claude_desktop_config.json
```

Example:

```json
{
  "mcpServers": {
    "instagram-cli": {
      "command": "/path/to/instagram-cli/.venv/bin/instagram-mcp",
      "args": [],
      "env": {
        "INSTAGRAM_CLI_ENV_FILE": "/path/to/instagram-cli/.env"
      }
    }
  }
}
```

Notes:

- use absolute paths
- point `INSTAGRAM_CLI_ENV_FILE` to the CLI `.env`
- restart Claude Desktop after editing the config

## Example Prompts for MCP Clients

- `Find today's reels about an attack on Dubai.`
- `Find 100 reels about Dubai real estate.`
- `How many followers does @lupikovoleg have?`
- `Show the last 10 publications from @lupikovoleg.`
- `Show the latest carousels from @lupikovoleg.`
- `Get comments for this reel: https://www.instagram.com/reel/XXXXXXXXXXX/`
- `Get 100 root comments for this reel: https://www.instagram.com/reel/XXXXXXXXXXX/`
- `Get one page of following for @username.`
- `Search this profile's followers for coffee accounts.`
- `Show pinned posts for @username.`
- `Show media where @username is tagged.`
- `Show replies for comment 123 on this post: https://www.instagram.com/p/XXXXXXXXXXX/`
- `Who is tagged in this reel: https://www.instagram.com/reel/XXXXXXXXXXX/`
- `Show deeper insight metrics for this reel.`
- `Show reels for hashtag dubai.`
- `Search places in Dubai and then show recent media for the first place.`
- `Search Instagram music for dubai and then show media for the first track.`
- `Show suggested profiles related to @username.`
- `Show the current HikerAPI balance.`
- `Rank likers of this reel by followers.`
- `Export the previous result to csv.`
- `Download the audio from this reel: https://www.instagram.com/reel/XXXXXXXXXXX/`
