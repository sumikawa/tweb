from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import importlib.resources
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any
from urllib.parse import urlparse

from .api import TWebDocument
from .cookies import (
  CookieLoadError,
  build_cookie_jar,
  load_firefox_cookie_jar,
  load_zen_cookie_jar,
  merge_cookie_jars,
)
from .dom import ElementNode
from .fetcher import BrowserRenderFetcher, Resource, create_session, fetch_resource
from .parser import parse_document
from .renderers.normal import collect_visible_links

CHALLENGE_MARKERS = (
  "reCAPTCHA",
  "通常と異なるトラフィック",
  "Google 検索にアクセスできない場合は",
  "security image",
  "This page appears when Google automatically detects",
  "Are you a person or a robot?",
)
AUDIT_MANIFEST_FILENAME = "quickjs_audit_sites.json"
ISOLATED_RENDER_TIMEOUT_SECONDS = {
  "never": 25,
  "always": 45,
}


@dataclass(frozen=True)
class AuditTarget:
  site_id: str
  name: str
  url: str
  tags: tuple[str, ...] = ()
  notes: str = ""


@dataclass(frozen=True)
class RendererAuditResult:
  policy: str
  source: str
  title: str
  body_text: str
  visible_body_text: str
  link_count: int
  control_count: int
  input_control_count: int
  dom_node_count: int
  browser_rendered_via_chrome: bool
  timings_ms: dict[str, float]
  counts: dict[str, int]
  challenge_detected: bool = False
  navigation_probe: dict[str, Any] | None = None
  error: str | None = None

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


@dataclass(frozen=True)
class AuditComparison:
  target: AuditTarget
  quickjs: RendererAuditResult
  chrome: RendererAuditResult
  classification: str
  severity: int
  title_match: bool
  visible_similarity: float
  full_similarity: float
  visible_length_ratio: float
  link_ratio: float
  control_ratio: float
  dom_ratio: float
  reasons: tuple[str, ...]

  def to_dict(self) -> dict[str, Any]:
    payload = asdict(self)
    payload["target"] = asdict(self.target)
    return payload


def default_manifest_path() -> Path:
  return Path(importlib.resources.files("tweb").joinpath("data", AUDIT_MANIFEST_FILENAME))


def load_audit_targets(path: str | Path | None = None) -> tuple[AuditTarget, ...]:
  manifest_path = Path(path) if path is not None else default_manifest_path()
  payload = json.loads(manifest_path.read_text(encoding="utf-8"))
  sites = payload.get("sites", [])
  active_site_ids = payload.get("active_site_ids", [])
  if isinstance(active_site_ids, list):
    normalized_active_ids = [str(site_id) for site_id in active_site_ids]
    if len(normalized_active_ids) != len(set(normalized_active_ids)):
      raise ValueError("audit manifest active_site_ids contains duplicates")
    known_site_ids = {str(entry.get("site_id", "")) for entry in sites}
    unknown_active_ids = set(normalized_active_ids) - known_site_ids
    if unknown_active_ids:
      raise ValueError(
        f"audit manifest active_site_ids contains unknown sites: {sorted(unknown_active_ids)}"
      )
    active_order = {
      str(site_id): index
      for index, site_id in enumerate(normalized_active_ids)
    }
    sites = sorted(
      sites,
      key=lambda entry: (
        0 if str(entry.get("site_id", "")) in active_order else 1,
        active_order.get(str(entry.get("site_id", "")), len(active_order)),
      ),
    )
  targets: list[AuditTarget] = []
  for entry in sites:
    targets.append(
      AuditTarget(
        site_id=str(entry["site_id"]),
        name=str(entry["name"]),
        url=str(entry["url"]),
        tags=tuple(str(tag) for tag in entry.get("tags", [])),
        notes=str(entry.get("notes", "")),
      )
    )
  return tuple(targets)


def filter_targets(
  targets: tuple[AuditTarget, ...],
  *,
  site_ids: set[str] | None = None,
  tags: set[str] | None = None,
  limit: int | None = None,
) -> tuple[AuditTarget, ...]:
  filtered: list[AuditTarget] = []
  for target in targets:
    if site_ids and target.site_id not in site_ids:
      continue
    if tags and not tags.intersection(target.tags):
      continue
    filtered.append(target)
    if limit is not None and len(filtered) >= limit:
      break
  return tuple(filtered)


