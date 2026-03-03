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
- `get_followers_page`
- `get_top_followers`
- `get_media_comments`
- `get_profile_stories`
- `get_profile_highlights`
- `get_media_likers`
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
- let the server handle merge, dedupe, filtering, and bounded freshness enrichment

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
  "limit": 5
}
```

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
- `How many followers does @lupikovoleg have?`
- `Show the last 10 publications from @lupikovoleg.`
- `Show the latest carousels from @lupikovoleg.`
- `Get comments for this reel: https://www.instagram.com/reel/XXXXXXXXXXX/`
- `Rank likers of this reel by followers.`
- `Export the previous result to csv.`
- `Download the audio from this reel: https://www.instagram.com/reel/XXXXXXXXXXX/`
