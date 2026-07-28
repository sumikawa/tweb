from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main(argv: list[str]) -> int:
  if len(argv) != 4:
    print("usage: render_with_chrome_devtools.py <browser> <url> <sleep_seconds>", file=sys.stderr)
    return 2
  browser, target, sleep_seconds_raw = argv[1:]
  sleep_seconds = float(sleep_seconds_raw)
  cookies = json.loads(sys.stdin.read() or "[]")

  inbound_read, inbound_write = os.pipe()
  outbound_read, outbound_write = os.pipe()
  saved_fd3 = _dup_if_open(3)
  saved_fd4 = _dup_if_open(4)
  process: subprocess.Popen[bytes] | None = None
  try:
    os.dup2(inbound_read, 3)
    os.dup2(outbound_write, 4)
    os.set_inheritable(3, True)
    os.set_inheritable(4, True)
    process = subprocess.Popen(
      [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--remote-debugging-pipe",
        "about:blank",
      ],
      pass_fds=(3, 4),
      stderr=subprocess.PIPE,
    )
    _restore_fd(3, saved_fd3)
    _restore_fd(4, saved_fd4)
    saved_fd3 = None
    saved_fd4 = None
    os.close(inbound_read)
    os.close(outbound_write)
    with os.fdopen(outbound_read, "rb", buffering=0) as stdout_pipe, os.fdopen(inbound_write, "wb", buffering=0) as stdin_pipe:
      next_id = 0

      def read_message() -> dict[str, object]:
        payload = bytearray()
        while True:
          chunk = stdout_pipe.read(1)
          if not chunk:
            raise RuntimeError(_read_process_stderr(process) or "Chrome DevTools pipe closed")
          if chunk == b"\0":
            break
          payload.extend(chunk)
        return json.loads(payload.decode("utf-8"))

      def send(
        method: str,
        params: dict[str, object] | None = None,
        *,
        session_id: str | None = None,
      ) -> dict[str, object]:
        nonlocal next_id
        next_id += 1
        request: dict[str, object] = {
          "id": next_id,
          "method": method,
        }
        if params is not None:
          request["params"] = params
        if session_id is not None:
          request["sessionId"] = session_id
        stdin_pipe.write(json.dumps(request).encode("utf-8"))
        stdin_pipe.write(b"\0")
        stdin_pipe.flush()
        while True:
          response = read_message()
          if response.get("id") != next_id:
            continue
          if "result" not in response and "error" not in response:
            continue
          if "error" in response:
            raise RuntimeError(f"Chrome DevTools error: {response['error']}")
          return response

      created = send("Target.createTarget", {"url": "about:blank"})
      target_id = created.get("result", {}).get("targetId")
      if not isinstance(target_id, str):
        raise RuntimeError("failed to create Chrome target")
      attached = send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
      session_id = attached.get("result", {}).get("sessionId")
      if not isinstance(session_id, str):
        raise RuntimeError("failed to attach Chrome target")
      send("Page.enable", session_id=session_id)
      send("Network.enable", session_id=session_id)
      send("Runtime.enable", session_id=session_id)
      send("Network.setCookies", {"cookies": cookies}, session_id=session_id)
      send("Page.navigate", {"url": target}, session_id=session_id)
      time.sleep(sleep_seconds)
      result = send(
        "Runtime.evaluate",
        {
          "expression": "document.documentElement.outerHTML",
          "returnByValue": True,
        },
        session_id=session_id,
      )
      value = result.get("result", {}).get("result", {}).get("value")
      if not isinstance(value, str):
        raise RuntimeError("Chrome DevTools did not return HTML")
      sys.stdout.write(value)
      return 0
  finally:
    _restore_fd(3, saved_fd3)
    _restore_fd(4, saved_fd4)
    for fd in (inbound_read, inbound_write, outbound_read, outbound_write):
      try:
        os.close(fd)
      except OSError:
        pass
    if process is not None:
      try:
        process.terminate()
        process.wait(timeout=5)
      except (OSError, subprocess.SubprocessError):
        process.kill()
        process.wait(timeout=5)


def _read_process_stderr(process: subprocess.Popen[bytes] | None) -> str:
  if process is None or process.stderr is None:
    return ""
  try:
    return process.stderr.read().decode("utf-8", errors="replace").strip()
  except OSError:
    return ""


def _dup_if_open(fd: int) -> int | None:
  try:
    return os.dup(fd)
  except OSError:
    return None


def _restore_fd(fd: int, saved: int | None) -> None:
  try:
    if saved is None:
      return
    os.dup2(saved, fd)
    os.close(saved)
  except OSError:
    pass


if __name__ == "__main__":
  raise SystemExit(main(sys.argv))