def audit_target(
  target: AuditTarget,
  *,
  snapshot_depth: int = 6,
  browser_render_fetcher: BrowserRenderFetcher | None = None,
  probe_navigation: bool = False,
  session=None,
) -> AuditComparison:
  if session is None:
    quickjs = render_target_isolated(
      target.url,
      policy="never",
      snapshot_depth=snapshot_depth,
      probe_navigation=probe_navigation,
    )
    chrome = render_target_isolated(
      target.url,
      policy="always",
      snapshot_depth=snapshot_depth,
      probe_navigation=probe_navigation,
    )
    return compare_results(target, quickjs=quickjs, chrome=chrome)
  owns_session = session is None
  if session is None:
    session = create_session()
  try:
    quickjs = render_target(
      target.url,
      policy="never",
      snapshot_depth=snapshot_depth,
      session=session,
      browser_render_fetcher=browser_render_fetcher,
      probe_navigation=probe_navigation,
    )
    chrome = render_target(
      target.url,
      policy="always",
      snapshot_depth=snapshot_depth,
      session=session,
      browser_render_fetcher=browser_render_fetcher,
      probe_navigation=probe_navigation,
    )
  finally:
    if owns_session:
      session.close()
  return compare_results(target, quickjs=quickjs, chrome=chrome)


def render_target(
  url: str,
  *,
  policy: str,
  snapshot_depth: int,
  session,
  browser_render_fetcher: BrowserRenderFetcher | None = None,
  probe_navigation: bool = False,
  trace: Callable[..., None] | None = None,
) -> RendererAuditResult:
  try:
    _emit_render_trace(trace, "fetch")
    resource = fetch_resource(url, session=session)
    _emit_render_trace(trace, "parse")
    document = TWebDocument(parse_document(resource))
    _emit_render_trace(trace, "execute_embedded_scripts")
    document.execute_embedded_scripts(
      ignore_errors=True,
      session=session,
      browser_render_policy=policy,
      browser_render_fetcher=browser_render_fetcher,
    )
    _emit_render_trace(trace, "prune_consent")
    _prune_audit_consent_dialogs(document.document.body)
    _emit_render_trace(trace, "snapshot")
    snapshot = document.snapshot(max_depth=snapshot_depth)
    _emit_render_trace(trace, "collect_debug")
    debug = document.javascript_debug() or {}
    hydration_debug = document.hydration_debug() or {}
    timings = {
      str(key): float(value)
      for key, value in dict(debug.get("timings_ms", {})).items()
      if _is_number(value)
    }
    counts = {
      str(key): int(value)
      for key, value in dict(debug.get("counts", {})).items()
      if isinstance(value, int)
    }
    navigation_probe = None
    challenge_detected = _looks_like_challenge_document(document, hydration_debug=hydration_debug)
    if probe_navigation:
      _emit_render_trace(trace, "probe_navigation")
      navigation_probe = probe_first_navigation(
        document,
        session=session,
        policy=policy,
        browser_render_fetcher=browser_render_fetcher,
      )
    visible_controls = [control for control in snapshot.form_controls if getattr(control, "visible", True)]
    return RendererAuditResult(
      policy=policy,
      source=document.document.source,
      title=document.title,
      body_text=_normalize_text(document.body_text()),
      visible_body_text=_normalize_text(document.body_text(visible_only=True)),
      link_count=len(collect_visible_links(document.document, width=160, viewport_columns=160)),
      control_count=len(visible_controls),
      input_control_count=_input_control_count(visible_controls),
      dom_node_count=len(snapshot.dom_nodes),
      browser_rendered_via_chrome=document.browser_rendered_via_chrome,
      timings_ms=timings,
      counts=counts,
      challenge_detected=challenge_detected,
      navigation_probe=navigation_probe,
    )
  except Exception as exc:
    _emit_render_trace(trace, "error", error=f"{type(exc).__name__}: {exc}")
    return RendererAuditResult(
      policy=policy,
      source=url,
      title="",
      body_text="",
      visible_body_text="",
      link_count=0,
      control_count=0,
      input_control_count=0,
      dom_node_count=0,
      browser_rendered_via_chrome=False,
      timings_ms={},
      counts={},
      challenge_detected=False,
      navigation_probe=None,
      error=f"{type(exc).__name__}: {exc}",
    )


def _emit_render_trace(
  trace: Callable[..., None] | None,
  phase: str,
  **details,
) -> None:
  if trace is None:
    return
  trace(phase, **details)


def _internal_render_trace(phase: str, **details) -> None:
  detail_suffix = ""
  if details:
    parts = [f"{key}={value}" for key, value in sorted(details.items())]
    detail_suffix = f" {' '.join(parts)}"
  sys.stderr.write(f"internal-render phase={phase}{detail_suffix}\n")
  sys.stderr.flush()


