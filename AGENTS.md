# AGENTS.md

## Editing Rules

- このドキュメントと関連ドキュメントは常に最新の状況を反映して更新する
- ユーザーが加えた未コミット変更を勝手に戻さない
- `uv run` は sandbox だと `~/.cache/uv` 権限で失敗しやすい。Codex で同系統のコマンドを実行する必要がある場合は、同じ失敗を繰り返さず最初から権限付き実行に切り替える
- sandbox / リモート実行で `uv run` を権限なしで動かす必要がある場合は、`UV_CACHE_DIR` と `PYTHONPYCACHEPREFIX` を `/private/tmp/...` に逃がして既知の cache 権限エラーを避ける
- クラッシュや segfault のような「落ちる」問題を修正するときは、再現時の入力・直前の処理段階・例外内容を後から追える debug log も併せて追加し、次回の調査をしやすくする
- audit / performance rerun で cohort 状態が変わったら、`performance.md` の該当行だけでなく `tweb/data/quickjs_audit_sites.json` の `active_site_ids` と cohort 説明も同じ変更で最新化する。active 表と manifest のどちらか一方だけ古い状態を残さない

## Repository Notes

- メインはPython3を使うこと
- JS処理部分はquick.jsを使う
- TUI は Textual を使う
- インデントは2スペースでタブは使わない
- キーボード操作は macOS の標準テキスト編集に近い Emacs 準拠を基本方針にする
- HTTP/HTTPS アクセスは極力既存ライブラリを使い、標準実装は `requests` を優先する
- 特定サイト向けに HTML や API を補完する fetch は入れず、取得層は汎用実装を保つ
- サイト独自のコードは最小に留め、まず汎用の runtime / DOM / hydration / interaction 側で吸収できないかを優先して検討する
- やむを得ずサイト独自のコードを追加した場合でも、そのコードは Chrome fallback の恒久代替ではなく QuickJS 側で読める状態まで持っていくことをゴールにする

## Related Documents

- README.md: アプリの使い方、目的など
- docs/DEVELOPMENT.md: 開発フロー、テスト、主要コマンド
- docs/API.md: Python ライブラリ API の使い方
- docs/PLAN.md: README.md を実装に落とし込むための段階的な開発計画
- docs/performance.md: 品質監査、性能計測、canonical audit site、実行履歴の台帳
- docs/DOM.md: DOM 表示を人間向け要約と AI 向け詳細に分ける方針
- docs/CSS.md: テキストベースで CSS の意味をどう反映するかの方針
- docs/JS.md: JavaScript の実装状況と実装方針
- docs/TUI.md: Textual ベース TUI の操作仕様
- docs/SECURITY.md: ブラウザとして一般的に必要なセキュリティ機能の TODO 整理
