# PLAN.md

## この文書の役割

この文書は、README.md に書かれた目標を実装へ落とし込むための作業計画を管理する。
使い方や現行仕様の詳細は README.md / TUI.md / DOM.md / CSS.md / SECURITY.md に委ね、ここでは次の 3 点を優先して整理する。

- 何が完了済みか
- どこが継続中か
- 次に何を進めるか

## 目標

- HTML を取得して解析し、人間が読める通常モードで安定表示できる
- 同じ取得結果から、人間向け DOM 要約と AI 向け詳細 DOM を提供できる
- CSS / JavaScript の最小実装を段階的に広げ、読解品質と操作可能性を上げる
- Textual ベース TUI で、macOS の標準テキスト編集に近い Emacs 準拠のキーボード操作を実現する
- BeautifulSoup 互換 API と今後の AI 操作用インターフェースを整備する
- 認証が必要なページに対しても、外部の認証情報マネージャと安全境界を保ったまま半自動で資格情報やセッションを渡せるようにする
- セキュリティ要件を `SECURITY.md` で継続管理し、機能追加と同時に詰める

## 前提

- メイン実装は Python3 を使う
- JS 実行は quick.js を使う
- TUI 基盤は Textual を使う
- HTTP/HTTPS 取得は既存ライブラリ優先とし、標準実装は `requests` を使う
- キーボード操作は macOS の標準テキスト編集に近い Emacs 準拠を基本方針にする
- 初期段階では Web 互換性の完全再現より、読解しやすさと AI から扱いやすい構造を優先する

## 現在地

- 完了済み Phase:
  Phase 1 から Phase 12、Phase 14 から Phase 16。基礎取得、通常表示、DOM 表示、BeautifulSoup 互換 API、CSS、quick.js 実行、Textual TUI、browser-render fallback、AI 向け snapshot / preflight / mutate API、generic runtime data collector、JS runtime の計測/キャッシュ基盤、renderer metadata 一体化、interactive metadata fallback 撤去、TUI ページ構築の計測と pane 切り替え時のキャッシュ再利用まで揃っている。
- 未着手 Phase:
  Phase 13（外部認証情報マネージャ連携）、Phase 18、Phase 19。Phase 13 には Cookie import と password 編集の既存基盤があるが、外部コマンドからの入力フローは未実装。
- 一部実装済み Phase:
  Phase 17。本文だけを表示する `--mode text --main-only` は実装済み。不要リソースの分類制御と本文安定ベースの終了判定は未着手。
- 進行中 Phase:
  Cross-cutting のセキュリティ。AI 向け API の基本境界は固まったが、same-origin、credential injection、外部認証フローの詳細化は継続中。
- 次の主対象 Phase:
  Phase 17。実装済みの本文表示オプションを維持し、不要リソースの抑制と本文安定ベースの終了判定を進める。
- 次点の設計課題:
  Phase 18 の後は、MCP surface を使った session 管理、認可モデル、observable debug surface をどこまで共通 API に寄せるかを詰める。
- 後続 backlog:
  Phase 19。現在の token ベース折り返しを、Unicode line breaking / CSS Text に寄せた break-opportunity ベースへ組み替え、日本語だけでなく mixed-script / CJK / dictionary-required scripts まで広げられる text layout 基盤を作る。
- 並行で回す品質ループ:
  `tweb.audit` による QuickJS 対 Chrome の代表サイト監査。現在は JP/EN を分けず unified manifest 44件を保持し、未解消差分を中心とする20件を `active_site_ids` で重点対象として回す。必要なら `--tag jp` / `--tag en` で絞る。browser-render を恒久解にせず、差分を backlog 化して QuickJS 側で潰す。raw fetch が安定する `quickjs_error` 系は比較が重くても canonical manifest から外さない。
- 現在の到達点:
  `requests` ベース取得、`dom` / `dom-ai` 表示、BeautifulSoup 互換 read API、quick.js 実行、Textual TUI、form submit と JS button の分類、`--browser-render never|auto|always` と既定 `auto` の fallback 運用がある。
- その他改善案:
  テキスト編集画面の改善。

## 直近の優先順位

1. Phase 9:
   完了。`snapshot()`、`debug_control()`、`agent_actions()` を read / preflight / mutate の 3 層として整理し、`AgentActionResult.status` / `reason` / `available_actions` / `requires_confirmation` を含む返り値を固定した。
2. セキュリティ:
   JS button / fetch / navigation / credential injection の許可モデルを `SECURITY.md` と `API.md` に揃えて、どこまでが既定拒否かをさらに詰める。
3. Phase 16:
   完了。renderer・controls/links・page build・viewport の段階別 timing、static-rich / hidden subtree の pane detection gate、pane 切り替え時のバッファと描画 metadata 再利用を実装した。計測結果は `docs/performance.md` に記録する。
4. Phase 17:
   WRS 的な最小レンダラ寄りの改善として、本文理解に不要なリソースを抑制し、render 完了判定を「画面全体」ではなく「本文安定」に寄せる。XHR/fetch は本文寄与の高いものを優先し、analytics/beacon/reporting 系は既定で落とせるようにする。
5. Phase 18:
   `snapshot()` / `debug_control()` / `agent_actions()` の既存境界を保ったまま、MCP server を薄い adapter として追加する。最初は 1 page/session 単位の read / preflight / mutate に限定し、TUI や内部 DOM 実装を MCP 前提にしない。
