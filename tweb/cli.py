from __future__ import annotations

import argparse
import importlib.resources
import logging
import os
import shutil
from pathlib import Path

from .api import TWebDocument
from .config import ConfigError, DEFAULT_CONFIG_PATH, load_runtime_config
from .cookies import (
  CookieLoadError,
  build_cookie_jar,
  load_cookie_file,
  load_firefox_cookie_jar,
  load_zen_cookie_jar,
  merge_cookie_jars,
)
from .fetcher import (
  FetchError,
  create_session,
  fetch_resource,
  override_default_headers,
  reset_default_headers,
)
from .js_runtime import JavaScriptRuntimeError
from .parser import parse_document
from .renderers.dom import render_dom
from .renderers.normal import render_normal
from .tui import run_tui_browser

DEFAULT_TARGET = str(importlib.resources.files("tweb").joinpath("data", "welcome.html"))
DEBUG_LOG_PATH = Path("debug.log")
DEBUG_LOGGER_NAME = "tweb"
CLI_PROG = "tw"
CLI_ERROR_PREFIX = f"{CLI_PROG}:"


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog=CLI_PROG,
    description="Open a web page in the TUI by default, or render text and DOM output with --mode.",
    epilog=(
      "Modes:\n"
      "  tui     interactive Textual browser (default)\n"
      "  text    human-oriented text output\n"
      "  dom     summarized DOM tree for inspection\n"
      "  dom-ai  detailed DOM tree for agents/tools\n"
      "\n"
      "Examples:\n"
      "  tw\n"
      "  tw https://example.com\n"
      "  tw https://example.com --mode dom --max-depth 2\n"
      "  tw ./page.html --mode text\n"
      "  tw https://example.com/private --cookie-file cookies.txt\n"
    ),
    formatter_class=argparse.RawDescriptionHelpFormatter,
  )
  parser.add_argument(
    "target",
    nargs="?",
    default=DEFAULT_TARGET,
    help="URL or local HTML file path; defaults to the welcome page when omitted; schemeless hosts default to http://",
  )
  _add_runtime_arguments(parser, include_mode=True)
  parser.add_argument(
    "--link-style",
    choices=("inline", "none"),
    default="none",
    help="How to show links in text mode",
  )
  parser.add_argument(
    "--max-depth",
    type=int,
    help="Maximum tree depth in DOM and dom-ai modes",
  )
  parser.add_argument(
    "--include-script-like",
    action="store_true",
    help="Include full script/style nodes in DOM and dom-ai modes",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_parser()
  args = parser.parse_args(argv)
  reset_default_headers()
  _apply_runtime_config(parser)
  debug_log_path = Path(args.debug_log) if args.debug_log is not None else DEBUG_LOG_PATH
  logger = _configure_debug_logging(enabled=args.debug or args.debug_log is not None, path=debug_log_path)
  if logger is not None:
    logger.debug("argv=%s", argv if argv is not None else [])
    logger.debug("parsed arguments=%s", vars(args))
  width = _resolve_width(args.width)
  session = _build_session(
    args.cookie,
    args.cookie_file,
    cookie_file_format=args.cookie_file_format,
    browser=args.cookie_from_browser,
    browser_profile=args.browser_profile,
    cookie_domains=args.cookie_domain,
    parser=parser,
  )

  try:
    try:
      if logger is not None:
        logger.debug("fetching target=%s mode=%s", args.target, args.mode)
      resource = fetch_resource(args.target, encoding=args.encoding, session=session)
      if logger is not None:
        logger.debug("fetched resource source=%s size=%d", resource.source, len(resource.content))
    except FetchError as exc:
      if logger is not None:
        logger.exception("fetch failed for %s", args.target)
      parser.exit(status=1, message=f"{CLI_ERROR_PREFIX} {exc}\n")

    scripts = _load_scripts(args.script, args.script_file, parser)
    if logger is not None and scripts:
      logger.debug("loaded scripts inline=%d file=%d", len(args.script), len(args.script_file))
    if args.mode == "tui":
      if logger is not None:
        logger.debug("starting tui source=%s width=%s", args.target, width)
      return run_tui_browser(
        args.target,
        encoding=args.encoding,
        width=width,
        scripts=scripts,
        session=session,
        browser_render_policy=args.browser_render,
        button_click_policy=args.button_click_policy,
        use_script_cache=not args.no_script_cache,
        debug_block_colors=args.debug_block_colors,
      )

    document = TWebDocument(parse_document(resource))
    if logger is not None:
      logger.debug("executing embedded scripts policy=%s", args.browser_render)
    document.execute_embedded_scripts(
      ignore_errors=True,
      session=session,
      browser_render_policy=args.browser_render,
      use_script_cache=not args.no_script_cache,
    )
    for script in scripts:
      try:
        if logger is not None:
          logger.debug("executing injected script chars=%d", len(script))
        document.execute_script(script, session=session)
      except JavaScriptRuntimeError as exc:
        if logger is not None:
          logger.exception("javascript execution failed")
        parser.exit(status=1, message=f"{CLI_ERROR_PREFIX} JavaScript error: {exc}\n")

    if args.mode in {"dom", "dom-ai"}:
      if logger is not None:
        logger.debug("rendering dom variant=%s max_depth=%s", args.mode, args.max_depth)
      print(
        render_dom(
          document.document,
          max_depth=args.max_depth,
          skip_script_like=not args.include_script_like,
          variant="ai" if args.mode == "dom-ai" else "summary",
          viewport_columns=max(width, 160),
          session=session,
        )
      )
      return 0

    if logger is not None:
      logger.debug("rendering normal width=%d link_style=%s", width, args.link_style)
    print(
      render_normal(
        document.document,
        width=width,
        link_style=args.link_style,
        session=session,
      )
    )
    return 0
  finally:
    if session is not None and args.mode != "tui":
      session.close()


def tw_main(argv: list[str] | None = None) -> int:
  return main(argv)


def main_from_path(
  path: str | Path,
  mode: str = "text",
  link_style: str = "none",
) -> str:
  if mode == "tui":
    raise ValueError("main_from_path does not support tui mode")
  resource = fetch_resource(str(path))
  document = TWebDocument(parse_document(resource))
  if mode == "normal":
    mode = "text"
  if mode in {"dom", "dom-ai"}:
    return render_dom(
      document.document,
      variant="ai" if mode == "dom-ai" else "summary",
      viewport_columns=160,
    )
  return render_normal(document.document, link_style=link_style)


def _load_scripts(
  inline_scripts: list[str],
  script_files: list[str],
  parser: argparse.ArgumentParser,
) -> list[str]:
  scripts = list(inline_scripts)
  for script_path in script_files:
    try:
      scripts.append(Path(script_path).read_text(encoding="utf-8"))
    except OSError as exc:
      parser.exit(status=1, message=f"{CLI_ERROR_PREFIX} failed to read script file {script_path}: {exc}\n")
  return scripts


def _add_runtime_arguments(
  parser: argparse.ArgumentParser,
  *,
  include_mode: bool,
  help_context: str = "rendering",
) -> None:
  width_help = "Render width. Defaults to the current terminal width"
  if include_mode:
    width_help += "; also used by TUI"
    parser.add_argument(
      "--mode",
      choices=("text", "dom", "dom-ai", "tui"),
      default="tui",
      help="Render mode: interactive TUI, text, summarized DOM, or detailed DOM",
    )
  parser.add_argument(
    "--width",
    type=int,
    help=width_help,
  )
  parser.add_argument(
    "--encoding",
    help="Override file decoding when reading local files",
  )
  parser.add_argument(
    "--debug",
    action="store_true",
    help=f"Write debug logging to {DEBUG_LOG_PATH}",
  )
  parser.add_argument(
    "--debug-log",
    help=f"Path to write debug logging; implies --debug and defaults to {DEBUG_LOG_PATH}",
  )
  parser.add_argument(
    "--browser-render",
    choices=("never", "auto", "always"),
    default="auto",
    help="How to use optional browser-render fallback for remote pages after quick.js: never, auto on clear client-render failure or client-render bailouts, or always",
  )
  parser.add_argument(
    "--script",
    action="append",
    default=[],
    help=f"Inline JavaScript to run before {help_context}; may be specified multiple times",
  )
  parser.add_argument(
    "--script-file",
    action="append",
    default=[],
    help=f"Path to a JavaScript file to run before {help_context}; may be specified multiple times",
  )
  parser.add_argument(
    "--no-script-cache",
    action="store_true",
    help="Disable in-memory external script reuse and force refetch or revalidation on each load",
  )
  parser.add_argument(
    "--debug-block-colors",
    action="store_true",
    help="In TUI mode, color each detected render block with a different background for layout debugging",
  )
  parser.add_argument(
    "--cookie",
    action="append",
    default=[],
    help="Cookie to send with HTTP/HTTPS requests in NAME=VALUE form; may be specified multiple times",
  )
  parser.add_argument(
    "--cookie-file",
    action="append",
    default=[],
    help="Path to a cookie file in name=value, Netscape, or JSON format; may be specified multiple times",
  )
  parser.add_argument(
    "--cookie-file-format",
    choices=("auto", "namevalue", "netscape", "json"),
    default="auto",
    help="Format used by --cookie-file; defaults to auto-detection",
  )
  parser.add_argument(
    "--cookie-from-browser",
    choices=("firefox", "zen"),
    help="Import cookies directly from an installed browser profile",
  )
  parser.add_argument(
    "--browser-profile",
    help="Browser profile name or path used with --cookie-from-browser",
  )
  parser.add_argument(
    "--cookie-domain",
    action="append",
    default=[],
    help="Restrict imported browser cookies to this domain; may be specified multiple times",
  )
  _add_button_click_policy_argument(parser)


def _add_button_click_policy_argument(parser: argparse.ArgumentParser) -> None:
  parser.add_argument(
    "--button-click-policy",
    choices=("off", "dom-only", "network"),
    default="network",
    help="How TUI treats JavaScript-driven type=button clicks: block them, allow DOM-only updates while blocking fetch/XHR/location changes, or allow network/navigation requests (default: network)",
  )

def _resolve_width(width: int | None) -> int:
  if width is not None:
    return width
  return shutil.get_terminal_size(fallback=(80, 24)).columns


def _configure_debug_logging(*, enabled: bool, path: Path = DEBUG_LOG_PATH) -> logging.Logger | None:
  logger = logging.getLogger(DEBUG_LOGGER_NAME)
  if not enabled:
    _remove_debug_handler(logger)
    logger.setLevel(logging.NOTSET)
    logger.propagate = False
    return None

  _remove_debug_handler(logger)
  if path.parent != Path():
    path.parent.mkdir(parents=True, exist_ok=True)
  handler = logging.FileHandler(path, mode="w", encoding="utf-8")
  handler.set_name("tweb-debug-file")
  handler.setLevel(logging.DEBUG)
  handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
  logger.addHandler(handler)
  logger.setLevel(logging.DEBUG)
  logger.propagate = False
  logger.debug("debug logging enabled file=%s", path.resolve())
  return logger


def _remove_debug_handler(logger: logging.Logger) -> None:
  for handler in list(logger.handlers):
    if handler.get_name() != "tweb-debug-file":
      continue
    logger.removeHandler(handler)
    handler.close()


def _apply_runtime_config(parser: argparse.ArgumentParser) -> None:
  config_path = os.environ.get("TW_CONFIG_PATH")
  try:
    config = load_runtime_config(Path(config_path) if config_path else DEFAULT_CONFIG_PATH)
  except ConfigError as exc:
    parser.exit(status=1, message=f"{CLI_ERROR_PREFIX} {exc}\n")
  if config.headers:
    override_default_headers(config.headers)


def _build_session(
  inline_cookies: list[str],
  cookie_files: list[str],
  *,
  cookie_file_format: str,
  browser: str | None,
  browser_profile: str | None,
  cookie_domains: list[str],
  parser: argparse.ArgumentParser,
):
  inline_pairs: list[tuple[str, str]] = []
  for raw_cookie in inline_cookies:
    name, value = _parse_cookie(raw_cookie, source="command line", parser=parser)
    inline_pairs.append((name, value))

  cookie_jar = build_cookie_jar(inline_pairs)
  for cookie_file in cookie_files:
    try:
      cookie_jar = merge_cookie_jars(cookie_jar, load_cookie_file(cookie_file, format_name=cookie_file_format))
    except CookieLoadError as exc:
      parser.exit(status=1, message=f"{CLI_ERROR_PREFIX} {exc}\n")

  if browser == "firefox":
    try:
      cookie_jar = merge_cookie_jars(
        cookie_jar,
        load_firefox_cookie_jar(profile=browser_profile, domains=cookie_domains),
      )
    except CookieLoadError as exc:
      parser.exit(status=1, message=f"{CLI_ERROR_PREFIX} {exc}\n")
  if browser == "zen":
    try:
      cookie_jar = merge_cookie_jars(
        cookie_jar,
        load_zen_cookie_jar(profile=browser_profile, domains=cookie_domains),
      )
    except CookieLoadError as exc:
      parser.exit(status=1, message=f"{CLI_ERROR_PREFIX} {exc}\n")

  if not list(cookie_jar):
    return None
  return create_session(cookie_jar)


def _parse_cookie(
  raw_cookie: str,
  *,
  source: str,
  parser: argparse.ArgumentParser,
) -> tuple[str, str]:
  if "=" not in raw_cookie:
    parser.exit(status=1, message=f"{CLI_ERROR_PREFIX} invalid cookie in {source}: {raw_cookie!r}; expected NAME=VALUE\n")
  name, value = raw_cookie.split("=", 1)
  name = name.strip()
  if not name:
    parser.exit(status=1, message=f"{CLI_ERROR_PREFIX} invalid cookie in {source}: empty cookie name\n")
  return (name, value)
