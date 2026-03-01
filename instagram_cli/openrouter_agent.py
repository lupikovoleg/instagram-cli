from __future__ import annotations

import json
from typing import Any, Callable

from instagram_cli.config import Settings

try:
  from openai import OpenAI
except ImportError:  # pragma: no cover
  OpenAI = None  # type: ignore[assignment]


class OpenRouterAgentError(RuntimeError):
  """Raised for OpenRouter related errors."""


class OpenRouterAgent:
  def __init__(self, settings: Settings) -> None:
    self._settings = settings
    self._client = None
    if settings.openrouter_api_key and OpenAI is not None:
      self._client = OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_headers={
          "HTTP-Referer": settings.openrouter_http_referer,
          "X-Title": settings.openrouter_app_title,
        },
      )

  @property
  def enabled(self) -> bool:
    return self._client is not None

  def _require(self):
    if self._client is None:
      raise OpenRouterAgentError(
        "OpenRouter is not configured. Set OPENROUTER_API_KEY (and optional model vars).",
      )
    return self._client

  @staticmethod
  def _build_system_prompt() -> str:
    return (
      "You are an Instagram analytics assistant. "
      "Prioritize metrics interpretation (likes, comments, saves, views, engagement, publish time, followers, stories, follower quality). "
      "If metrics are missing, say exactly what is missing. "
      "Use concise practical recommendations and avoid generic fluff. "
      "Use clean Markdown when structure helps readability. "
      "When you mention Instagram links, always print the full raw URL visibly. "
      "Do not hide URLs behind Markdown link labels like [Watch](url). "
      "Avoid Markdown tables for search/list outputs that contain links; use numbered lists with the full URL instead. "
      "For any question that asks for concrete Instagram stats, always call tools first. "
      "Use search_instagram only for discovery when the user gives a vague keyword/topic/brand query rather than an exact profile URL, username, or media URL. "
      "If the user gives profile URL/username, use get_profile_stats, get_recent_reels, or get_profile_reels. "
      "If the user gives reel or post URL, use get_reel_stats, get_media_comments, or get_media_likers as needed. "
      "If the user asks to list stories, use get_profile_stories. "
      "If the user asks to list highlights, use get_profile_highlights. "
      "If the user asks about the last week, convert that to days_back=7 unless they specify another range. "
      "If the user asks for the latest or last N reels, use get_profile_reels with the right limit. "
      "Do not claim that you can classify reels into trial/main modes, because this CLI does not support that reliably. "
      "If the user asks about trial reels or main reels, say that this classification is currently unsupported and offer recent reels by date instead. "
      "If the user asks to list followers or inspect follower pages, use get_followers_page first. "
      "If the user asks for biggest/top followers, use get_top_followers. "
      "When using get_top_followers, explicitly say the ranking is approximate and sampled to control API spend. "
      "Keep follower queries conservative by default: use one page and a small sample unless the user explicitly asks for deeper coverage. "
      "If the user asks who liked a post/reel, use get_media_likers. "
      "If the user asks for top/ranked likers by follower count, use rank_media_likers_by_followers, and mention if the liker list may be capped. "
      "If the user asks for comments, commenters, or top comments, start with get_media_comments. "
      "If the user asks to download this reel/post, use download_media_content. "
      "If the user asks to download audio from a reel/post, use download_media_audio. "
      "If the user asks to download the latest or last reel for a profile, first load it with get_profile_reels(limit=1), then use download_media_content without a URL. "
      "If the user asks to download stories, use download_profile_stories. "
      "If the user asks to download highlights, use download_profile_highlights. "
      "If they say 'this profile', 'these stories', 'that reel', or similar, use session context. "
      "For follow-up queries about the latest reel (e.g. likes/views/comments/publication time), use get_last_reel_metric. "
      "If target is omitted in follow-up, infer it from current session context. "
      "If the user asks to export, use export_session_data on the most recent collection already stored in session. "
      "If the user says 'export that', 'save it', or 'download as csv/json', they mean the last collection in session unless they specify another one. "
      "Use get_session_context if references like 'this profile', 'this reel', 'that list', 'previous result', or 'export that' are ambiguous. "
      "Do not perform broad follower crawls unless the user explicitly asks for that depth. "
      "Do not call expensive ranking tools unless the user explicitly asks for ranking/export depth. "
      "Never invent numbers."
    )

  @staticmethod
  def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
      return content
    if isinstance(content, list):
      parts: list[str] = []
      for part in content:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
          parts.append(part["text"])
      return "".join(parts)
    return ""

  def ask(
    self,
    *,
    question: str,
    context: dict[str, Any] | None = None,
    model: str | None = None,
    on_stream_chunk: Callable[[str], None] | None = None,
  ) -> str:
    client = self._require()
    chosen_model = model or self._settings.openrouter_chat_model

    context_json = json.dumps(context or {}, ensure_ascii=False, indent=2)
    user_prompt = (
      f"USER_QUESTION:\n{question.strip()}\n\n"
      f"AVAILABLE_METRICS_CONTEXT_JSON:\n{context_json}"
    )

    stream = client.chat.completions.create(
      model=chosen_model,
      temperature=0.3,
      stream=True,
      messages=[
        {"role": "system", "content": self._build_system_prompt()},
        {"role": "user", "content": user_prompt},
      ],
    )

    chunks: list[str] = []
    for chunk in stream:
      choices = getattr(chunk, "choices", None)
      if not choices:
        continue
      delta = getattr(choices[0], "delta", None)
      if delta is None:
        continue
      text = self._normalize_content(getattr(delta, "content", None))
      if text:
        chunks.append(text)
        if on_stream_chunk:
          for char in text:
            on_stream_chunk(char)
    return "".join(chunks).strip()

  def ask_with_tools(
    self,
    *,
    question: str,
    tool_specs: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]],
    context: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
    model: str | None = None,
    on_stream_chunk: Callable[[str], None] | None = None,
    max_steps: int = 4,
  ) -> str:
    client = self._require()
    chosen_model = model or self._settings.openrouter_chat_model
    context_json = json.dumps(context or {}, ensure_ascii=False, indent=2)

    messages: list[dict[str, Any]] = [
      {"role": "system", "content": self._build_system_prompt()},
      {
        "role": "system",
        "content": (
          "SESSION_CONTEXT_JSON:\n"
          f"{context_json}\n"
          "Use this context as memory and refresh it through tools when needed."
        ),
      },
    ]

    if history:
      for item in history[-8:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
          messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question.strip()})

    steps = 0
    while steps < max_steps:
      steps += 1
      response = client.chat.completions.create(
        model=chosen_model,
        temperature=0.2,
        messages=messages,
        tools=tool_specs,
        tool_choice="auto",
      )

      choice = response.choices[0]
      message = choice.message
      message_content = self._normalize_content(getattr(message, "content", None))
      tool_calls = getattr(message, "tool_calls", None) or []

      if not tool_calls:
        if on_stream_chunk is None:
          return message_content.strip()

        # Real final-token streaming pass for better UX.
        stream_response = client.chat.completions.create(
          model=chosen_model,
          temperature=0.2,
          messages=messages + [
            {
              "role": "system",
              "content": "Now provide final response to the user. Do not call tools.",
            },
          ],
          tools=tool_specs,
          tool_choice="none",
          stream=True,
        )
        streamed_chunks: list[str] = []
        for chunk in stream_response:
          choices = getattr(chunk, "choices", None)
          if not choices:
            continue
          delta = getattr(choices[0], "delta", None)
          if delta is None:
            continue
          text = self._normalize_content(getattr(delta, "content", None))
          if text:
            streamed_chunks.append(text)
            for char in text:
              on_stream_chunk(char)

        streamed_text = "".join(streamed_chunks).strip()
        if streamed_text:
          return streamed_text

        final_text = message_content.strip()
        if final_text:
          for char in final_text:
            on_stream_chunk(char)
        return final_text

      assistant_message: dict[str, Any] = {
        "role": "assistant",
        "content": message_content or "",
        "tool_calls": [],
      }
      for call in tool_calls:
        function = getattr(call, "function", None)
        name = getattr(function, "name", "") if function is not None else ""
        arguments_raw = getattr(function, "arguments", "{}") if function is not None else "{}"
        call_id = getattr(call, "id", "")
        assistant_message["tool_calls"].append(
          {
            "id": call_id,
            "type": "function",
            "function": {
              "name": name,
              "arguments": arguments_raw,
            },
          },
        )
      messages.append(assistant_message)

      for call in tool_calls:
        function = getattr(call, "function", None)
        name = getattr(function, "name", "") if function is not None else ""
        arguments_raw = getattr(function, "arguments", "{}") if function is not None else "{}"
        call_id = getattr(call, "id", "")
        try:
          parsed_args = json.loads(arguments_raw) if arguments_raw else {}
          if not isinstance(parsed_args, dict):
            parsed_args = {}
        except json.JSONDecodeError:
          parsed_args = {}

        try:
          tool_result = tool_executor(name, parsed_args)
        except Exception as exc:
          tool_result = {"ok": False, "error": f"tool_execution_failed:{exc}"}

        messages.append(
          {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": json.dumps(tool_result, ensure_ascii=False),
          },
        )
    fallback = (
      "Could not complete the request within the tool-step limit. "
      "Please clarify the request or share a valid profile/reel link or username."
    )
    if on_stream_chunk:
      for char in fallback:
        on_stream_chunk(char)
    return fallback
