# CSS.md

## 目的

このアプリでの CSS 対応は、GUI ブラウザの見た目を完全再現するためではなく、テキストベースの読解と AI 操作に必要な意味だけを反映するために行う。

言い換えると、CSS は「ピクセルの再現」ではなく「可視性、強調、意味の補助情報」を取り込むために使う。

## 基本方針

- レイアウトの完全再現は目指さない
- テキスト出力に意味のある差だけを反映する
- AI が誤って不可視要素を操作しないよう、可視状態を優先して扱う
- 通常モードと `dom-ai` の両方で、CSS の解釈結果を使い回せる形にする

## 何を再現するか

Phase 6 では以下を優先する。

### 1. 可視性

- `display: none`
- `visibility: hidden`
- `hidden` 属性

これらは最優先で扱う。通常モードでは非表示要素を出さない。`dom-ai` では、必要ならノード自体は残しつつ `visible=false` のような状態を後で付与できる形にする。

### 2. テキスト強調

- `font-weight: bold`
- `font-style: italic`
- `text-decoration: underline`
- `text-decoration: line-through`

これらはテキストベース表現に落としやすい。レンダラ API では次のような方針で通常モードに反映する。

- 太字: ターミナルの ANSI 太字
- 斜体: `_text_`
- 下線: 明示マーカーまたは属性情報
- 打ち消し: `~~text~~`

見出しも `#` 記法に加えて本文部分を太字で出す。ただし、見出しを直接含むリスト項目では `#` を重ねず、リスト記号と太字で示す。番号付きリストでは通常項目・見出し付き項目・入れ子で共通の番号処理を使い、`start`・`reversed`・`li[value]` を反映する。本文は空行と番号幅に応じた字下げで分ける。通常モードでは強調記法を増やしすぎると可読性を下げるため、装飾は限定的に行う。CLI の `--mode text` はパイプ・保存・他ツールからの利用で制御文字を混ぜないようプレーンテキストにし、TUI は表示層で装飾する。

### 3. ブロック性

- `display: block`
- `display: inline`
- `display: inline-block`
- `display: list-item`
- `display: flex`
- `display: inline-flex`
- `flex-direction: column`
- `flex`
- `flex-basis`
- `display: grid`
- `grid-template-columns`
- `width`

これは厳密なレイアウト再現ではなく、改行や箇条書き解釈の補助に使う。

`display:flex` は通常モードでは「横並びコンテナ」として扱い、直接子要素を同じ文脈へ畳み込む。`flex-direction: column` のときだけ通常のブロック積みを維持する。`inline-flex` はインライン寄りの扱いにする。

ただし、block 系の直接子要素がちょうど 2 つで、各子要素の `width` / `flex-basis` / `flex` から幅比を取れる場合は、通常モードでも左右 2 カラムとして近似表示してよい。Wikipedia の `#mp-left` / `#mp-right` のような main page レイアウトはこの近似対象に含める。

`display:grid` は完全再現しないが、2 カラムの `grid-template-columns` を持つ単純なコンテナについては、通常モードで左右カラムとして近似表示してよい。

## 何を再現しないか

少なくとも初期段階では、以下は再現対象にしない。

- 位置合わせ
  - `position`
  - `top`
  - `left`
  - `z-index`
- ピクセル寸法
  - `width`
  - `height`
  - `margin`
  - `padding`
- 複雑なレイアウト
  - 3 カラム以上の Grid
  - Float
  - Multi-column
- 色そのものの再現
  - `color`
  - `background`
  - `border`
- アニメーション
  - `transition`
  - `animation`

これらは GUI ブラウザで重要でも、テキストベース出力にそのまま持ち込んでも意味が薄い。

## 適用順序

CSS 解釈は次の順序で適用する。

1. HTML 属性
   - `hidden`
2. 外部 CSS / 埋め込み `<style>`
   - セレクタごとの詳細度を比較する
   - 詳細度が同じなら後勝ちにする
3. `style` 属性

Phase 6 では `!important` や継承の完全再現までは行わず、通常モードと `dom-ai` で共通利用するための最小カスケードにとどめる。

## `@media` の扱い

テキストベース環境でも、`@media` は「どの CSS ルールを有効にするか」を決める条件として扱う。

### 最初に対応するもの

