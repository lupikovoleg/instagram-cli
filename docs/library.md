# Python Library

`instagram-cli` can be used as a normal Python dependency in another project.

This is additive to the current CLI and MCP flows:

- `instagram` still runs the interactive terminal interface
- `instagram-mcp` still runs the local MCP server
- `InstagramClient` exposes the same deterministic capability layer for direct Python use

## Install

From GitHub:

```bash
pip install git+https://github.com/lupikovoleg/instagram-cli.git
```

From a local checkout:

```bash
cd /path/to/instagram-cli
pip install .
```

## Public API

```python
from instagram_cli import InstagramClient, Settings, create_mcp_server
```

Main public objects:

- `InstagramClient`: stable embeddable client for direct Python use
- `Settings`: configuration loader
- `create_mcp_server`: build the same MCP server used by `instagram-mcp`

## Recommended Integration Modes

Use the package in one of two ways:

### Option A: Direct Python Embedding

Recommended for your own Python product or backend agent runtime.

Use this when:

- your agent already runs inside your backend
- you want the lowest latency and least moving parts
- you want full control over session state, logging, retries, and batch jobs

Flow:

`your LLM runtime -> client.tool_schemas() -> client.call_tool(...) -> tool result -> next LLM turn`

This is the recommended internal integration path.

### Option B: MCP Server

Recommended when the host already speaks MCP or when you want to expose the same tool layer to external MCP clients.

Use this when:

- you want to plug into Claude Desktop, Claude Code, Cursor, or another MCP client
- your host runtime is not tightly coupled to Python imports
- you want a protocol boundary between the model runtime and execution layer

Flow:

`MCP client -> instagram-mcp -> instagram-cli tools`

For most internal Python products, prefer Option A over MCP.

## Quick Example

```python
from instagram_cli import InstagramClient

client = InstagramClient.from_env(
    env_file="/path/to/instagram-cli/.env",
    use_openrouter_search_expansion=False,
)

profile = client.get_profile_stats(target="lupikovoleg")
publications = client.get_profile_publications(
    target="lupikovoleg",
    limit=25,
    publication_type="all",
)

print(profile["profile"]["followers"])
print(publications["count"])
```

## Option A: Direct Python Embedding

This is the simplest way to integrate `instagram-cli` into your own custom agent.

```python
import json

from openai import OpenAI
from instagram_cli import InstagramClient

llm = OpenAI(api_key="...", base_url="https://openrouter.ai/api/v1")
instagram = InstagramClient.from_env(env_file="/path/to/instagram-cli/.env")

messages = [
    {"role": "system", "content": "Use tools for Instagram facts."},
    {"role": "user", "content": "Analyze the latest 25 publications from @lupikovoleg."},
]

response = llm.chat.completions.create(
    model="google/gemini-3-flash-preview",
    messages=messages,
    tools=instagram.tool_schemas(),
    tool_choice="auto",
)

message = response.choices[0].message
for tool_call in message.tool_calls or []:
    arguments = json.loads(tool_call.function.arguments or "{}")
    result = instagram.call_tool(tool_call.function.name, **arguments)
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result, ensure_ascii=False),
        }
    )
```

Notes:

- `InstagramClient` is the recommended public API for direct embedding.
- `tool_schemas()` returns OpenAI-style function schemas for your agent runtime.
- `call_tool(name, **arguments)` is the deterministic execution path.
- This uses the same internal `InstagramOps` layer as the CLI and MCP server.

Runnable example:

```bash
python /path/to/instagram-cli/examples/custom_agent.py \
  --env-file /path/to/instagram-cli/.env \
  "Find today's reels about an attack on Dubai"
```

## Use in a Custom Agent

You can wrap `InstagramClient` methods as tools in any agent framework.

```python
from instagram_cli import InstagramClient

client = InstagramClient.from_env(env_file="/path/to/instagram-cli/.env")

tools = client.tool_schemas()

result = client.call_tool(
    "get_profile_publications",
    target="lupikovoleg",
    limit=25,
    publication_type="all",
)
```

Useful helpers:

- `client.tool_names()`: list supported tool names
- `client.tool_schemas()`: OpenAI-style function schemas derived from the public method signatures
- `client.tool_schemas(names=[...])`: restrict the exposed tool set for a narrower agent
- `client.call_tool(name, **arguments)`: deterministic dispatcher for agent tool execution
- `client.export_collection(...)`: export any result to `csv` or `json`
- `client.summarize_result(...)`: generate a compact summary for agent memory or logs

See the full example agent loop in [examples/custom_agent.py](/Users/oleglupikov/instagram-cli/examples/custom_agent.py).

## Search Behavior

`InstagramClient.search_instagram(...)` defaults to deterministic search expansion.

If you want the same LLM-assisted search expansion used by the interactive CLI:

```python
client = InstagramClient.from_env(
    env_file="/path/to/instagram-cli/.env",
    use_openrouter_search_expansion=True,
)
```

That only affects `search_instagram`. All other methods remain deterministic.

## Configuration

The library uses the same settings model as the CLI:

- default env file: `/path/to/instagram-cli/.env`
- override at runtime:
  - `InstagramClient.from_env(env_file="...")`
  - `Settings.load(env_file="...")`
- or use environment variables directly

Required credentials:

- `HIKERAPI_KEY` or `HIKERAPI_TOKEN`
- `OPENROUTER_API_KEY` only if you enable LLM search expansion

## Backward Compatibility

The library layer is a thin facade over `InstagramOps`.

That means:

- CLI behavior stays on the same internal ops layer
- MCP behavior stays on the same internal ops layer
- adding the public Python API does not replace or fork existing logic

## When to Use What

- Use `instagram` when you want terminal UX and session context.
- Use `InstagramClient` when you want direct Python integration inside another app or agent process.
- Use `instagram-mcp` when the agent runtime already speaks MCP or when you need an MCP boundary for external clients.
