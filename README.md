# Instagram CLI

Terminal-first Instagram analytics: profile and Reels stats + an agent with tool calling for natural-language queries.

## Features

- Fetch Reels stats by URL:
  - `views`, `likes`, `comments`, `saves`
  - `engagement_rate`
  - publish time (`local` + `UTC`)
  - `viral_index`
  - trial/main reel signal when available
- Fetch profile stats by URL or username:
  - followers, following, post count
  - `verified` / `private`
  - stories availability (`has_stories`, `stories_count`)
- Fetch filtered profile reels:
  - latest reels
  - reels from the last `N` days
  - trial-only or main-only reels
- Fetch media audience data:
  - media comments
  - media likers
  - ranked likers by follower count
- Inspect followers with request-budget controls:
  - fetch one followers page with low API cost
  - estimate `top followers` from a bounded sampled subset
  - explicit API budget reporting (`page_requests`, `profile_lookups`, `cache_hits`)
- Export the current collection:
  - `csv`
  - `json`
- Natural-language queries (no command prefix required):
  - `how many followers does lupikovoleg have?`
  - `does @username have stories?`
  - `how many likes does the latest reel have?`
  - `who are the top followers of @username?`
  - `show the last 5 trial reels from this profile from the last week`
  - `export that to csv`
  - paste a profile or reel URL directly
- Session memory:
  - current profile
  - current reel / media
  - recent reels for follow-up questions
  - last collection for export and follow-up actions
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
instagram> followers lupikovoleg 20
instagram> top-followers lupikovoleg 25 10
instagram> reel https://www.instagram.com/reel/XXXXXXXXXXX/
instagram> reels lupikovoleg 5 7 trial
instagram> comments https://www.instagram.com/reel/XXXXXXXXXXX/ 20
instagram> likers https://www.instagram.com/reel/XXXXXXXXXXX/ 20
instagram> export csv latest-trial-reels
instagram> how many followers does lupikovoleg have?
instagram> does @lupikovoleg have stories?
instagram> how many likes does the latest reel have?
instagram> who are the top followers of @lupikovoleg?
instagram> show the last 5 trial reels from this profile from the last week
instagram> export that to csv
```

## Commands

- `help` — show help
- `actions` — show available actions
- `reel <instagram_reel_url>` — fetch reel stats
- `profile <instagram_profile_url_or_username>` — fetch profile stats
- `reels <instagram_profile_url_or_username> [limit] [days_back] [all|trial|main]` — fetch filtered reels
- `comments <instagram_media_url> [limit]` — fetch media comments
- `likers <instagram_media_url> [limit]` — fetch media likers
- `followers <instagram_profile_url_or_username> [limit]` — fetch one follower page
- `top-followers <instagram_profile_url_or_username> [sample_size] [top_n]` — approximate biggest followers
- `export <csv|json> [filename_hint]` — export the most recent collection in session
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
  - `get_profile_reels`
  - `get_followers_page`
  - `get_top_followers`
  - `get_media_comments`
  - `get_media_likers`
  - `rank_media_likers_by_followers`
  - `get_last_reel_metric`
  - `export_session_data`
  - `get_session_context`
- For simple direct input (single URL or username), CLI can call stats endpoints directly.

## Trial Reel Detection

- Trial-vs-main detection uses `/v1/user/clips/chunk`.
- The current heuristic is:
  - `trial`: `product_type == "clips"` and `reshare_count` is missing
  - `main`: reel payload includes `reshare_count`
- This is based on the current HikerAPI documentation and payload behavior.

## Natural-Language Patterns

The agent is configured to handle follow-up context such as:

- `show the last 5 trial reels from this profile from the last week`
- `what about the main reels?`
- `export that to csv`
- `show comments for this post`
- `who liked this reel?`
- `rank those likers by followers`

When the target is omitted, the CLI uses current session context first:

- current profile
- current reel / media
- recent reels
- last fetched collection

## Follower Cost Control

- Default follower-page strategy: `/g2/user/followers`
- `top-followers` is intentionally approximate:
  - it samples a bounded subset of followers
  - then enriches only that subset with profile lookups
  - it reports the request budget used
- This avoids accidental full follower crawls that could burn HikerAPI credits.
- Ranked media likers by follower count can also be expensive because every liker profile must be enriched.
- If you need full-account follower ranking, build it as an explicit batch/export job, not as an open-ended chat request.

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
  - for filtered reel analysis use `reels ...`
  - for audience data use `comments ...` or `likers ...`

## Security Notes

- Do not commit `.env` with real secrets.
- Use separate restricted keys for CI/production.
