# JS.md

このドキュメントは、`tweb` における JavaScript 対応の実装状況と実装方針をまとめたものである。CLI / TUI からどう使うかの入口は `README.md`、セキュリティ上の TODO は `SECURITY.md` を参照する。

## 基本方針

- JavaScript 実行エンジンは quick.js を使う
- 取得層は既存の `requests` ベース実装を再利用し、JavaScript 向けにも別系統の site-specific fetch は足さない
- JS 対応は「一般的なページを壊れにくく読むための最小ブラウザ互換」を優先し、フルブラウザ互換は最初から目指さない
- DOM 操作、埋め込み script 実行、最小ネットワーク API、再レンダリング整合性を段階的に広げる
- 特定サイト向けの HTML 補完や API 直叩きは取得層に入れず、必要なら JavaScript 実行結果や汎用的なフォールバックとして扱う
- user-visible な挙動や許可境界を変えたときは `README.md`、`PLAN.md`、`SECURITY.md` と同期する

## 現在の実装状況

最初に結論を書くと、現状の `tweb` は「軽量な quick.js 実行環境としてはかなり広めに動く」が、「実ブラウザ同等」ではない。特に、対応済み API の中にも最小 shim として成立しているだけのものが含まれる。

### 対応済み

#### 実行経路

- `tweb/js_runtime.py` に quick.js ベースのランタイムを持つ
- Python API では `TWebDocument.execute_script()`、`execute_inline_scripts()`、`execute_embedded_scripts()` を使える
- CLI では `--script` / `--script-file` で JavaScript を適用してから再レンダリングできる
- TUI / CLI の通常経路では埋め込み script を実行してから表示する
- `--browser-render auto|always` を指定したときは、quick.js だけで崩れるリモートページに browser-render fallback を使える
- `auto` は `main` 消失や明確な client-render failure だけでなく、quick.js 実行後も loading placeholder が残る場合にも fallback 対象にする
- browser-render fetcher は現状 `chrome` provider を実装し、`execute_embedded_scripts(..., browser_render_fetcher=...)` で差し替え注入できる
- browser-render fetcher の注入面は `BrowserRenderRequest(target, provider, timeout)` と `BrowserRenderResult(content, source, headers, status_code)` を共通 contract とし、Cookie bridge・timeout・empty DOM 判定を fetch 層でまとめて扱う
- debug log の `browser-render decision` には `trigger=auto-fallback|manual-retry` と `failure_class=...` が出るので、救済経路へ進んだ理由を切り分けやすい
- quick.js runtime には既定のメモリ制限があり、limit 超過は明示的な `JavaScriptRuntimeError` として返す
- `tweb.audit` は browser-render fallback を診断用途に固定利用し、代表20サイトで `never` と `always` の差分を機械比較できる
- audit render は子プロセス隔離なので、QuickJS の crash/segfault を `quickjs_error` として集計しつつ残りサイトを継続できる。internal render subprocess は `fetch` / `parse` / `execute_embedded_scripts` / `snapshot` など直前 phase を stderr に残すため、`exit -11` でもどこで落ちたかを追いやすい
- 巨大 inline hydration script、特に `window.__data = JSON.parse("...")` のような root payload は raw HTML 側から先に回収し、同名 root を runtime collector で再度 `JSON.stringify` しない
- webpackJsonp 系 bundle が quick.js の compile-time `stack underflow` で止まる場合は、問題の module だけを局所的に前処理し、それでもだめな object entry だけを no-op 化して残りの bundle 実行を継続する
- webpackJsonp の `[` / `{` 対応は regex、template literal、comment をまたぐ大きい bundle でも lenient に切り出し、bundle 全体が読める限り module 登録を継続する

#### DOM の基本操作

