from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tweb.audit import (
  AuditTarget,
  RendererAuditResult,
  compare_results,
  filter_targets,
  isolated_render_timeout_seconds,
  load_audit_targets,
  main,
  _prune_audit_consent_dialogs,
  render_target,
  render_target_isolated,
)
from tweb.fetcher import Resource, create_session
from tweb.parser import parse_document


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample.html"


def comparison_result(**overrides):
  values = {
    "error": None,
    "title": "Example",
    "body_text": "",
    "visible_body_text": "",
    "link_count": 0,
    "control_count": 0,
    "input_control_count": 0,
    "dom_node_count": 0,
    "challenge_detected": False,
  }
  values.update(overrides)
  return SimpleNamespace(**values)


class AuditTest(unittest.TestCase):
  @patch("tweb.audit.render_target")
  @patch("tweb.audit.create_session")
  def test_internal_render_uses_persistent_session_without_browser_cookies(
    self,
    mock_create_session,
    mock_render_target,
  ) -> None:
    session = mock_create_session.return_value
    result = Mock()
    result.to_dict.return_value = {}
    mock_render_target.return_value = result

    with patch("tweb.audit._build_audit_session", return_value=None), patch("sys.stdout"):
      exit_code = main([
        "--internal-render-target-url", "https://example.com",
        "--internal-render-target-policy", "never",
        "--internal-render-target-snapshot-depth", "6",
      ])

    self.assertEqual(exit_code, 0)
    mock_render_target.assert_called_once_with(
      "https://example.com",
      policy="never",
      snapshot_depth=6,
      session=session,
      probe_navigation=False,
      trace=unittest.mock.ANY,
    )
    session.close.assert_called_once_with()

  def test_prunes_modal_cookie_consent_from_audit_document(self) -> None:
    document = parse_document(Resource(
      source="https://example.com",
      content="""
      <html><body>
        <main>Forecast content</main>
        <div role="dialog" aria-modal="true">
          This website uses cookies. Accept all. Reject all. Customise consent.
        </div>
        <div role="alertdialog" aria-modal="true">
          Data Preferences. Cookie List. Save preferences. Allow All.
        </div>
        <div role="dialog" aria-modal="true">Save this search</div>
      </body></html>
      """,
    ))

    _prune_audit_consent_dialogs(document.body)

    self.assertIn("Forecast content", document.body.text_content())
    self.assertNotIn("Accept all", document.body.text_content())
    self.assertNotIn("Data Preferences", document.body.text_content())
    self.assertIn("Save this search", document.body.text_content())

  def test_classifies_chrome_only_robot_challenge_as_challenge_branch(self) -> None:
    target = AuditTarget("example", "Example", "https://example.com")
    quickjs = comparison_result(
      title="Example",
      visible_body_text="Normal searchable content with useful links",
      body_text="Normal searchable content with useful links",
      link_count=5,
      input_control_count=1,
      dom_node_count=20,
    )
    chrome = comparison_result(
      title="Skyscanner",
      visible_body_text="Are you a person or a robot? Please enable JavaScript and cookies.",
      body_text="Are you a person or a robot? Please enable JavaScript and cookies.",
      dom_node_count=10,
    )

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "challenge_branch")

  def test_classifies_structurally_different_functional_shell_as_alternate(self) -> None:
    target = AuditTarget("example", "Example", "https://example.com")
    quickjs = comparison_result(
      title="Travel",
      visible_body_text="Search flights hotels cars destinations deals account navigation",
      body_text="Search flights hotels cars destinations deals account navigation",
      link_count=100,
      input_control_count=3,
      dom_node_count=60,
    )
    chrome = comparison_result(
      title="Travel",
      visible_body_text="Search hotels flights cars destinations offers account navigation",
      body_text="Search hotels flights cars destinations offers account navigation",
      link_count=100,
      input_control_count=3,
      dom_node_count=100,
    )

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "alternate_content_branch")

  def test_classifies_low_input_static_portal_shortfall_as_minor_gap(self) -> None:
    target = AuditTarget("example", "Example", "https://example.com")
    quickjs = comparison_result(
      title="Retail",
      visible_body_text="shared primary content " * 70,
      body_text="shared primary content " * 90,
      link_count=121,
      dom_node_count=84,
    )
    chrome = comparison_result(
      title="Retail",
      visible_body_text="shared primary content " * 95,
      body_text="shared primary content " * 100,
      link_count=130,
      input_control_count=4,
      dom_node_count=217,
    )

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "minor_gap")

  def test_default_manifest_contains_unified_targets(self) -> None:
    targets = load_audit_targets()

    self.assertEqual(len(targets), 44)
    self.assertEqual([target.site_id for target in targets[:19]], [
      "qiita-home", "jalan-home", "ndl-home", "yahoo-news-jp-home",
      "gnavi-home", "env-home", "mlit-home", "rakuten-travel-home",
      "gihyo-home", "walgreens-home", "kayak-home", "eventbrite-home",
      "walmart-home", "fsa-home", "navitime-home", "jaxa-home",
      "accuweather-home", "skyscanner-home", "webmd-home",
    ])
    self.assertEqual(targets[19].site_id, "publickey-home")
    self.assertEqual(targets[-1].site_id, "weathercom-home")
    jp_ids = {target.site_id for target in targets if "jp" in target.tags}
    self.assertEqual(jp_ids, {
      "publickey-home", "qiita-home", "jalan-home", "egov-home",
      "mynavi-baito-home", "mhlw-home", "yahoo-travel-home", "ikyu-home",
      "ndl-home", "ipa-home", "zexy-home", "zenn-home",
      "yahoo-news-jp-home", "gnavi-home", "epark-home", "env-home",
      "mlit-home", "itmedia-news-home", "rakuten-travel-home", "gihyo-home",
      "fsa-home", "navitime-home", "jaxa-home", "cao-home",
    })
    self.assertNotIn("suumo-home", {target.site_id for target in targets})
    self.assertNotIn("hotpepper-gourmet-home", {target.site_id for target in targets})
    self.assertNotIn("nhk-news-home", {target.site_id for target in targets})
    self.assertNotIn("impress-watch-home", {target.site_id for target in targets})
    self.assertNotIn("gigazine-home", {target.site_id for target in targets})
    self.assertIn("navitime-home", {target.site_id for target in targets})
    self.assertNotIn("jma-bosai-home", {target.site_id for target in targets})
    self.assertIn("bbc-weather-home", {target.site_id for target in targets})
    self.assertIn("weathercom-home", {target.site_id for target in targets})
    self.assertIn("jp", {tag for target in targets for tag in target.tags})
    self.assertIn("en", {tag for target in targets for tag in target.tags})
    self.assertIn("public", {tag for target in targets for tag in target.tags})
    self.assertIn("service", {tag for target in targets for tag in target.tags})
    self.assertIn("government", {tag for target in targets for tag in target.tags})
    self.assertIn("jobs", {tag for target in targets for tag in target.tags})
    self.assertNotIn("social", {tag for target in targets for tag in target.tags})
    self.assertIn("travel", {tag for target in targets for tag in target.tags})
    self.assertIn("weather", {tag for target in targets for tag in target.tags})

  def test_filter_targets_supports_site_id_and_tag(self) -> None:
    targets = (
      AuditTarget("a", "A", "https://a.example", ("news",)),
      AuditTarget("b", "B", "https://b.example", ("shopping",)),
      AuditTarget("c", "C", "https://c.example", ("news", "jp")),
    )

    filtered = filter_targets(targets, site_ids={"c", "b"}, tags={"jp", "shopping"})

    self.assertEqual([item.site_id for item in filtered], ["b", "c"])

  def test_manifest_rejects_unknown_active_site(self) -> None:
    with TemporaryDirectory() as tmpdir:
      manifest = Path(tmpdir) / "audit.json"
      manifest.write_text(
        '{"active_site_ids":["missing"],"sites":[{"site_id":"known","name":"Known","url":"https://example.com"}]}',
        encoding="utf-8",
      )

      with self.assertRaisesRegex(ValueError, "unknown sites.*missing"):
        load_audit_targets(manifest)

  def test_isolated_render_timeout_seconds_varies_by_policy(self) -> None:
    self.assertEqual(isolated_render_timeout_seconds("never", probe_navigation=False), 25)
    self.assertEqual(isolated_render_timeout_seconds("always", probe_navigation=False), 45)
    self.assertEqual(isolated_render_timeout_seconds("never", probe_navigation=True), 40)

  @patch("tweb.audit.fetch_resource")
  def test_render_target_collects_metrics(self, mock_fetch_resource) -> None:
    mock_fetch_resource.return_value = Resource(
      source=str(SAMPLE),
      content=SAMPLE.read_text(encoding="utf-8"),
    )
    session = create_session()
    try:
      result = render_target(str(SAMPLE), policy="never", snapshot_depth=4, session=session)
    finally:
      session.close()

    self.assertEqual(result.title, "tweb sample")
    self.assertIn("Welcome to tweb", result.visible_body_text)
    self.assertEqual(result.link_count, 1)
    self.assertIsNone(result.error)

  @patch("tweb.audit.fetch_resource")
  def test_render_target_counts_only_visible_links(self, mock_fetch_resource) -> None:
    mock_fetch_resource.return_value = Resource(
      source="https://example.com",
      content=(
        "<html><head><title>Example</title><style>#hidden { display: none; }</style></head>"
        "<body><main><a href='/shown'>Shown</a><nav id='hidden'><a href='/hidden'>Hidden</a></nav></main></body></html>"
      ),
    )
    session = create_session()
    try:
      result = render_target("https://example.com", policy="never", snapshot_depth=4, session=session)
    finally:
      session.close()

    self.assertEqual(result.link_count, 1)

  @patch("tweb.audit.fetch_resource")
  def test_render_target_counts_only_visible_input_controls(self, mock_fetch_resource) -> None:
    mock_fetch_resource.return_value = Resource(
      source="https://example.com",
      content=(
        "<html><head><title>Example</title><style>#hidden { display: none; }</style></head>"
        "<body><main><input id='visible' type='text' value='ok' />"
        "<input id='hidden' type='checkbox' checked /></main></body></html>"
      ),
    )
    session = create_session()
    try:
      result = render_target("https://example.com", policy="never", snapshot_depth=4, session=session)
    finally:
      session.close()

    self.assertEqual(result.control_count, 1)
    self.assertEqual(result.input_control_count, 1)

  @patch("tweb.audit.fetch_resource")
  def test_render_target_can_probe_navigation(self, mock_fetch_resource) -> None:
    root_html = (
      "<html><head><title>Root</title></head>"
      "<body><main><a href='https://example.com/next'>Next page</a></main></body></html>"
    )
    next_html = (
      "<html><head><title>Next</title></head>"
      "<body><main><p>Loaded destination</p></main></body></html>"
    )
    mock_fetch_resource.side_effect = [
      Resource(source="https://example.com", content=root_html),
      Resource(source="https://example.com/next", content=next_html),
    ]
    session = create_session()
    try:
      result = render_target(
        "https://example.com",
        policy="never",
        snapshot_depth=4,
        session=session,
        probe_navigation=True,
      )
    finally:
      session.close()

    self.assertIsNotNone(result.navigation_probe)
    self.assertEqual(result.navigation_probe["target"], "https://example.com/next")
    self.assertEqual(result.navigation_probe["title"], "Next")

  @patch("tweb.audit._render_target_after_isolated_failure")
  @patch("tweb.audit.subprocess.Popen")
  def test_render_target_isolated_returns_structured_error_for_signal_exit(
    self,
    mock_popen,
    mock_fallback,
  ) -> None:
    process = mock_popen.return_value
    process.communicate.return_value = ("", "internal-render phase=execute_embedded_scripts\n")
    process.returncode = -11
    mock_fallback.return_value = None

    result = render_target_isolated("https://example.com", policy="never", snapshot_depth=4)

    self.assertEqual(result.policy, "never")
    self.assertIn("internal-render phase=execute_embedded_scripts", result.error)

  @patch("tweb.audit.render_target")
  @patch("tweb.audit.create_session")
  @patch("tweb.audit.subprocess.Popen")
  def test_render_target_isolated_falls_back_in_process_after_signal_exit(
    self,
    mock_popen,
    mock_create_session,
    mock_render_target,
  ) -> None:
    process = mock_popen.return_value
    process.communicate.return_value = ("", "")
    process.returncode = -11
    session = mock_create_session.return_value
    mock_render_target.return_value = RendererAuditResult(
      policy="never",
      source="https://example.com",
      title="Example",
      body_text="Alpha",
      visible_body_text="Alpha",
      link_count=1,
      control_count=0,
      input_control_count=0,
      dom_node_count=3,
      browser_rendered_via_chrome=False,
      timings_ms={"script_eval": 1.0},
      counts={"eval_calls": 1},
      challenge_detected=False,
      navigation_probe=None,
      error=None,
    )

    result = render_target_isolated("https://example.com", policy="never", snapshot_depth=4)

    self.assertEqual(result.title, "Example")
    self.assertIsNone(result.error)
    self.assertEqual(result.counts.get("isolated_render_fallbacks"), 1)
    mock_render_target.assert_called_once_with(
      "https://example.com",
      policy="never",
      snapshot_depth=4,
      session=session,
      probe_navigation=False,
    )
    session.close.assert_called_once_with()

  @patch("tweb.audit._render_target_after_isolated_failure")
  @patch("tweb.audit.subprocess.Popen")
  @patch("tweb.audit.os.killpg")
  def test_render_target_isolated_returns_structured_error_for_timeout(
    self,
    mock_killpg,
    mock_popen,
    mock_fallback,
  ) -> None:
    process = mock_popen.return_value
    process.pid = 123
    process.communicate.side_effect = subprocess.TimeoutExpired(cmd=["python3"], timeout=25)
    mock_fallback.return_value = None
    result = render_target_isolated("https://example.com", policy="never", snapshot_depth=4)

    self.assertEqual(result.policy, "never")
    self.assertIn("timed out after 25s", result.error)
    mock_killpg.assert_called_once_with(123, unittest.mock.ANY)

  @patch("tweb.audit.render_target")
  @patch("tweb.audit.create_session")
  @patch("tweb.audit.subprocess.Popen")
  @patch("tweb.audit.os.killpg")
  def test_render_target_isolated_falls_back_in_process_after_quickjs_timeout(
    self,
    mock_killpg,
    mock_popen,
    mock_create_session,
    mock_render_target,
  ) -> None:
    process = mock_popen.return_value
    process.pid = 123
    process.communicate.side_effect = subprocess.TimeoutExpired(cmd=["python3"], timeout=25)
    session = mock_create_session.return_value
    mock_render_target.return_value = RendererAuditResult(
      policy="never",
      source="https://example.com",
      title="Example",
      body_text="Alpha",
      visible_body_text="Alpha",
      link_count=1,
      control_count=0,
      input_control_count=0,
      dom_node_count=3,
      browser_rendered_via_chrome=False,
      timings_ms={"script_eval": 1.0},
      counts={"eval_calls": 1},
      challenge_detected=False,
      navigation_probe=None,
      error=None,
    )

    result = render_target_isolated("https://example.com", policy="never", snapshot_depth=4)

    self.assertEqual(result.title, "Example")
    self.assertIsNone(result.error)
    self.assertEqual(result.counts.get("isolated_render_fallbacks"), 1)
    self.assertEqual(result.counts.get("isolated_render_timeout_fallbacks"), 1)
    mock_render_target.assert_called_once_with(
      "https://example.com",
      policy="never",
      snapshot_depth=4,
      session=session,
      probe_navigation=False,
    )
    session.close.assert_called_once_with()
    mock_killpg.assert_called_once_with(123, unittest.mock.ANY)

  @patch("tweb.audit.render_target")
  @patch("tweb.audit.create_session")
  @patch("tweb.audit.subprocess.Popen")
  @patch("tweb.audit.os.killpg")
  def test_render_target_isolated_falls_back_in_process_after_chrome_timeout(
    self,
    mock_killpg,
    mock_popen,
    mock_create_session,
    mock_render_target,
  ) -> None:
    process = mock_popen.return_value
    process.pid = 123
    process.communicate.side_effect = subprocess.TimeoutExpired(cmd=["python3"], timeout=45)
    session = mock_create_session.return_value
    mock_render_target.return_value = RendererAuditResult(
      policy="always",
      source="https://example.com",
      title="Example",
      body_text="Alpha",
      visible_body_text="Alpha",
      link_count=1,
      control_count=0,
      input_control_count=0,
      dom_node_count=3,
      browser_rendered_via_chrome=True,
      timings_ms={"browser_render": 2.0},
      counts={"eval_calls": 1},
      challenge_detected=False,
      navigation_probe=None,
      error=None,
    )

    result = render_target_isolated("https://example.com", policy="always", snapshot_depth=4)

    self.assertEqual(result.title, "Example")
    self.assertIsNone(result.error)
    self.assertEqual(result.counts.get("isolated_render_fallbacks"), 1)
    self.assertEqual(result.counts.get("isolated_render_timeout_fallbacks"), 1)
    mock_render_target.assert_called_once_with(
      "https://example.com",
      policy="always",
      snapshot_depth=4,
      session=session,
      probe_navigation=False,
    )
    session.close.assert_called_once_with()
    mock_killpg.assert_called_once_with(123, unittest.mock.ANY)

  @patch("tweb.audit.fetch_resource")
  def test_compare_results_classifies_major_gap_when_chrome_is_much_richer(self, mock_fetch_resource) -> None:
    quickjs_html = (
      "<html><head><title>Example</title></head>"
      "<body><main><p>Loading</p></main></body></html>"
    )
    chrome_html = (
      "<html><head><title>Example</title></head>"
      "<body><main><h1>Real content</h1><p>Loaded article body with enough text to compare.</p>"
      "<a href='/a'>A</a><a href='/b'>B</a><a href='/c'>C</a><a href='/d'>D</a></main></body></html>"
    )
    mock_fetch_resource.return_value = Resource(source="https://example.com", content=quickjs_html)
    target = AuditTarget("example", "Example", "https://example.com")
    session = create_session()
    try:
      quickjs = render_target("https://example.com", policy="never", snapshot_depth=6, session=session)
      chrome = render_target(
        "https://example.com",
        policy="always",
        snapshot_depth=6,
        session=session,
        browser_render_fetcher=lambda *_args, **_kwargs: Resource(
          source="https://example.com",
          content=chrome_html,
        ),
      )
    finally:
      session.close()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "major_gap")
    self.assertIn("quickjs visible body is much shorter than chrome", comparison.reasons)

  def test_compare_results_classifies_match_for_near_equal_outputs(self) -> None:
    target = AuditTarget("example", "Example", "https://example.com")
    quickjs = type("Result", (), {
      "error": None,
      "title": "Example",
      "body_text": "Alpha Beta Gamma",
      "visible_body_text": "Alpha Beta Gamma",
      "link_count": 3,
      "control_count": 0,
      "input_control_count": 0,
      "dom_node_count": 10,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Example",
      "body_text": "Alpha Beta Gamma",
      "visible_body_text": "Alpha Beta Gamma",
      "link_count": 3,
      "control_count": 0,
      "input_control_count": 0,
      "dom_node_count": 10,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "match")
    self.assertEqual(comparison.severity, 0)

  def test_compare_results_classifies_google_challenge_branch_separately(self) -> None:
    target = AuditTarget("google-search", "Google Search", "https://www.google.com/search?q=OpenAI")
    quickjs = type("Result", (), {
      "error": None,
      "title": "Google Search",
      "body_text": "Google 検索にアクセスできない場合は、ここをクリックしてください。",
      "visible_body_text": "",
      "link_count": 3,
      "control_count": 0,
      "input_control_count": 0,
      "dom_node_count": 29,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "https://www.google.com/search?q=OpenAI&sei=test",
      "body_text": "このページについて お使いのコンピュータ ネットワークから通常と異なるトラフィックが検出されました。 reCAPTCHA",
      "visible_body_text": "このページについて 通常と異なるトラフィック",
      "link_count": 3,
      "control_count": 1,
      "input_control_count": 1,
      "dom_node_count": 64,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "challenge_branch")
    self.assertIn("both modes resolved to a challenge/interstitial branch", comparison.reasons)

  def test_compare_results_classifies_quickjs_only_challenge_branch_separately(self) -> None:
    target = AuditTarget("booking-home", "Booking.com", "https://www.booking.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "",
      "body_text": "",
      "visible_body_text": "",
      "link_count": 0,
      "control_count": 0,
      "input_control_count": 0,
      "dom_node_count": 0,
      "challenge_detected": True,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Booking.com | Official site",
      "body_text": "Real content " * 200,
      "visible_body_text": "Real content " * 200,
      "link_count": 30,
      "control_count": 6,
      "input_control_count": 6,
      "dom_node_count": 200,
      "challenge_detected": False,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "challenge_branch")
    self.assertIn("quickjs resolved to a challenge/interstitial branch", comparison.reasons)

  def test_compare_results_classifies_richer_quickjs_branch_separately(self) -> None:
    target = AuditTarget("duckduckgo-search", "DuckDuckGo Search", "https://duckduckgo.com/?q=OpenAI")
    quickjs = type("Result", (), {
      "error": None,
      "title": "OpenAI at DuckDuckGo",
      "body_text": "OpenAI result " * 300,
      "visible_body_text": "OpenAI result " * 300,
      "link_count": 49,
      "control_count": 1,
      "input_control_count": 1,
      "dom_node_count": 92,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "OpenAI at DuckDuckGo",
      "body_text": "Short branch " * 20,
      "visible_body_text": "Short branch " * 20,
      "link_count": 36,
      "control_count": 2,
      "input_control_count": 2,
      "dom_node_count": 64,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "alternate_content_branch")
    self.assertIn("quickjs recovered a richer alternate content branch than chrome", comparison.reasons)

  def test_compare_results_treats_near_equal_richer_quickjs_branch_as_match(self) -> None:
    target = AuditTarget("soumu-home", "総務省", "https://www.soumu.go.jp/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "総務省",
      "body_text": "Headline body " * 1600,
      "visible_body_text": "Headline body " * 1600,
      "link_count": 322,
      "control_count": 29,
      "input_control_count": 2,
      "dom_node_count": 299,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "総務省",
      "body_text": "Headline body " * 1590,
      "visible_body_text": "Headline body " * 1000,
      "link_count": 323,
      "control_count": 29,
      "input_control_count": 2,
      "dom_node_count": 311,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "match")
    self.assertNotIn("quickjs recovered a richer alternate content branch than chrome", comparison.reasons)

  def test_compare_results_treats_high_visible_parity_as_match_despite_hidden_text_difference(self) -> None:
    target = AuditTarget("reference-home", "Reference", "https://example.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "Reference",
      "body_text": "QuickJS hidden branch " * 200,
      "visible_body_text": "Shared visible guidance " * 100,
      "link_count": 45,
      "control_count": 3,
      "input_control_count": 2,
      "dom_node_count": 95,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Reference",
      "body_text": "Chrome hidden branch " * 300,
      "visible_body_text": "Shared visible guidance " * 105,
      "link_count": 50,
      "control_count": 3,
      "input_control_count": 2,
      "dom_node_count": 100,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "match")

  def test_compare_results_treats_balanced_text_and_structure_parity_as_match(self) -> None:
    target = AuditTarget("archive-home", "Archive", "https://example.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "Archive",
      "body_text": "shared " * 850 + "quick " * 150,
      "visible_body_text": "shared " * 850 + "quick " * 150,
      "link_count": 100,
      "control_count": 3,
      "input_control_count": 2,
      "dom_node_count": 100,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Archive",
      "body_text": "shared " * 850 + "other " * 150,
      "visible_body_text": "shared " * 850 + "other " * 150,
      "link_count": 100,
      "control_count": 3,
      "input_control_count": 2,
      "dom_node_count": 100,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "match")

  def test_compare_results_treats_visible_and_link_near_match_as_match_despite_dom_shortfall(self) -> None:
    target = AuditTarget("zexy-home", "Zexy", "https://zexy.net/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "Zexy",
      "body_text": "shared body " * 320,
      "visible_body_text": "shared body " * 310,
      "link_count": 314,
      "control_count": 12,
      "input_control_count": 2,
      "dom_node_count": 626,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Zexy",
      "body_text": "shared body " * 322,
      "visible_body_text": "shared body " * 314,
      "link_count": 316,
      "control_count": 12,
      "input_control_count": 2,
      "dom_node_count": 1000,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "match")

  def test_compare_results_classifies_comparable_dynamic_branches_as_alternate(self) -> None:
    target = AuditTarget("transport-home", "Transport", "https://example.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "Transport",
      "body_text": "shared shell " * 300 + "route options " * 100,
      "visible_body_text": "route option " * 400,
      "link_count": 86,
      "control_count": 20,
      "input_control_count": 12,
      "dom_node_count": 97,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Transport",
      "body_text": "shared shell " * 300 + "travel cards " * 100,
      "visible_body_text": "travel card " * 420,
      "link_count": 100,
      "control_count": 20,
      "input_control_count": 12,
      "dom_node_count": 100,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "alternate_content_branch")
    self.assertIn(
      "quickjs and chrome recovered different dynamic branches with comparable coverage",
      comparison.reasons,
    )

  def test_compare_results_classifies_near_equal_visible_branch_with_modest_control_delta_as_alternate(self) -> None:
    target = AuditTarget("qiita-home", "Qiita", "https://qiita.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "Qiita",
      "body_text": "shared shell " * 450 + "quick branch " * 120,
      "visible_body_text": "shared visible " * 240 + "quick branch " * 120,
      "link_count": 385,
      "control_count": 30,
      "input_control_count": 1,
      "dom_node_count": 804,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Qiita",
      "body_text": "shared shell " * 450 + "chrome branch " * 120,
      "visible_body_text": "shared visible " * 240 + "chrome branch " * 120,
      "link_count": 387,
      "control_count": 32,
      "input_control_count": 2,
      "dom_node_count": 1000,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "alternate_content_branch")
    self.assertIn(
      "quickjs and chrome recovered comparable alternate branches with near-equal visible coverage",
      comparison.reasons,
    )

  def test_compare_results_treats_near_threshold_visible_shortfall_as_minor_gap(self) -> None:
    target = AuditTarget("jica-home", "JICA", "https://www.jica.go.jp/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "JICA - 国際協力機構",
      "body_text": "Project body " * 1200,
      "visible_body_text": "Visible body " * 1000,
      "link_count": 495,
      "control_count": 64,
      "input_control_count": 4,
      "dom_node_count": 247,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "JICA - 国際協力機構",
      "body_text": "Project body " * 2600,
      "visible_body_text": "Visible body " * 2940,
      "link_count": 613,
      "control_count": 116,
      "input_control_count": 4,
      "dom_node_count": 290,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "minor_gap")

  def test_compare_results_treats_picker_dense_near_match_as_match(self) -> None:
    target = AuditTarget("travel-home", "Travel", "https://example.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "Travel",
      "body_text": "shared body " * 500,
      "visible_body_text": "shared visible " * 300,
      "link_count": 552,
      "control_count": 45,
      "input_control_count": 9,
      "dom_node_count": 508,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Travel",
      "body_text": "shared body " * 514,
      "visible_body_text": "shared visible " * 300,
      "link_count": 567,
      "control_count": 37,
      "input_control_count": 20,
      "dom_node_count": 723,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "match")
    self.assertNotIn("quickjs extracted far fewer user-input controls", comparison.reasons)

  def test_compare_results_treats_duplicate_chrome_content_as_match(self) -> None:
    target = AuditTarget("portal-home", "Portal", "https://example.com/")
    shared = "alpha beta gamma delta epsilon zeta eta theta iota kappa "
    quickjs = type("Result", (), {
      "error": None,
      "title": "Portal",
      "body_text": shared * 10,
      "visible_body_text": shared * 10,
      "link_count": 93,
      "control_count": 16,
      "input_control_count": 2,
      "dom_node_count": 178,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Portal",
      "body_text": shared * 14,
      "visible_body_text": shared * 14,
      "link_count": 100,
      "control_count": 30,
      "input_control_count": 2,
      "dom_node_count": 200,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "match")

  def test_compare_results_treats_functional_shell_with_missing_feed_as_minor_gap(self) -> None:
    target = AuditTarget("transport-home", "Transport", "https://example.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "Transport",
      "body_text": "shared shell " * 500 + "route search " * 200,
      "visible_body_text": "route search " * 100,
      "link_count": 55,
      "control_count": 45,
      "input_control_count": 20,
      "dom_node_count": 82,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "Transport",
      "body_text": "shared shell " * 500 + "current feed " * 200,
      "visible_body_text": "route search " * 100 + "current feed " * 900,
      "link_count": 100,
      "control_count": 49,
      "input_control_count": 21,
      "dom_node_count": 100,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "minor_gap")
    self.assertIn("quickjs retained the functional shell but missed dynamic discovery content", comparison.reasons)

  def test_compare_results_classifies_link_rich_quickjs_branch_separately(self) -> None:
    target = AuditTarget("ap-news-home", "AP News", "https://apnews.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "AP News",
      "body_text": "Headline " * 900,
      "visible_body_text": "Headline " * 900,
      "link_count": 1800,
      "control_count": 0,
      "input_control_count": 0,
      "dom_node_count": 875,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "AP News",
      "body_text": "Headline " * 1200,
      "visible_body_text": "Headline " * 1200,
      "link_count": 1600,
      "control_count": 4,
      "input_control_count": 4,
      "dom_node_count": 900,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "alternate_content_branch")

  def test_compare_results_does_not_mark_equal_large_outputs_as_alternate_branch(self) -> None:
    target = AuditTarget("suumo-home", "SUUMO", "https://suumo.jp/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "SUUMO",
      "body_text": "A" * 5000,
      "visible_body_text": "A" * 3851,
      "link_count": 415,
      "control_count": 0,
      "input_control_count": 0,
      "dom_node_count": 368,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "SUUMO",
      "body_text": "A" * 5000,
      "visible_body_text": "A" * 3851,
      "link_count": 415,
      "control_count": 0,
      "input_control_count": 0,
      "dom_node_count": 368,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "match")
    self.assertNotIn(
      "quickjs recovered a richer alternate content branch than chrome",
      comparison.reasons,
    )

  def test_compare_results_downgrades_navigation_heavy_gap_to_minor_when_visible_content_is_close(self) -> None:
    target = AuditTarget("jalan-home", "Jalan.net", "https://www.jalan.net/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "宿・ホテル予約 - 旅行ならじゃらんnet",
      "body_text": "QuickJS body " * 500,
      "visible_body_text": "QuickJS visible " * 80,
      "link_count": 224,
      "control_count": 111,
      "input_control_count": 111,
      "dom_node_count": 542,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "宿・ホテル予約 - 旅行ならじゃらんnet",
      "body_text": "Chrome body " * 700,
      "visible_body_text": "QuickJS visible " * 100,
      "link_count": 521,
      "control_count": 111,
      "input_control_count": 111,
      "dom_node_count": 1306,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "minor_gap")

  def test_compare_results_downgrades_visibility_heavy_gap_when_full_body_is_still_close(self) -> None:
    target = AuditTarget("rakuten-travel-home", "Rakuten Travel", "https://travel.rakuten.co.jp/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "楽天トラベル: 宿・ホテル予約 国内旅行・海外旅行 予約サイト",
      "body_text": "A" * 7500,
      "visible_body_text": "A" * 313,
      "link_count": 515,
      "control_count": 94,
      "input_control_count": 94,
      "dom_node_count": 456,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "楽天トラベル: 宿・ホテル予約 国内旅行・海外旅行 予約サイト",
      "body_text": "A" * 10000,
      "visible_body_text": ("A" * 313) + ("B" * 687),
      "link_count": 1000,
      "control_count": 100,
      "input_control_count": 100,
      "dom_node_count": 1000,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "minor_gap")

  def test_compare_results_downgrades_cross_locale_variant_to_minor_gap(self) -> None:
    target = AuditTarget("duckduckgo-home", "DuckDuckGo", "https://duckduckgo.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "DuckDuckGo - Protection. Privacy. Peace of mind.",
      "body_text": "Switch to DuckDuckGo. It's private and free! " * 40,
      "visible_body_text": "Switch to DuckDuckGo. It's private and free! " * 40,
      "link_count": 16,
      "control_count": 2,
      "input_control_count": 2,
      "dom_node_count": 180,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "DuckDuckGo - プライバシー。保護。安心。",
      "body_text": "DuckDuckGoに切り替えませんか。プライベートで無料です。 " * 80,
      "visible_body_text": "DuckDuckGoに切り替えませんか。プライベートで無料です。 " * 80,
      "link_count": 105,
      "control_count": 4,
      "input_control_count": 4,
      "dom_node_count": 201,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "minor_gap")
    self.assertIn("quickjs and chrome resolved to different locale variants", comparison.reasons)
    self.assertNotIn("quickjs visible body differs heavily from chrome", comparison.reasons)

  def test_compare_results_downgrades_dom_only_gap_to_minor_when_visible_output_is_close(self) -> None:
    target = AuditTarget("asahi-news-jp-home", "Asahi", "https://www.asahi.com/")
    quickjs = type("Result", (), {
      "error": None,
      "title": "朝日新聞デジタル",
      "body_text": "Headline " * 1400,
      "visible_body_text": "Headline " * 1400,
      "link_count": 792,
      "control_count": 1,
      "input_control_count": 1,
      "dom_node_count": 459,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "朝日新聞デジタル",
      "body_text": "Headline " * 1450,
      "visible_body_text": "Headline " * 1450,
      "link_count": 817,
      "control_count": 4,
      "input_control_count": 4,
      "dom_node_count": 1000,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "minor_gap")
    self.assertIn("quickjs DOM tree is much smaller than chrome", comparison.reasons)

  def test_compare_results_downgrades_cross_locale_widget_gap_to_minor_gap(self) -> None:
    target = AuditTarget("weathercom-home", "The Weather Channel", "https://weather.com/")
    common_chunk = "Weather Home Search Forecast Alerts Radar Stories AAA "
    locale_chunk = "東京 現在地 Cloudy Forecast Advisory Widget AAA "
    quickjs = type("Result", (), {
      "error": None,
      "title": "National and Local Weather Radar, Daily Forecast, Hurricane and information from The Weather Channel and weather.com",
      "body_text": common_chunk * 700,
      "visible_body_text": common_chunk * 220,
      "link_count": 69,
      "control_count": 16,
      "input_control_count": 1,
      "dom_node_count": 121,
    })()
    chrome = type("Result", (), {
      "error": None,
      "title": "National and Local Weather Radar, Daily Forecast, Hurricane and information from The Weather Channel and weather.com",
      "body_text": (common_chunk * 560) + (locale_chunk * 140),
      "visible_body_text": (common_chunk * 176) + (locale_chunk * 44),
      "link_count": 84,
      "control_count": 19,
      "input_control_count": 2,
      "dom_node_count": 276,
    })()

    comparison = compare_results(target, quickjs=quickjs, chrome=chrome)

    self.assertEqual(comparison.classification, "minor_gap")
    self.assertIn("quickjs and chrome resolved to different locale variants", comparison.reasons)


if __name__ == "__main__":
  unittest.main()
