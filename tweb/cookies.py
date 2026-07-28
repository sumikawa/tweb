from __future__ import annotations

from collections.abc import Sequence
from configparser import ConfigParser
from http.cookiejar import CookieJar
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory

from requests.cookies import RequestsCookieJar, create_cookie


class CookieLoadError(RuntimeError):
  pass


def build_cookie_jar(inline_cookies: Sequence[tuple[str, str]]) -> RequestsCookieJar:
  jar = RequestsCookieJar()
  for name, value in inline_cookies:
    jar.set(name, value)
  return jar


def merge_cookie_jars(*jars: RequestsCookieJar | CookieJar | None) -> RequestsCookieJar:
  merged = RequestsCookieJar()
  for jar in jars:
    if jar is None:
      continue
    for cookie in jar:
      merged.set_cookie(cookie)
  return merged


def load_cookie_file(path: str | Path, *, format_name: str = "auto") -> RequestsCookieJar:
  cookie_path = Path(path)
  text = _read_cookie_file(cookie_path)
  detected_format = _detect_cookie_file_format(text) if format_name == "auto" else format_name
  if detected_format == "namevalue":
    return _load_namevalue_cookie_jar(text, source=str(cookie_path))
  if detected_format == "netscape":
    return _load_netscape_cookie_jar(text, source=str(cookie_path))
  if detected_format == "json":
    return _load_json_cookie_jar(text, source=str(cookie_path))
  raise CookieLoadError(f"unsupported cookie file format: {detected_format}")


def load_firefox_cookie_jar(
  *,
  profile: str | None = None,
  domains: Sequence[str] = (),
) -> RequestsCookieJar:
  profile_dir = resolve_mozilla_profile("firefox", profile)
  return _load_mozilla_cookie_jar(profile_dir, domains=domains, browser="Firefox")


def load_zen_cookie_jar(
  *,
  profile: str | None = None,
  domains: Sequence[str] = (),
) -> RequestsCookieJar:
  profile_dir = resolve_mozilla_profile("zen", profile)
  return _load_mozilla_cookie_jar(profile_dir, domains=domains, browser="Zen")


def _load_mozilla_cookie_jar(
  profile_dir: Path,
  *,
  domains: Sequence[str],
  browser: str,
) -> RequestsCookieJar:
  cookie_db = profile_dir / "cookies.sqlite"
  if not cookie_db.exists():
    raise CookieLoadError(f"{browser} cookies database not found: {cookie_db}")
  normalized_domains = tuple(domain.lstrip(".").lower() for domain in domains if domain.strip())

  with TemporaryDirectory(prefix="tweb-firefox-cookies-") as temp_dir:
    copied_db = Path(temp_dir) / "cookies.sqlite"
    shutil.copy2(cookie_db, copied_db)
    try:
      connection = sqlite3.connect(copied_db)
    except sqlite3.Error as exc:
      raise CookieLoadError(f"failed to open {browser} cookies database {cookie_db}: {exc}") from exc
    try:
      query = "SELECT name, value, host, path, expiry, isSecure FROM moz_cookies"
      params: list[str] = []
      if normalized_domains:
        predicates = []
        for domain in normalized_domains:
          predicates.append("(host = ? OR host = ? OR host LIKE ?)")
          params.extend([domain, f".{domain}", f"%.{domain}"])
        query = f"{query} WHERE {' OR '.join(predicates)}"
      rows = connection.execute(query, params).fetchall()
    except sqlite3.Error as exc:
      raise CookieLoadError(f"failed to read {browser} cookies from {cookie_db}: {exc}") from exc
    finally:
      connection.close()

  jar = RequestsCookieJar()
  for name, value, host, path, expiry, is_secure in rows:
    jar.set_cookie(
      create_cookie(
        name=name,
        value=value,
        domain=host,
        path=path or "/",
        secure=bool(is_secure),
        expires=expiry or None,
      )
    )
  return jar


def resolve_firefox_profile(profile: str | None = None) -> Path:
  return resolve_mozilla_profile("firefox", profile)


def resolve_zen_profile(profile: str | None = None) -> Path:
  return resolve_mozilla_profile("zen", profile)


def resolve_mozilla_profile(browser: str, profile: str | None = None) -> Path:
  browser_key = browser.strip().lower()
  browser_dir = _mozilla_profile_base_dir(browser_key)
  profiles_ini = browser_dir / "profiles.ini"
  installs_ini = browser_dir / "installs.ini"
  if profile:
    candidate = Path(profile).expanduser()
    if candidate.is_dir():
      return candidate
  if not profiles_ini.exists():
    raise CookieLoadError(f"{browser_key} profiles.ini not found: {profiles_ini}")

  config = ConfigParser()
  config.read(profiles_ini, encoding="utf-8")
  profile_sections = [config[name] for name in config.sections() if name.startswith("Profile")]
  if not profile_sections:
    raise CookieLoadError(f"no {browser_key} profiles defined in {profiles_ini}")

  if profile:
    for section in profile_sections:
      path_value = section.get("Path", "")
      name_value = section.get("Name", "")
      if profile in {name_value, path_value, Path(path_value).name}:
        return _resolve_firefox_profile_path(browser_dir, section)
    raise CookieLoadError(f"{browser_key} profile not found: {profile}")

  install_default = _resolve_install_default_profile(browser_dir, installs_ini)
  if install_default is not None:
    return install_default

  for section in profile_sections:
    if section.get("Default") == "1":
      return _resolve_firefox_profile_path(browser_dir, section)
  return _resolve_firefox_profile_path(browser_dir, profile_sections[0])