- `document.title` / `document.body` / `document.documentElement` / `document.currentScript`
- `querySelector` / `querySelectorAll` / `matches` / `closest`
- `getElementById` / `getElementsByTagName` / `getElementsByClassName`
- `textContent` / `innerHTML` / `outerHTML`
- 属性参照と更新、`classList`、`dataset`
- `createElement` / `createElementNS` / `createTextNode` / `createComment` / `createDocumentFragment`
- `appendChild` / `append` / `prepend` / `insertBefore` / `replaceChildren` / `replaceWith` / `remove`
- `cloneNode` / `contains` / `isEqualNode` / `getRootNode()`
- `createRange` / `createTreeWalker` / `getSelection` の最小実装
- `getComputedStyle()` の最小実装

#### script 実行とイベント

- inline script を順番に実行できる
- 外部 script 読み込みに対応している
- 動的に挿入した `<script src=...>` の読み込みに対応している
- `async` / `defer` / `type="module"` は、即時 inline script の後段へ回す最小動作を持つ
- 複数 script 間で `window` のグローバル状態を共有する
- `DOMContentLoaded` / `readystatechange` / `load` / `pageshow` / `visibilitychange` / `focus` を最小限 dispatch する
- 本文・link・control が十分な静的 portal は `load` / `pageshow` を省略して `DOMContentLoaded` まで実行し、jQuery ready 内の取得処理は保持する。400 link以上の超高密度 page は ready timer も省略する
- `setTimeout` / `clearTimeout` / `setInterval` / `clearInterval`
- `requestAnimationFrame` / `requestIdleCallback` / `queueMicrotask`
- 直近の timer / microtask を drain するが、遠い future timer は無限に待たない

#### 外部 script cache の方針

- 外部 script の cache は性能改善の候補だが、最初からブラウザ級の永続 HTTP cache を再現する前提では持たない
- external script cache は `diskcache` に保存し、同じ script を process をまたいでも再取得しないことを狙う
- cache key は `URL` を基本にし、レスポンスが `Vary` を返したときだけその request 条件で variant を分ける
- `Cache-Control` / `ETag` / `Last-Modified` を無視した長寿命キャッシュは、古い bundle や deploy 切り替えを踏み続ける危険があるため避ける
- 対象はまず `GET` の外部 script に限定し、runtime 中の一般 `fetch` / XHR JSON 応答まで同じ cache に広げない
- `--debug` では script cache の hit / miss / revalidate / bypass を追えるようにし、速度改善と挙動差の切り分けをしやすくする
- 必要なら `--no-script-cache` のような無効化手段を持てるようにし、live repro や原因切り分け時に強制再取得できるようにする

#### Phase 12 で追加した性能面

