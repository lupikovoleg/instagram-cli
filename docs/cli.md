# CLI Guide

This document covers the interactive terminal workflow exposed by `instagram`.

## Interaction Model

The CLI supports two ways of working:

- explicit commands such as `profile`, `reel`, `comments`, or `download`
- natural-language prompts routed through the agent and tool calling

The session keeps short-lived context so follow-up prompts can refer to:

- the current profile
- the current reel or post
- the latest publications or reels list
- the latest search results
- the latest exportable collection
- the latest download result

## Core Commands

General:

- `help` - show help
- `actions` - show common tasks
- `open [url|@username|index|profile|reel]` - open a URL in the default browser
- `update` - fast-forward update the local git repo if remote commits exist
- `render` - show current render mode
- `render <rich|plain>` - switch output mode
- `reload` - reload `.env`
- `last` - print raw JSON for the most recent fetched stats
- `exit` / `quit` - leave the CLI

Profiles and media:

- `profile <instagram_profile_url_or_username>` - fetch profile stats
- `reel <instagram_reel_url>` - fetch reel stats
- `stats <url_or_username>` - auto-detect the target type

Collections:

- `reels <instagram_profile_url_or_username> [limit] [days_back]` - fetch filtered reels
- `publications <instagram_profile_url_or_username> [limit] [days_back] [all|reels|posts|carousels]` - fetch profile publications from the main grid
- `stories [instagram_profile_url_or_username] [limit]` - list active stories
- `highlights [instagram_profile_url_or_username] [limit]` - list highlight folders

Audience data:

- `comments <instagram_media_url> [limit]` - fetch media comments
- `likers <instagram_media_url> [limit]` - fetch media likers
- `followers <instagram_profile_url_or_username> [limit]` - fetch one followers page
- `top-followers <instagram_profile_url_or_username> [sample_size] [top_n]` - estimate biggest followers from a bounded sample

Downloads and exports:

- `download media <instagram_media_url>` - download a reel or post
- `download audio <instagram_media_url>` - download the audio track from a reel or post
- `download stories [instagram_profile_url_or_username] [limit]` - download active stories
- `download highlights [instagram_profile_url_or_username] [title_filter]` - download highlights
- `export <csv|json> [filename_hint]` - export the latest collection in session

Agent controls:

- `ask <question>` - ask the agent directly
- `model` - show the current model
- `model <openrouter_model_id>` - switch the model for the current session

## Natural-Language Examples

Profile and stats:

- `How many followers does @lupikovoleg have?`
- `Does this profile have stories?`
- `Show profile stats for lupikovoleg`

Search and discovery:

- `Find reels about an attack on Dubai`
- `Find today's reels about an attack on Dubai`
- `Search Portugal creators`
- `Open 1`

Profile publications:

- `Show the last 10 publications from this profile`
- `Show the latest carousels from @username`
- `Analyze this profile's publications`
- `Show posts from the last 7 days`

Media audience:

- `Show comments for this reel`
- `Who liked this post?`
- `Rank those likers by followers`

Downloads and exports:

- `Download this reel`
- `Download audio from this reel`
- `Download these stories`
- `Download highlights for this profile`
- `Export that to csv`

## Search Behavior

CLI search is a hybrid pipeline:

- the agent interprets the request
- query expansion can use OpenRouter in CLI mode
- the tool executes multiple HikerAPI `/gql/topsearch` calls
- results are merged and deduplicated
- `media_only` filters keep only posts or reels when requested
- freshness filtering can enrich results with publication timestamps and keep only:
  - `today`
  - `last N days`

This means prompts such as `find today's reels about an attack on Dubai` can use:

- the original topic
- translated variants
- short keyword variants
- freshness filtering after retrieval

## Downloads

Downloaded files are stored under:

- `/path/to/instagram-cli/output/downloads/`

Each download run creates:

- a timestamped directory
- the saved media files
- `metadata.json` with the download plan and saved file paths

Current supported content:

- reels
- posts
- audio tracks when the media payload exposes a direct downloadable track URL
- active stories
- highlights

## Update Checks

On startup, the CLI checks whether the local git repo is behind its upstream branch.

- if new commits exist, the banner shows an update notice
- `update` runs `git pull --ff-only`
- the update is refused if the working tree is dirty or the branch has diverged

## Cost Control

Follower and liker analysis can become expensive very quickly.

Current safeguards:

- follower pages default to `/g2/user/followers`
- `top-followers` is approximate and bounded
- expensive enrichment is capped by default
- request-budget information is surfaced for follower ranking flows

Use explicit batch jobs for full crawls rather than open-ended chat requests.
