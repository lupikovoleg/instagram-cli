from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env_bool(name: str, default: bool = False) -> bool:
  raw = os.getenv(name)
  if raw is None:
    return default
  return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_project_root() -> Path:
  return Path(__file__).resolve().parent.parent


def get_env_file_path() -> Path:
  override = os.getenv("INSTAGRAM_CLI_ENV_FILE")
  if override:
    return Path(override).expanduser().resolve()
  return (get_project_root() / ".env").resolve()


def load_env_file() -> list[Path]:
  env_path = get_env_file_path()
  loaded: list[Path] = []
  if env_path.exists():
    # Use own .env as source of truth for this CLI.
    load_dotenv(env_path, override=True)
    loaded.append(env_path)
  return loaded


def _quote_env_value(value: str) -> str:
  # Keep plain values when safe; quote only when needed.
  if re.fullmatch(r"[A-Za-z0-9_./:@+\-]+", value):
    return value
  escaped = value.replace("\\", "\\\\").replace('"', '\\"')
  return f'"{escaped}"'


def upsert_env_values(env_path: Path, values: dict[str, str]) -> None:
  env_path.parent.mkdir(parents=True, exist_ok=True)

  existing_lines: list[str] = []
  if env_path.exists():
    existing_lines = env_path.read_text(encoding="utf-8").splitlines()

  key_pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
  line_index_by_key: dict[str, int] = {}
  for idx, line in enumerate(existing_lines):
    match = key_pattern.match(line)
    if match:
      line_index_by_key[match.group(1)] = idx

  for key, value in values.items():
    rendered = f"{key}={_quote_env_value(value)}"
    if key in line_index_by_key:
      existing_lines[line_index_by_key[key]] = rendered
    else:
      existing_lines.append(rendered)

  env_path.write_text("\n".join(existing_lines).strip() + "\n", encoding="utf-8")


@dataclass
class Settings:
  loaded_env_files: list[Path]
  env_file: Path

  openrouter_api_key: str | None
  openrouter_base_url: str
  openrouter_analysis_model: str
  openrouter_chat_model: str
  openrouter_vision_model: str
  openrouter_http_referer: str
  openrouter_app_title: str

  hikerapi_token: str | None
  hikerapi_key: str | None
  hikerapi_base_url: str
  proxy_url: str | None
  proxy_socks5_url: str | None
  debug: bool

  @property
  def hiker_access_key(self) -> str | None:
    return self.hikerapi_token or self.hikerapi_key

  @property
  def needs_bootstrap(self) -> bool:
    return (self.openrouter_api_key or "").strip() == "" or (self.hiker_access_key or "").strip() == ""

  @classmethod
  def load(cls) -> "Settings":
    loaded_env_files = load_env_file()
    env_file = get_env_file_path()
    return cls(
      loaded_env_files=loaded_env_files,
      env_file=env_file,
      openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
      openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
      openrouter_analysis_model=os.getenv("OPENROUTER_ANALYSIS_MODEL", "google/gemini-3-flash-preview"),
      openrouter_chat_model=os.getenv("OPENROUTER_CHAT_MODEL", "google/gemini-3-flash-preview"),
      openrouter_vision_model=os.getenv("OPENROUTER_VISION_MODEL", "google/gemini-3-flash-preview"),
      openrouter_http_referer=os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost:3000"),
      openrouter_app_title=os.getenv("OPENROUTER_APP_TITLE", "ReteNZA"),
      hikerapi_token=os.getenv("HIKERAPI_TOKEN"),
      hikerapi_key=os.getenv("HIKERAPI_KEY"),
      hikerapi_base_url=os.getenv("HIKERAPI_BASE_URL", "https://api.instagrapi.com"),
      proxy_url=os.getenv("PROXY_URL"),
      proxy_socks5_url=os.getenv("PROXY_SOCKS5_URL"),
      debug=_env_bool("DEBUG", default=False),
    )