6. MCP 設計の詰め:
   session の寿命、tool schema の後方互換、debug 情報の露出範囲、secret-confirmation の扱いを `API.md` / `SECURITY.md` と同期できる形で整理する。
7. QuickJS 品質監査:
  `tweb/data/quickjs_audit_sites.json` の unified 44サイトをcanonical inventoryとして保持し、`active_site_ids` の20サイトを継続比較する。`--tag jp` / `--tag en` も併用しながら `major_gap` と `quickjs_error` を優先して generic runtime / DOM / hydration / interaction の不足へ分解する。
8. Phase 19 の設計メモ:
  line wrap は「語 token を幅で送る」実装から、「Unicode line breaking に基づく break opportunity を先に列挙し、その中から最終改行位置を選ぶ」実装へ寄せる。日本語は句読点や small kana などの禁則を守り、英字/CJK 混在や将来の Thai/Khmer などの dictionary-required scripts も扱える形を目標にする。

## フェーズ別計画

### Phase 1: プロジェクト基盤

状態: 完了

- パッケージ構成と CLI 起点を整備済み
- 実行方法と主要ドキュメントの分離方針を確立済み

### Phase 2: 取得と HTML 解析

状態: 完了

- HTTP / ローカルファイル入力を扱う取得層を実装済み
- scheme 省略のホスト入力は `http://` 補完、ローカルファイルはパスとして維持する
- Cookie を付けた取得と同一セッション継続を実装済み
- HTML を内部 DOM に変換し、タイトル・本文・リンク抽出を実装済み
- 壊れた HTML への最低限の耐性を実装済み

### Phase 3: 通常モード表示

状態: 完了

- 見出し、段落、リンク、リストなどの基本表示を実装済み
- 基本的な HTML table を列揃えしたテキスト表として表示できる
- 折り返しとリンク表示の基本方針を実装済み
- `--link-style none|inline` の切り替えを実装済み

今後の拡張候補:

- table の colspan / rowspan / 複雑な入れ子への対応改善
- `select` / `option` の見せ方の改善

### Phase 4: DOM モード表示

状態: 完了

- `dom` と `dom-ai` の役割分離を実装済み
- 深さ制限付きの調査用表示と AI 向け詳細表示を使い分けられる

今後の拡張候補:

- TUI の選択対象や操作 API と `dom-ai` の対応づけ強化

### Phase 5: BeautifulSoup 互換 API

状態: 完了

- `find` / `find_all` / `select` / `get_text` / `attrs` / `text` の基本操作を実装済み
- CLI とは別に Python API として import できる形を整備済み

今後の拡張候補:

- AI から扱いやすい戻り値形式の明確化
- 操作系 API を追加する場合の責務分離

### Phase 6: CSS 対応

状態: 完了

完了済み:

- 可視性系の最小解釈
- `font-weight` / `font-style` / `text-decoration` の一部反映
- `style` 属性と埋め込み CSS の基本対応
- 外部 stylesheet 読み込みの最小実装
- セレクタごとの優先順位を考慮した最小カスケード
- 子孫セレクタと `>` を含む基本セレクタ対応
- `display:flex` / `inline-flex` の通常モード向け最小解釈
- `display:grid` の 2 カラム近似
- 通常モード / `dom-ai` / TUI 間で使い回せる `StyleContext`

完了条件:

- 基本的な CSS の有無で表示内容が合理的に変わり、対応範囲が文書化されている

### Phase 7: JavaScript 対応

状態: 完了

完了済み:

- quick.js 経由の最小 DOM 操作ブリッジ
- `querySelector` / `querySelectorAll` / `document.title` / `document.body` / `document.documentElement`
- `textContent` / `innerHTML` / 属性参照と更新
- CLI からの `--script` / `--script-file` 実行
- browser-render fallback の利用ポリシーを `never` / `auto` / `always` に整理し、既定を `auto` として明文化
- quick.js runtime に既定のメモリ制限を追加
- memory limit 超過時のエラー表示を明確化し、制限事項を文書へ同期
- JS 実行後の再レンダリング整合性と実装制限を `JS.md` / `SECURITY.md` / `README.md` に同期

完了条件:

- 軽量な DOM 書き換えを安定して実行でき、対応範囲と制限が明確になっている

### Phase 8: キーボードブラウジング / TUI

状態: 完了

完了済み:

- Textual ベースの最小 TUI
- 本文閲覧、リンク遷移、履歴移動の基盤
- 通常表示と DOM 要約表示の切り替え
- checkbox/label ベース dropdown の開閉
- text input / password input / textarea / select / radio / checkbox / submit を含む最小 form 操作
- `type="button"` を submit と分離し、JS 駆動 button は別操作として扱う基盤
- `click_button_control()` 相当の API と TUI 連携を追加し、`type="button"` で DOM 更新までの click を実行できるようにした
- バックグラウンド読み込みとキャンセル
- Emacs 準拠の主要移動操作、長文ページのスクロール、検索、open-location、ショートカットヘルプ
- ステータス行でのリンク先表示、submit 先表示、JS button の policy と click 結果表示
- JS 駆動 button を `off` / `dom-only` / `network` の段階許可で扱う TUI/API 境界
- JS 駆動 button click の結果を `dom_updated` / `navigation_requested` / `network_requested` / `javascript_required` として UI / API に反映