- `@media screen`
- `@media all`
- `@media print`
- `@media (max-width: ...px)`
- `@media (min-width: ...px)`

初期方針としては次の通りにする。

- `screen` は既定で真
- `all` は常に真
- `print` は既定で偽

つまり通常の閲覧モードでは、`@media screen` は有効なものとして扱う。

### 幅条件の評価

`max-width` / `min-width` は、実ブラウザのピクセル幅ではなく、ターミナル幅から導出した仮想 viewport 幅で評価する。

基準は次の通りにする。

- TUI 実行時は現在の terminal columns を使う
- CLI では `--width` があればそれを優先する
- それ以外は既定幅を使う

内部では `viewport_width_px` を持ち、まずは次の近似で十分とする。

- `1 column = 8px`

例:

- 80 columns -> `640px`
- 100 columns -> `800px`

この仮想幅を使って、たとえば `@media (max-width: 768px)` を評価する。

### この設計の意図

- ターミナル幅を変えると media query の判定も変わる
- TUI のリサイズに追従しやすい
- CLI の `--width` 指定で再現性を持たせられる
- CSS の一般的なブレークポイントをある程度そのまま使える

### 制限

- これは本当の CSS ピクセルではなく近似値
- フォント差や全角文字幅までは正確に表現しない
- 目的はレイアウト完全再現ではなく、どのルールを有効にするかの判定である

## 通常モードへの反映

通常モードでは以下を優先する。

- 非表示要素を出さない
- 強調表現を必要最小限で反映する
- ブロック要素の改行規則に CSS の `display` を少しだけ反映する
- `display:flex` / `inline-flex` は通常は直接子要素の並び順にだけ反映し、完全な配置や伸縮計算までは再現しない

通常モードは「読むための整形済みテキスト」なので、CSS 情報をそのまま大量に露出しない。

## `dom-ai` への反映

`dom-ai` では、CSS の結果を操作判断に使えることが重要である。

将来的には各ノードに次のような情報を付与する前提で考える。

- `visible=true/false`
- `display=block|inline|none`
- `flex_direction=row|column`
- `font_weight=bold`
- `font_style=italic`
- `text_decoration=underline|line-through`

ここでは「見た目の装飾」よりも、「そのノードが操作対象かどうか」を優先する。

## 実装方針

Phase 6 では以下の順で進める。

1. `style` 属性のパーサを作る
2. `hidden` / `display:none` / `visibility:hidden` を通常モードへ反映する
3. 同じ判定を `dom-ai` にも出せる形へ整理する
4. 埋め込み `<style>` の最小解釈を追加する
5. 外部 CSS を読み、`Cache-Control` / `ETag` / `Last-Modified` を見た file cache で再利用する

現在は通常の `rel=stylesheet` に加えて `rel=preload as=style` も外部 stylesheet として先読みし、link の load callback 前から style 判定へ反映する。`aria-hidden=true` は `hidden` / `display:none` / `visibility:hidden` と同じ visible subtree 判定へ統合し、cheap probe と最終 `StyleContext` で結果がずれないようにする。

現時点の最小セレクタ方針:

- 単一セレクタ
  - `tag`
  - `.class`
  - `#id`
  - `[attr]`
  - `[attr=value]`
  - `[attr=value][other=value]`
- 結合子
  - `.wrapper .item`
  - `figure figcaption`
- `main > p`
- 疑似クラス
  - `:root`

一方で、次はまだ後回しにする。

- `+`
- `~`
- `:not(...)`
- 疑似要素

### 詳細度の最小方針

Phase 6 では、次の順で詳細度を比較する。

1. inline style
2. `#id`
3. `.class` / `[attr]` / `:root`
4. `tag`

同じ詳細度なら後に現れたルールを優先する。これにより、基本的な CSS の優先順位は通常モードと `dom-ai` の両方で一貫して解釈できる。

## 完了条件

Phase 6 の最低ラインは次の通り。

- `hidden`、`display:none`、`visibility:hidden` が通常モードで効く
- `dom-ai` から可視状態を確認できる
- 強調系プロパティの一部がテキスト表現または属性情報として利用できる

## 非目標

- Chrome や Safari と同水準の CSS レンダリング
- CSSOM 完全互換
- レスポンシブレイアウト再現
- ピクセル単位の配置再現
