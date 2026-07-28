from __future__ import annotations

from pathlib import Path
from threading import Event
import unittest
from unittest.mock import Mock, PropertyMock, patch

import requests

from tweb.fetcher import (
  BrowserRenderRequest,
  DEFAULT_HEADERS,
  FetchCancelled,
  FetchError,
  create_session,
  fetch_rendered_resource,
  fetch_rendered_resource_for_request,
  fetch_resource,
  normalize_target,
  override_default_headers,
  reset_default_headers,
  resolve_resource_url,
  sanitize_headers_for_log,
  sanitize_text_for_log,
  sanitize_url_for_log,
)


class FetcherTest(unittest.TestCase):
  def tearDown(self) -> None:
    reset_default_headers()

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_uses_requests(self, mock_request: Mock) -> None:
    response = Mock()
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.url = "https://example.com/final"
    response.headers = {"Content-Length": "15"}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"<html>", b"ok", b"</html>"]
    mock_request.return_value = response

    resource = fetch_resource("https://example.com")

    self.assertEqual(resource.source, "https://example.com/final")
    self.assertEqual(resource.content, "<html>ok</html>")
    mock_request.assert_called_once_with(
      "GET",
      "https://example.com",
      timeout=30,
      data=None,
      headers=DEFAULT_HEADERS,
      stream=True,
    )

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_prefers_html_meta_charset_when_header_lacks_charset(self, mock_request: Mock) -> None:
    response = Mock()
    response.encoding = "ISO-8859-1"
    response.apparent_encoding = "utf-8"
    response.url = "https://example.com/login"
    response.headers = {"content-type": "text/html"}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [
      (
        b"<!doctype html><html><head><meta charset=\"utf-8\"></head>"
        b"<body>\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e</body></html>"
      )
    ]
    mock_request.return_value = response

    resource = fetch_resource("https://example.com")

    self.assertEqual(resource.content, "<!doctype html><html><head><meta charset=\"utf-8\"></head><body>日本語</body></html>")

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_prefers_header_charset_over_meta_charset(self, mock_request: Mock) -> None:
    response = Mock()
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.url = "https://example.com"
    response.headers = {"content-type": "text/html; charset=shift_jis"}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [
      b"<html><head><meta charset=\"utf-8\"></head><body>\x93\xfa\x96{\x8c\xea</body></html>"
    ]
    mock_request.return_value = response

    resource = fetch_resource("https://example.com")

    self.assertIn("日本語", resource.content)

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_normalizes_windows_31j_charset_alias(self, mock_request: Mock) -> None:
    response = Mock()
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.url = "https://example.com"
    response.headers = {"content-type": "text/html; charset=Windows-31J"}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [
      b"<html><body>\x93\xfa\x96{\x8c\xea</body></html>"
    ]
    mock_request.return_value = response

    resource = fetch_resource("https://example.com")

    self.assertIn("日本語", resource.content)

  @patch("tweb.fetcher.requests.compat.chardet.detect", return_value={"encoding": "utf-8"})
  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_uses_body_bytes_for_apparent_encoding_without_touching_response_content(
    self,
    mock_request: Mock,
    mock_detect: Mock,
  ) -> None:
    response = Mock()
    type(response).apparent_encoding = PropertyMock(side_effect=RuntimeError("The content for this response was already consumed"))
    response.encoding = None
    response.url = "https://example.com/no-charset"
    response.headers = {"content-type": "text/html"}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"<html><body>plain ascii</body></html>"]
    mock_request.return_value = response

    resource = fetch_resource("https://example.com")

    self.assertEqual(resource.content, "<html><body>plain ascii</body></html>")
    mock_detect.assert_called_once_with(b"<html><body>plain ascii</body></html>")

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_reports_status(self, mock_request: Mock) -> None:
    response = Mock()
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.url = "https://example.com/final"
    response.headers = {"Content-Length": "15"}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"<html>", b"ok", b"</html>"]
    mock_request.return_value = response
    statuses: list[str] = []

    resource = fetch_resource("https://example.com", on_status=statuses.append)

    self.assertEqual(resource.content, "<html>ok</html>")
    self.assertEqual(
      statuses,
      [
        "Connecting https://example.com...",
        "Downloading https://example.com/final... 0/15 bytes",
        "Downloading https://example.com/final... 6/15 bytes",
        "Downloading https://example.com/final... 8/15 bytes",
        "Downloading https://example.com/final... 15/15 bytes",
      ],
    )

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_wraps_requests_errors(self, mock_request: Mock) -> None:
    mock_request.side_effect = requests.RequestException("boom")

    with self.assertRaises(FetchError):
      fetch_resource("https://example.com")

  def test_sanitize_url_for_log_redacts_query_and_fragment(self) -> None:
    sanitized = sanitize_url_for_log("https://example.com/path?a=1&token=secret#frag")

    self.assertEqual(
      sanitized,
      "https://example.com/path?a=%3Credacted%3E&token=%3Credacted%3E#<redacted>",
    )

  def test_sanitize_headers_for_log_redacts_sensitive_headers(self) -> None:
    sanitized = sanitize_headers_for_log(
      {
        "Authorization": "Bearer secret",
        "Cookie": "sid=abc",
        "X-CSRF-Token": "csrf",
        "Accept": "text/html",
      }
    )

    self.assertEqual(
      sanitized,
      {
        "Authorization": "<redacted>",
        "Cookie": "<redacted>",
        "X-CSRF-Token": "<redacted>",
        "Accept": "text/html",
      },
    )

  def test_sanitize_text_for_log_redacts_embedded_urls(self) -> None:
    sanitized = sanitize_text_for_log(
      "boom for https://example.com/path?token=secret#frag and http://test.local/x?q=1"
    )

    self.assertNotIn("secret", sanitized)
    self.assertNotIn("#frag", sanitized)
    self.assertIn("token=%3Credacted%3E", sanitized)
    self.assertIn("q=%3Credacted%3E", sanitized)

  def test_override_default_headers_updates_user_agent_until_reset(self) -> None:
    original_user_agent = DEFAULT_HEADERS["User-Agent"]

    override_default_headers({"User-Agent": "Configured Agent/3.0"})
    self.assertEqual(DEFAULT_HEADERS["User-Agent"], "Configured Agent/3.0")

    reset_default_headers()
    self.assertEqual(DEFAULT_HEADERS["User-Agent"], original_user_agent)

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_logs_sanitized_url_and_headers(self, mock_request: Mock) -> None:
    response = Mock()
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.url = "https://example.com/final?sid=abc#frag"
    response.headers = {}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"ok"]
    mock_request.return_value = response

    with self.assertLogs("tweb", level="DEBUG") as captured:
      fetch_resource(
        "https://example.com/start?token=secret#frag",
        request_headers={
          "Authorization": "Bearer secret",
          "Cookie": "sid=abc",
        },
      )

    joined = "\n".join(captured.output)
    self.assertNotIn("secret", joined)
    self.assertNotIn("sid=abc", joined)
    self.assertNotIn("#frag", joined)
    self.assertIn("token=%3Credacted%3E", joined)
    self.assertIn("Authorization': '<redacted>'", joined)

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_error_message_sanitizes_url(self, mock_request: Mock) -> None:
    mock_request.side_effect = requests.RequestException(
      "boom for https://example.com/private?token=secret#frag"
    )

    with self.assertRaises(FetchError) as raised:
      fetch_resource("https://example.com/start?token=secret#frag")

    message = str(raised.exception)
    self.assertNotIn("secret", message)
    self.assertNotIn("#frag", message)
    self.assertIn("token=%3Credacted%3E", message)

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_defaults_schemeless_host_to_http(self, mock_request: Mock) -> None:
    response = Mock()
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.url = "http://example.com/final"
    response.headers = {}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"ok"]
    mock_request.return_value = response

    resource = fetch_resource("example.com/path")

    self.assertEqual(resource.source, "http://example.com/final")
    mock_request.assert_called_once_with(
      "GET",
      "http://example.com/path",
      timeout=30,
      data=None,
      headers=DEFAULT_HEADERS,
      stream=True,
    )

  @patch("tweb.fetcher.requests.request")
  def test_fetch_remote_can_be_cancelled(self, mock_request: Mock) -> None:
    response = Mock()
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.url = "https://example.com/final"
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"<html>", b"ok", b"</html>"]
    mock_request.return_value = response
    cancelled = Event()
    cancelled.set()

    with self.assertRaises(FetchCancelled):
      fetch_resource("https://example.com", cancelled_event=cancelled)

  def test_create_session_seeds_cookies(self) -> None:
    session = create_session({"sid": "abc", "theme": "dark"})
    try:
      self.assertEqual(session.cookies.get("sid"), "abc")
      self.assertEqual(session.cookies.get("theme"), "dark")
    finally:
      session.close()

  def test_create_session_preserves_cookie_metadata(self) -> None:
    jar = requests.cookies.RequestsCookieJar()
    jar.set("sessionid", "abc123", domain=".example.com", path="/private")

    session = create_session(jar)
    try:
      self.assertEqual(session.cookies.get("sessionid", domain=".example.com", path="/private"), "abc123")
    finally:
      session.close()

  @patch("tweb.fetcher.subprocess.run")
  def test_fetch_rendered_resource_uses_dump_dom_without_cookies(self, mock_run: Mock) -> None:
    completed = Mock()
    completed.stdout = "<html>ok</html>"
    mock_run.return_value = completed

    resource = fetch_rendered_resource("https://example.com")

    self.assertEqual(resource.content, "<html>ok</html>")
    mock_run.assert_called_once()

  @patch("tweb.fetcher._fetch_rendered_resource_via_devtools", return_value="<html>secure</html>")
  @patch("tweb.fetcher.subprocess.run")
  def test_fetch_rendered_resource_passes_matching_session_cookies_to_devtools(
    self,
    mock_run: Mock,
    mock_devtools: Mock,
  ) -> None:
    jar = requests.cookies.RequestsCookieJar()
    jar.set("sessionid", "abc123", domain=".example.com", path="/")
    jar.set("other", "skip", domain=".elsewhere.com", path="/")
    session = create_session(jar)
    try:
      resource = fetch_rendered_resource("https://example.com/private", session=session)
    finally:
      session.close()

    self.assertEqual(resource.content, "<html>secure</html>")
    mock_run.assert_not_called()
    mock_devtools.assert_called_once()
    self.assertEqual(
      mock_devtools.call_args.kwargs["cookies"],
      [
        {
          "name": "sessionid",
          "value": "abc123",
          "domain": ".example.com",
          "path": "/",
          "secure": False,
        }
      ],
    )

  def test_fetch_rendered_resource_rejects_unknown_provider(self) -> None:
    with self.assertRaises(FetchError) as raised:
      fetch_rendered_resource("https://example.com", provider="webkit")  # type: ignore[arg-type]

    self.assertIn("browser-render provider unavailable", str(raised.exception))

  @patch("tweb.fetcher._find_chrome_binary", return_value="/bin/chrome")
  @patch("tweb.fetcher.subprocess.run")
  def test_fetch_rendered_resource_for_request_uses_timeout_from_request(
    self,
    mock_run: Mock,
    _mock_browser: Mock,
  ) -> None:
    completed = Mock()
    completed.stdout = "<html>ok</html>"
    mock_run.return_value = completed

    resource = fetch_rendered_resource_for_request(
      BrowserRenderRequest(target="https://example.com/app", timeout=9)
    )

    self.assertEqual(resource.content, "<html>ok</html>")
    self.assertEqual(resource.source, "https://example.com/app")
    self.assertEqual(mock_run.call_args.kwargs["timeout"], 9)

  def test_fetch_remote_uses_provided_session(self) -> None:
    session = Mock()
    response = Mock()
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.url = "https://example.com/secure"
    response.headers = {}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"ok"]
    session.request.return_value = response

    resource = fetch_resource("https://example.com", session=session)

    self.assertEqual(resource.source, "https://example.com/secure")
    self.assertEqual(resource.content, "ok")
    session.request.assert_called_once_with(
      "GET",
      "https://example.com",
      timeout=30,
      data=None,
      headers=DEFAULT_HEADERS,
      stream=True,
    )

  def test_fetch_remote_post_sends_form_data(self) -> None:
    session = Mock()
    response = Mock()
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.url = "https://example.com/submit"
    response.headers = {}
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"posted"]
    session.request.return_value = response

    resource = fetch_resource(
      "https://example.com/submit",
      session=session,
      method="post",
      form_data=[("q", "hello"), ("go", "1")],
    )

    self.assertEqual(resource.source, "https://example.com/submit")
    self.assertEqual(resource.content, "posted")
    session.request.assert_called_once_with(
      "POST",
      "https://example.com/submit",
      data=[("q", "hello"), ("go", "1")],
      timeout=30,
      headers=DEFAULT_HEADERS,
      stream=True,
    )

  def test_default_headers_look_like_a_browser(self) -> None:
    self.assertIn("Mozilla/5.0", DEFAULT_HEADERS["User-Agent"])
    self.assertEqual(DEFAULT_HEADERS["Sec-Fetch-Dest"], "document")
    self.assertEqual(DEFAULT_HEADERS["Sec-CH-UA-Platform"], '"macOS"')

  def test_resolve_resource_url_for_remote_source(self) -> None:
    resolved = resolve_resource_url("https://example.com/posts/index.html", "../site.css")
    self.assertEqual(resolved, "https://example.com/site.css")

  def test_resolve_resource_url_for_local_source(self) -> None:
    resolved = resolve_resource_url("/tmp/demo/index.html", "styles/site.css")
    self.assertEqual(resolved, str((Path("/tmp/demo").resolve() / "styles/site.css")))

  def test_fetch_local_rejects_post_submit(self) -> None:
    with self.assertRaises(FetchError):
      fetch_resource("tests/fixtures/form.html", method="post", form_data=[("q", "hello")])

  def test_normalize_target_keeps_local_paths(self) -> None:
    self.assertEqual(normalize_target("./tests/fixtures/sample.html"), "./tests/fixtures/sample.html")
    self.assertEqual(normalize_target("/tmp/sample.html"), "/tmp/sample.html")

  def test_normalize_target_defaults_common_hosts_to_http(self) -> None:
    self.assertEqual(normalize_target("example.com"), "http://example.com")
    self.assertEqual(normalize_target("localhost:8000/demo"), "http://localhost:8000/demo")


if __name__ == "__main__":
  unittest.main()