- `document.execute_embedded_scripts()` は phase 別の timing/count を `javascript_debug()` と debug log に残し、script eval / page event dispatch / async drain / style rebuild / hydration / browser-render 比較を追える。加えて `slow_scripts` で遅い script 上位を持ち、巨大 bundle 1 本が total time を支配しているかを live site で切り分けやすくした
- `querySelector` / `querySelectorAll` / subtree selector は mutation epoch 単位の cache を持ち、同じ selector を同一 DOM 状態で繰り返す bundle の固定費を落とせる。 hit/miss は `selector_query_cache_hits` / `selector_query_cache_misses` として `javascript_debug()` に残す
- `getElementById` / `getElementsByTagName` / `getElementsByClassName` は `querySelector` / `querySelectorAll` へのフォールバックではなく、bridge 側の専用 tree traversal fast path を使う。 jQuery / jQuery UI 系の bundle はこの 3 API を高頻度に叩くため、selector engine を毎回通さない方が安定して効く
- `compareDocumentPosition()` は document 全体の平坦化ではなく ancestor/sibling ベースで比較し、detached node 同士では軽く `DOCUMENT_POSITION_DISCONNECTED` を返す。 jQuery 3 の support probe がここで止まると後続 bundle 全体が進まないため、基本 DOM 互換として先に吸収する
- jQuery が読まれた後は legacy shorthand shim を自動で当て、`$(window).load(fn)` のような古い event shorthand を `on('load', fn)` へ逃がす。 `$('#node').load('/fragment.html', ...)` の Ajax 版はそのまま維持する
- 無視可能な外部scriptエラーの後にQuickJS runtimeを作り直す場合、成功済みのjQuery本体は定数bootstrapと同様に再実行する。クリーンruntimeへライブラリglobalを戻し、後続scriptを `$ is not defined` で連鎖停止させない。jQuery pluginやDOM操作scriptは再実行対象に広げない
- script 実行前後には `id` 由来の window named property を同期し、`<div id="emergency">` を `window.emergency` / bare `emergency` として参照する旧来 script を止めにくくする。既存の built-in や明示代入済み global は上書きしない
- `gcse:searchbox-only` のような custom-element search placeholder は、runtime が実際の `<input>` / submit button をまだ差し込めなくても synthetic form control として見せる。 Google Custom Search のように remote script 依存で検索 UI が遅延生成される page でも、監査上の入力系 control を落としにくくする
- `document.write()` / `document.writeln()` は実行中 script の直後へ HTML fragment を挿入できる。挿入 fragment 内の外部 script は parser-blocking として source を取得し、現在の QuickJS context で同期評価する。個別 script の取得・評価失敗は後続 parser-inserted script を止めず、Google CSE の placeholder や legacy dependency chain を後続の visible DOM 収集へつなげる
- detached document と `iframe.contentDocument` は `open()` / `write()` / `writeln()` / `close()` を持ち、広告・計測 script が一時 document へ markup を書く bootstrap を止めにくくする
- `Node.prototype.contains()` は prototype target が個別 method を持たない場合も self/descendant traversal へ fallback し、MutationObserver callback の node containment check を継続できる
- 可視本文がすでに十分ある page では、単独の `Loading...` / `NOTICE Loading...` placeholder を埋め込み script 後に prune する。 client shell の残骸だけが QuickJS 結果へ混ざって `alternate_content_branch` 扱いになるのを避ける
- `XMLHttpRequest` は `responseType='document'` に加えて `overrideMimeType()` と `responseXML` を持ち、same-origin partial HTML を読み込んで header / footer / topics を差し込む政府系サイトの callback を止めにくくした
- XHR の `responseText` は bytes から charset-aware に復元し、`text/html` が charset 無しで返る partial HTML でも `overrideMimeType('...;charset=UTF-8')` と meta charset を尊重して文字化けを避ける
- page event dispatch は QuickJS の `set_time_limit()` を使わず、既存の async drain budget / preflight / pending-job 上限で守る。 Python bridge を使う `querySelectorAll` 系 callback は time limit と両立せず、通常監査パスで hydration が途中停止するため
- delayed script が多い page だけでなく、raw HTML の時点で本文・link・control が十分ある静的ポータルでは、expensive page event dispatch 自体を skip できる。 `load` / `pageshow` 後の UI polish や animation を待つより、既に取れている本文を保持して timeout を避ける方が quality/perf の両面で有利なため
- DOM mutation 後の `parentNode` / `removeChild` / `insertBefore` 系は `_tweb_parent` を保持して tree 全探索へ落ちにくくしている。 page event や jQuery callback 内で親要素探索が多いサイトでも、mutation-heavy path の固定費を減らせる
- `TextNode` の内容更新や text node の detach のような text-only mutation では、selector query cache epoch と style context cache を落とさない。 selector/style に無関係な本文差し替えだけで `querySelector(All)` の結果を毎回捨てるのを避け、mutation-heavy app bundle の固定費を下げる
- Splide のように mount 前だけ `visibility:hidden` を付ける carousel では、text-rich かつ未初期化の container を単純な hidden 扱いにしない。初期 CSS の都合で本文が丸ごと invisible 判定されるのを避ける
- external script は既定の user cache dir に `diskcache` ベースの永続 cache を持ち、`URL` を基本キーにして `Vary` があるときだけ request 条件で variant を分ける
- cache entry は `Cache-Control` / `ETag` / `Last-Modified` を見て短い再検証を行い、`no-store` は保持しない
- crash safety 用の quickjs preflight は同一条件の結果を runtime 内で再利用し、probe に渡す prior script 群も直近数本と文字数上限に絞って payload 膨張を避ける
- `_drain_async_work()` は DOM/network 変化のない timer 進行だけが続く場合に早期停止し、無駄な待ちを減らす
- raw 200 link以上の静的リッチ page は1回の async drain を8 timerに制限する。timer実行直前のstep・DOM mutation数をdebug logへ残し、native crash時の直前段階を追えるようにする
- post-load 後も本文が極端に sparse な page は `250ms -> 1s -> 5s -> 10s` の段階的 horizon で pending timer を排水し、途中 callback の互換エラーを隔離して次段へ進む。本文がすでに読める動的 page でも、DOM mutation と ready timer が残る場合だけ `1s` 上限の短い追加排水を行う
- closed `select` の visible text は選択 option だけを採用し、未指定の single-select は先頭 option、multiple-select は明示 `selected` だけを本文として扱う
- hydration 後の初期 body 復元は、mount 後 DOM が初期 shell より 3 個以上多い form controls を持つ場合は抑止する。Vue のように `el` 自体を描画済み root へ置換して元 id を消す app を client failure と誤認し、正常な検索 UI を空 shell へ戻さないため
- style cache は引き続き全体 rebuild だが、invalidations / rebuilds 自体を計測できるようになったため、次の局所化改善を定量比較できる
- static-page 判定用の document metrics cache は delayed script skip / expensive page event skip だけでなく、post-script の loading placeholder / client-failure shell prune にも phase 単位で再利用する。大きい DOM で同じ visible body / link / control 集計を繰り返さず、generic cleanup コストを抑える
- substantial body がすでに読める page でも、runtime hint や hidden content hint があり visible links がまだ少ないときは、raw HTML 上の long anchors を `Recovered Links` section として lazy に再利用できる。hidden DOM 全量復元より軽い経路で feed/discovery branch の link shortfall を補い、`jaxa-home` / `yahoo-news-jp-home` 系の minor gap を詰めやすくする