完了条件:

- マウスなしでページ閲覧とリンク遷移ができ、主要な移動操作が一貫している
- form submit と JS 駆動 click の違いが UI と API の両方で明確になっている

### Phase 9: AI 操作インターフェースの整備

状態: 完了

目的:

- AI が現在ページを安全に読める API を定義する
- ノード検索、リンク抽出、フォーム候補確認などの操作面を整理する
- 閲覧用、事前確認用、操作用の 3 層を分離する
- 出力は曖昧な文字列より構造化データを優先する

完了済み:

- `TWebDocument.snapshot()` で、リンク・フォーム・DOM ノードを JSON 化しやすい構造で取得できる土台を追加した
- `find` / `find_all` / `select` / `get_text` などの BeautifulSoup 互換面は維持し、変更系は `agent_actions()` 側に寄せる方針で進める
- `AgentPageSnapshot` に read-only の検索補助を追加し、link / form control / DOM node を `snapshot` 上で ID や条件から直接絞り込めるようにした
- `debug_control()` / `debug_controls()` で、button click や form submit の事前確認に使える構造化デバッグ情報を返せるようにした
- `AgentSnapshotControl.supported_actions` と `AgentActionRequest` / `AgentActionResult` / `agent_actions().invoke()` を追加し、read-only 判定と change-capable invoke の境界を構造化して明示した
- `snapshot` / `debug_control()` / `agent_actions().invoke()` を read / preflight / mutate の 3 層として `API.md` / `DOM.md` で明文化した
- `AgentActionResult` に `status` / `reason` / `available_actions` / `requires_confirmation` を追加し、not-found / unsupported / blocked / requires-confirmation を例外ではなく構造化結果で返せるようにした
- password input への値注入は mutate API 上で既定拒否とし、`confirmed=True` を付けた明示再実行に分離した
- button click policy の block を `blocked_by_policy` だけでなく mutation API 上でも表現できるようにし、interaction 自体を止めたケースだけ `status="blocked"` / `reason="blocked_by_policy"` に寄せるようにした

完了条件:

- AI からのページ分析と基本操作呼び出しが安定し、権限境界が明確になっている

### Phase 10: Runtime Data / Hydration 汎用化

状態: 完了

目的:

- `window.__NUXT__` や `__NEXT_DATA__` のような既知 root だけでなく、chunk 列や遅延投入データを汎用に拾える runtime data collector を作る
- 特定サイトの module id や URL 形式に依存せず、配列・オブジェクトの形から「見出しつきセクション」「カード一覧」「ナビ候補」を推定する構造推論を追加する
- 抽出した runtime data から href を再構成する処理を site 別分岐ではなく、base URL・既存 DOM・相対リンク規則を使う汎用 link resolver に寄せる
- script 実行後に失われた `main` / `aside` / loading placeholder を復元して差し込む DOM reconciliation を、site 固有判定ではなく一般的な container 推定として整理する
- どの補完結果を採用したか、なぜ browser-render fallback へ進んだかを追える debug 情報と confidence 判定を持たせる

完了済み:

- `tweb/runtime_data.py` を追加し、`window` 上の既知 hydration root、inline JSON script、chunk 配列、`fetch` / XHR 応答の 4 系統を同じ正規化インターフェースへ流し込めるようにした
- inline script に直接埋め込まれた JSON literal と text fragment 辞書も generic collector で読めるようにし、short shell ページの recovered text 補完へ流せるようにした
- generic collector は `HydrationSection` / `HydrationLink` / 補助テキストへ正規化し、`title + item list + role` を共通の出口として扱う
- リンクは明示 URL / path / pathname または同一ラベルに対して一意な既存 DOM anchor を採用する。`urlname` / `key` / `engName` / `parentDir` / `slug` からのサイト依存 URL 推測は削除し、根拠のない item はテキストとして保持する
- browser-render fallback 前に generic runtime data 補完を試し、その結果を `confidence` と source summary を持つ `hydration_debug()` で追えるようにした
- `tests.test_document_api` / `tests.test_js_runtime` に inline JSON、`__next_f`、network JSON 応答、loading shell 差し替えの回帰を追加した
- `__next_f` については runtime 上の配列だけでなく inline script の `push(...)` 文字列も回帰対象に含め、source summary で `inline-chunk` を確認して note.com topic sidebar の categories / subCategories 再発を防ぐ
- note.com の固定 API probe / retry / Python 再取得を削除した。ページが発行する通信の JSON は既存の runtime network collector で扱う。class static block の構文互換と、footer を残して消失した main の復元もサイト名に依存せず実装した
- 本文・ナビの分類を `tweb/hydration_targets.py` へまとめ、URL 形式と特定 class 名による用途判定を削除した。HTML / ARIA、見出し・既存リンクとの対応、一覧構造、リンク密度、ナビに隣接する一意な空領域で判定する。曖昧な候補は既存 DOM を置換せず main 側へ補完する

残っている残差:

- カクヨムの作品・目次 schema の解釈と episode URL の生成規則
- shell 全体の置換に頼らず、pane / disclosure / tab 単位で復元対象をより細かく選ぶ一般化
- disclosure 復元は見出し一致ベースの generic 補完まで進んだが、複数候補の曖昧解消や section role を使った対象選別は未整理

