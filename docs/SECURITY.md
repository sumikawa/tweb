# SECURITY.md

このドキュメントは、`tweb` をブラウザとして実装する上で一般的に必要になるセキュリティ機能を整理したものである。実装済みのものは明示し、未実装のものは TODO として管理する。

## 前提

- `tweb` はローカルファイルと HTTP/HTTPS の両方を扱う
- JavaScript 実行、DOM 操作、フォーム送信、TUI 操作を段階的に拡張していく
- セキュリティは「危険な機能をあとから塞ぐ」のではなく、「最初から制限付きで開ける」を基本方針にする

## 現在の実装済み項目

- [x] 取得対象は現状 `http` / `https` / ローカルファイルに限定され、他スキームはそのままネットワーク取得しない
- [x] HTTPS 取得は `requests` の標準証明書検証を使い、独自に無効化していない
- [x] HTTP/HTTPS 取得には 30 秒タイムアウトを設定している
- [x] JavaScript 実行環境は quick.js ブリッジ経由で、DOM 参照・更新、最小 Web API、最小ネットワーク API を公開している
- [x] JavaScript からの `fetch` / XHR は既存の取得層を通す最小実装を持つ
- [x] JavaScript から Python 関数や OS 機能を直接呼び出す汎用 API は現状公開していない
- [x] 取得処理はキャンセルイベントを受け付け、少なくとも fetch 中断の経路を持っている
- [x] runtime data 補完の debug は source summary / confidence を返す形に留め、取得 payload 全文を既定 API にそのまま露出しない
- [x] browser-render fallback は `BrowserRenderRequest` / `BrowserRenderResult` の contract にまとめ、Cookie bridge・provider timeout・empty DOM 判定を fetch 層で共通に扱う

## 優先度の高い TODO

### 1. オリジン分離と URL 境界

- [ ] same-origin policy の基本モデルを定義する
- [ ] `http` / `https` / `file` / 将来の独自スキームを別オリジンとして扱う
- [ ] `file://` を通常の Web オリジンと同等に混在させない
- [x] リダイレクト後の最終 URL は `response.url` で追跡している
- [ ] オリジン判定まで含めて一貫した境界管理にする
- [ ] 相対 URL 解決時に base URL を一貫して扱う

### 2. ローカルファイルアクセス制御

- [ ] `file://` 読み込みを明示的に許可された場合だけ有効にする方針を決める
- [x] Web ページ上の JavaScript から任意ローカルファイルを読む API は現状公開していない
- [ ] ローカル HTML からの外部ネットワークアクセス可否を制御できるようにする
- [ ] パストラバーサルや意図しない絶対パス解決を防ぐ

### 3. JavaScript サンドボックス

- [x] quick.js 側へ露出する API は、フルブラウザ互換ではなく最小 DOM / Web API に絞っている
- [x] 任意の Python 関数や OS 機能を JS から直接呼べないようにしている
- [x] 既定のメモリ使用量制限を入れて、巨大オブジェクト生成は `JavaScriptRuntimeError` として失敗させる
- [ ] スクリプト実行時間制限を入れる
- [x] メモリ使用量制限を入れる
- [ ] 無限ループや巨大オブジェクト生成で TUI/CLI 全体が固まらないようにする
- [ ] `eval` 相当の扱い、動的コード実行の許可範囲を明示する

### 4. ネットワークアクセス制御

- [x] JavaScript からの追加通信機能として `fetch` / XHR の最小実装がある
- [ ] JavaScript からの追加通信機能をどの条件で許可するか明示する
- [ ] `fetch` / XHR は same-origin と CORS を前提に再設計する
- [ ] サーバーサイド実行環境としての SSRF を防ぐ制御を入れる
- [ ] `localhost`、RFC1918、link-local、metadata endpoint などへのアクセス制御方針を定義する
- [ ] リダイレクトで禁止先へ到達するケースも検査する
- [ ] runtime data collector のために観測した network response を、収集対象・保持件数・サイズ上限ごとに明文化する

### 5. Cookie / セッション / 認証情報

- [ ] Cookie を実装するなら jar をオリジン単位で分離する
- [ ] `Secure`、`HttpOnly`、`SameSite` の基本ルールを反映する
- [ ] 永続保存する場合は保存先と保護方式を決める
- [ ] Authorization header や認証情報を別オリジンへ誤送信しない
- [ ] browser-render fallback へ渡す Cookie bridge も same-origin / public suffix / redirect 後 origin を含めた方針で明文化する
- [ ] リダイレクト時の認証ヘッダ引き継ぎ条件を厳密にする
- [ ] 外部 secret manager から受け取った資格情報を、どの origin / form / submit にだけ使えるかを明示できるようにする
- [ ] password input への値注入、Cookie import、bearer token 利用を同じ権限にせず分離する
- [ ] 自動 submit を既定で無効にし、入力補助と送信を別確認にする
- [x] AI 向け mutate API では password input への値注入を既定拒否し、`requires_confirmation` を返して明示確認つき再実行に分離した

### 6. TLS / 証明書検証

- [x] HTTPS は `requests` 標準の証明書検証を使い、明示的に無効化していない
- [ ] 証明書エラー時の表示と失敗動作を定義する
- [ ] ホスト名検証失敗、期限切れ、自己署名などを区別して扱えるようにする
- [ ] 将来例外許可を入れる場合はセッション限定かつ明示確認付きにする

### 7. 安全なリソース読み込み