#### 取得とデータ API

- `fetch`
- `XMLHttpRequest`
- `Request` / `Response` / `Headers`
- `URL` / `URLSearchParams`
- `FormData`
- `Blob` / `File` / `FileReader`
- `ReadableStream` / `WritableStream` / `TransformStream`
- `TextEncoder` / `TextDecoder`
- `document.cookie`: HTTP(S) 文書での代入を requests session の CookieJar に反映し、domain / path / Secure / 有効期限に従って再取得へ引き継ぐ

#### 周辺 API

- `window` / `location` / `navigator` / `history` / `navigation` / `console`
- 初期 script / timer の `location.reload()` は実行後に同じ session で GET 再取得し、新しい文書の script を実行する。1 回のページ読み込みにつき再取得は最大 3 回で、上限到達は debug log に記録する。button click の reload は既存の navigation policy に従う
- `EventTarget` / `Event` / `CustomEvent` / `MouseEvent` / `KeyboardEvent` / `PointerEvent` など主要イベント型
- `localStorage` / `sessionStorage`
- `indexedDB` の最小実装
- `matchMedia`
- `MutationObserver` / `IntersectionObserver` の最小実装
- `Intl` の一部

#### hydration data フォールバック

- `tweb/runtime_data.py` の generic collector が、`window.__NUXT__` / `__NEXT_DATA__` / `__INITIAL_STATE__` / `__APOLLO_STATE__` / `__PRELOADED_STATE__` の既知 root、inline JSON script、`__next_f` などの chunk 配列、runtime 中の `fetch` / XHR JSON 応答を同じ出口へ正規化する
- inline script に直接埋め込まれた JSON literal や `[{type,value,children}]` 形式の text fragment も generic collector が拾い、short shell ページでは recovered text として本文へ差し込める
- これは Web 側で一般的な埋め込み状態であり、`tweb` 独自概念ではない
- `tweb` 独自なのは、本文が空または loading 表示しかない場合に、その埋め込み状態から見出し・リンク・セクション候補を抽出して補完表示へ注入するフォールバックである
- この処理は特定サイト専用ではなく、`HydrationSection` / `HydrationLink` / 補助テキストへの汎用構造抽出として実装している
- 本文がすでに十分取れているページでは、UUID・内部 URL・日時・短い UI ラベルのような low-signal な hydration 値では補完を発火させない
- 補完後は `document.hydration_debug()` で、どの source を採用したか、`confidence` が何か、site-specific fallback を併用したかを確認できる
- 1000文字以下でもlinkと入力controlを持つcompactな機能UIは、未表示のhydration値より優先して保持し、app mountを置換しない
- note.com 向けには generic collector でも `__next_f` の React flight 断片から category や note object を section 化し、必要な場合だけ site-specific 側で既存レイアウト保持を助ける
- note.com home の Nuxt mount が QuickJS 上で完走しない場合は、page runtime から既存の `/api/v3/mkit_layouts/json?context=home_tl&page=1` を呼び、返ってきた section の note title/link を `timeline__body` に補完する
- note.com home/topic の runtime fetch は共通の `mkit_layouts` probe helper に寄せ、section probe が pending の間は短い drain/poll を繰り返してから空判定する
- それでも QuickJS 側 probe が空のままなら、同じ session で同 endpoint を Python 側から再取得して補完し、Chrome fallback には逃がさない

