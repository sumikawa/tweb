from __future__ import annotations

from collections.abc import Callable
import copy
from dataclasses import dataclass
from http.cookiejar import CookieJar
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import Event, Lock, local
from typing import Literal
from urllib.parse import parse_qsl, quote_plus, urljoin, urlparse, urlunparse

import requests

_BASE_DEFAULT_HEADERS = {
  "User-Agent": (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
  ),
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.9",
  "Cache-Control": "no-cache",
  "Pragma": "no-cache",
  "Sec-CH-UA": '"Chromium";v="137", "Google Chrome";v="137", "Not/A)Brand";v="24"',
  "Sec-CH-UA-Mobile": "?0",
  "Sec-CH-UA-Platform": '"macOS"',
  "Sec-Fetch-Dest": "document",
  "Sec-Fetch-Mode": "navigate",
  "Sec-Fetch-Site": "none",
  "Sec-Fetch-User": "?1",
  "Upgrade-Insecure-Requests": "1",
}
DEFAULT_HEADERS = dict(_BASE_DEFAULT_HEADERS)

_CHROME_CANDIDATES = (
  "google-chrome",
  "chromium",
  "chromium-browser",
  "chrome",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

_IPV4_HOST_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_HTML_META_CHARSET_RE = re.compile(r"<meta[^>]+charset=['\"]?\s*([a-zA-Z0-9._-]+)", re.IGNORECASE)
_CONTENT_TYPE_CHARSET_RE = re.compile(r"charset=([a-zA-Z0-9._-]+)", re.IGNORECASE)
LOGGER = logging.getLogger("tweb")
ASSET_FETCH_MAX_WORKERS = 4
_ENCODING_ALIASES = {
  "windows-31j": "cp932",
}
_REDACTED = "<redacted>"
_SENSITIVE_HEADER_NAMES = {
  "authorization",
  "cookie",
  "set-cookie",
  "proxy-authorization",
  "x-csrf-token",
  "x-xsrf-token",
}
_URL_TEXT_RE = re.compile(r"(?P<url>(?:https?|file)://[^\s'\"<>]+)")


class FetchError(RuntimeError):
  pass


class FetchCancelled(FetchError):
  pass


@dataclass
class Resource:
  source: str
  content: str
  headers: dict[str, str] | None = None
  status_code: int | None = None


@dataclass(frozen=True)
class BrowserRenderRequest:
  target: str
  provider: str = "chrome"
  timeout: int = 20


@dataclass(frozen=True)
class BrowserRenderResult:
  content: str
  source: str | None = None
  headers: dict[str, str] | None = None
  status_code: int = 200


StatusCallback = Callable[[str], None]
BrowserRenderProvider = Literal["chrome"]
BrowserRenderFetcher = Callable[..., BrowserRenderResult | Resource]


def sanitize_url_for_log(url: str) -> str:
  parsed = urlparse(url)
  if not parsed.scheme:
    return url
  query = parsed.query
  fragment = parsed.fragment
  if not query and not fragment:
    return url
  sanitized_query = _sanitize_query_for_log(query)
  sanitized_fragment = _REDACTED if fragment else ""
  return urlunparse(
    (
      parsed.scheme,
      parsed.netloc,
      parsed.path,
      parsed.params,
      sanitized_query,
      sanitized_fragment,
    )
  )


def sanitize_headers_for_log(headers: dict[str, str] | None) -> dict[str, str] | None:
  if headers is None:
    return None
  sanitized: dict[str, str] = {}
  for key, value in headers.items():
    if key.lower() in _SENSITIVE_HEADER_NAMES:
      sanitized[key] = _REDACTED
    else:
      sanitized[key] = value
  return sanitized


def sanitize_text_for_log(text: str) -> str:
  return _URL_TEXT_RE.sub(lambda match: sanitize_url_for_log(match.group("url")), text)


def _sanitize_query_for_log(query: str) -> str:
  if not query:
    return query
  pairs = parse_qsl(query, keep_blank_values=True)
  if not pairs:
    return _REDACTED
  return "&".join(
    f"{quote_plus(key)}={quote_plus(_REDACTED)}"
    for key, _value in pairs
  )


def create_session(cookies: dict[str, str] | CookieJar | None = None) -> requests.Session:
  session = requests.Session()
  if cookies:
    if isinstance(cookies, dict):
      session.cookies.update(cookies)
    else:
      for cookie in cookies:
        session.cookies.set_cookie(cookie)
  LOGGER.debug("created requests session cookies=%d", len(session.cookies))
  return session


def reset_default_headers() -> None:
  DEFAULT_HEADERS.clear()
  DEFAULT_HEADERS.update(_BASE_DEFAULT_HEADERS)


def override_default_headers(headers: dict[str, str]) -> None:
  for key, value in headers.items():
    DEFAULT_HEADERS[str(key)] = str(value)


class PersistentSessionPool:
  def __init__(self, base_session: requests.Session) -> None:
    self._base_session = base_session
    self._thread_local = local()
    self._cookie_lock = Lock()
    self._worker_sessions: list[requests.Session] = []

  @property
  def cookies(self) -> requests.cookies.RequestsCookieJar:
    return self._base_session.cookies

  def request(self, method: str, url: str, **kwargs) -> requests.Response:
    worker_session = self._worker_session()
    with self._cookie_lock:
      _replace_cookie_jar(worker_session.cookies, self._base_session.cookies)
    response = worker_session.request(method, url, **kwargs)
    with self._cookie_lock:
      _merge_cookie_jar(self._base_session.cookies, worker_session.cookies)
    return response

  def close(self) -> None:
    self._worker_sessions.clear()

  def _worker_session(self) -> requests.Session:
    session = getattr(self._thread_local, "session", None)
    if session is not None:
      return session
    session = _clone_session(self._base_session)
    self._thread_local.session = session
    self._worker_sessions.append(session)
    return session


def create_persistent_session_pool(session: object | None) -> object | None:
  if not isinstance(session, requests.Session):
    return session
  return PersistentSessionPool(session)


def _clone_session(session: requests.Session) -> requests.Session:
  cloned = requests.Session()
  cloned.headers.clear()
  cloned.headers.update(session.headers)
  cloned.auth = session.auth
  cloned.proxies = dict(session.proxies)
  cloned.verify = session.verify
  cloned.cert = session.cert
  cloned.max_redirects = session.max_redirects
  cloned.trust_env = session.trust_env
  cloned.params = dict(session.params)
  cloned.hooks = {name: list(values) for name, values in session.hooks.items()}
  for prefix, adapter in session.adapters.items():
    cloned.mount(prefix, adapter)
  _replace_cookie_jar(cloned.cookies, session.cookies)
  return cloned


def _replace_cookie_jar(
  target: requests.cookies.RequestsCookieJar,
  source: CookieJar,
) -> None:
  target.clear()
  _merge_cookie_jar(target, source)


def _merge_cookie_jar(
  target: requests.cookies.RequestsCookieJar,
  source: CookieJar,
) -> None:
  for cookie in source:
    target.set_cookie(copy.copy(cookie))


def fetch_resource(
  target: str,
  encoding: str | None = None,
  cancelled_event: Event | None = None,
  on_status: StatusCallback | None = None,
  session: requests.Session | None = None,
  method: str = "get",
  form_data: list[tuple[str, str]] | None = None,
  request_headers: dict[str, str] | None = None,
) -> Resource:
  target = normalize_target(target)
  method = method.strip().lower() or "get"
  parsed = urlparse(target)
  LOGGER.debug(
    "fetch_resource target=%s normalized=%s method=%s",
    sanitize_url_for_log(target),
    sanitize_url_for_log(parsed.geturl()),
    method,
  )
  if parsed.scheme in {"http", "https"}:
    return _fetch_remote(
      target,
      cancelled_event=cancelled_event,
      on_status=on_status,
      session=session,
      method=method,
      form_data=form_data,
      request_headers=request_headers,
    )
  if method != "get":
    raise FetchError(f"local resource does not support {method.upper()} submit: {target}")
  return _fetch_local(Path(target), encoding=encoding, cancelled_event=cancelled_event, on_status=on_status)


def normalize_target(target: str) -> str:
  stripped = target.strip()
  if not stripped:
    return target
  if stripped.startswith("//"):
    return f"http:{stripped}"
  if _looks_like_local_path(stripped):
    return target
  if _looks_like_http_target(stripped):
    return f"http://{stripped}"
  return target


def resolve_resource_url(base: str, target: str) -> str:
  parsed_target = urlparse(target)
  if parsed_target.scheme or target.startswith("//"):
    return urljoin(base, target) if base else target

  parsed_base = urlparse(base)
  if parsed_base.scheme in {"http", "https", "file"}:
    return urljoin(base, target)

  base_path = Path(base)
  if target.startswith("/"):
    return str(Path(target))
  return str((base_path.parent / target).resolve())


def _looks_like_local_path(target: str) -> bool:
  return (
    target.startswith(("/", "./", "../", "~/"))
    or target.startswith("file:")
    or " " in target
  )


def _looks_like_http_target(target: str) -> bool:
  first_segment = re.split(r"[/?#]", target, maxsplit=1)[0]
  host = first_segment
  if ":" in host and not host.startswith("["):
    host = host.split(":", 1)[0]
  if host == "localhost":
    return True
  if host.startswith("[") and host.endswith("]"):
    return True
  if _IPV4_HOST_RE.match(host):
    return True
  return "." in host


def fetch_rendered_resource(
  target: str,
  *,
  cancelled_event: Event | None = None,
  on_status: StatusCallback | None = None,
  session: requests.Session | None = None,
  provider: BrowserRenderProvider = "chrome",
) -> Resource:
  request = BrowserRenderRequest(target=target, provider=provider)
  return fetch_rendered_resource_for_request(
    request,
    cancelled_event=cancelled_event,
    on_status=on_status,
    session=session,
  )


def fetch_rendered_resource_for_request(
  request: BrowserRenderRequest,
  *,
  cancelled_event: Event | None = None,
  on_status: StatusCallback | None = None,
  session: requests.Session | None = None,
) -> Resource:
  if request.provider != "chrome":
    raise FetchError(f"browser-render provider unavailable: {request.provider}")
  parsed = urlparse(request.target)
  if parsed.scheme not in {"http", "https"}:
    raise FetchError(f"browser-render fallback only supports remote URLs: {request.target}")
  browser = _find_chrome_binary()
  if browser is None:
    raise FetchError("browser-render fallback unavailable: Chrome/Chromium not found")
  LOGGER.debug(
    "browser-render fallback target=%s provider=%s browser=%s timeout=%s",
    sanitize_url_for_log(request.target),
    request.provider,
    browser,
    request.timeout,
  )
  if cancelled_event is not None and cancelled_event.is_set():
    raise FetchCancelled(f"cancelled rendered fetch for {request.target}")
  _notify_status(on_status, f"Rendering {request.target} in headless Chrome...")
  cookies = _cookies_for_url(session, request.target)
  try:
    if cookies:
      body = _fetch_rendered_resource_via_devtools(
        browser,
        request.target,
        cookies=cookies,
        timeout=request.timeout,
      )
    else:
      completed = subprocess.run(
        [
          browser,
          "--headless=new",
          "--disable-gpu",
          "--virtual-time-budget=8000",
          "--dump-dom",
          request.target,
        ],
        capture_output=True,
        text=True,
        timeout=request.timeout,
        check=True,
      )
      body = completed.stdout.strip()
  except (OSError, subprocess.SubprocessError) as exc:
    raise FetchError(f"failed to render {request.target} with headless Chrome: {exc}") from exc
  if cancelled_event is not None and cancelled_event.is_set():
    raise FetchCancelled(f"cancelled rendered fetch for {request.target}")
  if not body:
    raise FetchError(f"headless Chrome returned empty DOM for {request.target}")
  LOGGER.debug(
    "browser-render fallback completed target=%s provider=%s bytes=%d",
    sanitize_url_for_log(request.target),
    request.provider,
    len(body),
  )
  return Resource(source=request.target, content=body, headers={}, status_code=200)


def _fetch_remote(
  url: str,
  cancelled_event: Event | None = None,
  on_status: StatusCallback | None = None,
  session: requests.Session | None = None,
  method: str = "get",
  form_data: list[tuple[str, str]] | None = None,
  request_headers: dict[str, str] | None = None,
) -> Resource:
  _notify_status(on_status, f"Connecting {url}...")
  LOGGER.debug(
    "remote fetch start method=%s url=%s form_fields=%d header_overrides=%s",
    method.upper(),
    sanitize_url_for_log(url),
    len(form_data or []),
    sanitize_headers_for_log(request_headers),
  )
  try:
    request = requests.request if session is None else session.request
    headers = dict(DEFAULT_HEADERS)
    if request_headers:
      headers.update(request_headers)
    response = request(
      method.upper(),
      url,
      data=form_data,
      timeout=30,
      headers=headers,
      stream=True,
    )
    if response.status_code != 304:
      response.raise_for_status()
  except requests.RequestException as exc:
    LOGGER.exception("remote fetch failed method=%s url=%s", method.upper(), sanitize_url_for_log(url))
    raise FetchError(
      f"failed to fetch {method.upper()} {sanitize_url_for_log(url)}: "
      f"{sanitize_text_for_log(str(exc))}"
    ) from exc
  LOGGER.debug("remote fetch response url=%s status=%s", sanitize_url_for_log(response.url), response.status_code)
  if response.status_code == 304:
    response.close()
    return Resource(
      source=response.url,
      content="",
      headers=dict(response.headers),
      status_code=304,
    )
  total_bytes = _content_length(response.headers.get("Content-Length"))
  downloaded_bytes = 0
  _notify_status(on_status, _download_status(response.url, downloaded_bytes, total_bytes))
  chunks: list[bytes] = []
  try:
    for chunk in response.iter_content(chunk_size=8192):
      if cancelled_event is not None and cancelled_event.is_set():
        raise FetchCancelled(f"cancelled fetch for {url}")
      if chunk:
        chunks.append(chunk)
        downloaded_bytes += len(chunk)
        _notify_status(on_status, _download_status(response.url, downloaded_bytes, total_bytes))
  finally:
    response.close()
  body_bytes = b"".join(chunks)
  apparent_encoding = _detect_apparent_encoding(body_bytes)
  resolved_encoding = _resolve_response_encoding(response, body_bytes, apparent_encoding=apparent_encoding)
  response.encoding = resolved_encoding
  body = body_bytes.decode(resolved_encoding, errors="replace")
  LOGGER.debug(
    "remote fetch complete url=%s bytes=%d encoding=%s header_encoding=%s apparent_encoding=%s",
    sanitize_url_for_log(response.url),
    len(body_bytes),
    resolved_encoding,
    _encoding_from_content_type_header(response.headers.get("content-type")),
    apparent_encoding,
  )
  return Resource(
    source=response.url,
    content=body,
    headers=dict(response.headers),
    status_code=response.status_code,
  )


def _resolve_response_encoding(
  response: requests.Response,
  body_bytes: bytes,
  *,
  apparent_encoding: str | None = None,
) -> str:
  header_encoding = _encoding_from_content_type_header(response.headers.get("content-type"))
  if header_encoding:
    return header_encoding

  meta_encoding = _encoding_from_html_meta(body_bytes)
  if meta_encoding:
    return meta_encoding

  if apparent_encoding:
    return apparent_encoding

  return "utf-8"


def _normalize_encoding_name(encoding: str | None) -> str | None:
  normalized = str(encoding or "").strip()
  if not normalized:
    return None
  return _ENCODING_ALIASES.get(normalized.lower(), normalized)


def _encoding_from_html_meta(body_bytes: bytes) -> str | None:
  sniffed = body_bytes[:4096].decode("ascii", errors="ignore")
  match = _HTML_META_CHARSET_RE.search(sniffed)
  return _normalize_encoding_name(match.group(1) if match else None)


def _encoding_from_content_type_header(content_type: str | None) -> str | None:
  if not content_type:
    return None
  match = _CONTENT_TYPE_CHARSET_RE.search(content_type)
  return _normalize_encoding_name(match.group(1) if match else None)


def _detect_apparent_encoding(body_bytes: bytes) -> str | None:
  detector = getattr(requests.compat, "chardet", None)
  if detector is None:
    return None
  try:
    detected = detector.detect(body_bytes)
  except Exception:
    return None
  if not isinstance(detected, dict):
    return None
  encoding = detected.get("encoding")
  if not isinstance(encoding, str) or not encoding:
    return None
  return _normalize_encoding_name(encoding)


def _find_chrome_binary() -> str | None:
  for candidate in _CHROME_CANDIDATES:
    if "/" in candidate:
      if Path(candidate).exists():
        return candidate
      continue
    resolved = shutil.which(candidate)
    if resolved:
      return resolved
  return None


def _cookies_for_url(
  session: requests.Session | None,
  target: str,
) -> list[dict[str, object]]:
  if session is None:
    return []
  parsed = urlparse(target)
  host = (parsed.hostname or "").lower()
  path = parsed.path or "/"
  is_secure = parsed.scheme == "https"
  cookies: list[dict[str, object]] = []
  for cookie in session.cookies:
    if not _cookie_matches_target(cookie, host=host, path=path, is_secure=is_secure):
      continue
    record: dict[str, object] = {
      "name": cookie.name,
      "value": cookie.value,
      "domain": cookie.domain,
      "path": cookie.path or "/",
      "secure": bool(cookie.secure),
    }
    if cookie.expires:
      record["expires"] = float(cookie.expires)
    cookies.append(record)
  return cookies


def _cookie_matches_target(cookie, *, host: str, path: str, is_secure: bool) -> bool:
  domain = (cookie.domain or "").lstrip(".").lower()
  if domain:
    if host != domain and not host.endswith(f".{domain}"):
      return False
  if cookie.secure and not is_secure:
    return False
  cookie_path = cookie.path or "/"
  if not path.startswith(cookie_path.rstrip("/") or "/"):
    return False
  return True


def _fetch_rendered_resource_via_devtools(
  browser: str,
  target: str,
  *,
  cookies: list[dict[str, object]],
  timeout: int,
) -> str:
  helper = Path(__file__).resolve().parents[1] / "scripts" / "render_with_chrome_devtools.py"
  completed = subprocess.run(
    [sys.executable, str(helper), browser, target, str(min(timeout, 5))],
    input=json.dumps(cookies),
    capture_output=True,
    text=True,
    timeout=timeout + 5,
    check=True,
  )
  return completed.stdout.strip()


def _fetch_local(
  path: Path,
  encoding: str | None = None,
  cancelled_event: Event | None = None,
  on_status: StatusCallback | None = None,
) -> Resource:
  if cancelled_event is not None and cancelled_event.is_set():
    raise FetchCancelled(f"cancelled fetch for {path}")
  if not path.exists():
    raise FetchError(f"local file not found: {path}")
  _notify_status(on_status, f"Reading {path}...")
  LOGGER.debug("local fetch path=%s encoding=%s", path, encoding or "utf-8")
  try:
    body = path.read_text(encoding=encoding or "utf-8")
  except UnicodeDecodeError:
    if encoding:
      raise FetchError(f"failed to decode {path} with encoding {encoding}")
    body = path.read_text(encoding="utf-8", errors="replace")
  except OSError as exc:
    raise FetchError(f"failed to read {path}: {exc}") from exc
  if cancelled_event is not None and cancelled_event.is_set():
    raise FetchCancelled(f"cancelled fetch for {path}")
  LOGGER.debug("local fetch complete path=%s chars=%d", path, len(body))
  return Resource(source=str(path), content=body, headers={}, status_code=200)


def _notify_status(on_status: StatusCallback | None, message: str) -> None:
  if on_status is not None:
    on_status(message)


def _content_length(value: str | None) -> int | None:
  if value is None:
    return None
  try:
    return int(value)
  except (TypeError, ValueError):
    return None


def _download_status(url: str, downloaded_bytes: int, total_bytes: int | None) -> str:
  if total_bytes is None or total_bytes <= 0:
    return f"Downloading {url}... {downloaded_bytes} bytes"
  return f"Downloading {url}... {downloaded_bytes}/{total_bytes} bytes"