完了条件:

- `tweb/site_specific.py` が「汎用抽出で取れない残差だけ」を扱う薄い fallback になる
- 新しい script-heavy サイトに対して、個別の regex や module id 追加なしで一定量のセクション復元ができる
- browser-render fallback の前に generic runtime data 補完を試し、その成否をテストと debug 出力で説明できる
- `JS.md` / `README.md` / `SECURITY.md` に、どこまでが generic runtime 補完でどこからが site-specific fallback かが整理されている

### Phase 11: Optional Browser-Render Strategy

状態: 完了

目的:

- TUI では通常表示を quick.js ベースに保ちつつ、必要時だけ明示操作で browser-render retry できる UI を持つ
- Chrome 直結の実装を fetch 層の抽象に切り出し、将来は別 provider や無効化実装へ差し替えられるようにする
- browser-render fallback に頼らず済むよう、quick.js 側で埋めるべき DOM API / timer / fetch まわりの不足を整理して段階的に縮小する

既実装:

- `--browser-render never|auto|always` で fallback ポリシーを明示制御できる
- remote URL には browser-render provider を通す fetch 層があり、現状 provider 名は `chrome` で差し替え注入点もある
- TUI では `r` が manual retry として見え、title / status で `Chrome manual retry` と `Chrome auto fallback` を区別する
- `browser-render decision ...` debug log に trigger と failure class が出るので、auto fallback / manual retry / provider unavailable を後から追える
- Python API では `execute_embedded_scripts(..., browser_render_fetcher=...)` で optional component を注入できる
- provider 差し替え面は `BrowserRenderRequest` / `BrowserRenderResult` contract に整理し、Cookie bridge・timeout・empty DOM 判定を fetch 層で共通に扱う
- 既定の `auto` fallback と明示的な retry は UI と debug の両方で分かれている

次に進める項目:

- browser-render が必要だった実ページの類型を継続収集し、QuickJS 側で吸収すべき DOM / event / network gap の優先順位を更新する
- `tweb.audit` のような定常比較から worst offenders を取り出し、単発の site-specific 修正要求ではなく failure class 単位の改善順へ落とす
- provider を追加する場合は、既存 contract 上で devtools/cdp 依存部分だけを差し替え、Cookie bridge の origin 境界や redirect 後の扱いを追加整理する

完了条件:

- 通常利用では Chrome 非依存を維持しつつ、必要時の救済経路だけを明示的に使える
- browser-render 実装が optional component として分離され、将来の差し替え余地がある
- quick.js 側の機能拡張によって browser-render が必要な場面を継続的に減らせる

### Phase 12: JS Runtime Performance and Cost Control

状態: 完了

目的:

- QuickJS ベースの読解品質を落とさず、JS-heavy ページで支配的な実行コストを継続的に減らせる測定面と改善面を作る
- site-specific な速度対処ではなく、script load、event dispatch、async drain、DOM/style 再計算、runtime data 補完の共通コストを対象にする
- browser-render fallback を性能面でも比較対象として使い、QuickJS 側で優先的に縮めるべきボトルネックを判断できるようにする

完了済み:

- third-party script skip、`StyleContext` cache、post-load async drain 短縮はすでに実ページで効果が出ている
- `javascript_debug()` と debug log に phase 別 timing/count を追加し、script eval / page event dispatch / async drain / style rebuild / hydration / browser-render 比較を追えるようにした
- external script は process 共有 file cache で再利用し、cache key は `URL` を基本にして `Vary` があるときだけ request 条件で分岐するようにした
- `Cache-Control` / `ETag` / `Last-Modified` を見た短い再検証を入れ、`no-store` は保持しない最小方針を実装した
- `_drain_async_work()` は DOM/network 変化のない timer 進行だけが続くときに早期停止し、無駄な待ちを減らすようにした
- `--no-script-cache` で cache を無効化でき、debug 時に hit / miss / revalidate / bypass の切り分けができる
- unittest で script cache reuse / bypass と debug surface の回帰を追加した

完了後も残る既知の残差:

- style cache invalidation はまだ全体 invalidation ベースで、attribute/class/style 単位の局所再計算には至っていない。これは Phase 12 の完了判定を妨げる未実装ではなく、次の最適化余地として残っている。
- 実ページの継続的な速度ベンチマーク fixture はまだ薄く、live repro の蓄積は今後も必要である。これも Phase 12 の完了後に継続して厚くしていく観測面の課題である。

完了条件:

- debug log を見れば、JS-heavy ページでどの処理群が支配的だったかを説明できる
- 外部 script cache を入れる場合でも、variant 違いの取り違えや stale bundle 固定化を避ける最小限の方針が文書化されている
- drain budget と style 再計算の改善で、代表的な JS-heavy ページの待ち時間を一段下げられる
- 新しい速度改善が site-specific hack ではなく、共通コスト削減として説明できる
- `PLAN.md` と `JS.md` に、性能改善の対象範囲と比較方法が同期されている

### Phase 13: 認証情報マネージャ連携

状態: 未着手（Cookie import・password 編集・AI API の確認要求は既存基盤として実装済み）

目的:

- `1Password` のような外部 secret manager を前提に、資格情報を `tweb` に直接保存せず必要時だけ明示的に受け渡す設計を作る
- 最初の対象は `op` CLI のような外部コマンド経由の半自動入力とし、`tweb` 自身が vault 実装や browser extension 互換を抱え込まない
- password input の編集、login form の補助、Cookie / session の持ち込みを同じ許可モデルで整理する
- origin と submit 先を見ながら、どの認証情報をどこへ送るかをユーザーが確認できる UI を定義する
- 自動 submit は既定にせず、入力・送信・永続化を別々の許可に分ける
- JavaScript から secret manager や OS 機能へ直接触れられない前提を保つ

既実装:

- CLI の Cookie / session 持ち込み、TUI の password 編集、AI 向け mutate API の password 入力確認は実装済み
- 外部 secret manager / 外部コマンドの実行と入力欄への受け渡しは未実装。既存の手動入力・Cookie import と区別する

未完了:

- 外部コマンド結果をどの UI / API からどの field へ入れるかの操作面がない
- origin / submit 先確認と、値そのもののマスキングを結び付けた仕様がない
- 失敗時ログや履歴に秘密情報を残さない整理が不足している
- 最初の surface を TUI / CLI / API のどれに絞るか未決定

次に進める項目:

- 最初の surface を 1 つに絞り、`op read ...` のような外部コマンド結果を password input / text input に流し込む最小フローを定義する
- TUI を最初の surface にする場合は、`Fill from command` 相当の操作について対象 field・対象 origin・実行コマンドの見せ方を決める
- Cookie / bearer token / session import を CLI で扱う場合のファイル形式とスコープを整理する
- ログ、履歴、例外表示に資格情報を残さないマスキング方針を固める
- `README.md` と `SECURITY.md` に、何が未実装で何が明示許可かを同期する

完了条件:

- 外部 secret manager からの資格情報受け渡しが、入力補助・送信・保存の境界を崩さずに利用できる
- origin 単位の確認、ログマスク、誤送信防止の方針が `SECURITY.md` と一致している
- 1Password など特定製品名は例として扱い、実装は汎用の外部コマンド / secret source 抽象で説明できる

### Phase 14: Renderer Metadata と Interactive Span の一体化

状態: 完了

目的:

- TUI の link / control hit test を、rendered text に対する後段の文字一致ではなく、renderer が生成した provenance 付き span metadata に基づいて行う
- `render_normal()` と `collect_visible_links()` の二重走査を減らし、表示テキスト・interactive span・block region の対応を 1 回の render pass で揃える
- 単文字リンク、空文字 anchor の accessible label 補完、overlay card link、CSS による非表示要素のようなケースで、文字列衝突ではなく DOM/render 由来の位置情報で安定判定できるようにする
- focused-pane / full-page / save-visible-page のような派生表示でも、どの interactive metadata がどの rendered text に対応するかを崩さない

完了した項目:

- `render_normal_with_metadata()` / `render_normal_subtree_with_metadata()` を追加し、rendered text と link/control span metadata を同じ render pass から返せるようにした
- link / iframe / input / textarea / select / button / tab の interactive span を renderer で生成し、TUI の `RenderedBuffer` へ直接載せる経路を作った
- focused-pane / subtree render でも同じ metadata contract を使い、full-page と subtree の両方に回帰テストを追加した
- TUI の `_build_render_buffer()` は renderer metadata を優先し、label ベース control や overlay link のような未 metadata ケースだけ既存 fallback を併用する形へ整理した
- `TUI.md` に、interactive span の由来と保証範囲を反映した

完了条件:

- TUI の link/control hit test は通常経路で rendered text の曖昧一致に依存しない
- 単文字リンクや overlay 的な重なりで、誤った文字位置が clickable にならない
- full-page / focused-pane / subtree render で、表示テキストと interactive metadata の対応が一貫している
- renderer metadata の生成責務と TUI 側の消費責務が `PLAN.md` / `TUI.md` で同期されている

### Phase 15: Interactive Metadata Fallback の撤去

状態: 完了

目的:

- Phase 14 で暫定的に残した plain text 再検索 fallback を撤去し、TUI の interactive span 復元を renderer metadata のみで成立させる
- overlay link、CSS hidden anchor text、label ベース control など現在 fallback に依存しているケースを、renderer metadata 側で表現し切る
- `collect_visible_links()` / `collect_visible_links_subtree()` と TUI の clickable 判定の間で、visible text と metadata の二重定義をなくす

完了した項目:

- `RenderedControlMetadata` に `source_kind` を追加し、token span だけでなく `<label>` / `aria-labelledby` 由来の clickable 範囲も renderer metadata として返せるようにした
- row-flex/overlay card link の空 anchor は表示テキストを増やさず、親コンテナ render 中に visible title 位置へ link metadata を付与する経路へ置き換えた
- `collect_visible_links()` / `collect_visible_links_subtree()` は renderer metadata 由来の adapter に寄せ、CSS hidden anchor text・overlay link・iframe を TUI と同じ span 情報から列挙するようにした
- `_build_render_buffer()` から link/control span 復元の plain text 再検索を削除し、renderer metadata のみを消費する形へ整理した
- full-page / focused-pane / subtree と direct buffer test の回帰を metadata 前提へ更新し、Phase 15 完了面を `tests.test_normal_renderer` / `tests.test_tui` で固定した

