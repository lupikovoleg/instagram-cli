# Instagram CLI

Terminal-first Instagram analytics: profile and Reels stats + an agent with tool calling for natural-language queries.

## Features

- Fetch Reels stats by URL:
  - `views`, `likes`, `comments`, `saves`
  - `engagement_rate`
  - publish time (`local` + `UTC`)
  - `viral_index`
- Fetch profile stats by URL or username:
  - followers, following, post count
  - `verified` / `private`
  - stories availability (`has_stories`, `stories_count`)
- Natural-language queries (no command prefix required):
  - `how many followers does lupikovoleg have?`
  - `does @username have stories?`
  - `how many likes does the latest reel have?`
  - paste a profile or reel URL directly
- Session memory:
  - current profile
  - current reel
  - recent reels for follow-up questions
- Agent mode:
  - model selects tools via tool calling
  - stats are fetched from APIs (not guessed)
- Output modes:
  - `rich` Markdown render in interactive terminal
  - `plain` text mode
  - typing indicator before answer starts: `. .. ...`

## Requirements

- macOS / Linux
- Python 3.10+
- API access:
  - `HikerAPI` key
  - `OpenRouter` key

## Installation

```bash
cd /Users/oleglupikov/instagram-cli
./install.sh
```

After install, run:

```bash
instagram
```

## First Run Setup

This CLI uses its **own** `.env` file (not `retenza/.env`).

Default path:
- `<project_root>/.env`

Override path:
- `INSTAGRAM_CLI_ENV_FILE=/path/to/.env`

If required keys are missing, on startup CLI will:
1. ask for `HikerAPI key`
2. ask for `OpenRouter API key`
3. save them into its own `.env`
4. show a quick usage guide and start interactive mode

## Quick Start

```bash
instagram
```

Example prompts:

```text
instagram> profile lupikovoleg
instagram> reel https://www.instagram.com/reel/XXXXXXXXXXX/
instagram> how many followers does lupikovoleg have?
instagram> does @lupikovoleg have stories?
instagram> how many likes does the latest reel have?
```

## Commands

- `help` — show help
- `actions` — show available actions
- `reel <instagram_reel_url>` — fetch reel stats
- `profile <instagram_profile_url_or_username>` — fetch profile stats
- `stats <url_or_username>` — auto-detect target type
- `ask <question>` — ask the agent
- `model` — show current model
- `model <openrouter_model_id>` — switch model for current session
- `render` — show current output mode
- `render <rich|plain>` — switch output mode
- `last` — print raw JSON for latest fetched stats
- `reload` — reload `.env`
- `exit` / `quit` — exit

## Environment Variables

Required:

- `HIKERAPI_KEY` or `HIKERAPI_TOKEN`
- `OPENROUTER_API_KEY`

Optional:

- `OPENROUTER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
- `OPENROUTER_CHAT_MODEL` (default: `google/gemini-3-flash-preview`)
- `OPENROUTER_ANALYSIS_MODEL`
- `OPENROUTER_VISION_MODEL`
- `OPENROUTER_HTTP_REFERER`
- `OPENROUTER_APP_TITLE`
- `HIKERAPI_BASE_URL` (default: `https://api.instagrapi.com`)
- `PROXY_URL`
- `PROXY_SOCKS5_URL`
- `DEBUG`

## Architecture

- HikerAPI provides raw Instagram stats.
- OpenRouter agent runs with tool calling:
  - `get_profile_stats`
  - `get_reel_stats`
  - `get_recent_reels`
  - `get_last_reel_metric`
  - `get_session_context`
- For simple direct input (single URL or username), CLI can call stats endpoints directly.

## Troubleshooting

- `OpenRouter is not configured...`
  - check `OPENROUTER_API_KEY` in local `.env`
- `HIKERAPI_TOKEN or HIKERAPI_KEY is missing`
  - check `HIKERAPI_KEY` / `HIKERAPI_TOKEN`
- `rich` rendering does not appear
  - run `render plain` to force plain output
  - ensure you are in interactive TTY (not piping stdin)
- Target parsing is wrong
  - use explicit commands: `profile ...` or `reel ...`

## Security Notes

- Do not commit `.env` with real secrets.
- Use separate restricted keys for CI/production.