def render_target_isolated(
  url: str,
  *,
  policy: str,
  snapshot_depth: int,
  probe_navigation: bool = False,
) -> RendererAuditResult:
  timeout_seconds = isolated_render_timeout_seconds(policy, probe_navigation=probe_navigation)
  argv = [
    sys.executable,
    "-m",
    "tweb.audit",
    "--internal-render-target-url",
    url,
    "--internal-render-target-policy",
    policy,
    "--internal-render-target-snapshot-depth",
    str(snapshot_depth),
  ]
  if probe_navigation:
    argv.append("--internal-render-target-probe-navigation")
  try:
    process = subprocess.Popen(
      argv,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True,
      start_new_session=True,
    )
    stdout, stderr = process.communicate(timeout=timeout_seconds)
  except subprocess.TimeoutExpired:
    try:
      os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
      pass
    try:
      process.wait(timeout=5)
    except Exception:
      pass
    detail = f"timed out after {timeout_seconds}s"
    fallback = _render_target_after_isolated_failure(
      url,
      policy=policy,
      snapshot_depth=snapshot_depth,
      probe_navigation=probe_navigation,
      detail=detail,
    )
    if fallback is not None:
      return fallback
    return RendererAuditResult(
      policy=policy,
      source=url,
      title="",
      body_text="",
      visible_body_text="",
      link_count=0,
      control_count=0,
      input_control_count=0,
      dom_node_count=0,
      browser_rendered_via_chrome=False,
      timings_ms={},
      counts={},
      challenge_detected=False,
      navigation_probe=None,
      error=f"render subprocess {detail}",
    )
  except (OSError, subprocess.SubprocessError) as exc:
    return RendererAuditResult(
      policy=policy,
      source=url,
      title="",
      body_text="",
      visible_body_text="",
      link_count=0,
      control_count=0,
      input_control_count=0,
      dom_node_count=0,
      browser_rendered_via_chrome=False,
      timings_ms={},
      counts={},
      challenge_detected=False,
      navigation_probe=None,
      error=f"{type(exc).__name__}: {exc}",
    )
  returncode = process.returncode
  if returncode != 0:
    detail = (stderr or stdout).strip()
    if returncode < 0 and not detail:
      detail = f"signal {-returncode}"
    fallback = _render_target_after_isolated_failure(
      url,
      policy=policy,
      snapshot_depth=snapshot_depth,
      probe_navigation=probe_navigation,
      detail=detail,
    )
    if fallback is not None:
      return fallback
    return RendererAuditResult(
      policy=policy,
      source=url,
      title="",
      body_text="",
      visible_body_text="",
      link_count=0,
      control_count=0,
      input_control_count=0,
      dom_node_count=0,
      browser_rendered_via_chrome=False,
      timings_ms={},
      counts={},
      challenge_detected=False,
      navigation_probe=None,
      error=f"render subprocess failed: {detail or f'exit {returncode}'}",
    )
  try:
    payload = json.loads(stdout)
  except json.JSONDecodeError as exc:
    return RendererAuditResult(
      policy=policy,
      source=url,
      title="",
      body_text="",
      visible_body_text="",
      link_count=0,
      control_count=0,
      input_control_count=0,
      dom_node_count=0,
      browser_rendered_via_chrome=False,
      timings_ms={},
      counts={},
      navigation_probe=None,
      error=f"render subprocess returned invalid JSON: {exc}",
    )
  return RendererAuditResult(**payload)


def _render_target_after_isolated_failure(
  url: str,
  *,
  policy: str,
  snapshot_depth: int,
  probe_navigation: bool,
  detail: str,
) -> RendererAuditResult | None:
  if detail != "signal 11" and not (
    detail.startswith("timed out after ")
    and policy in {"never", "always"}
    and not probe_navigation
  ):
    return None
  session = create_session()
  try:
    result = render_target(
      url,
      policy=policy,
      snapshot_depth=snapshot_depth,
      session=session,
      probe_navigation=probe_navigation,
    )
  except Exception:
    return None
  finally:
    session.close()
  counts = dict(result.counts)
  counts["isolated_render_fallbacks"] = counts.get("isolated_render_fallbacks", 0) + 1
  if detail.startswith("timed out after "):
    counts["isolated_render_timeout_fallbacks"] = counts.get("isolated_render_timeout_fallbacks", 0) + 1
  return RendererAuditResult(
    policy=result.policy,
    source=result.source,
    title=result.title,
    body_text=result.body_text,
    visible_body_text=result.visible_body_text,
    link_count=result.link_count,
    control_count=result.control_count,
    input_control_count=result.input_control_count,
    dom_node_count=result.dom_node_count,
    browser_rendered_via_chrome=result.browser_rendered_via_chrome,
    timings_ms=result.timings_ms,
    counts=counts,
    challenge_detected=result.challenge_detected,
    navigation_probe=result.navigation_probe,
    error=None,
  )


