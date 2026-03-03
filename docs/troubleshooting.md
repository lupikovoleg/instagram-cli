# Troubleshooting and Configuration

## Environment Variables

Required for the interactive CLI:

- `HIKERAPI_KEY` or `HIKERAPI_TOKEN`
- `OPENROUTER_API_KEY`

Optional:

- `OPENROUTER_BASE_URL` default: `https://openrouter.ai/api/v1`
- `OPENROUTER_CHAT_MODEL` default: `google/gemini-3-flash-preview`
- `OPENROUTER_ANALYSIS_MODEL`
- `OPENROUTER_VISION_MODEL`
- `OPENROUTER_HTTP_REFERER`
- `OPENROUTER_APP_TITLE`
- `HIKERAPI_BASE_URL` default: `https://api.instagrapi.com`
- `PROXY_URL`
- `PROXY_SOCKS5_URL`
- `DEBUG`

The CLI uses its own local `.env` by default:

- `/path/to/instagram-cli/.env`

Override it with:

- `INSTAGRAM_CLI_ENV_FILE=/path/to/custom.env`

## Common Issues

`OpenRouter is not configured`

- check `OPENROUTER_API_KEY` in the CLI `.env`

`HIKERAPI_TOKEN or HIKERAPI_KEY is missing`

- check `HIKERAPI_KEY` or `HIKERAPI_TOKEN`

`rich rendering does not appear`

- run `render plain` to force plain output
- ensure the CLI runs in an interactive TTY rather than piped stdin

Target parsing is wrong

- use an explicit command such as `profile ...`, `reel ...`, `publications ...`, `comments ...`, or `likers ...`

`update` refuses to run

- commit or stash local changes first
- if the branch diverged, update manually instead of relying on `git pull --ff-only`

## Comments Caveat

Instagram comment totals can include threaded replies.

That means:

- media info may say `5` comments total
- a root-comments endpoint may return only `2` items

This does not automatically mean the API truncated the response. It can simply mean:

- `2` root comments
- `3` nested replies

Treat root comment lists and total comment counts as different things.

## Cost and Scope Caveat

Large follower or liker analysis can become very expensive.

Examples:

- exact top followers across tens of thousands of followers
- exact top likers ranked by follower count

Default CLI and MCP tools use bounded strategies to avoid accidental high spend. If you need exact full crawls, implement them as explicit batch jobs with:

- request budgets
- checkpoints
- resume support
- export steps

## Security Notes

- do not commit `.env` with live secrets
- rotate keys that were ever committed to git history
- prefer restricted keys for automation or shared environments
