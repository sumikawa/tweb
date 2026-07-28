# API.md

`tweb` は CLI だけでなく、Python ライブラリとしても使える。ここでは現在の公開 API と、読み取り中心の BeautifulSoup 風 API、AI 向けの構造化 snapshot、変更系の操作 API を分けてまとめる。

## 公開 import

```python
from tweb import (
  AgentActionRequest,
  AgentActionResult,
  AgentPageSnapshot,
  AgentSnapshotControl,
  AgentSnapshotLink,
  AgentSnapshotNode,
  AgentSnapshotOption,
  ControlDebugInfo,
  ControlSubmissionPreview,
  JavaScriptRuntimeError,
  QuickJSRuntime,
  TWebAgentActions,
  TWebDocument,
  TWebElement,
  create_session,
  fetch_resource,
  parse_document,
)
```

通常は `QuickJSRuntime` を直接触らず、`TWebDocument` を入口に使えば足りる。

## 最小例

```python
from tweb import TWebDocument, fetch_resource, parse_document

resource = fetch_resource("https://example.com")
document = TWebDocument(parse_document(resource))

print(document.title)
print(document.body_text())
for link in document.links():
  print(link.text, link.href)
```

ローカルファイルも同じ流れで扱える。

```python
from tweb import TWebDocument, fetch_resource, parse_document

resource = fetch_resource("./page.html")
document = TWebDocument(parse_document(resource))
print(document.find("h1").text)
```

## 取得

`fetch_resource(target, ...)` は URL またはローカルパスから `Resource` を返す。

- `http://` / `https://` は `requests` で取得する
- ローカルファイルはそのまま読む
- `session=` を渡すと Cookie 付きで取得できる
- `method=` と `form_data=` を渡すと form submit 後の再取得にも使える

Cookie 付き session を作る例:

```python
from requests.cookies import RequestsCookieJar
from tweb import create_session, fetch_resource

jar = RequestsCookieJar()
jar.set("sessionid", "abc123", domain=".example.com", path="/")
session = create_session(jar)

resource = fetch_resource("https://example.com/private", session=session)
session.close()
```

## パースとドキュメント API

`parse_document(resource)` は内部 DOM を作り、`TWebDocument` がその操作面を提供する。

### `TWebDocument`

主な読み取り API:

- `title`: ページタイトル
- `html`: `<html>` の `TWebElement`
- `body`: `<body>` の `TWebElement`
- `body_text()`: 本文テキスト
- `links()`: `Link(text, href)` の一覧
- `find(name=None, attrs=None)`: 最初の一致
- `find_all(name=None, attrs=None, limit=None)`: 一覧
- `select(selector)`: 簡易 CSS selector
- `snapshot(...)`: AI 向けの構造化 snapshot
- `hydration_debug()`: runtime data 補完の source summary / confidence
- `javascript_debug()`: script eval / async drain / style rebuild / script cache の timing/count
- `agent_actions()`: 変更系 API の入口
- `debug_control(...)`, `debug_controls()`: form / button のデバッグ向け記述
- `invoke_agent_action(...)` / `agent_actions().invoke(...)`: 構造化された基本操作の入口

例:

```python
article = document.find("article")
headings = document.find_all("h2")
primary_links = document.select('main a[href^="/"]')
```

### `TWebElement`

`TWebElement` は `TWebDocument.find()` や `select()` の戻り値として使う。

主な参照 API:

- `name`: タグ名
- `attrs`: 属性 dict
- `text`: 要素配下のテキスト
- `get(key, default=None)`: 属性取得
- `get_text(separator=" ", strip=True)`: テキスト取得
- `find(...)`, `find_all(...)`, `select(...)`: 部分木に対する検索

例:

```python
card = document.select(".card")[0]
title = card.find("h3").text
href = card.find("a").get("href")
```

### BeautifulSoup 互換性の位置づけ

現在の方針は、読み取り面では BeautifulSoup 風の API を維持し、変更系は別オブジェクトに分けることにある。

- `find` / `find_all` / `select` / `get_text` は読み取り面として維持する
- form 編集、submit、JS button click は `agent_actions()` 側に寄せる
- `execute_script()` は強い機能なので、単純な読み取り API と同列には扱わない