#### `site_specific.py` の現在位置

- `tweb/site_specific.py` は「サイト名ベースの例外集」であり続けるのではなく、generic 側へまだ昇格しきれていない残差を一時的に置く場所として扱う
- 現在ここにある処理は、大きくは次の failure class に分けて理解する
- interactive section が初期 HTML では折りたたまれていて、既存 DOM だけでは中身を読めない
- page runtime には必要データへ到達する経路があるが、QuickJS 上で mount や async 完了が不安定で、そのままでは本文が空のまま残る
- 上の経路が runtime 側でも不安定なとき、同じ session を使って Python 側から同等データを取り直せば browser-render fallback を避けられる

#### 現在の残差を failure class で見る

- disclosure / accordion:
  `HydrationSection` を見出し一致で hidden panel や `aria-controls` 付き button に差し込む generic disclosure 補完を入れた。Kakuyomu TOC もこの経路で開閉可能になり、残差は複数候補の曖昧解消や role ベースの対象選別に縮んだ。
- note.com topic runtime:
  `/api/v3/mkit_layouts/json?context=category_<topic>&page=1` の section payload を、home と同じ runtime fetch helper + Python retry helper に寄せた。`/topic/outdoor/camping` のような多段 path は API 側の `category_outdoor_camping` に正規化して叩く。残っているのは endpoint 自体が note.com 固有である点で、probe / retry の仕組み自体は residual ではなくなった。
- note.com home runtime:
  runtime probe を数回待ってから、だめなら Python 側で同 endpoint を再取得する仕組みは topic と共通 helper に寄せた。残っているのは endpoint と item shape が note.com 固有である点で、retry 制御自体は residual ではなくなった。
- note.com `__next_f` layout restore:
  section 自体は generic collector で取れる。初期レイアウト復元も body 全置換ではなく、main ancestor path と shell sibling を generic に戻すところまでは移したが、pane ごとの部分復元はまだ residual として残している。
- inline Flight chunk scan:
  `window.__next_f` の実行結果だけでなく、HTML 内の `__next_f.push(...)` 文字列そのものも generic runtime-data collector が読む。script 実行順や runtime 状態で `__next_f` 参照を取りこぼしても、topic sidebar の categories / subCategories のような nav data を復元できる。
- 可視 client-failure shell の後始末:
  本文側に十分な可視テキストが残っているのに、`申し訳ありません、ただ今障害が発生しております。` のような失敗 shell だけが別 section としてぶら下がる場合は、その shell を browser fallback 前に DOM から落として最終出力へ混ぜない。