- [ ] 外部 CSS、外部 JS、画像、iframe 相当の読み込みポリシーを明確化する
- [ ] データ URL、`javascript:` URL、`blob:` 的な扱いを個別に決める
- [ ] 自動ダウンロードや自動実行につながる URL を既定で無効にする
- [ ] MIME type と実際の内容の不一致に対する扱いを決める

### 8. コンテンツ分離と DOM 汚染対策

- [ ] レンダラ内部用のメタデータとページ由来データを分離する
- [ ] DOM 再構築時に属性やテキストを安全に扱う
- [ ] 画面表示用テキストと実行対象コード片を混同しない
- [ ] 将来 HTML 再出力や UI 埋め込みを行う場合は XSS 相当の混入経路を点検する

### 9. フォーム送信の安全性

- [x] 送信先 URL、メソッド、エンコーディングを可視化する
- [ ] `file` input を実装する場合は明示選択なしに送信できないようにする
- [ ] 自動 submit や JS による隠れた遷移を抑制または可視化する
- [ ] 認証情報入力欄の扱いを通常テキスト入力より慎重にする
- [x] HTML の submit semantics と JS 駆動 button click を別経路で扱い、誤って submit に見なさない
- [x] JS 駆動 button click の結果は `dom_updated` / `navigation_requested` / `network_requested` / `javascript_required` のように分類して可視化する
- [x] `dom-only` 許可では `onclick` による DOM 更新までに留め、fetch / XHR / `location` 変更は別許可に分離する
- [x] AI 向け `agent_actions().invoke()` では、interaction 自体が policy で止まったケースを `status="blocked"` / `reason="blocked_by_policy"` として構造化して返し、network だけ止めつつ DOM 更新が成立したケースは別扱いにする
- [ ] reCAPTCHA や外部認証のような高権限フローは通常の form submit と同列に自動化しない

### 10. ダウンロードと外部アプリ連携

- [ ] ダウンロード機能を入れる場合は保存先を明示する
- [ ] 取得したファイルを自動で実行・オープンしない
- [ ] `mailto:`、外部アプリスキーム、OS 連携を入れる場合は確認付きにする
- [ ] `op` CLI や 1Password のような外部 credential tool を呼ぶ場合は、対象 origin と取得対象 secret を表示してから明示実行する
- [ ] browser extension や secret manager API を将来使う場合でも、ページ JavaScript から直接届く経路は作らない

## 追加で必要な TODO

### 11. CORS / CSP / セキュリティヘッダ

- [ ] CORS を実装する場合は preflight を含む基本ルールを整理する
- [ ] Content Security Policy を少なくとも制限要因として解釈できる余地を残す
- [ ] `X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy` などの扱いを整理する
- [ ] Referrer 送信ポリシーを制御できるようにする

### 12. iframe / 埋め込みコンテンツ

- [ ] iframe 相当を実装する場合は親子オリジン分離を維持する
- [ ] `sandbox` 属性に相当する制約の必要性を整理する
- [ ] 埋め込み文書のナビゲーション権限を制御する

### 13. 履歴・キャッシュ・状態管理

- [ ] キャッシュを実装する場合は認証付きレスポンスの保存条件を定義する
- [ ] 閲覧履歴、フォーム履歴、Cookie、ローカル状態の保存範囲を分離する
- [ ] プライベート利用モード相当が必要か検討する

### 14. 機密情報の表示とログ

- [x] URL に含まれる query や fragment の機密情報をログへ無制限に出さない
- [x] Authorization header、Cookie、CSRF token、個人情報をデバッグ出力からマスクする
- [x] 例外時にも機密情報をそのまま表示しない
- [ ] 外部 secret manager のコマンド文字列、vault item 名、field 名をどこまでログに残すか方針を決める
- [ ] password input へ流し込んだ値や import した token を履歴・最近使った値として再表示しない

### 15. クリックジャッキング・なりすまし・UI 安全性

- [x] TUI 上で実際の遷移先や送信先を分かる形で表示する
- [ ] ラベル表示文字列と実 URL が乖離している場合に確認しやすくする
- [ ] 危険なスキームや権限昇格操作は確認を挟む

### 16. DoS 耐性

- [ ] 巨大 HTML、深すぎる DOM、極端に長い属性値への上限を設ける
- [ ] CSS/JS の病的ケースで過剰に CPU を使わないようにする
- [x] 取得処理はキャンセルイベントで中断可能にしている
- [ ] レンダリング、パース、スクリプト実行も含めて全体をキャンセル可能にする
- [x] 取得層には 30 秒のタイムアウトがある
- [ ] レスポンスサイズ上限や段階別の上限を追加する

## 実装時の原則

- デフォルト deny を基本にする
- 明示許可が必要な機能は CLI/TUI から分かるようにする
- ローカルファイル、ネットワーク、JavaScript、フォーム送信は別々に許可できるようにする
- secret manager 連携は「外部コマンド実行」「入力補助」「送信」「永続化」を別々に許可できるようにする
- 「人間向け表示」と「AI 向け API」で同じ安全境界を共有する
- テストは正常系だけでなく、禁止されるべきケースを先に固定する
- `type="button"` や JS ハンドラ起点の操作は、HTML form submit と同じ成功条件で扱わない

## ドキュメント連携 TODO

- [x] README.md にセキュリティ方針の概要と `SECURITY.md` へのリンクを追加した
- [x] PLAN.md にセキュリティ実装フェーズまたは横断タスクを追加した
- [ ] JS / fetch / form / file access を拡張するたびに、この文書を更新する
