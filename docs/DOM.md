# DOM.md

## 目的

DOM 表示は 2 系統に分ける。

- `dom`: 人間がページ構造をざっと確認するための要約表示
- `dom-ai`: AI が操作対象を特定するための詳細表示

この分離を前提にしないと、1 つの出力形式が「見やすさ」と「操作精度」のどちらも中途半端になる。

## 基本方針

AI による操作を意図した DOM 表示では、見やすさよりも識別可能性と再現性を優先する。

そのため `dom-ai` では以下を重視する。

- 安定したノード ID を出す
- 親子関係を機械的に追える形式にする
- 属性を省略しない
- テキストを要約しない
- 人間向けの簡略表現を優先しない

一方で `dom` は人間向けの要約表示として維持する。

## `dom` の役割

- 木構造の概観を素早く把握する
- 主要属性とテキスト要約を確認する
- 大きなページでも読み切れるようにする
- `script` / `style` は既定で省略してよい

## `dom-ai` の役割

- AI がクリック候補、入力対象、リンク対象、ラベル対応を特定する
- 後段の操作 API や TUI 操作と接続しやすい出力を提供する
- ページ再解析時にどのノードを見ていたかを追跡しやすくする

## `dom-ai` の出力要件

- 各ノードに一意なノード ID を付ける
- 各ノードに親ノード ID を付ける
- 要素ノードはタグ名と属性一覧を完全出力する
- テキストノードは本文を切り詰めずに出す
- 深さ制限を使う場合も、打ち切られたことを明示する
- `script` / `style` は既定で省略可能だが、省略されたことは出力する

## 現状の接続点

- Python API では `snapshot().dom_nodes` が `dom-ai` と同じ方向の情報を持つ
- `AgentPageSnapshot.node()` / `find_nodes()` で、`node_id`・タグ名・属性・可視状態・親 ID を使った read-only 検索ができる
- link と form control も `snapshot.link()` / `find_links()` / `control()` / `find_controls()` で同じ snapshot から辿れる
- form control には `supported_actions` が載るので、read-only な snapshot だけで次の操作候補を決められる

## API 層の分担

- read: `snapshot()` は page の現状態を読むだけで、副作用を起こさない
- preflight: `debug_control()` / `debug_controls()` は submit 先、click hint、navigation target を確認するために使う
- mutate: `agent_actions().invoke()` は実際の変更要求を受けるが、失敗時も `status` / `reason` / `available_actions` で構造化結果を返す

この 3 層は同じ `control_id` を共有するが、権限境界は共有しない。AI はまず `snapshot()` と `debug_control()` で候補を絞り、その後に mutate を呼ぶ前提にする。

## 今後の拡張

- CSS 適用後の可視状態をノードへさらに増やす
- JS 実行後の DOM 差分を扱えるようにする
- TUI の選択対象と `dom-ai` のノード ID を対応付ける
- JS ランタイム側のノード参照と `dom-ai` のノード識別子を対応付ける