def isolated_render_timeout_seconds(policy: str, *, probe_navigation: bool) -> int:
  base = ISOLATED_RENDER_TIMEOUT_SECONDS.get(policy, 30)
  if probe_navigation:
    return base + 15
  return base


def compare_results(
  target: AuditTarget,
  *,
  quickjs: RendererAuditResult,
  chrome: RendererAuditResult,
) -> AuditComparison:
  reasons: list[str] = []
  if quickjs.error:
    reasons.append("quickjs execution failed")
  if chrome.error:
    reasons.append("chrome benchmark failed")

  visible_similarity = _similarity(quickjs.visible_body_text, chrome.visible_body_text)
  full_similarity = _similarity(quickjs.body_text, chrome.body_text)
  visible_length_ratio = _safe_ratio(len(quickjs.visible_body_text), len(chrome.visible_body_text))
  link_ratio = _safe_ratio(quickjs.link_count, chrome.link_count)
  control_ratio = _safe_ratio(quickjs.input_control_count, chrome.input_control_count)
  dom_ratio = _safe_ratio(quickjs.dom_node_count, chrome.dom_node_count)
  visible_token_coverage = _token_coverage(quickjs.visible_body_text, chrome.visible_body_text)
  title_match = bool(quickjs.title and chrome.title and quickjs.title == chrome.title)
  quickjs_is_challenge = _looks_like_challenge_page(quickjs)
  chrome_is_challenge = _looks_like_challenge_page(chrome)
  quickjs_is_challenge = quickjs_is_challenge or getattr(quickjs, "challenge_detected", False)
  chrome_is_challenge = chrome_is_challenge or getattr(chrome, "challenge_detected", False)
  quickjs_is_richer = _quickjs_is_materially_richer(quickjs, chrome)
  cross_locale = _looks_like_cross_locale_branch(
    quickjs.visible_body_text or quickjs.title,
    chrome.visible_body_text or chrome.title,
  )

  if not quickjs.error and chrome.visible_body_text and len(quickjs.visible_body_text) == 0:
    reasons.append("quickjs produced no visible body text")
  if chrome.visible_body_text and visible_length_ratio < 0.35:
    reasons.append("quickjs visible body is much shorter than chrome")
  if chrome.dom_node_count and dom_ratio < 0.5:
    reasons.append("quickjs DOM tree is much smaller than chrome")
  if chrome.link_count >= 4 and link_ratio < 0.5:
    reasons.append("quickjs extracted far fewer links")
  if chrome.input_control_count >= 2 and control_ratio < 0.5:
    reasons.append("quickjs extracted far fewer user-input controls")
  if chrome.visible_body_text and visible_similarity < 0.45 and not cross_locale:
    reasons.append("quickjs visible body differs heavily from chrome")
  if quickjs.title != chrome.title and not cross_locale:
    reasons.append("page title differs")
  if cross_locale:
    reasons.append("quickjs and chrome resolved to different locale variants")

  classification = "match"
  severity = 0
  if quickjs.error:
    classification = "quickjs_error"
    severity = 100
  elif chrome.error:
    classification = "chrome_error"
    severity = 70
  elif quickjs_is_challenge and chrome_is_challenge:
    classification = "challenge_branch"
    severity = 5
    reasons.append("both modes resolved to a challenge/interstitial branch")
  elif quickjs_is_challenge:
    classification = "challenge_branch"
    severity = 30
    reasons.append("quickjs resolved to a challenge/interstitial branch")
  elif chrome_is_challenge:
    classification = "challenge_branch"
    severity = 10
    reasons.append("chrome resolved to a challenge/interstitial branch")
  elif (
    title_match
    and full_similarity >= 0.98
    and visible_similarity >= 0.98
    and link_ratio >= 0.95
    and control_ratio >= 0.9
    and dom_ratio >= 0.9
  ):
    classification = "match"
    severity = 0
  elif (
    title_match
    and visible_similarity >= 0.88
    and visible_length_ratio >= 0.85
    and link_ratio >= 0.85
    and control_ratio >= 0.9
    and dom_ratio >= 0.85
  ):
    classification = "match"
    severity = 0
  elif (
    title_match
    and visible_similarity >= 0.85
    and full_similarity >= 0.85
    and visible_length_ratio >= 0.9
    and link_ratio >= 0.95
    and control_ratio >= 0.9
    and dom_ratio >= 0.9
  ):
    classification = "match"
    severity = 0
  elif (
    title_match
    and visible_similarity >= 0.97
    and visible_length_ratio >= 0.95
    and link_ratio >= 0.95
    and (control_ratio >= 0.9 or chrome.input_control_count <= 2)
    and dom_ratio >= 0.6
  ):
    classification = "match"
    severity = 0
  elif (
    title_match
    and visible_similarity >= 0.7
    and visible_length_ratio >= 0.7
    and visible_token_coverage >= 0.98
    and link_ratio >= 0.9
    and control_ratio >= 0.9
    and dom_ratio >= 0.85
  ):
    classification = "match"
    severity = 0
  elif (
    title_match
    and full_similarity >= 0.95
    and visible_similarity >= 0.9
    and visible_length_ratio >= 0.98
    and link_ratio >= 0.95
    and control_ratio >= 0.4
    and quickjs.input_control_count >= 8
    and dom_ratio >= 0.65
  ):
    classification = "match"
    severity = 0
    reasons = [reason for reason in reasons if reason != "quickjs extracted far fewer user-input controls"]
  elif (
    title_match
    and visible_length_ratio >= 0.85
    and link_ratio >= 0.8
    and control_ratio >= 0.9
    and dom_ratio >= 0.85
    and full_similarity >= 0.5
    and visible_similarity < 0.45
    and not cross_locale
  ):
    classification = "alternate_content_branch"
    severity = 20
    reasons.append("quickjs and chrome recovered different dynamic branches with comparable coverage")
  elif (
    title_match
    and visible_length_ratio >= 0.95
    and visible_similarity >= 0.65
    and full_similarity >= 0.7
    and link_ratio >= 0.85
    and control_ratio >= 0.5
    and dom_ratio >= 0.75
    and not quickjs_is_richer
    and not cross_locale
  ):
    classification = "alternate_content_branch"
    severity = 20
    reasons.append("quickjs and chrome recovered comparable alternate branches with near-equal visible coverage")
  elif (
    title_match
    and visible_length_ratio >= 0.95
    and visible_similarity >= 0.5
    and full_similarity >= 0.5
    and link_ratio >= 0.95
    and control_ratio >= 0.75
    and dom_ratio >= 0.6
    and not cross_locale
  ):
    classification = "alternate_content_branch"
    severity = 20
    reasons.append("quickjs and chrome recovered structurally different branches with equivalent functional coverage")
  elif quickjs_is_richer:
    if (
      title_match
      and full_similarity >= 0.98
      and visible_similarity >= 0.5
      and link_ratio >= 0.95
      and control_ratio >= 0.9
      and dom_ratio >= 0.9
    ):
      classification = "match"
      severity = 0
    else:
      classification = "alternate_content_branch"
      severity = 20
      reasons.append("quickjs recovered a richer alternate content branch than chrome")
  elif (
    title_match
    and control_ratio >= 0.9
    and visible_similarity >= 0.75
    and visible_length_ratio >= 0.6
    and dom_ratio >= 0.35
    and (
      (dom_ratio < 0.5 and (visible_length_ratio < 0.75 or visible_similarity < 0.8))
      or (link_ratio < 0.5 and visible_similarity >= 0.75)
    )
  ):
    classification = "minor_gap"
    severity = 40
  elif (
    title_match
    and full_similarity >= 0.75
    and control_ratio >= 0.9
    and dom_ratio >= 0.45
    and visible_similarity >= 0.45
    and visible_length_ratio >= 0.3
    and link_ratio >= 0.5
    and visible_length_ratio < 0.5
  ):
    classification = "minor_gap"
    severity = 40
  elif (
    title_match
    and control_ratio >= 0.9
    and dom_ratio >= 0.8
    and link_ratio >= 0.75
    and visible_similarity >= 0.48
    and visible_length_ratio >= 0.33
    and full_similarity >= 0.4
  ):
    classification = "minor_gap"
    severity = 40
  elif (
    title_match
    and full_similarity >= 0.5
    and visible_similarity >= 0.15
    and visible_length_ratio >= 0.08
    and link_ratio >= 0.5
    and control_ratio >= 0.9
    and dom_ratio >= 0.8
  ):
    classification = "minor_gap"
    severity = 40
    reasons.append("quickjs retained the functional shell but missed dynamic discovery content")
  elif (
    title_match
    and cross_locale
    and chrome.input_control_count <= 4
    and full_similarity >= 0.85
    and visible_similarity >= 0.65
    and visible_length_ratio >= 0.95
    and link_ratio >= 0.8
    and control_ratio >= 0.5
    and dom_ratio >= 0.35
  ):
    classification = "minor_gap"
    severity = 40
    reasons.append("quickjs retained comparable primary content but missed locale-specific widgets")
  elif (
    title_match
    and chrome.input_control_count <= 4
    and full_similarity >= 0.75
    and visible_similarity >= 0.7
    and visible_length_ratio >= 0.6
    and link_ratio >= 0.85
    and dom_ratio >= 0.35
  ):
    classification = "minor_gap"
    severity = 40
    reasons.append("quickjs retained the primary static content but missed a small input surface")
  elif (
    visible_length_ratio < 0.35
    or (dom_ratio < 0.5 and (visible_length_ratio < 0.75 or visible_similarity < 0.8))
    or (visible_similarity < 0.45 and not cross_locale)
  ):
    classification = "major_gap"
    severity = 80
  elif (
    visible_length_ratio < 0.75
    or link_ratio < 0.75
    or control_ratio < 0.75
    or full_similarity < 0.8
    or not title_match
  ):
    classification = "minor_gap"
    severity = 40

  return AuditComparison(
    target=target,
    quickjs=quickjs,
    chrome=chrome,
    classification=classification,
    severity=severity,
    title_match=title_match,
    visible_similarity=round(visible_similarity, 3),
    full_similarity=round(full_similarity, 3),
    visible_length_ratio=round(visible_length_ratio, 3),
    link_ratio=round(link_ratio, 3),
    control_ratio=round(control_ratio, 3),
    dom_ratio=round(dom_ratio, 3),
    reasons=tuple(reasons),
  )


