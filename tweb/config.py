from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("~/.config/tw/config.yml")


class ConfigError(ValueError):
  pass


@dataclass(frozen=True)
class RuntimeConfig:
  headers: dict[str, str]


def load_runtime_config(path: Path | None = None) -> RuntimeConfig:
  config_path = (path or DEFAULT_CONFIG_PATH).expanduser()
  if not config_path.exists():
    return RuntimeConfig(headers={})
  try:
    text = config_path.read_text(encoding="utf-8")
  except OSError as exc:
    raise ConfigError(f"failed to read config file {config_path}: {exc}") from exc
  return parse_runtime_config(text, source=str(config_path))


def parse_runtime_config(text: str, *, source: str = "<string>") -> RuntimeConfig:
  headers: dict[str, str] = {}
  user_agent: str | None = None
  in_headers = False
  header_indent: int | None = None
  for line_number, raw_line in enumerate(text.splitlines(), start=1):
    line = raw_line.rstrip()
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
      continue
    leading = raw_line[: len(raw_line) - len(raw_line.lstrip(" \t"))]
    if "\t" in leading:
      raise ConfigError(f"{source}:{line_number}: tab indentation is not supported")
    indent = len(line) - len(line.lstrip(" "))
    key, separator, raw_value = stripped.partition(":")
    if not separator:
      raise ConfigError(f"{source}:{line_number}: expected 'key: value'")
    value = raw_value.lstrip()
    if indent == 0:
      in_headers = False
      header_indent = None
      if key == "headers":
        if value:
          raise ConfigError(f"{source}:{line_number}: inline maps are not supported for headers")
        in_headers = True
        continue
      if key == "user_agent":
        user_agent = _parse_scalar(value, source=source, line_number=line_number)
        continue
      raise ConfigError(f"{source}:{line_number}: unsupported top-level key: {key}")
    if not in_headers:
      raise ConfigError(f"{source}:{line_number}: nested entries are only supported under headers")
    if header_indent is None:
      header_indent = indent
    elif indent != header_indent:
      raise ConfigError(f"{source}:{line_number}: inconsistent headers indentation")
    headers[key] = _parse_scalar(value, source=source, line_number=line_number)
  if user_agent is not None:
    headers["User-Agent"] = user_agent
  return RuntimeConfig(headers=headers)


def _parse_scalar(value: str, *, source: str, line_number: int) -> str:
  if not value:
    return ""
  if value[0] in {"'", '"'}:
    quote = value[0]
    if len(value) < 2 or value[-1] != quote:
      raise ConfigError(f"{source}:{line_number}: unterminated quoted string")
    return value[1:-1]
  return value