完了条件:

- `_build_render_buffer()` が link/control span 復元のために plain text 再検索を使わない
- overlay card link、CSS hidden anchor text、単文字リンク、label ベース control で metadata のみから正しい clickable span が構築できる
- `collect_visible_links()` / subtree 版が renderer metadata と矛盾しない
- TUI.md / PLAN.md 上で fallback が暫定実装ではなく不要になったことが明記されている

### Phase 16: TUI Rendering Path Performance

状態: 完了（最初のスコープ。2026-10-19）

目的:

- `--mode text` と TUI の待ち時間差を renderer と後段処理に分けて説明できるようにする
- single-column / static-rich article の不要な pane 検出を避け、multi-pane の `v` 操作を維持する

実装済み:

- debug log の `tui timing phase=... elapsed_ms=...` で、renderer、controls/links、page build、interactive order、source buffer、pane detection、focused pane、display buffer、pane region 統合、viewport 更新を計測する。ページ構築分は `BrowserPage.build_timings_ms` にも保持する
- pane detection は通常レンダラと同じ lightweight 判定を先に評価し、該当ページでは layout hint の走査と full CSS 構築を行わない。構造走査は hidden / template 等の対象外 subtree に降りず、表示に寄与しない layout hint による false positive を減らす
- `BrowserPage` に source buffer、全体表示用 buffer、pane target、pane subtree の `NormalRenderResult` を保持する。本文照合と focus 描画で同じ text / interactive metadata を再利用する
- `v` の切り替えだけが元のページキャッシュを明示的に渡す。同一 document・source text・width のとき再利用し、load / DOM 更新後の rerender / resize / background render では新規構築する
- ページ構築の段階間で worker のキャンセルを検査し、キャンセル済みの後段処理を続けない

検証:

- TUI / normal renderer / CLI の 271 tests が成功。既存の multi-pane focus / restore、リンク、カーソル復元、nested pane、resize、background render 中断の回帰を含む
- hidden/template 内だけの layout hint、static-rich page の CSS/走査省略、外部 stylesheet の true multi-pane、キャッシュ再利用、resize・DOM 更新時の破棄、段階別計測、キャンセルを追加テストで固定した
- 取得した Python ドキュメントの HTML を Textual headless TUI で再生し、キーボード `v` による focus / restore と本文復元を確認した。実ターミナルでの体感確認とは区別する
- 同一取得 HTML による API 直測と TUI 計測は `docs/performance.md` に記録した。Wikipedia の live fetch は HTTP 403 のため検証できていない

継続する最適化余地:

- 初回の multi-pane 検出・subtree render では CSS の再評価が残る。renderer の style / block / pane 情報を単一 pass から返す拡張は今後の候補とする
- lightweight 判定の link 数閾値は変更していない。低 link 数の記事への適用拡大は、実ページの取得・表示比較で判断する
- キャンセルは段階間で確認する。個々の CSS matching / render / buffer 構築中を強制停止するものではない

### Phase 17: WRS-Style Rendering Efficiency

状態: 一部実装済み（本文表示オプションのみ。実行効率化の主スコープは未着手）

目的:

- `tweb` を「完全なブラウザ再現」ではなく「本文理解に必要な最小レンダラ」へ一段寄せ、JS-heavy ページの成功率と実行コストの両方を改善する
- 取得・リソース選別・JS 実行・render 完了判定・本文抽出の責務をさらに分離し、どこで時間や失敗が発生したかを debug surface で説明できるようにする
- browser-render fallback や site-specific 補完の前に、QuickJS 側で吸収できる一般的な無駄リソース・待ち過ぎ・不要ネットワークを減らす

設計案:

- 本文理解に不要なリソースを renderer 側で積極的に抑制し、画像・動画・font・analytics・beacon・reporting のような非必須 fetch を既定で落とせるようにする
- render 完了判定を「ページ全体が静かになるまで待つ」方式から、「主要本文コンテナ・可視文字数・見出し/段落候補が一定期間安定したら打ち切る」方式へ寄せる
- fetch / XHR は一律許可ではなく、document/json/html/api のような本文寄与が高いものを優先し、tracking/telemetry 系は分類して既定抑制できるようにする
- JS 実行中に発生した subresource / XHR / timer を phase 別に記録し、どの分類が許可・遮断・本文寄与あり/なしと判断されたかを debug で追えるようにする
- render 打ち切り理由を timeout だけにせず、`body-stable`、`content-converged`、`network-idle-but-no-progress`、`blocked-nonessential-network` のような分類で残す
- stateless 実行方針は維持しつつ、同一 run 内では JS/CSS の再取得を減らせるよう phase 12 の cache 基盤を本文理解優先のポリシーで再利用する

最初のスコープ:

- 不要リソース遮断の既定分類を導入する
- 本文安定ベースの render 打ち切り条件を追加する
- XHR / fetch の分類制御と debug surface を追加する
- 直前の render で「何を待ち、何を落とし、何を本文寄与と判断したか」を後から確認できるようにする

実装済みの本文表示オプション:

