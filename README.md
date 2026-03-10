# Instagram CLI

Terminal-first Instagram analytics, downloads, and MCP tools powered by HikerAPI, OpenRouter, and FastMCP.

```text
 ___ _   _ ____ _____  _    ____ ____      _    __  __      ____ _     ___
|_ _| \ | / ___|_   _|/ \  / ___|  _ \    / \  |  \/  |    / ___| |   |_ _|
 | ||  \| \___ \ | | / _ \| |  _| |_) |  / _ \ | |\/| |   | |   | |    | |
 | || |\  |___) || |/ ___ \ |_| |  _ <  / ___ \| |  | |   | |___| |___ | |
|___|_| \_|____/ |_/_/   \_\____|_| \_\/_/   \_\_|  |_|    \____|_____|___|
                           INSTAGRAM-CLI by @lupikovoleg
```

## What It Does

- Search Instagram by topic with adaptive deep pagination, including multilingual reel and media discovery
- Filter search results by freshness, including `today` and `last N days`
- Fetch profile stats, reel stats, up to 100 root comments per media, likers, followers, following, stories, and highlights
- Analyze profile publications from the main grid:
  - reels
  - posts
  - carousels
- Inspect pinned posts, tagged publications, comment replies, tagged users, and media insight metrics
- Discover content and entities through:
  - hashtags
  - places
  - music tracks
  - suggested related profiles
- Check HikerAPI balance and request-rate data from the CLI or MCP
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

Install as a Python dependency in another project:

```bash
pip install git+https://github.com/lupikovoleg/instagram-cli.git
```

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
instagram> search reels about dubai attack
instagram> publications lupikovoleg 10 30 all
instagram> comments https://www.instagram.com/reel/XXXXXXXXXXX/ 100
instagram> download media https://www.instagram.com/reel/XXXXXXXXXXX/
instagram> export csv latest-results
instagram> how many followers does @lupikovoleg have?
instagram> find today's reels about an attack on Dubai
instagram> find 100 reels about Dubai real estate
```

Start the MCP server:

```bash
instagram-mcp
```

Use it as a Python library:

```python
from instagram_cli import InstagramClient

client = InstagramClient.from_env(env_file="/path/to/instagram-cli/.env")
profile = client.get_profile_stats(target="lupikovoleg")
```

Custom agent example:

```bash
python /path/to/instagram-cli/examples/custom_agent.py \
  --env-file /path/to/instagram-cli/.env \
  "How many followers does @lupikovoleg have?"
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

- Internal Python integration is documented in the [Python library guide](docs/library.md). For your own Python product, prefer direct embedding with `InstagramClient` over MCP.
- [CLI guide](docs/cli.md)
- [Python library guide](docs/library.md)
- [MCP guide](docs/mcp.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting and configuration](docs/troubleshooting.md)

## Project Notes

- CLI mode uses OpenRouter for natural-language tool selection and query expansion.
- Search is adaptive by default: if `limit` is omitted, the tool can paginate internally up to 50 final results; explicit one-shot search requests are capped at 100.
- High-level comment collection returns root comments only and can paginate internally up to 100 comments per media.
- MCP mode does not use OpenRouter internally for search. MCP clients can pass `query_variants` when richer multilingual retrieval is needed.
- Python library mode uses the same deterministic `InstagramOps` layer as the CLI and MCP server, exposed through `InstagramClient`.
- Expensive follower and liker analysis is intentionally capped by default to avoid burning HikerAPI credits.
- Some tools are exact page reads, while sampled ranking tools explicitly mark themselves as approximate.