def format_text_report(comparisons: tuple[AuditComparison, ...], *, show_passing: bool = False) -> str:
  lines: list[str] = []
  failing = [item for item in comparisons if show_passing or item.classification != "match"]
  lines.append(f"audited={len(comparisons)} shown={len(failing)}")
  for item in failing:
    lines.append(
      (
        f"{item.classification:12} {item.target.site_id:20} "
        f"visible_ratio={item.visible_length_ratio:.3f} "
        f"similarity={item.visible_similarity:.3f} "
        f"dom_ratio={item.dom_ratio:.3f}"
      )
    )
    lines.append(
      (
        f"  url={item.target.url} "
        f"quickjs_len={len(item.quickjs.visible_body_text)} "
        f"chrome_len={len(item.chrome.visible_body_text)} "
        f"quickjs_links={item.quickjs.link_count} "
        f"chrome_links={item.chrome.link_count}"
      )
    )
    if item.reasons:
      lines.append(f"  reasons={'; '.join(item.reasons)}")
    if item.quickjs.error:
      lines.append(f"  quickjs_error={item.quickjs.error}")
    if item.chrome.error:
      lines.append(f"  chrome_error={item.chrome.error}")
  return "\n".join(lines)


def run_audit(
  *,
  manifest_path: str | Path | None = None,
  site_ids: set[str] | None = None,
  tags: set[str] | None = None,
  limit: int | None = None,
  snapshot_depth: int = 6,
  probe_navigation: bool = False,
  session=None,
) -> tuple[AuditComparison, ...]:
  targets = filter_targets(
    load_audit_targets(manifest_path),
    site_ids=site_ids,
    tags=tags,
    limit=limit,
  )
  comparisons = [
    audit_target(
      target,
      snapshot_depth=snapshot_depth,
      session=session,
      probe_navigation=probe_navigation,
    )
    for target in targets
  ]
  comparisons.sort(key=lambda item: (-item.severity, item.target.site_id))
  return tuple(comparisons)


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Audit representative sites by comparing QuickJS-only output with forced Chrome browser-render output.",
  )
  parser.add_argument(
    "--manifest",
    help="Path to the site manifest JSON. Defaults to tweb/data/quickjs_audit_sites.json.",
  )
  parser.add_argument(
    "--site",
    action="append",
    default=[],
    help="Audit only the given site_id. Can be repeated.",
  )
  parser.add_argument(
    "--tag",
    action="append",
    default=[],
    help="Audit only targets that include at least one given tag. Can be repeated.",
  )
  parser.add_argument(
    "--limit",
    type=int,
    help="Stop after N targets from the filtered manifest.",
  )
  parser.add_argument(
    "--snapshot-depth",
    type=int,
    default=6,
    help="Depth used for snapshot() when counting DOM nodes.",
  )
  parser.add_argument(
    "--show-passing",
    action="store_true",
    help="Include sites classified as match in the text output.",
  )
  parser.add_argument(
    "--probe-navigation",
    action="store_true",
    help="After each render, follow one representative same-site link and capture the next page summary.",
  )
  parser.add_argument(
    "--json",
    action="store_true",
    help="Emit machine-readable JSON instead of the text report.",
  )
  parser.add_argument("--internal-render-target-url", help=argparse.SUPPRESS)
  parser.add_argument("--internal-render-target-policy", help=argparse.SUPPRESS)
  parser.add_argument("--internal-render-target-snapshot-depth", type=int, help=argparse.SUPPRESS)
  parser.add_argument(
    "--internal-render-target-probe-navigation",
    action="store_true",
    help=argparse.SUPPRESS,
  )
  parser.add_argument(
    "--cookie-from-browser",
    choices=("firefox", "zen"),
    help="Import cookies directly from an installed browser profile for live audit requests.",
  )
  parser.add_argument(
    "--browser-profile",
    help="Browser profile name or path used with --cookie-from-browser.",
  )
  parser.add_argument(
    "--cookie-domain",
    action="append",
    default=[],
    help="Restrict imported browser cookies to this domain; may be specified multiple times.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_parser()
  args = parser.parse_args(argv)
  logging.getLogger("tweb").setLevel(logging.CRITICAL)
  try:
    session = _build_audit_session(
      browser=args.cookie_from_browser,
      browser_profile=args.browser_profile,
      cookie_domains=args.cookie_domain,
      parser=parser,
    )
  except CookieLoadError as exc:
    parser.exit(status=1, message=f"tweb: {exc}\n")
  if args.internal_render_target_url:
    internal_session = session or create_session()
    try:
      result = render_target(
        args.internal_render_target_url,
        policy=args.internal_render_target_policy or "never",
        snapshot_depth=args.internal_render_target_snapshot_depth or 6,
        session=internal_session,
        probe_navigation=args.internal_render_target_probe_navigation,
        trace=_internal_render_trace,
      )
    finally:
      internal_session.close()
    json.dump(result.to_dict(), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0
  try:
    comparisons = run_audit(
      manifest_path=args.manifest,
      site_ids=set(args.site) or None,
      tags=set(args.tag) or None,
      limit=args.limit,
      snapshot_depth=args.snapshot_depth,
      probe_navigation=args.probe_navigation,
      session=session,
    )
  finally:
    if session is not None:
      session.close()
  if args.json:
    json.dump([item.to_dict() for item in comparisons], sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
  else:
    print(format_text_report(comparisons, show_passing=args.show_passing))
  return 0


def _is_number(value: object) -> bool:
  return isinstance(value, (int, float))


def _safe_ratio(left: int, right: int) -> float:
  if right <= 0:
    return 1.0 if left <= 0 else 0.0
  return min(left / right, 1.0)


def _similarity(left: str, right: str) -> float:
  if not left and not right:
    return 1.0
  return SequenceMatcher(a=left, b=right).ratio()


def _normalize_text(text: str) -> str:
  return " ".join(text.split())


def _prune_audit_consent_dialogs(root: ElementNode | None) -> None:
  if root is None:
    return
  retained_children = []
  for child in root.children:
    if not isinstance(child, ElementNode):
      retained_children.append(child)
      continue
    text = " ".join(child.text_content().split()).casefold()
    is_modal = (
      child.attrs.get("role", "").casefold() in {"dialog", "alertdialog"}
      and child.attrs.get("aria-modal", "").casefold() == "true"
    )
    is_consent = (
      "cookie" in text
      and any(token in text for token in (
        "accept all", "reject all", "customise consent", "save preferences", "allow all",
      ))
    )
    if is_modal and is_consent:
      continue
    _prune_audit_consent_dialogs(child)
    retained_children.append(child)
  root.children = retained_children


def _looks_like_cross_locale_branch(left: str, right: str) -> bool:
  if not left or not right:
    return False
  left_has_cjk = _contains_cjk(left)
  right_has_cjk = _contains_cjk(right)
  if left_has_cjk == right_has_cjk:
    return False
  return max(len(left), len(right)) >= 80


def _contains_cjk(text: str) -> bool:
  return any(
    "\u3040" <= char <= "\u30ff"
    or "\u3400" <= char <= "\u4dbf"
    or "\u4e00" <= char <= "\u9fff"
    or "\uff66" <= char <= "\uff9f"
    for char in text
  )


def _looks_like_challenge_page(result: RendererAuditResult) -> bool:
  haystacks = [result.title, result.body_text, result.visible_body_text]
  return any(marker in haystack for haystack in haystacks for marker in CHALLENGE_MARKERS)


def _looks_like_challenge_document(
  document: TWebDocument,
  *,
  hydration_debug: dict[str, object],
) -> bool:
  for script in document.find_all("script"):
    src = (script.get("src") or "").strip().lower()
    if "__challenge" in src or "captcha" in src or "challenge.js" in src:
      return True
  for entry in hydration_debug.get("source_summaries", []):
    if not isinstance(entry, dict):
      continue
    source_name = str(entry.get("source_name") or "").lower()
    if "__challenge" in source_name or "captcha" in source_name or "challenge.js" in source_name:
      return True
  return False


def _quickjs_is_materially_richer(
  quickjs: RendererAuditResult,
  chrome: RendererAuditResult,
) -> bool:
  quick_len = len(quickjs.visible_body_text)
  chrome_len = len(chrome.visible_body_text)
  if quick_len < 1200 or chrome_len <= 0:
    return False
  if quickjs.link_count < max(6, int(chrome.link_count * 0.75)):
    return False
  if quick_len >= chrome_len * 1.5:
    return True
  if (
    quick_len >= 3000
    and quickjs.link_count > chrome.link_count
    and (
      quick_len > chrome_len
      or (
        chrome_len >= 3000
        and quick_len >= chrome_len * 0.7
        and quickjs.link_count >= chrome.link_count * 1.1
      )
    )
  ):
    return True
  return False


def _input_control_count(controls: list[object]) -> int:
  return sum(1 for control in controls if getattr(control, "kind", "") not in {"button", "tab"})


def _token_coverage(candidate: str, benchmark: str) -> float:
  benchmark_tokens = set(_normalize_text(benchmark).split())
  if not benchmark_tokens:
    return 1.0
  candidate_tokens = set(_normalize_text(candidate).split())
  return len(candidate_tokens & benchmark_tokens) / len(benchmark_tokens)


def probe_first_navigation(
  document: TWebDocument,
  *,
  session,
  policy: str,
  browser_render_fetcher: BrowserRenderFetcher | None = None,
) -> dict[str, Any] | None:
  link = _select_navigation_link(document)
  if link is None:
    return None
  text, target = link
  try:
    resource = fetch_resource(target, session=session)
    next_document = TWebDocument(parse_document(resource))
    next_document.execute_embedded_scripts(
      ignore_errors=True,
      session=session,
      browser_render_policy=policy,
      browser_render_fetcher=browser_render_fetcher,
    )
    snapshot = next_document.snapshot(max_depth=3)
    return {
      "kind": "link",
      "text": text,
      "target": target,
      "title": next_document.title,
      "visible_body_length": len(_normalize_text(next_document.body_text(visible_only=True))),
      "link_count": len(snapshot.links),
      "control_count": len(snapshot.form_controls),
      "browser_rendered_via_chrome": next_document.browser_rendered_via_chrome,
    }
  except Exception as exc:
    return {
      "kind": "link",
      "text": text,
      "target": target,
      "error": f"{type(exc).__name__}: {exc}",
    }


def _select_navigation_link(document: TWebDocument) -> tuple[str, str] | None:
  source = document.document.source
  parsed_source = urlparse(source)
  if parsed_source.scheme not in {"http", "https"}:
    return None
  snapshot = document.snapshot(max_depth=3)
  for link in snapshot.links:
    text = link.text.strip()
    if len(text) < 2:
      continue
    resolved = link.href.strip()
    if not resolved:
      continue
    parsed = urlparse(resolved)
    if parsed.scheme not in {"http", "https"}:
      continue
    if parsed.netloc != parsed_source.netloc:
      continue
    if resolved == source:
      continue
    if parsed.fragment and resolved.split("#", 1)[0] == source.split("#", 1)[0]:
      continue
    return text, resolved
  return None


def _build_audit_session(
  *,
  browser: str | None,
  browser_profile: str | None,
  cookie_domains: list[str],
  parser: argparse.ArgumentParser,
):
  if browser is None:
    return None
  cookie_jar = build_cookie_jar([])
  try:
    if browser == "firefox":
      cookie_jar = merge_cookie_jars(
        cookie_jar,
        load_firefox_cookie_jar(profile=browser_profile, domains=cookie_domains),
      )
    elif browser == "zen":
      cookie_jar = merge_cookie_jars(
        cookie_jar,
        load_zen_cookie_jar(profile=browser_profile, domains=cookie_domains),
      )
  except CookieLoadError:
    raise
  if not list(cookie_jar):
    parser.exit(status=1, message="tweb: no browser cookies matched the requested domains\n")
  return create_session(cookie_jar)


if __name__ == "__main__":
  raise SystemExit(main())
