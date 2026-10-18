# DEVELOPMENT.md

このドキュメントは、`tweb` を開発・調査・保守するときの入口をまとめたものです。ユーザー向けの使い方は `README.md`、機能ごとの詳細方針は各 `docs/*.md` を参照してください。

## 開発ワークフロー

新規セッションでは、まず branch と worktree を作成します。

```bash
make create BRANCH=feature/example PYTHON=python3.12
```

作業後に worktree を削除:

```bash
make remove BRANCH=feature/example PYTHON=python3.12
```

マージ済み worktree をまとめて掃除:

```bash
make clean PYTHON=python3.12
```

- 既定の worktree パスはリポジトリ直下の `./wt-<branch>`
- 必要なら `PATHNAME=...` と `BASE=...` を指定できる
- 未マージでも強制的に消す場合は `FORCE=1` を使う
- `main` は保護対象で、`make clean` の削除対象にしない

## `uv run` とキャッシュ

Codex や sandbox 環境では `~/.cache/uv` の権限エラーを踏みやすいため、`uv run` が必要なコマンドは最初から一時ディレクトリへ逃がすのを基本にします。

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m unittest tests.test_cli
```

また、フルテストは `make test` で同じ一時キャッシュ設定つきで実行できます。

- `make clean` のように `uv` が不要な補助コマンドでは `PYTHON=python3.12` を優先する
- `.git` 配下への書き込み失敗や ref lock 失敗は、repo 不具合ではなく環境権限の問題として扱う

## よく使う開発コマンド

通常表示:

```bash
tw https://example.com --mode text
tw ./page.html --mode text
tw https://example.com/article --mode text --main-only
```

`--main-only` は祖先を含む表示状態を確認し、表示可能な `<main>`、`<article>` を優先します。該当する要素がない場合は、表示可能な `div` / `section` から本文を推定します。候補の文字数・段落数・見出し数・リンク数は、子から親への一度の走査で集計します。

DOM / DOM-AI:

```bash
tw https://example.com --mode dom
tw https://example.com --mode dom-ai
```

TUI:

```bash
tw https://example.com
```

追加 script 適用:

```bash
tw https://example.com --script "document.querySelector('h1').textContent = 'CLI Title';" --mode text
tw https://example.com --script-file ./patch.js --mode text
```

Cookie / browser-render:

```bash
tw https://example.com/private --cookie-file cookies.txt
tw https://example.com/private --cookie-from-browser firefox --cookie-domain example.com
tw https://example.com/app --browser-render auto
tw https://example.com/app --browser-render always
```

デバッグログ:

```bash
tw https://example.com --debug
tw https://example.com --debug-log /tmp/tweb-debug.log
```

## テスト

まずは対象に近い unittest を絞って回します。

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m unittest tests.test_cli tests.test_document_api
```

フルテスト:

```bash
make test
```

代表的なテスト面:

- `tests/test_cli.py`: CLI オプションと設定ファイル
- `tests/test_document_api.py`: タイトル、本文、リンク、API 振る舞い。note topic の runtime probe テストは Python 側の追加取得をモックし、実サイトの応答に依存させない
- `tests/test_fetcher.py`: 取得層、Cookie、session
- `tests/test_normal_renderer.py`: 通常表示レンダラ
- `tests/test_dom_renderer.py`: DOM / DOM-AI 表示
- `tests/test_js_runtime.py`: QuickJS runtime と DOM bridge
- `tests/test_tui.py`: Textual TUI

## 監査と性能計測

QuickJS と browser-render の差分監査は `tweb.audit` で行います。

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m tweb.audit
```

JSON 出力:

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m tweb.audit --json > /tmp/tweb-audit.json
```

一部の target だけ回す:

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m tweb.audit --tag en
```

- canonical manifest は `tweb/data/quickjs_audit_sites.json`
- 実行履歴と判断の台帳は `docs/performance.md`
- cohort 状態を変えたら manifest と `docs/performance.md` を同じ変更で更新する

## リポジトリ構成

主要なコード:

- `tweb/cli.py`: `tw` CLI 入口
- `tweb/fetcher.py`: URL / ローカルファイル取得、session / Cookie 初期化
- `tweb/parser.py`: HTML パース
- `tweb/dom.py`: DOM 抽象
- `tweb/css.py`: CSS 解釈
- `tweb/js_runtime.py`: QuickJS runtime の公開入口
- `tweb/js_runtime_bridge.py`: QuickJS 側へ注入する DOM / browser bridge
- `tweb/api.py`: `TWebDocument` と BeautifulSoup 風 API
- `tweb/runtime_data.py`: runtime data / hydration collector
- `tweb/site_specific.py`: generic collector で吸収しきれない残差
- `tweb/tui.py`: Textual TUI
- `tweb/renderers/normal.py`: 通常表示レンダラ
- `tweb/renderers/dom.py`: DOM / DOM-AI レンダラ

## ドキュメントの役割分担

- `README.md`: ユーザー向けの使い方
- `docs/DEVELOPMENT.md`: 開発フロー、コマンド、構成
- `docs/API.md`: Python API
- `docs/DOM.md`: DOM / DOM-AI の方針
- `docs/CSS.md`: CSS 解釈の方針
- `docs/JS.md`: QuickJS、hydration、browser-render
- `docs/TUI.md`: TUI 操作仕様
- `docs/SECURITY.md`: セキュリティ方針と TODO
- `docs/PLAN.md`: 段階的な開発計画
- `docs/performance.md`: 品質監査と性能記録