def _mozilla_profile_base_dir(browser_key: str) -> Path:
  if browser_key == "firefox":
    return Path.home() / "Library" / "Application Support" / "Firefox"
  if browser_key == "zen":
    return Path.home() / "Library" / "Application Support" / "zen"
  raise CookieLoadError(f"unsupported Mozilla-family browser: {browser_key}")


def _resolve_install_default_profile(browser_dir: Path, installs_ini: Path) -> Path | None:
  if not installs_ini.exists():
    return None
  config = ConfigParser()
  config.read(installs_ini, encoding="utf-8")
  for section_name in config.sections():
    default_path = config[section_name].get("Default", "").strip()
    if not default_path:
      continue
    return browser_dir / default_path
  return None


def _resolve_firefox_profile_path(firefox_dir: Path, section) -> Path:
  path_value = section.get("Path", "")
  if not path_value:
    raise CookieLoadError("Firefox profile entry is missing Path")
  if section.get("IsRelative", "1") == "1":
    return firefox_dir / path_value
  return Path(path_value).expanduser()


def _read_cookie_file(path: Path) -> str:
  try:
    return path.read_text(encoding="utf-8")
  except OSError as exc:
    raise CookieLoadError(f"failed to read cookie file {path}: {exc}") from exc


def _detect_cookie_file_format(text: str) -> str:
  stripped = text.lstrip()
  if not stripped:
    return "namevalue"
  if stripped.startswith("{") or stripped.startswith("["):
    return "json"
  for line in stripped.splitlines():
    candidate = line.strip()
    if not candidate:
      continue
    if candidate.startswith("# Netscape HTTP Cookie File"):
      return "netscape"
    if candidate.startswith("#HttpOnly_") or candidate.count("\t") >= 6:
      return "netscape"
    break
  return "namevalue"


def _load_namevalue_cookie_jar(text: str, *, source: str) -> RequestsCookieJar:
  jar = RequestsCookieJar()
  for line_number, raw_line in enumerate(text.splitlines(), start=1):
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    name, value = _parse_namevalue_cookie(line, source=f"{source}:{line_number}")
    jar.set(name, value)
  return jar


def _parse_namevalue_cookie(raw_cookie: str, *, source: str) -> tuple[str, str]:
  if "=" not in raw_cookie:
    raise CookieLoadError(f"invalid cookie in {source}: {raw_cookie!r}; expected NAME=VALUE")
  name, value = raw_cookie.split("=", 1)
  name = name.strip()
  if not name:
    raise CookieLoadError(f"invalid cookie in {source}: empty cookie name")
  return (name, value)


def _load_netscape_cookie_jar(text: str, *, source: str) -> RequestsCookieJar:
  jar = RequestsCookieJar()
  for line_number, raw_line in enumerate(text.splitlines(), start=1):
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    fields = raw_line.split("\t")
    if len(fields) != 7:
      raise CookieLoadError(
        f"invalid Netscape cookie record in {source}:{line_number}: expected 7 tab-separated fields"
      )
    domain, _include_subdomains, path, secure_flag, expires, name, value = fields
    jar.set_cookie(
      create_cookie(
        name=name,
        value=value,
        domain=domain,
        path=path or "/",
        secure=secure_flag.upper() == "TRUE",
        expires=int(expires) if expires.isdigit() else None,
      )
    )
  return jar


def _load_json_cookie_jar(text: str, *, source: str) -> RequestsCookieJar:
  try:
    payload = json.loads(text)
  except json.JSONDecodeError as exc:
    raise CookieLoadError(f"invalid JSON cookie file {source}: {exc}") from exc
  if isinstance(payload, dict):
    payload = payload.get("cookies", payload)
  if not isinstance(payload, list):
    raise CookieLoadError(f"invalid JSON cookie file {source}: expected a list or object with cookies")

  jar = RequestsCookieJar()
  for index, item in enumerate(payload, start=1):
    if not isinstance(item, dict):
      raise CookieLoadError(f"invalid cookie object in {source} at index {index}: expected an object")
    name = str(item.get("name", "")).strip()
    if not name:
      raise CookieLoadError(f"invalid cookie object in {source} at index {index}: missing name")
    value = str(item.get("value", ""))
    jar.set_cookie(
      create_cookie(
        name=name,
        value=value,
        domain=str(item.get("domain", "")) or "",
        path=str(item.get("path", "/")) or "/",
        secure=bool(item.get("secure", False)),
        expires=_coerce_optional_int(item.get("expires")),
      )
    )
  return jar


def _coerce_optional_int(value: object) -> int | None:
  if value in {None, "", 0, "0"}:
    return None
  if isinstance(value, int):
    return value
  if isinstance(value, str) and value.lstrip("-").isdigit():
    return int(value)
  raise CookieLoadError(f"invalid cookie expires value: {value!r}")