これは AI から使うときに、閲覧専用 API と副作用のある API の境界を明確にするためでもある。

## AI 向け snapshot API

`snapshot()` は、現在ページの主要情報を JSON 化しやすい dataclass 群で返す。

```python
snapshot = document.snapshot(max_depth=2)

print(snapshot.title)
print(snapshot.body_text)
print(snapshot.links[0].href if snapshot.links else "")
print(snapshot.form_controls[0].control_id if snapshot.form_controls else "")
print(snapshot.to_dict()["dom_nodes"][0]["node_id"] if snapshot.dom_nodes else "")
```

戻り値 `AgentPageSnapshot` の主なフィールド:

- `source`: 元 URL またはローカルパス
- `title`: ページタイトル
- `body_text`: 本文テキスト
- `links`: `AgentSnapshotLink`
- `form_controls`: `AgentSnapshotControl`
- `dom_nodes`: `AgentSnapshotNode`

主な引数:

- `max_depth`: DOM ノードをどこまで辿るか
- `include_script_like`: `script` / `style` を詳細に含めるか
- `viewport_columns`: CSS 可視性評価に使う幅

`AgentPageSnapshot` 自体にも、AI から使いやすい read-only 検索補助を持たせている。

```python
snapshot = document.snapshot(max_depth=3)

search_box = snapshot.control("q")
radio_controls = snapshot.find_controls(kind="radio", name="scope")
search_label_nodes = snapshot.find_nodes(node_type="text", text_contains="search")
docs_link = snapshot.link(href="https://example.com/docs")
```

主な補助メソッド:

- `link(href=None, text=None)`: 最初の一致する link を返す
- `find_links(href=None, text=None, text_contains=None, limit=None)`: link 一覧を絞り込む
- `control(control_id)`: control ID で 1 件引く
- `find_controls(kind=None, name=None, label_contains=None, input_type=None, limit=None)`: form control 一覧を絞り込む
- `node(node_id)`: node ID で 1 件引く
- `find_nodes(node_type=None, tag=None, text_contains=None, attrs=None, visible=None, parent_id=None, include_skipped=True, limit=None)`: DOM ノード一覧を絞り込む

各 `AgentSnapshotControl` は、操作可否の判断に使える次のフィールドも持つ。

- `disabled`
- `readonly`
- `supported_actions`

### `AgentSnapshotLink`

- `text`
- `href`

### `AgentSnapshotControl`

- `control_id`
- `kind`
- `name`
- `label`
- `value`
- `checked`
- `options`
- `input_type`

`options` は `AgentSnapshotOption(value, label, selected)` の配列として返る。

### `AgentSnapshotNode`

`dom_nodes` は親子関係を `node_id` / `parent_id` で表すフラット配列で返る。

主なフィールド:

- `node_id`
- `parent_id`
- `node_type`: `"element"` または `"text"`
- `tag`
- `text`
- `attrs`
- `visible`
- `hidden_reason`
- `display`
- `flex_direction`
- `grid_template_columns`
- `visibility`
- `font_weight`
- `font_style`
- `text_decoration`
- `skipped`

`snapshot.to_dict()` を使うと、そのまま JSON シリアライズしやすい dict になる。

この read-only 補助は `snapshot` 内だけを対象にし、DOM 変更や form submit は行わない。副作用を伴う操作は引き続き `agent_actions()` へ分離する。

## 変更系 API

`agent_actions()` は `TWebAgentActions` を返し、form 編集や submit などの副作用を持つ操作をここから呼ぶ。

```python
actions = document.agent_actions()
actions.set_text_control("q", "updated query")
actions.toggle_checkbox("safe")
```

`TWebDocument` 自体にも同名メソッドは残っているが、AI 操作用には `agent_actions()` 経由を推奨する。

### 構造化 action invoke

個別メソッドを直接呼んでもよいが、AI からは `AgentActionRequest` を使った `invoke()` のほうが安定して扱いやすい。

```python
actions = document.agent_actions()

result = actions.invoke(
  AgentActionRequest(
    action="set_text",
    control_id="q",
    value="hogehoge",
  )
)

submit = actions.invoke(
  AgentActionRequest(
    action="submit_form",
    control_id="tweb-button-1",
    current_source="https://example.com/form",
  )
)
```

