# Instagram CLI

Terminal-first Instagram analytics, downloads, and MCP tools powered.

```text
 ___ _   _ ____ _____  _    ____ ____      _    __  __      ____ _     ___
|_ _| \ | / ___|_   _|/ \  / ___|  _ \    / \  |  \/  |    / ___| |   |_ _|
 | ||  \| \___ \ | | / _ \| |  _| |_) |  / _ \ | |\/| |   | |   | |    | |
 | || |\  |___) || |/ ___ \ |_| |  _ <  / ___ \| |  | |   | |___| |___ | |
|___|_| \_|____/ |_/_/   \_\____|_| \_\/_/   \_\_|  |_|    \____|_____|___|
                           INSTAGRAM-CLI by @lupikovoleg
```

## What It Does

- Search Instagram by topic, including multilingual reel and media discovery
- Filter search results by freshness, including `today` and `last N days`
- Fetch profile stats, reel stats, comments, likers, followers, stories, and highlights
- Analyze profile publications from the main grid:
  - reels
  - posts
  - carousels
- Download Instagram content locally:
  - reels and posts
  - audio tracks
  - active stories
  - highlights
- Export collected results to `csv` or `json`
- Support natural-language interaction with tool calling in the CLI
- Handle chained workflows such as:
  - search -> inspect -> rank -> export
  - open a profile -> analyze publications -> download content
  - fetch a reel -> inspect comments or likers -> export the result
- Expose the same capability layer through a local MCP server for Claude and other MCP clients

## Requirements

- macOS or Linux
- Python `3.10+`
- `HIKERAPI_KEY` or `HIKERAPI_TOKEN`
- `OPENROUTER_API_KEY` for the interactive CLI agent

## Installation

```bash
cd /path/to/instagram-cli
./install.sh
```

This installs two commands:

- `instagram` for the interactive CLI
- `instagram-mcp` for the local MCP server

## First Run

The CLI uses its own `.env` file.

- default path: `/path/to/instagram-cli/.env`
- override path: `INSTAGRAM_CLI_ENV_FILE=/path/to/custom.env`

If required keys are missing, the CLI bootstrap asks for them and writes the local `.env`.

## Quick Start

Start the CLI:

```bash
instagram
```

Typical commands:

```text
instagram> profile lupikovoleg
instagram> search portugal creators
instagram> publications lupikovoleg 10 30 all
instagram> comments https://www.instagram.com/reel/XXXXXXXXXXX/ 20
instagram> download media https://www.instagram.com/reel/XXXXXXXXXXX/
instagram> export csv latest-results
instagram> how many followers does @lupikovoleg have?
instagram> find today's reels about an attack on Dubai
```

Start the MCP server:

```bash
instagram-mcp
```

## MCP Setup

Claude Code:

```bash
claude mcp add instagram-cli -- /path/to/instagram-cli/.venv/bin/instagram-mcp
```

Claude Desktop config file on macOS:

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

## Documentation

- [CLI guide](docs/cli.md)
- [MCP guide](docs/mcp.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting and configuration](docs/troubleshooting.md)

## Project Notes

- CLI mode uses OpenRouter for natural-language tool selection and query expansion.
- MCP mode does not use OpenRouter internally for search. MCP clients should pass `query_variants` when richer multilingual retrieval is needed.
- Expensive follower and liker analysis is intentionally capped by default to avoid burning HikerAPI credits.