- CLI の `--mode text --main-only` と `main_from_path(..., main_only=True)` で、本文領域だけを通常レンダラで表示できる
- 表示可能な `<main>` / `<article>` を優先し、存在しない場合は本文候補を推定する。候補がなければページ全体へ戻る
- このオプションは描画対象の選択であり、JS 実行やネットワーク待ちを本文安定で打ち切る機能ではない

今後の拡張候補:

- 本文テキスト・見出し境界・主要リンク候補を構造化して返す専用 read API。既存 renderer/TUI の正本を置き換えない

未解決論点:

- リソース分類を MIME type、URL pattern、initiator 種別のどこまでで判定するか
- 本文安定の判定に DOM node 数、可視文字数、main/article 候補、layout block 数のどれを採用するか
- 同じ fetch でも初回本文構築に必要な API と、追跡系 API をどの程度安全に見分けられるか
- CLI の本文表示に加えて構造化抽出を提供する場合、`snapshot()` 系へ寄せるか、独立 read API にするか

次に進める項目:

- 既存 debug log と `javascript_debug()` / `hydration_debug()` の出力を確認し、追加すべき resource/network/render-cutoff reason を棚卸しする
- render 完了判定の候補指標を小さな fixture と既知の JS-heavy サイトで比較し、過待機と早切りの失敗 class を整理する
- `SECURITY.md` / `JS.md` に、本文理解のために許可するネットワークと既定で落とすネットワークの方針を書く
- 既存の `--main-only` を基盤に構造化抽出を追加する場合、呼び出し面と戻り値の最小案を `API.md` 候補としてまとめる

完了条件:

- JS-heavy ページで、本文理解に不要なリソース待ちによる無駄時間を減らせる
- render 打ち切り理由と subresource/XHR の許可・遮断判断を debug から説明できる
- 本文安定ベースの完了判定が live repro と focused tests の両方で回帰管理される
- 実装済みの `--main-only` は opt-in を維持し、実行効率化を加えても既存の通常表示/TUI 契約を壊さない。構造化抽出 API は追加の拡張候補とする

### Phase 18: MCP Adapter Surface

状態: 未着手

目的:

- `tweb` を GUI 自動操作ではなく「構造化された browser/document tool」として MCP client から扱えるようにする
- 既存の `snapshot()` / `debug_control()` / `agent_actions()` の read / preflight / mutate 境界を壊さず、そのまま MCP tool surface に写像する
- TUI や内部 renderer 実装を MCP に従属させず、Python API の薄い adapter として追加する
- 1 page/session 単位の最小 surface から始め、secret 取り扱いと確認要求を既存の security model と整合させる

設計案:

- transport は標準的な MCP server とし、`tweb` 本体の公開面は Python API のまま維持する
- server 実装は `tweb.mcp` のような独立 module に閉じ込め、fetch/parse/runtime/render の内部層へ直接触らず `TWebDocument` と session helper だけを使う
- session は `session_id` で識別し、URL/path・Cookie/session・現在 document・直近 debug 情報を server 側で保持する
- 最初の tool 群は `open_page`、`get_snapshot`、`debug_control`、`list_controls`、`invoke_action`、`close_session` 程度に絞り、TUI 相当のキー操作や画面座標操作は exposed しない
- `invoke_action` は既存 `AgentActionResult` の `status` / `reason` / `available_actions` / `requires_confirmation` をそのまま返し、password や policy block の確認再実行も既存 contract に合わせる
- `dom-ai` の生文字列出力ではなく `snapshot().to_dict()` 相当の構造化データを正本にし、人間向け text render は二次的な debug 用 surface に留める
- browser-render fallback、external command、credential manager など optional capability は既定では tool surface に混ぜず、後から capability flag か別 tool として分離する

最初のスコープ:

- ローカル path / HTTP(S) URL を開いて `TWebDocument` を session 化できる
- 1 session に対して snapshot 取得、control の事前確認、基本 action invoke ができる
- mutate 後に最新 snapshot を取り直せる
- エラーは Python 例外の文字列ではなく構造化された `code` / `message` / `details` へ正規化する

未解決論点:

- session の寿命を stateless 再open 優先にするか、複数 tool call を跨ぐ stateful model にするか
- Cookie / imported session を tool 引数で毎回受けるか、server 側 resource として持つか
- `requires_confirmation` を 2 段階 tool call にするか、MCP client 側 confirmation UI とどう接続するか
- debug/log surface に hydration / javascript / browser-render のどこまで露出するか
- 長時間動く session の cache・timeout・resource cleanup をどの層で担保するか

次に進める項目:

- MCP tool schema の最小案を `AgentPageSnapshot` / `ControlDebugInfo` / `AgentActionResult` に対応づけて具体化する
- `create_session()` と `TWebDocument` を使う server 内部の state model を決め、stateless で足りない箇所だけ stateful にする
- `API.md` と `SECURITY.md` に、MCP surface は Python API の別 transport であって権限境界の新設ではないことを明記する
- secret-confirmation と browser-render fallback を初期 scope から外すか、capability flag で opt-in にするか決める

完了条件:

- MCP client から、ページ open・snapshot 取得・control 事前確認・基本 action invoke の最小往復ができる
- Python API と MCP tool surface の責務分担が `PLAN.md` / `API.md` / `SECURITY.md` で矛盾しない
- TUI や renderer の内部実装を直接 MCP へ露出せず、thin adapter として保守できる
- 確認要求、資格情報、optional capability の扱いが既存 security model と整合している