## `site_specific` を減らす方針

- 方針 1:
  サイト名ではなく failure class で整理する。`note.com 対応` と呼ぶのではなく、`flight 断片からの section 正規化不足` や `interactive disclosure 展開不足` として扱う。
- 方針 2:
  抽出器を 1 つに無理に統合するより、`HydrationSection` 相当の共通正規化面を強くする。`__NEXT_DATA__`、`__NUXT__`、flight、XHR/`fetch` 観測は収集方法が別でもよい。
- 方針 3:
  補完を発火してよい条件を generic にする。`main` 消失、loading shell 継続、既存本文の薄さ、section role の不足などを組み合わせ、URL ではなくページ状態で判断する。
- 方針 4:
  browser-render fallback は逃げ道だけでなく差分計測装置として使う。QuickJS 結果と browser-render 結果の差から、足りない DOM API、event、network model、runtime data を逆算する。
- 方針 5:
  `site_specific.py` に新しい分岐を足す前に、その分岐が吸収している failure class、generic 側へ昇格できる候補、最後まで残差として残す理由を最低限書く。

## 定常監査ループ

- `python3 -m tweb.audit` は `tweb/data/quickjs_audit_sites.json` の unified 44サイトを既定対象にし、QuickJS-only と forced Chrome の出力差をランキングする。現在は JP/EN を分けず 1 つの canonical manifest にまとめ、未解消差分を中心とする20サイトを `active_site_ids` で重点対象として明示し、必要なら `--tag jp` や `--tag en` で絞る
- 指標は visible body text 長、visible/full body 類似度、title 一致、link 数、入力系 control 数、snapshot DOM node 数で、`match` / `minor_gap` / `major_gap` / `quickjs_error` に分類する
- button/tab は raw count として保持するが、監査の主比較は text/select/radio/checkbox/submit などの user-input control に寄せ、装飾的な site chrome button の増減で過検知しにくくしている
- `--probe-navigation` を使うと same-site の代表リンクを1件だけ追加取得し、次画面の title / visible body length / link/control 数も監査 JSON に残せる
- Chrome と QuickJS が本文の locale variant だけ異なる場合は、その locale 差を別 reason として扱い、文字列類似度だけで `major_gap` を付けない
- title・link・入力系 control・DOM が十分近く、visible body だけが閾値近辺で短いケースは `major_gap` ではなく `minor_gap` に寄せる。 text-rich carousel や delayed card 群の軽微差分で過大分類しないため
- `public`、`service`、`reference`、`research`、`government`、`transport`、`weather` などの tag を manifest に持たせているので、言語別にもカテゴリ別にも同じ inventory を継続監視できる
- raw fetch が安定している `quickjs_error` / timeout 系は、比較コストを理由に canonical cohort から外さず、runtime 改善の回帰 target として残す
- 新しい live bug を直したら、再発監視したい URL を manifest に追加し、単発修正で終わらせず定常比較へ入れる

## 実装順の目安

- 1.
  `site_specific.py` の各分岐に、対象サイト名ではなく failure class を 1 行で対応付ける。
- 2.
  `HydrationSection` のような共通 section/link 正規化面を強化し、既知 root、flight、runtime probe、Python retry を同じ出口へ流す。
- 3.
  disclosure/accordion、tab、pane のような interactive section 展開を、個別 DOM class 名ではなく汎用 interaction model へ寄せる。
- 4.
  QuickJS 側で不足している API や async 実行モデルを、実ページ failure の多い順に埋める。
- 5.
  generic 側で吸収できた分岐から `site_specific.py` を削り、最後に残るものだけを残差として扱う。

### 限定対応

