from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
  sys.path.insert(0, str(PROJECT_ROOT))


SYSTEM_PROMPT = (
  "You are an Instagram research assistant backed by deterministic Instagram tools. "
  "Always use tools first for factual Instagram data. "
  "Prefer direct stats tools for exact URLs and usernames. "
  "Use search tools for discovery tasks. "
  "Keep answers concise, practical, and grounded in tool results. "
  "Never invent Instagram numbers."
)


def _build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="custom-agent-example",
    description="Example custom agent that uses instagram-cli as a Python library.",
  )
  parser.add_argument(
    "prompt",
    help="User request for the agent.",
  )
  parser.add_argument(
    "--env-file",
    default=os.getenv("INSTAGRAM_CLI_ENV_FILE"),
    help="Path to the instagram-cli .env file.",
  )
  parser.add_argument(
    "--model",
    default=os.getenv("AGENT_MODEL", "google/gemini-3-flash-preview"),
    help="OpenAI-compatible chat model to use for the custom agent.",
  )
  parser.add_argument(
    "--base-url",
    default=os.getenv("AGENT_BASE_URL", "https://openrouter.ai/api/v1"),
    help="OpenAI-compatible base URL for the custom agent model provider.",
  )
  parser.add_argument(
    "--api-key",
    default=os.getenv("AGENT_API_KEY") or os.getenv("OPENROUTER_API_KEY"),
    help="API key for the custom agent model provider.",
  )
  parser.add_argument(
    "--max-steps",
    type=int,
    default=6,
    help="Maximum number of tool-calling turns.",
  )
  return parser


def _normalize_message_content(content: Any) -> str:
  if isinstance(content, str):
    return content
  if isinstance(content, list):
    parts: list[str] = []
    for item in content:
      if isinstance(item, dict):
        text = item.get("text")
        if isinstance(text, str):
          parts.append(text)
    return "".join(parts)
  return ""


def _extract_tool_calls(message: Any) -> list[Any]:
  tool_calls = getattr(message, "tool_calls", None)
  return tool_calls if isinstance(tool_calls, list) else []


def run_agent(
  *,
  prompt: str,
  env_file: str | None,
  model: str,
  base_url: str,
  api_key: str,
  max_steps: int,
) -> str:
  try:
    from instagram_cli import InstagramClient
  except ImportError as exc:
    raise RuntimeError(
      "Missing instagram-cli dependencies. Install the package environment first, for example: "
      "pip install git+https://github.com/lupikovoleg/instagram-cli.git",
    ) from exc

  try:
    from openai import OpenAI
  except ImportError as exc:
    raise RuntimeError(
      "Missing dependency 'openai'. Install the package environment first, for example: "
      "pip install git+https://github.com/lupikovoleg/instagram-cli.git",
    ) from exc

  if not api_key:
    raise RuntimeError(
      "Missing API key for the custom agent model. "
      "Set AGENT_API_KEY or OPENROUTER_API_KEY.",
    )

  instagram = InstagramClient.from_env(
    env_file=env_file,
    use_openrouter_search_expansion=False,
  )
  llm = OpenAI(api_key=api_key, base_url=base_url)

  messages: list[dict[str, Any]] = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": prompt},
  ]
  tools = instagram.tool_schemas()

  for _ in range(max(1, max_steps)):
    response = llm.chat.completions.create(
      model=model,
      temperature=0,
      messages=messages,
      tools=tools,
      tool_choice="auto",
    )
    message = response.choices[0].message
    assistant_content = _normalize_message_content(getattr(message, "content", None))
    tool_calls = _extract_tool_calls(message)

    assistant_message: dict[str, Any] = {"role": "assistant"}
    if assistant_content:
      assistant_message["content"] = assistant_content
    if tool_calls:
      assistant_message["tool_calls"] = [
        {
          "id": tool_call.id,
          "type": "function",
          "function": {
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
          },
        }
        for tool_call in tool_calls
      ]
    messages.append(assistant_message)

    if not tool_calls:
      return assistant_content.strip()

    for tool_call in tool_calls:
      tool_name = tool_call.function.name
      try:
        arguments = json.loads(tool_call.function.arguments or "{}")
      except json.JSONDecodeError as exc:
        tool_result = {
          "ok": False,
          "error": "invalid_tool_arguments",
          "message": str(exc),
        }
      else:
        try:
          tool_result = instagram.call_tool(tool_name, **arguments)
        except Exception as exc:
          tool_result = {
            "ok": False,
            "error": "tool_execution_failed",
            "message": str(exc),
          }

      messages.append(
        {
          "role": "tool",
          "tool_call_id": tool_call.id,
          "content": json.dumps(tool_result, ensure_ascii=False),
        },
      )

  raise RuntimeError(f"Custom agent stopped after {max_steps} tool-calling steps.")


def main(argv: list[str] | None = None) -> int:
  parser = _build_parser()
  args = parser.parse_args(argv)

  env_file = args.env_file
  if env_file:
    env_file = str(Path(env_file).expanduser().resolve())

  try:
    answer = run_agent(
      prompt=args.prompt,
      env_file=env_file,
      model=args.model,
      base_url=args.base_url,
      api_key=args.api_key,
      max_steps=args.max_steps,
    )
  except Exception as exc:
    print(f"Error: {exc}", file=sys.stderr)
    return 1

  print(answer)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