### Phase 19: Unicode/CSS Text ベースの改行・折り返し一般化

状態: 未着手

目的:

- 現在の通常表示 renderer が持つ token ベースの折り返しを、Unicode line breaking と CSS Text の考え方に寄せた break-opportunity ベースへ置き換える
- 日本語だけの対症療法ではなく、mixed-script text、CJK、space-delimited language、dictionary-based segmentation を要する writing system を同じ枠組みで扱えるようにする
- TUI / normal renderer / subtree renderer で改行規則を共有し、live repro ごとの ad hoc wrap fix を増やさずに済む基盤へ寄せる

設計案:

- 折り返し単位は単純な非空白 token ではなく、まず grapheme cluster を基準にした表示単位列へ落とす
- その上で UAX #14 相当の line break opportunity を列挙し、mandatory break / forbidden break / soft wrap opportunity を区別する
- `lang` と writing-system 推定が取れるときは、その情報で CJK strictness や dictionary-required script の segmentation policy を切り替える
- 日本語/CJK では、句読点・small kana・iteration mark・長音記号などの禁則を `line-break: normal/strict` 相当の方針で扱う
- 英語など space-delimited language では space / hyphen / soft hyphen を優先し、`overflow-wrap` 相当の emergency break は通常候補が尽きたときだけ使う
- Thai / Khmer / Lao など辞書や言語依存分割が必要な script は、辞書ベース segmenter を optional capability とし、未対応時の fallback も明文化する

最初のスコープ:

- `tweb/renderers/normal.py` の `_wrap_paragraph()` を break-opportunity ベースへ置き換える
- normal renderer と subtree renderer の回帰を `tests.test_normal_renderer` で固定する
- 日本語の句読点行頭禁止、英字/CJK 混在の早すぎる改行回避、space-delimited language の既存表示維持を最初の受け入れ条件にする

未解決論点:

- UAX #14 相当を自前実装するか、Python で依存追加して segmenter / line break class を引くか
- `lang` が取れない text run に対して、script 判定だけでどこまで tailoring するか
- dictionary-required scripts の fallback を「文字単位の emergency break」にするか、「未対応として見た目 overflow を許す」か
- TUI 側の cursor / span metadata が改行規則変更でどこまで影響を受けるか

次に進める項目:

- UAX #14 / CSS Text に沿って、`tweb` で必要な最小 line break class と tailoring 範囲を整理する
- 現在の wrap regression を failure class ごとに棚卸しし、`token が大きすぎる`・`禁則を破る`・`dictionary segmentation 不足` へ分解する
- 実装前に `CSS.md` または text layout を扱う文書へ、`white-space` / `word-break` / `line-break` / `overflow-wrap` の採用方針を書き出す

完了条件:

- 日本語・英語・mixed-script text の基本的な折り返しが、token 粒度の偶然ではなく break opportunity に基づいて説明できる
- 日本語の禁則が回帰テストで固定され、ad hoc な単語単位 heuristics を増やさずに live repro を閉じられる
- 将来の dictionary-based language 対応を追加しても、renderer 全体を書き直さずに segmenter / tailoring 追加で拡張できる

### Cross-cutting: セキュリティ

状態: 継続中

- 詳細 TODO は `SECURITY.md` で管理する
- ローカルファイル、ネットワーク、JavaScript、フォーム送信を別々に許可できる設計を維持する
- 機能追加時に、許可モデルと安全境界の追記を同時に行う

直近の論点:

- JavaScript 実行の時間・メモリ制限
- 外部 CSS / 外部 JS / 画像 / iframe 相当の読み込み方針
- TUI 上での遷移先や送信先の可視化
- ログや Cookie の扱いの明確化
- JS 駆動 button click を DOM 更新まで許すか、fetch / XHR / navigation まで許すかの分離
- secret manager から渡した資格情報をどの origin / どの submit にだけ使えるかの明確化

## 検証方針

- fixture / unit test:
  フェーズごとに最小 fixture を用意し、期待出力を固定しやすいテストを書く。通常モード、DOM モード、TUI の差分を独立に確認する。repo ではまず `uv run python3 -m unittest ...` を基本の検証面にする。
- live repro:
  実ページの退行が疑われる変更では、`uv run tw <url>` または `uv run tw <url> --mode text|dom|dom-ai` の実経路で確認する。特定の不具合報告がある場合は、その URL と起動オプションをそのまま再現する。
- runtime / JS:
  CSS / JavaScript / hydration は小さなサンプルから広げるが、browser-render や site-specific fallback に関わる変更では fixture だけで済ませず、必要なら live path も合わせて見る。
- AI API:
  `snapshot()` や `debug_control()` などの AI 向け API は構造化された戻り値と権限境界の両方を前提に検証する。
- docs sync:
  user-visible な挙動や許可モデルを変えたときは、関連ドキュメントも同時更新する。

## 更新ルール

- 実装が完了したら、そのフェーズの状態を更新する
- 継続中フェーズは「完了済み」と「次に進める項目」を分けて保つ
- 詳細仕様は関連ドキュメントへ寄せ、この文書には作業判断に必要な要約だけを残す
- 方針変更時は README.md / TUI.md / DOM.md / CSS.md / SECURITY.md との整合を確認する