- `fetch` / `XMLHttpRequest` は API 名としては使えるが、内部では既存の Python 取得層を同期的に呼ぶ最小実装であり、実ブラウザの通信モデルそのものではない
- ローカルファイルと `http` / `https` を扱えるが、same-origin policy、CORS、SSRF 制御、追加通信の許可モデルはまだ未整理
- TUI / CLI で保持している session を渡した場合は、その session を経由して取得する
- TUI から `type="button"` の click を実行し、`onclick` や `addEventListener("click", ...)` による DOM 更新を反映できるが、通信や遷移の分類は未整理
- `iframe` は `contentDocument` / `contentWindow` を持つ最小 shim があるが、独立した実ページ読み込みや本格的な frame ナビゲーションまではしていない
- `DOMParser` は HTML fragment に加えて XML を Python DOM へ一括解析し、namespace prefix付き要素と `getElementsByTagName()` を扱う。`canvas`、`audio`、`dialog`、`Image`、`BroadcastChannel` などは互換性のための軽量実装が中心で、描画・再生・OS 統合まで保証しない
- `MutationObserver` / `IntersectionObserver` / `matchMedia` / `indexedDB` / `storage` は、実ページ互換のための最小動作を優先している
- `Worker` コンストラクタはあるが、別スレッドで script を実行する本物の worker ではない
- React 系サイトで必要になった DOM 互換はかなり増えているが、すべての SPA を安定再現できる段階ではない

### 未対応

- フルブラウザ互換
- JavaScript 実行時間の厳密な制限
- 厳密な same-origin policy / CORS enforcement
- 実行可能な本物の `Worker` / `SharedWorker`
- `ServiceWorker`
- `WebSocket`
- 実ブラウザ相当のレイアウト計算、描画、ペイント、メディア再生
- JS 駆動 button click の詳細分類と許可制御の完成
- すべてのクライアントレンダリング SPA を browser-render fallback なしで読める状態

## 制限と未解決事項

- quick.js runtime の既定メモリ制限はあるが、CLI/TUI からの細かい調整やページ単位のポリシー分岐は未実装
- quick.js の `set_time_limit()` は page event dispatch のような ignore-errors 経路では局所的に使い始めたが、一般の script eval 全体へ広げる厳密な wall-clock 制限は未実装
- same-origin policy と CORS は未整理
- `fetch` / XHR をどこまで既定許可にするかは再整理が必要
- 外部 script cache は `URL` 基本と `Vary` 分岐の永続 cache まで実装済みで、`Vary` の広い組み合わせ対応や eviction policy は今後の整理対象である
- iframe、worker などは一部 shim を持つが、service worker、WebSocket などは未対応
- JS 駆動 button click は submit と別物として扱い、現状は DOM 更新までを優先している。遷移・通信の分類は強化中
- React 系サイトでは互換性を拡張し続けているが、すべてのクライアントレンダリング SPA を安定再現できる段階ではない
- 一部の大きい bundle では quick.js コンパイラ固有の失敗を局所 fallback で吸収しており、完全互換ではなく「読めるところまで進める」方針を取っている

## 実装上の整理ポイント

- ランタイムの公開入口と `QuickJSRuntime` 本体は `tweb/js_runtime.py`
- Python 側の bundle 前処理や構文補助は `tweb/js_runtime_helpers.py`
- 巨大な JS bridge 定義は `tweb/js_runtime_bridge.py`
- 文書 API からの呼び出しと hydration data フォールバックの入口は `tweb/api.py`
- runtime data collector と generic section/link 正規化は `tweb/runtime_data.py`
- generic 側へまだ昇格していない残差の hydration / interaction 補完は `tweb/site_specific.py`
- CLI の script 読み込みは `tweb/cli.py`
- TUI の script 実行フローは `tweb/tui.py`
- 回帰テストは主に `tests/test_js_runtime.py` と `tests/test_cli.py`

## 今後の方針

