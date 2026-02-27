from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from instagram_cli.config import Settings, upsert_env_values
from instagram_cli.repl import run_repl, write_shell_wrapper


def _build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="instagram",
    description="Interactive Instagram stats + AI analysis CLI.",
  )
  parser.add_argument(
    "--install-wrapper",
    action="store_true",
    help="Create ~/.local/bin/instagram wrapper for this Python interpreter.",
  )
  parser.add_argument(
    "--wrapper-path",
    default=str(Path.home() / ".local" / "bin" / "instagram"),
    help="Where to create wrapper when --install-wrapper is used.",
  )
  return parser


def _prompt_required(label: str, *, secret: bool = False) -> str:
  while True:
    try:
      value = getpass.getpass(f"{label}: ") if secret else input(f"{label}: ")
    except (KeyboardInterrupt, EOFError):
      print("\nSetup cancelled.")
      raise SystemExit(1)
    value = value.strip()
    if value:
      return value
    print("Value is required.")


def _print_setup_intro(env_path: Path) -> None:
  print("\n" + "=" * 64)
  print("Instagram CLI first-time setup")
  print("=" * 64)
  print(f"Config file: {env_path}")
  print("Enter API keys once. They will be saved to this local .env file.\n")


def _print_post_setup_help() -> None:
  print("\n" + "=" * 64)
  print("Setup complete")
  print("=" * 64)
  print("Try these commands:")
  print("  instagram")
  print("  profile lupikovoleg")
  print("  reel https://www.instagram.com/reel/<code>/")
  print("  how many followers does lupikovoleg have?")
  print("  how many likes does the latest reel have?")
  print("  help")
  print("=" * 64 + "\n")


def _ensure_bootstrapped_settings(settings: Settings) -> Settings:
  if not settings.needs_bootstrap:
    return settings

  if not sys.stdin.isatty():
    print(
      "Missing required keys in instagram-cli .env and no interactive stdin available.\n"
      f"Please fill {settings.env_file} with OPENROUTER_API_KEY and HIKERAPI_KEY (or HIKERAPI_TOKEN).",
    )
    raise SystemExit(1)

  _print_setup_intro(settings.env_file)

  hiker_value = (settings.hiker_access_key or "").strip()
  if not hiker_value:
    hiker_value = _prompt_required("HikerAPI key", secret=True)

  openrouter_value = (settings.openrouter_api_key or "").strip()
  if not openrouter_value:
    openrouter_value = _prompt_required("OpenRouter API key", secret=True)

  values = {
    "HIKERAPI_KEY": hiker_value,
    "OPENROUTER_API_KEY": openrouter_value,
    "OPENROUTER_BASE_URL": settings.openrouter_base_url,
    "OPENROUTER_CHAT_MODEL": settings.openrouter_chat_model,
    "OPENROUTER_ANALYSIS_MODEL": settings.openrouter_analysis_model,
    "OPENROUTER_VISION_MODEL": settings.openrouter_vision_model,
    "OPENROUTER_HTTP_REFERER": settings.openrouter_http_referer,
    "OPENROUTER_APP_TITLE": settings.openrouter_app_title,
    "HIKERAPI_BASE_URL": settings.hikerapi_base_url,
    "DEBUG": "true" if settings.debug else "false",
  }
  if settings.proxy_url:
    values["PROXY_URL"] = settings.proxy_url
  if settings.proxy_socks5_url:
    values["PROXY_SOCKS5_URL"] = settings.proxy_socks5_url

  upsert_env_values(settings.env_file, values)

  fresh_settings = Settings.load()
  if fresh_settings.needs_bootstrap:
    print("Setup failed: required keys are still missing in .env")
    raise SystemExit(1)

  _print_post_setup_help()
  return fresh_settings


def main(argv: list[str] | None = None) -> int:
  parser = _build_parser()
  args = parser.parse_args(argv)

  if args.install_wrapper:
    wrapper_path = Path(args.wrapper_path).expanduser()
    python_bin = Path(sys.executable).resolve()
    write_shell_wrapper(wrapper_path, python_bin)
    print(f"Wrapper created: {wrapper_path}")
    return 0

  settings = Settings.load()
  settings = _ensure_bootstrapped_settings(settings)
  return run_repl(settings)


if __name__ == "__main__":
  raise SystemExit(main())
