# tweb

`tweb` は、Web ページをテキストとして読みやすく表示しつつ、必要に応じて DOM や JavaScript 実行結果も確認できるテキストベースのブラウザです。CLI は `tw` に一本化し、既定では TUI として起動します。

AI やスクリプトから扱いやすい Python API も用意しており、本文抽出、リンク列挙、DOM 調査、フォームや Cookie を使った取得まで同じ基盤で扱えます。

## できること

- 通常表示で本文を読みやすいテキストとして確認する
- `dom` / `dom-ai` でページ構造を調べる
- `tw` でキーボード中心の TUI ブラウザとして使う
- `tw --mode text|dom|dom-ai` で同じコマンドから通常表示や DOM 表示へ切り替える
- Cookie を付けてページを開く
- JavaScript 実行後の内容を表示する
- QuickJS だけでは崩れるページで browser-render fallback を使う
- Python ライブラリとして本文・リンク・DOM を扱う

## インストール

Python 3.12 以上を前提にしています。

```bash
uv tool install --from . tweb
```

または:

```bash
python3 -m pip install .
```

どちらの方法でも `tw` が入ります。

## 使い始める

`example.com` のように URL scheme を省略した入力は `http://example.com` として扱います。ローカルファイルは `./page.html` や `/tmp/sample.html` のようにパスで渡せます。引数を省略した場合は welcome ページを TUI で表示します。

TUI:

```bash
tw https://example.com
tw ./page.html
```

通常表示:

```bash
tw https://example.com --mode text
tw https://example.com/article --mode text --main-only
```

DOM 表示:

```bash
tw https://example.com --mode dom
```

AI 向け詳細 DOM:

```bash
tw https://example.com --mode dom-ai
```

`--width` を省略した場合は現在のターミナル幅を使い、取得できない場合は `80` を使います。`--link-style` の既定値は `none` です。
`--main-only` を付けると `text` モードでは表示可能な `<main>`、`<article>` を優先し、該当する要素がないページでは本文らしいコンテナを推定して描画します。非表示の祖先内や `template` 内の要素は候補に含めません。候補が見つからない場合は `<body>` 全体に戻ります。

## よく使うオプション

Cookie を付ける:

```bash
tw https://example.com/private --cookie "sessionid=abc123"
tw https://example.com/private --cookie-file cookies.txt
tw https://example.com/private --cookie-from-browser firefox --cookie-domain example.com
tw https://example.com/private --cookie-from-browser zen --cookie-domain example.com
```

JavaScript を追加で適用する:

```bash
tw https://example.com --script "document.body.prepend('hello')"
tw https://example.com --script-file ./patch.js
```

browser-render fallback を切り替える:

```bash
tw https://example.com/app --browser-render never
tw https://example.com/app --browser-render auto
tw https://example.com/app --browser-render always
```

デバッグログを出す:

```bash
tw https://example.com --debug
tw https://example.com --debug-log /tmp/tweb-debug.log
```

`--debug` は既定では実行ディレクトリの `debug.log` に出力します。`--debug-log` で出力先を変更でき、このオプション単体でも debug logging を有効化します。認証系の値はログ出力時にマスクされます。

## 設定ファイル

`tw` は起動時に `~/.config/tw/config.yml` を読めます。現在は `headers.User-Agent` と top-level の `user_agent` をサポートし、HTTP/HTTPS の既定ヘッダーへ反映します。

```yaml
headers:
  User-Agent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
```

または:

```yaml
user_agent: "My custom agent"
```

一時的に別ファイルを使う場合は `TW_CONFIG_PATH=/path/to/config.yml` を指定します。

## Python API

最小例:

```python
from tweb import TWebDocument, fetch_resource, parse_document

resource = fetch_resource("https://example.com")
document = TWebDocument(parse_document(resource))

print(document.title)
print(document.body_text())
for link in document.links():
  print(link.text, link.href)
```

API の詳細は [docs/API.md](docs/API.md) を参照してください。

## 詳細ドキュメント

- [docs/TUI.md](docs/TUI.md): TUI の操作仕様とキーバインド
- [docs/API.md](docs/API.md): Python ライブラリ API
- [docs/DOM.md](docs/DOM.md): `dom` / `dom-ai` の表示方針
- [docs/CSS.md](docs/CSS.md): CSS 解釈の方針
- [docs/JS.md](docs/JS.md): JavaScript 実行と browser-render fallback
- [docs/SECURITY.md](docs/SECURITY.md): セキュリティ方針と未実装項目
- [docs/PLAN.md](docs/PLAN.md): 開発計画
- [docs/performance.md](docs/performance.md): 品質監査と性能計測の記録