- JavaScript 実行エンジンは引き続き quick.js を主系として維持し、全面的な別エンジン置換は既定方針にしない
- 置換を検討する場合も、まずは quick.js と現在の DOM bridge / Python callback / 同期的な取得統合を崩さずに済むかを優先して判断する
- 特定の bundle や構文クラスだけが quick.js と相性悪く失敗する場合は、全面置換より先に局所的な前処理や限定フォールバックで吸収できるかを検討する
- それでも quick.js 側で吸収しにくい失敗が継続する場合に限り、既定は quick.js のまま、問題の script 実行だけ補助エンジンを併用する構成を検討する
- 互換 API を増やすときは、実ページの失敗要因に直接効くものを優先する
- 取得層は汎用実装を保ち、site-specific な抜け道を作らない
- 外部 script cache は process 間で再利用できる永続 cache まで実装済みで、今後は variant 管理と eviction の整理を続ける
- JavaScript 実行結果は通常モード / DOM モード / TUI の表示と整合するように保つ
- 通信、DOM 更新、遷移の許可境界は曖昧にせず、段階的に分けていく
- セキュリティ上の制約と実装済み機能の差分は `SECURITY.md` に明示する

## 個別 URL の確認記録

- 2026-10-19: `https://www.kanaloco.jp/electiondata/article-1311506` は、HTTP 307 の JavaScript Cookie challenge が `location.reload()` を要求する。Cookie の session 反映と再読み込み実装により、`--browser-render never --mode text` で再取得が HTTP 200 となり、記事タイトルと周辺本文を表示できた。開票速報の候補者一覧はこの時点では未確認だった。Chrome fallback は使用していない。
- 同変更の回帰確認: JavaScript / document API / CLI / TUI の 610 tests 中 609 件成功。`test_augments_note_topic_sections_from_runtime_probe` は失敗したが、作業開始時点の `828d82f` から抽出した変更前コードでも同じ失敗を再現した。今回追加した Cookie / reload / TUI の 6 tests は成功。
- main の `2fab30f` を統合後、JavaScript / document API / CLI / TUI / 通常描画の回帰テスト 695 件がすべて成功した。
- 同 URL の修正前の追加比較: Chrome の実ブラウザと `--browser-render always --mode text` では候補者 7 名の氏名・得票数・略歴と定数・立候補者数・開票率を表示する。一方、QuickJS の候補者一覧は 0 件で、`v-cloak` と未展開の `template v-for` が残る。表の実体は `<table>` ではなく Vue 2.6.12 が生成する `div` の一覧である。
- 元 HTML の inline script には 7 名分の XML が含まれるため、一覧欠落はデータ未取得や通常描画レンダラの表対応が原因ではない。XML を `DOMParser` で解析後、`jQuery(xmlDocument).find('root > places > place')` が `TypeError: createElement is not implemented` で失敗する。QuickJS の同 XML に対する `querySelectorAll('root > places > place')` は 1 件を返し、単純な jQuery `find('place')` も 1 件を返す。XML Document の jQuery selector 初期化互換性が不足し、後続の Vue mount に到達しなかった。
- 候補者一覧の修正: XML Document に selector engine の feature probe 用ノード生成 API と文書の子ノード情報を追加し、解析した XML 要素の大文字・小文字と ownerDocument を保持する。jQuery の `find('> candidate')` が 7 件を返すようになった。さらに HTML 属性のシリアライズは二重引用符の中のシングルクォートを保持し、Vue のテンプレート式に `&#x27;` が残って render function のコンパイルに失敗する問題を解消した。サイト専用 fetch / data 補完は追加していない。
- 修正後の実 URL 確認: `--browser-render never --mode text` で候補者一覧を描画できた。取得済み HTML 内の XML と照合し、QuickJS と Chrome のテキスト出力の両方に氏名・得票数・略歴が各 7/7 件、開票率が一致することを確認した。開票データは取得時点で変わるため、この確認は保持した同じデータに対する照合結果である。周辺 script の既存エラーは残っているが、候補者一覧の生成は成功した。
- 候補者一覧修正の回帰確認: XML selector engine の feature probe、XML の nodeName / ownerDocument、テンプレート式の HTML 属性シリアライズを追加テストした。JavaScript / document API / CLI / TUI / 通常描画 / parser の合計 699 tests がすべて成功した。