主な `action`:

- `set_text`
- `append_text`
- `backspace_text`
- `toggle_checkbox`
- `cycle_select`
- `select_radio`
- `submit_form`
- `click_button`
- `debug_control`

返り値 `AgentActionResult` には、`status`、`reason`、`available_actions`、`requires_confirmation`、`changed`、`submission`、`button_click`、`debug` が入り、成功時も失敗時も例外ではなく構造化結果として扱える。

主な `status`:

- `ok`: 実行または preflight が成功した
- `not_found`: 対象 `control_id` が見つからない
- `unsupported`: その control ではその action を使えない
- `blocked`: policy により最終効果が止められた
- `requires_confirmation`: 実行前に追加確認が必要

主な補助フィールド:

- `reason`: `control_not_found` / `action_not_supported_for_control` / `blocked_by_policy` / `password_input_requires_confirmation` などの機械判定用コード
- `available_actions`: その control で許される action の一覧
- `requires_confirmation`: 再確認付きで同じ request を投げ直すべきケースかどうか

たとえば password input は、既定では `requires_confirmation` を返して値注入を止める。明示的に許可する場合だけ `confirmed=True` を付けて再実行する。

```python
password_result = actions.invoke(
  AgentActionRequest(
    action="set_text",
    control_id="password",
    value="secret",
  )
)

if password_result.status == "requires_confirmation":
  password_result = actions.invoke(
    AgentActionRequest(
      action="set_text",
      control_id="password",
      value="secret",
      confirmed=True,
    )
  )
```

### control デバッグ情報

button click や form submit を調べたいときは、実行前に `debug_control()` / `debug_controls()` で構造化された説明を取れる。

```python
actions = document.agent_actions()
debug = actions.debug_control("tweb-button-1")

print(debug.kind)
print(debug.click_hint)
print(debug.form_action)
print(debug.submit_preview.url if debug.submit_preview is not None else "")
```

主なフィールド:

- `kind`: `text` / `textarea` / `select` / `checkbox` / `radio` / `submit` / `button` / `tab`
- `tag`: 実 DOM のタグ名
- `form_action`, `form_method`: form owner がある場合の送信先
- `submit_preview`: submit control の場合の `ControlSubmissionPreview`
- `click_hint`: `submit` / `disclosure_toggle` / `tab_activation` / `navigation` / `javascript`
- `controlled_target`: `aria-controls` がある場合の対象 ID
- `navigation_target`: class-based tab などで遷移先を事前推定できる場合の URL

### control 一覧

```python
controls = document.form_controls()
for control in controls:
  print(control.control_id, control.kind, control.name, control.value)
```

checkbox だけ見たい場合:

```python
checkboxes = document.checkbox_controls()
```

### テキスト系 control の編集

```python
actions.append_text_to_control("q", " more")
actions.backspace_control_text("q")
actions.set_text_control("q", "search term")
```

同じ `name` を持つ mirrored input がある場合も同期される。

### select / radio / checkbox

```python
actions.cycle_select_control("category")
actions.cycle_select_control("category", reverse=True)
actions.select_radio_control("scope-all")
actions.toggle_checkbox("safe")
```

### submit 情報の組み立て

`submit_form_control(control_id, current_source)` は即 fetch せず、送信内容を `FormSubmission` として返す。

```python
submission = actions.submit_form_control("tweb-button-1", "https://example.com/form")
if submission is not None:
  print(submission.method)
  print(submission.action)
  print(submission.url())
  print(submission.form_data())
```

- GET form では `url()` が便利
- POST form では `form_data()` をそのまま `fetch_resource(..., method="post", form_data=...)` に渡せる

### JavaScript button click

`type="button"` のような JS 駆動 button は `click_button_control()` で扱う。

```python
result = actions.click_button_control("login-button", policy="dom-only")
print(result.clicked, result.classification, result.dom_changed)
```

`policy`:

- `"off"`: 実行しない
- `"dom-only"`: DOM 更新だけ許容し、通信や遷移は block
- `"network"`: 通信や遷移も許容

