from __future__ import annotations

import subprocess
import sys
from tempfile import NamedTemporaryFile
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
import os
from unittest.mock import Mock, patch

from tweb.cookies import build_cookie_jar
from tweb.cli import DEBUG_LOG_PATH, DEFAULT_TARGET, _resolve_width, main, tw_main
from tweb.fetcher import DEFAULT_HEADERS, reset_default_headers
from tweb.renderers.normal import ANSI_BOLD, ANSI_BOLD_RESET

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample.html"
JS_DOM = ROOT / "tests" / "fixtures" / "js_dom.html"
UPDATE_TITLE = ROOT / "tests" / "fixtures" / "update_title.js"


class CliTest(unittest.TestCase):
  def tearDown(self) -> None:
    reset_default_headers()

  def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
      [sys.executable, "-m", "tweb", *args],
      cwd=ROOT,
      text=True,
      capture_output=True,
      check=False,
    )

  def run_cli_with_env(self, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
      [sys.executable, "-m", "tweb", *args],
      cwd=ROOT,
      text=True,
      capture_output=True,
      check=False,
      env=merged_env,
    )

  def run_main_file(self, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
      [sys.executable, str(ROOT / "tweb" / "__main__.py"), *args],
      cwd=ROOT,
      text=True,
      capture_output=True,
      check=False,
    )

  def test_normal_mode(self) -> None:
    result = self.run_cli(str(SAMPLE), "--mode", "text")
    self.assertEqual(result.returncode, 0)
    self.assertIn("tweb sample", result.stdout)
    self.assertIn(f"# {ANSI_BOLD}Welcome to tweb{ANSI_BOLD_RESET}", result.stdout)
    self.assertIn("the documentation", result.stdout)
    self.assertNotIn("[1]", result.stdout)
    self.assertNotIn("https://example.com/docs", result.stdout)

  def test_normal_mode_defaults_to_welcome_page_when_target_is_omitted(self) -> None:
    result = self.run_cli("--mode", "text")
    self.assertEqual(result.returncode, 0)
    self.assertEqual(Path(DEFAULT_TARGET).name, "welcome.html")
    self.assertIn("tweb welcome", result.stdout)
    self.assertIn(f"# {ANSI_BOLD}Welcome to tweb{ANSI_BOLD_RESET}", result.stdout)

  def test_main_file_mode(self) -> None:
    result = self.run_main_file(str(SAMPLE), "--mode", "text")
    self.assertEqual(result.returncode, 0)
    self.assertIn("tweb sample", result.stdout)

  def test_cli_help_describes_modes_and_examples(self) -> None:
    result = self.run_cli("-h")
    self.assertEqual(result.returncode, 0)
    self.assertIn("Open a web page in the TUI by default", result.stdout)
    self.assertIn("Modes:", result.stdout)
    self.assertIn("tw", result.stdout)
    self.assertIn("tw https://example.com --mode dom --max-depth 2", result.stdout)

  def test_dom_mode(self) -> None:
    result = self.run_cli(str(SAMPLE), "--mode", "dom")
    self.assertEqual(result.returncode, 0)
    self.assertIn("#document", result.stdout)
    self.assertIn("- <html>", result.stdout)
    self.assertIn('- <h1> text="Welcome to tweb"', result.stdout)

  def test_dom_mode_max_depth(self) -> None:
    result = self.run_cli(str(SAMPLE), "--mode", "dom", "--max-depth", "1")
    self.assertEqual(result.returncode, 0)
    self.assertIn("... 5 child nodes", result.stdout)
    self.assertIn("... 3 child nodes", result.stdout)

  def test_dom_ai_mode(self) -> None:
    result = self.run_cli(str(SAMPLE), "--mode", "dom-ai")
    self.assertEqual(result.returncode, 0)
    self.assertIn("type=element tag=html parent=document", result.stdout)
    self.assertIn(
      'type=element tag=a parent=',
      result.stdout,
    )
    self.assertIn(
      'attrs={"href": "https://example.com/docs"}',
      result.stdout,
    )
    self.assertIn('type=text', result.stdout)

  def test_inline_link_style(self) -> None:
    result = self.run_cli(str(SAMPLE), "--mode", "text", "--link-style", "inline")
    self.assertEqual(result.returncode, 0)
    self.assertIn("the documentation (https://example.com/docs)", result.stdout)
    self.assertNotIn("\n\nLinks\n\n", result.stdout)

  def test_none_link_style(self) -> None:
    result = self.run_cli(str(SAMPLE), "--mode", "text", "--link-style", "none")
    self.assertEqual(result.returncode, 0)
    self.assertIn("the documentation", result.stdout)
    self.assertNotIn("[1]", result.stdout)
    self.assertNotIn("https://example.com/docs", result.stdout)
    self.assertNotIn("\n\nLinks\n\n", result.stdout)

  def test_footnote_link_style_is_rejected(self) -> None:
    result = self.run_cli(str(SAMPLE), "--link-style", "footnote")
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("invalid choice", result.stderr)
    self.assertIn("footnote", result.stderr)

  @patch("tweb.cli.render_normal", return_value="rendered")
  @patch("tweb.cli.fetch_resource")
  @patch("tweb.cli._resolve_width", return_value=132)
  def test_uses_terminal_width_when_width_is_omitted(
    self,
    mock_resolve_width: Mock,
    mock_fetch_resource: Mock,
    mock_render_normal: Mock,
  ) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()

    result = main([str(SAMPLE), "--mode", "text"])

    self.assertEqual(result, 0)
    mock_resolve_width.assert_called_once_with(None)
    self.assertEqual(mock_render_normal.call_args.kwargs["width"], 132)

  @patch("tweb.cli.render_normal", return_value="rendered")
  @patch("tweb.cli.fetch_resource")
  @patch("tweb.cli._resolve_width", return_value=91)
  def test_explicit_width_overrides_terminal_width(
    self,
    mock_resolve_width: Mock,
    mock_fetch_resource: Mock,
    mock_render_normal: Mock,
  ) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()

    result = main([str(SAMPLE), "--mode", "text", "--width", "91"])

    self.assertEqual(result, 0)
    mock_resolve_width.assert_called_once_with(91)
    self.assertEqual(mock_render_normal.call_args.kwargs["width"], 91)

  @patch("tweb.cli.shutil.get_terminal_size", return_value=os.terminal_size((132, 24)))
  def test_resolve_width_uses_terminal_size_when_width_is_omitted(self, mock_terminal_size: Mock) -> None:
    self.assertEqual(_resolve_width(None), 132)
    mock_terminal_size.assert_called_once_with(fallback=(80, 24))

  @patch("tweb.cli.shutil.get_terminal_size")
  def test_resolve_width_skips_terminal_lookup_when_width_is_explicit(self, mock_terminal_size: Mock) -> None:
    self.assertEqual(_resolve_width(91), 91)
    mock_terminal_size.assert_not_called()

  def test_runs_inline_script_before_rendering(self) -> None:
    result = self.run_cli(
      str(JS_DOM),
      "--mode",
      "text",
      "--script",
      "document.querySelector('#title').textContent = 'CLI Inline Title';",
    )
    self.assertEqual(result.returncode, 0)
    self.assertIn(f"# {ANSI_BOLD}CLI Inline Title{ANSI_BOLD_RESET}", result.stdout)

  def test_runs_script_file_before_rendering(self) -> None:
    result = self.run_cli(str(JS_DOM), "--mode", "text", "--script-file", str(UPDATE_TITLE))
    self.assertEqual(result.returncode, 0)
    self.assertIn(f"# {ANSI_BOLD}CLI Updated Title{ANSI_BOLD_RESET}", result.stdout)
    self.assertIn("CLI Updated Body", result.stdout)

  @patch("tweb.cli.fetch_resource")
  def test_main_reads_user_agent_from_default_config_file(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()
    with TemporaryDirectory() as temp_dir:
      config_dir = Path(temp_dir) / ".config" / "tw"
      config_dir.mkdir(parents=True)
      (config_dir / "config.yml").write_text(
        'headers:\n  User-Agent: "CLI Test Agent/1.0"\n',
        encoding="utf-8",
      )
      with patch.dict(os.environ, {"HOME": temp_dir}, clear=False):
        result = main([str(SAMPLE), "--mode", "text"])

    self.assertEqual(result, 0)
    self.assertEqual(DEFAULT_HEADERS["User-Agent"], "CLI Test Agent/1.0")

  @patch("tweb.cli.fetch_resource")
  def test_main_applies_user_agent_from_config(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()
    with TemporaryDirectory() as temp_dir:
      config_path = Path(temp_dir) / "config.yml"
      config_path.write_text("headers:\n  User-Agent: Test Agent/2.0\n", encoding="utf-8")
      with patch.dict(os.environ, {"TW_CONFIG_PATH": str(config_path)}, clear=False):
        result = main([str(SAMPLE), "--mode", "text"])

    self.assertEqual(result, 0)
    self.assertEqual(DEFAULT_HEADERS["User-Agent"], "Test Agent/2.0")

  def test_cli_rejects_invalid_runtime_config(self) -> None:
    with TemporaryDirectory() as temp_dir:
      config_path = Path(temp_dir) / "config.yml"
      config_path.write_text("headers: {}\n", encoding="utf-8")
      result = self.run_cli_with_env(
        str(SAMPLE),
        env={"TW_CONFIG_PATH": str(config_path)},
      )

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("inline maps are not supported for headers", result.stderr)

  @patch("tweb.cli.fetch_resource")
  def test_passes_inline_cookies_via_session(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()

    result = main([str(SAMPLE), "--mode", "text", "--cookie", "sid=abc", "--cookie", "theme=dark"])

    self.assertEqual(result, 0)
    session = mock_fetch_resource.call_args.kwargs["session"]
    self.assertIsNotNone(session)
    self.assertEqual(session.cookies.get("sid"), "abc")
    self.assertEqual(session.cookies.get("theme"), "dark")
    session.close()

  @patch("tweb.cli.fetch_resource")
  def test_passes_cookie_file_via_session(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()
    with NamedTemporaryFile("w+", encoding="utf-8") as cookie_file:
      cookie_file.write("# comment\nsid=abc\n theme = dark \n")
      cookie_file.flush()

      result = main([str(SAMPLE), "--mode", "text", "--cookie-file", cookie_file.name])

    self.assertEqual(result, 0)
    session = mock_fetch_resource.call_args.kwargs["session"]
    self.assertIsNotNone(session)
    self.assertEqual(session.cookies.get("sid"), "abc")
    self.assertEqual(session.cookies.get("theme"), " dark")
    session.close()

  @patch("tweb.cli.fetch_resource")
  def test_passes_netscape_cookie_file_via_session(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()
    with NamedTemporaryFile("w+", encoding="utf-8") as cookie_file:
      cookie_file.write(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tTRUE\t2147483647\tsid\tabc123\n"
      )
      cookie_file.flush()

      result = main([str(SAMPLE), "--mode", "text", "--cookie-file", cookie_file.name, "--cookie-file-format", "netscape"])

    self.assertEqual(result, 0)
    session = mock_fetch_resource.call_args.kwargs["session"]
    self.assertIsNotNone(session)
    self.assertEqual(session.cookies.get("sid", domain=".example.com", path="/"), "abc123")
    session.close()

  @patch("tweb.cli.fetch_resource")
  @patch("tweb.cli.load_firefox_cookie_jar")
  def test_passes_firefox_browser_cookies_via_session(
    self,
    mock_load_firefox_cookie_jar: Mock,
    mock_fetch_resource: Mock,
  ) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()
    mock_load_firefox_cookie_jar.return_value = build_cookie_jar([("sessionid", "firefox-value")])

    result = main(
      [
        str(SAMPLE),
        "--mode",
        "text",
        "--cookie-from-browser",
        "firefox",
        "--browser-profile",
        "default-release",
        "--cookie-domain",
        "example.com",
      ]
    )

    self.assertEqual(result, 0)
    mock_load_firefox_cookie_jar.assert_called_once_with(
      profile="default-release",
      domains=["example.com"],
    )
    session = mock_fetch_resource.call_args.kwargs["session"]
    self.assertIsNotNone(session)
    self.assertEqual(session.cookies.get("sessionid"), "firefox-value")
    session.close()

  @patch("tweb.cli.fetch_resource")
  @patch("tweb.cli.load_zen_cookie_jar")
  def test_passes_zen_browser_cookies_via_session(
    self,
    mock_load_zen_cookie_jar: Mock,
    mock_fetch_resource: Mock,
  ) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()
    mock_load_zen_cookie_jar.return_value = build_cookie_jar([("sessionid", "zen-value")])

    result = main(
      [
        str(SAMPLE),
        "--mode",
        "text",
        "--cookie-from-browser",
        "zen",
        "--browser-profile",
        "default",
        "--cookie-domain",
        "example.com",
      ]
    )

    self.assertEqual(result, 0)
    mock_load_zen_cookie_jar.assert_called_once_with(
      profile="default",
      domains=["example.com"],
    )
    session = mock_fetch_resource.call_args.kwargs["session"]
    self.assertIsNotNone(session)
    self.assertEqual(session.cookies.get("sessionid"), "zen-value")
    session.close()

  def test_reports_javascript_errors(self) -> None:
    result = self.run_cli(str(JS_DOM), "--mode", "text", "--script", "throw new Error('boom')")
    self.assertEqual(result.returncode, 1)
    self.assertIn("JavaScript error", result.stderr)

  def test_debug_writes_debug_log_file(self) -> None:
    with TemporaryDirectory() as tmpdir:
      env = os.environ.copy()
      existing_pythonpath = env.get("PYTHONPATH")
      env["PYTHONPATH"] = str(ROOT) if not existing_pythonpath else f"{str(ROOT)}{os.pathsep}{existing_pythonpath}"

      result = subprocess.run(
        [sys.executable, "-m", "tweb", str(SAMPLE), "--mode", "text", "--debug"],
        cwd=tmpdir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
      )

      self.assertEqual(result.returncode, 0)
      debug_log = Path(tmpdir) / DEBUG_LOG_PATH
      self.assertTrue(debug_log.exists())
      log_text = debug_log.read_text(encoding="utf-8")
      self.assertIn("debug logging enabled", log_text)
      self.assertIn("fetching target=", log_text)

  def test_debug_log_option_writes_requested_file(self) -> None:
    with TemporaryDirectory() as tmpdir:
      env = os.environ.copy()
      existing_pythonpath = env.get("PYTHONPATH")
      env["PYTHONPATH"] = str(ROOT) if not existing_pythonpath else f"{str(ROOT)}{os.pathsep}{existing_pythonpath}"
      custom_log = Path(tmpdir) / "logs" / "custom-debug.log"

      result = subprocess.run(
        [sys.executable, "-m", "tweb", str(SAMPLE), "--mode", "text", "--debug-log", str(custom_log)],
        cwd=tmpdir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
      )

      self.assertEqual(result.returncode, 0)
      self.assertTrue(custom_log.exists())
      self.assertFalse((Path(tmpdir) / DEBUG_LOG_PATH).exists())
      log_text = custom_log.read_text(encoding="utf-8")
      self.assertIn("debug logging enabled", log_text)
      self.assertIn("fetching target=", log_text)

  def test_debug_logs_ignored_inline_null_failure_without_runtime_reset(self) -> None:
    with TemporaryDirectory() as tmpdir:
      html_path = Path(tmpdir) / "ignored-null.html"
      html_path.write_text(
        """
        <html>
          <body>
            <script>window.beforeCrash = '1';</script>
            <script>throw null;</script>
            <script>document.body.appendChild(document.createTextNode('after reset'));</script>
          </body>
        </html>
        """,
        encoding="utf-8",
      )
      env = os.environ.copy()
      existing_pythonpath = env.get("PYTHONPATH")
      env["PYTHONPATH"] = str(ROOT) if not existing_pythonpath else f"{str(ROOT)}{os.pathsep}{existing_pythonpath}"

      result = subprocess.run(
        [sys.executable, "-m", "tweb", str(html_path), "--mode", "text", "--debug"],
        cwd=tmpdir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
      )

      self.assertEqual(result.returncode, 0)
      self.assertIn("after reset", result.stdout)
      log_text = (Path(tmpdir) / DEBUG_LOG_PATH).read_text(encoding="utf-8")
      self.assertIn("embedded script eval failed index=1", log_text)
      self.assertIn("error=null", log_text)
      self.assertNotIn("embedded script runtime reset index=1", log_text)
      self.assertIn('"runtime_resets_after_ignored_errors": 0', log_text)

  def test_reports_javascript_memory_limit_errors(self) -> None:
    result = self.run_cli(
      str(JS_DOM),
      "--mode",
      "text",
      "--script",
      "const chunks = []; while (true) { chunks.push('x'.repeat(1000)); }",
    )
    self.assertEqual(result.returncode, 1)
    self.assertIn("JavaScript memory limit exceeded", result.stderr)

  @patch("tweb.cli.run_tui_browser", return_value=0)
  @patch("tweb.cli._resolve_width", return_value=80)
  def test_tui_mode_delegates_to_textual_app(self, _mock_resolve_width: Mock, mock_run_tui_browser) -> None:
    result = main([str(SAMPLE), "--mode", "tui"])
    self.assertEqual(result, 0)
    mock_run_tui_browser.assert_called_once_with(
      str(SAMPLE),
      encoding=None,
      width=80,
      scripts=[],
      session=None,
      browser_render_policy="auto",
      button_click_policy="dom-only",
      use_script_cache=True,
      debug_block_colors=False,
    )

  @patch("tweb.cli.TWebDocument")
  @patch("tweb.cli.fetch_resource")
  def test_browser_render_policy_is_passed_to_document(self, mock_fetch_resource: Mock, mock_document_cls: Mock) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()
    document = mock_document_cls.return_value

    result = main([str(SAMPLE), "--mode", "text", "--browser-render", "auto"])

    self.assertEqual(result, 0)
    document.execute_embedded_scripts.assert_called_once_with(
      ignore_errors=True,
      session=None,
      browser_render_policy="auto",
      use_script_cache=True,
    )

  @patch("tweb.cli.main", return_value=0)
  def test_tw_main_is_a_compatibility_alias(self, mock_main: Mock) -> None:
    result = tw_main(["https://example.com"])

    self.assertEqual(result, 0)
    mock_main.assert_called_once_with(["https://example.com"])

  @patch("tweb.cli.main", return_value=0)
  def test_tw_main_forwards_arguments_unchanged(self, mock_main: Mock) -> None:
    result = tw_main(["https://example.com", "--debug"])

    self.assertEqual(result, 0)
    mock_main.assert_called_once_with(["https://example.com", "--debug"])

  @patch("tweb.cli.run_tui_browser", return_value=0)
  @patch("tweb.cli._resolve_width", return_value=80)
  def test_tui_mode_passes_button_click_policy(self, _mock_resolve_width: Mock, mock_run_tui_browser) -> None:
    result = main([str(SAMPLE), "--mode", "tui", "--button-click-policy", "network"])

    self.assertEqual(result, 0)
    self.assertEqual(mock_run_tui_browser.call_args.kwargs["button_click_policy"], "network")

  @patch("tweb.cli.TWebDocument")
  @patch("tweb.cli.fetch_resource")
  def test_no_script_cache_is_passed_to_document(self, mock_fetch_resource: Mock, mock_document_cls: Mock) -> None:
    mock_fetch_resource.return_value = type("Resource", (), {"source": str(SAMPLE), "content": SAMPLE.read_text()})()
    document = mock_document_cls.return_value

    result = main([str(SAMPLE), "--mode", "text", "--no-script-cache"])

    self.assertEqual(result, 0)
    document.execute_embedded_scripts.assert_called_once_with(
      ignore_errors=True,
      session=None,
      browser_render_policy="auto",
      use_script_cache=False,
    )

  @patch("tweb.cli.run_tui_browser", return_value=0)
  @patch("tweb.cli._resolve_width", return_value=80)
  def test_tui_mode_passes_no_script_cache(self, _mock_resolve_width: Mock, mock_run_tui_browser) -> None:
    result = main([str(SAMPLE), "--mode", "tui", "--no-script-cache"])

    self.assertEqual(result, 0)
    self.assertEqual(mock_run_tui_browser.call_args.kwargs["use_script_cache"], False)

  @patch("tweb.cli.run_tui_browser", return_value=0)
  @patch("tweb.cli._resolve_width", return_value=80)
  def test_tui_mode_passes_debug_block_colors(self, _mock_resolve_width: Mock, mock_run_tui_browser) -> None:
    result = main([str(SAMPLE), "--mode", "tui", "--debug-block-colors"])

    self.assertEqual(result, 0)
    self.assertEqual(mock_run_tui_browser.call_args.kwargs["debug_block_colors"], True)

  @patch("tweb.cli.main", return_value=0)
  def test_tw_command_defaults_to_welcome_page_when_target_is_omitted(self, mock_main: Mock) -> None:
    result = tw_main([])

    self.assertEqual(result, 0)
    mock_main.assert_called_once_with([])

  def test_tw_help_lists_tui_related_options(self) -> None:
    result = subprocess.run(
      [sys.executable, "-c", "from tweb.cli import tw_main; raise SystemExit(tw_main(['-h']))"],
      cwd=ROOT,
      text=True,
      capture_output=True,
      check=False,
    )

    self.assertEqual(result.returncode, 0)
    self.assertIn("Open a web page in the TUI by default", result.stdout)
    self.assertIn("tw https://example.com", result.stdout)
    self.assertIn("--mode {text,dom,dom-ai,tui}", result.stdout)
    self.assertIn("--width WIDTH", result.stdout)
    self.assertIn("--cookie-file COOKIE_FILE", result.stdout)
    self.assertIn("tw https://example.com/private --cookie-file cookies.txt", result.stdout)

  @patch("tweb.cli.main", return_value=0)
  def test_tw_command_forwards_runtime_options(self, mock_main: Mock) -> None:
    result = tw_main(
      [
        "https://example.com/private",
        "--width",
        "100",
        "--encoding",
        "shift_jis",
        "--browser-render",
        "always",
        "--button-click-policy",
        "network",
        "--no-script-cache",
        "--debug-block-colors",
        "--script",
        "document.title = 'updated'",
        "--script-file",
        str(UPDATE_TITLE),
        "--cookie",
        "sid=abc",
        "--cookie-file",
        "cookies.txt",
        "--cookie-file-format",
        "netscape",
        "--cookie-from-browser",
        "firefox",
        "--browser-profile",
        "default-release",
        "--cookie-domain",
        "example.com",
      ]
    )

    self.assertEqual(result, 0)
    mock_main.assert_called_once_with(
      [
        "https://example.com/private",
        "--width",
        "100",
        "--encoding",
        "shift_jis",
        "--browser-render",
        "always",
        "--button-click-policy",
        "network",
        "--no-script-cache",
        "--debug-block-colors",
        "--script",
        "document.title = 'updated'",
        "--script-file",
        str(UPDATE_TITLE),
        "--cookie",
        "sid=abc",
        "--cookie-file",
        "cookies.txt",
        "--cookie-file-format",
        "netscape",
        "--cookie-from-browser",
        "firefox",
        "--browser-profile",
        "default-release",
        "--cookie-domain",
        "example.com",
      ]
    )


if __name__ == "__main__":
  unittest.main()
