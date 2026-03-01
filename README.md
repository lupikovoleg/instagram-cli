# Instagram CLI

Terminal-first Instagram analytics: profile and Reels stats + an agent with tool calling for natural-language queries.

```text
 ___ _   _ ____ _____  _    ____ ____      _    __  __      ____ _     ___
|_ _| \ | / ___|_   _|/ \  / ___|  _ \    / \  |  \/  |    / ___| |   |_ _|
 | ||  \| \___ \ | | / _ \| |  _| |_) |  / _ \ | |\/| |   | |   | |    | |
 | || |\  |___) || |/ ___ \ |_| |  _ <  / ___ \| |  | |   | |___| |___ | |
|___|_| \_|____/ |_/_/   \_\____|_| \_\/_/   \_\_|  |_|    \____|_____|___|
                           INSTAGRAM-CLI by @lupikovoleg
```

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
- Fetch filtered profile reels:
  - latest reels
  - reels from the last `N` days
- List ephemeral/profile collections:
  - active stories
  - highlight folders
- Fetch media audience data:
  - media comments
  - media likers
  - ranked likers by follower count
- Download content to local files:
  - reels and posts
  - media audio tracks when the payload exposes a downloadable audio URL
  - active stories
  - highlights
  - download metadata JSON with saved paths
- Inspect followers with request-budget controls:
  - fetch one followers page with low API cost
  - estimate `top followers` from a bounded sampled subset
  - explicit API budget reporting (`page_requests`, `profile_lookups`, `cache_hits`)
- Export the current collection:
  - `csv`
  - `json`
- Natural-language queries (no command prefix required):
  - `search portugal creators`
  - `how many followers does lupikovoleg have?`
  - `does @username have stories?`
  - `how many likes does the latest reel have?`
  - `who are the top followers of @username?`
  - `show the last 5 reels from this profile from the last week`
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
cd /path/to/instagram-cli
./install.sh
```

After install, run:

```bash
instagram
```

## First Run Setup

This CLI uses its **own** `.env` file.

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
instagram> search portugal creators
instagram> open 1
instagram> update
instagram> followers lupikovoleg 20
instagram> top-followers lupikovoleg 25 10
instagram> reel https://www.instagram.com/reel/XXXXXXXXXXX/
instagram> reels lupikovoleg 5 7
instagram> stories lupikovoleg
instagram> highlights lupikovoleg
instagram> comments https://www.instagram.com/reel/XXXXXXXXXXX/ 20
instagram> likers https://www.instagram.com/reel/XXXXXXXXXXX/ 20
instagram> download media https://www.instagram.com/reel/XXXXXXXXXXX/
instagram> download audio https://www.instagram.com/reel/XXXXXXXXXXX/
instagram> download stories lupikovoleg
instagram> download highlights lupikovoleg
instagram> export csv latest-reels
instagram> how many followers does lupikovoleg have?
instagram> does @lupikovoleg have stories?
instagram> how many likes does the latest reel have?
instagram> who are the top followers of @lupikovoleg?
instagram> show the last 5 reels from this profile from the last week
instagram> show this profile's stories
instagram> show this profile's highlights
instagram> export that to csv
instagram> download this reel
instagram> download audio from this reel
instagram> download the latest reel from this profile
instagram> download these stories
```

## Commands

- `help` — show help
- `actions` — show available actions
- `reel <instagram_reel_url>` — fetch reel stats
- `search <query>` — discover profiles/media by keyword
- `open [url|@username|index|profile|reel]` — open a URL in the default browser
- `profile <instagram_profile_url_or_username>` — fetch profile stats
- `reels <instagram_profile_url_or_username> [limit] [days_back]` — fetch filtered reels
- `stories [instagram_profile_url_or_username] [limit]` — list active stories
- `highlights [instagram_profile_url_or_username] [limit]` — list highlight folders
- `comments <instagram_media_url> [limit]` — fetch media comments
- `likers <instagram_media_url> [limit]` — fetch media likers
- `download media <instagram_media_url>` — download a reel or post
- `download audio <instagram_media_url>` — download the audio track from a reel or post
- `download stories [instagram_profile_url_or_username] [limit]` — download active stories
- `download highlights [instagram_profile_url_or_username] [title_filter]` — download highlights
- `followers <instagram_profile_url_or_username> [limit]` — fetch one follower page
- `top-followers <instagram_profile_url_or_username> [sample_size] [top_n]` — approximate biggest followers
- `export <csv|json> [filename_hint]` — export the most recent collection in session
- `stats <url_or_username>` — auto-detect target type
- `ask <question>` — ask the agent
- `model` — show current model
- `model <openrouter_model_id>` — switch model for current session
- `update` — fast-forward update the local git repo if remote commits exist
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
  - `search_instagram`
  - `get_profile_stats`
  - `get_reel_stats`
  - `get_recent_reels`
  - `get_profile_reels`
  - `get_profile_stories`
  - `get_profile_highlights`
  - `get_followers_page`
  - `get_top_followers`
  - `get_media_comments`
  - `download_media_content`
  - `download_media_audio`
  - `download_profile_stories`
  - `download_profile_highlights`
  - `get_media_likers`
  - `rank_media_likers_by_followers`
  - `get_last_reel_metric`
  - `export_session_data`
  - `get_session_context`
- For simple direct input (single URL or username), CLI can call stats endpoints directly.

## Repo Updates

- On startup, the CLI checks whether the local git repo is behind its upstream branch.
- If new commits exist, the banner shows an update notice.
- To update safely, run:

```text
update
```

Behavior:

- uses `git pull --ff-only`
- refuses to update if the working tree is dirty
- refuses automatic update if the branch diverged

## Natural-Language Patterns

The agent is configured to handle follow-up context such as:

- `search portugal creators`
- `open 1`
- `show the last 5 reels from this profile from the last week`
- `show this profile's stories`
- `show this profile's highlights`
- `export that to csv`
- `show comments for this post`
- `who liked this reel?`
- `rank those likers by followers`
- `download this reel`
- `download audio from this reel`
- `download the latest reel from this profile`
- `download these stories`
- `download highlights for this profile`

When the target is omitted, the CLI uses current session context first:

- current search results
- current profile
- current reel / media
- recent reels
- last fetched collection
- last download result

## Downloads

Downloaded files are stored under:

- `/path/to/instagram-cli/output/downloads/`

Each download run creates:

- a timestamped directory
- the saved media files
- `metadata.json` with the source plan and file paths

Notes:

- Reels and posts are downloaded from media payload URLs.
- Audio download uses a direct track URL from the media payload when available.
- Stories are downloaded from the active stories feed.
- Highlights are resolved in two steps:
  - `/v1/user/highlights` for folders
  - `/v1/highlight/by/id` for highlight items

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