`invoke(action="click_button", ...)` で `dom-only` により network / navigation が止められた場合は、`status="blocked"` と `reason="blocked_by_policy"` を返しつつ、`button_click.classification` で `navigation_requested` や `network_requested` を確認できる。

戻り値 `ButtonClickResult` では次のような情報を見られる。

- `clicked`
- `classification`
- `dom_changed`
- `blocked_by_policy`
- `navigation_target`
- `network_requests`

## JavaScript 実行

`tweb` の JS 実行は quick.js ベースで、通常は `TWebDocument` 経由で使う。

### 任意スクリプトを 1 本実行する

```python
document.execute_script(
  "document.body.setAttribute('data-ready', '1')"
)
```

- `source_url=` を渡すと `document.currentScript.src` 相当の文脈を与えられる
- 実行後は DOM と interaction 情報が同期される

### 埋め込み script を実行する

```python
document.execute_embedded_scripts(
  ignore_errors=True,
  session=session,
  browser_render_policy="never",
  use_script_cache=True,
)
```

主な引数:

- `ignore_errors`: `False` にすると JS 例外をそのまま上げる
- `session`: 外部 script や fetch/XHR に使う session
- `browser_render_policy`: `"never" | "auto" | "always"`
- `use_script_cache`: `URL` 基本で `Vary` に従う `diskcache` ベースの永続 external script file cache を使うかどうか

補助 API:

- `execute_inline_scripts(ignore_errors=True)`: 外部 script を読まず、inline script だけ実行する

失敗時は `JavaScriptRuntimeError` を捕まえる。

```python
from tweb import JavaScriptRuntimeError

try:
  document.execute_embedded_scripts(ignore_errors=False)
except JavaScriptRuntimeError as exc:
  print(exc)
```

runtime data 補完の判断を見たいときは `hydration_debug()` を呼べる。

```python
document.execute_embedded_scripts(ignore_errors=True)
debug = document.hydration_debug()
print(debug["confidence"])
print(debug["source_summaries"])
```

JS-heavy ページで何が重かったかを見たいときは `javascript_debug()` を呼べる。

```python
document.execute_embedded_scripts(ignore_errors=True, use_script_cache=False)
debug = document.javascript_debug()
print(debug["timings_ms"])
print(debug["script_cache"])
```

## 推奨フロー

読み取り中心なら次の形が基本になる。

```python
from tweb import TWebDocument, fetch_resource, parse_document

document = TWebDocument(parse_document(fetch_resource("https://example.com")))
document.execute_embedded_scripts(ignore_errors=True)

print(document.title)
print(document.body_text())
```

AI 向けに構造化された読み取り結果がほしいなら snapshot を使う。

```python
snapshot = document.snapshot(max_depth=2)
payload = snapshot.to_dict()
print(payload["title"])
```

認証付きページや script 依存ページなら session を渡す。

```python
from requests.cookies import RequestsCookieJar
from tweb import TWebDocument, create_session, fetch_resource, parse_document

jar = RequestsCookieJar()
jar.set("sessionid", "abc123", domain=".example.com", path="/")
session = create_session(jar)

try:
  resource = fetch_resource("https://example.com/app", session=session)
  document = TWebDocument(parse_document(resource))
  document.execute_embedded_scripts(ignore_errors=True, session=session)
finally:
  session.close()
```

## 現状の境界

- 公開 API の中心は `TWebDocument` と `TWebElement`
- `QuickJSRuntime` は低レベル API なので、通常は直接使わない
- selector はフル CSS 互換ではなく、実装済みの簡易 subset
- JS 実行は quick.js ベースで、ブラウザ完全互換ではない
- form submit は送信内容の組み立てまでが主で、実際の遷移や再取得は呼び出し側で行う
- AI 向けの構造化読み取りは `snapshot()`、副作用のある変更系は `agent_actions()` に分ける
- `snapshot().form_controls[*].supported_actions` を見れば、どの変更系 API を許すかを read-only 側だけで判断できる

## 関連ドキュメント

- `README.md`: CLI 中心の使い方
- `DOM.md`: DOM 表示方針
- `CSS.md`: CSS 解釈方針
- `JS.md`: JavaScript の実装状況と制約
- `TUI.md`: TUI 操作仕様
