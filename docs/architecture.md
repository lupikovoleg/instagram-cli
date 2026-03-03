# Architecture

This document describes how the CLI and MCP server are structured.

## Components

Main layers:

- `instagram_cli/hiker_api.py`
  - HikerAPI client and endpoint wrappers
- `instagram_cli/ops.py`
  - deterministic reusable operations shared by CLI and MCP
- `instagram_cli/openrouter_agent.py`
  - tool-calling loop and CLI-oriented search expansion
- `instagram_cli/repl.py`
  - interactive terminal interface and CLI session state
- `instagram_cli/mcp_server.py`
  - FastMCP entrypoint and tool exposure

## Execution Paths

CLI path:

1. user enters a command or natural-language prompt
2. direct commands call deterministic operations immediately
3. natural-language prompts go through the agent
4. the agent selects tools and the CLI updates session context
5. results can be exported or used in follow-up prompts

MCP path:

1. the MCP client chooses a tool
2. the server executes deterministic operations from `ops.py`
3. the server returns structured output and `result_id` values
4. the client can read or export previous results explicitly

## Search Pipeline

The search pipeline is deliberately split by interface.

CLI mode:

- the agent can use OpenRouter for query expansion
- it builds:
  - the original topic
  - normalized topic variants
  - translated variants
  - short keyword variants
- the tool then executes several `/gql/topsearch` calls
- results are merged and deduplicated
- optional enrichment fetches media info for freshness filtering

MCP mode:

- search does not call OpenRouter internally
- the client should pass `query_variants`
- the server still handles:
  - multi-query execution
  - merge and dedupe
  - `media_only`
  - `today_only`
  - `days_back`
  - bounded freshness enrichment

## Content Coverage

The capability layer supports:

- profile stats
- reel stats
- stories and highlights
- comments
- likers
- followers pages
- approximate top followers
- downloads
- main-grid publications

Profile publication coverage now includes:

- reels
- non-reel posts
- carousels

The main grid comes from `/v1/user/medias/chunk` because it provides:

- stable pagination
- enough metadata to distinguish publication kinds
- a simpler response shape than the GraphQL alternative

## Session State vs Result IDs

CLI uses in-memory session context for follow-up prompts such as:

- `show this profile's stories`
- `download this reel`
- `export that to csv`

MCP does not rely on the same interactive state. Instead it uses explicit `result_id` handles for follow-up reads and exports.

## Cost Control

The project avoids unbounded HikerAPI spend by default.

Examples:

- follower ranking is sampled and capped
- liker ranking enriches bounded sets unless the caller explicitly asks for larger jobs
- freshness enrichment only runs when the request requires time filtering

This is intentional. Exact large-scale scans should be implemented as explicit batch jobs with budgeting, progress reporting, and resume support.

## Known Limits

- comment totals can include threaded replies even when a root-comments endpoint returns fewer items
- trial-reel classification is intentionally unsupported because the current HikerAPI signals are not reliable enough
- some downloads depend on whether Instagram payloads expose direct media URLs
