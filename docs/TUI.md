# TUI.md

## 目的

TUI モードの操作仕様と表示方針をまとめる。

## 現在の実装

- TUI 基盤は `Textual`
- `tw <target>` で起動する
- `tw <target> --mode tui` と明示しても同じ挙動になる
- `--width` を省略した場合は現在のターミナル横幅を使い、取得できない場合は `80` を使う
- 本文のみを表示する
- `x` で通常表示と DOM 要約表示をその場で切り替えられる
- 複数 pane として描画された block 上では `v` で他 pane を取り除いて現在 pane を広い表示幅で再描画し、もう一度 `v` で元に戻せる
- `v` で focused pane 表示に入ったあとは、その pane 内に段落空行や入れ子の 2 カラムがあっても、表示全体を 1 つの block として扱う
- pane が検出できるページでは、Shift-Arrow 用の block も pane 判定を優先し、同じ pane に属する後続本文は 1 つの block としてまとめる
- single-column の連続本文は段落間の空行では block を増やさず、Shift-Arrow では主に grid / pane 境界だけを block 境界として扱う
- `v` は現在行が直接 multi-pane 上にない場合でも、その行を含む本文 subtree を逆引きでき、かつ上部メニューのような sibling chrome を落とせるときは本文側だけを focused 表示にする
- 本文中の可視文字だけでなく、その行の右側に残っている表示空白にも 1 文字カーソルを置ける
- カーソル位置は 1 文字だけ背景色を変えて表示する
- リンクは通常時でも下線付きで表示し、クリック可能だと分かるようにする
- form control のトークンや label も通常時から強調表示し、`Enter` で操作できる要素だと分かるようにする
- 通常表示の link / control span は renderer が返す metadata をそのまま使い、full-page / focused-pane / subtree で同じ clickable 範囲を保つ
- カーソルがリンクや checkbox/label ベースのトグル上にあるときは、その 1 文字を青背景で表示する
- ステータス行には現在位置を `line X col Y` で表示する
- カーソルがリンク上にあるときは、ステータス行にリンク先も表示する
- カーソルが submit control 上にあるときは、ステータス行に `GET` / `POST`、送信先 URL、`enctype` も表示する
- カーソルが `type="button"` 上にあるときは、ステータス行に現在の `button click policy` も表示する
- ページ遷移や form submit による取得中は、ステータス行に `Connecting ...` `Downloading ...` `Parsing ...` `Rendering ...` など現在フェーズを表示し、`(N s)` 相当の経過秒数を添えて末尾に `Esc to cancel` を付ける。リンク上では raw `href` ではなく実際に解決される遷移先を表示する
- `checkbox + label` ベースのメニューや dropdown は `Enter` で開閉できる
- 最小 form 対応として、text input / textarea はポップアップ編集、password input はマスク付きの単一行ポップアップ編集、select は切り替え、radio / checkbox は選択、submit button は GET/POST submit を扱える
- `type="button"` の button は submit しない。TUI から click を実行し、`onclick` や `addEventListener("click", ...)` の結果を `dom_updated` / `navigation_requested` / `network_requested` / `javascript_required` に分類して表示する
- `--button-click-policy off|dom-only|network` で JS 駆動 button の許可範囲を切り替える。TUI の既定値は `network` で、通常の対話ブラウズでは通信や遷移も許可する。`dom-only` では DOM 更新だけを許し、fetch / XHR / `location` 変更は block して結果だけ可視化する
- `--debug-block-colors` を付けると、検出した render block ごとに背景色を変えて block の範囲を追いやすくし、pane 末尾の表示空白まで同じ背景色で塗る
- この policy が必要なのは、submit は送信先 URL と method を事前に計算できる一方、JS 駆動 button は DOM 更新だけで終わる場合もあれば、裏で fetch / XHR / `location` 変更を起こす場合もあり、同じ `Enter` でも副作用の強さが一定でないためである
- 編集中はポップアップが開き、本文タイトルも `Editing: ...` に切り替わる
- 編集ポップアップは text 系 input / textarea を共通の操作感で扱い、password input だけは表示をマスクした単一行入力にする
- `/` でページ内サーチのポップアップを開き、Enter で次の一致箇所へジャンプできる
- 検索語が入っている間は `n` / `p` で次 / 前の一致箇所へ移動できる
- `o` で URL またはローカルパスを入力するポップアップを開き、その場で別ページへ移動できる
- `h` で表示履歴のポップアップを開き、過去に表示した URL / path を一覧から選んでその履歴位置へ戻れる。履歴一覧の縦棒左側には、取得できた場合はページ title を優先表示する
- 表示履歴は `~/.config/tw/history.json` に 1 行 1 エントリで保存し、次回起動時にも再利用する。同じ URL / path を再訪した場合は古い履歴を消し、最新位置だけを残す。`tw` が同梱する welcome page は履歴に入れない
- `c` で現在表示中のレンダリング結果を macOS のコピーバッファへ送れる
- `s` で現在表示中のレンダリング結果を `.txt` として保存できる
- `c` / `s` で扱う内容はその時点の表示状態そのものを使い、`x` で DOM 要約に切り替えていれば DOM 要約を、`v` で他 pane を隠していればその pane だけを対象にする
- `?` でショートカットヘルプを開き、`Esc` または `?` で閉じる
- リンク先の取得はバックグラウンド worker で行い、読み込み中も UI は固まらない
- 端末の横幅が変わったときの再描画はバックグラウンド worker で行い、新しい表示ができるまで直前の画面を残す。再描画中のステータスは `Rendering ... (Ns) Esc to cancel` になる

## キーバインド

- `Right` / `Ctrl-F`: 1 文字右へ移動
- `Left` / `Ctrl-B`: 1 文字左へ移動
- `Down` / `Ctrl-N`: 1 行下へ移動
- `Up` / `Ctrl-P`: 1 行上へ移動
- `Shift-Right` / `Shift-Down`: 次のブロック先頭へ移動する
- `Shift-Left` / `Shift-Up`: 前のブロック先頭へ移動する
- `Home` / `Ctrl-A`: 行頭へ移動
- `End` / `Ctrl-E`: 行末へ移動
- `PageDown` / `Ctrl-V`: 1 ページ下へ進み、カーソルは新しい画面の左上へ移動する
- `PageUp` / `Alt-V`: 1 ページ上へ戻り、カーソルは新しい画面の左上へ移動する
  - 端末によっては `Alt-V` が `Esc` の後に `v` として送られるため、その入力も受け付ける
  - iTerm2 などで `Option-v` が文字 `√` として送られる場合も受け付ける
- `Tab`: 次のリンクまたは control 先頭へジャンプ
- `Shift-Tab`: 前のリンクまたは control 先頭へジャンプ
- `/`: ページ内サーチのポップアップを開き、Enter で現在位置の次の一致箇所へ移動する。末尾まで見つからなければ先頭へ wrap する
- `n`: 直前の検索語で現在位置の次の一致箇所へ移動する。末尾まで見つからなければ先頭へ wrap する
- `p`: 直前の検索語で現在位置の前の一致箇所へ移動する。先頭まで見つからなければ末尾へ wrap する
- `o`: URL またはローカルパスの入力ポップアップを開き、Enter で開く。URL scheme を省略したホスト名は `http://` として扱う
- `h`: 表示履歴のポップアップを開く。`Up` / `Down` で選択し、`Enter` でその履歴位置へ移動する。ここでの履歴は `b` / `f` の戻る・進むスタックとは別で、これまで表示に成功したページの記録を新しい順に並べる。`*` が現在位置を示し、各行は `title | URL/path` を優先し、title が無い場合は従来どおり末尾の path 要素を左側に出す。履歴が画面高を超える場合は選択行に追従して一覧をスクロールする。内容は `~/.config/tw/history.json` から復元し、更新も同じファイルへ保存する
- `c`: 現在表示中のレンダリング結果を macOS の `pbcopy` へ送り、コピーバッファへ入れる
- `s`: 保存先パスの入力ポップアップを開き、Enter で現在表示中のレンダリング結果を UTF-8 のテキストとして保存する
- `Esc` のあとに `<`: ページトップへ移動
- `Esc` のあとに `>`: ページ最下段へ移動
- `Enter`: リンク上なら遷移し、checkbox/label ベースのトグル上なら開閉する。text input / textarea では編集ポップアップを開き、select では次候補へ切り替え、radio / checkbox では選択、submit button では GET/POST submit を行い、`type="button"` では DOM 更新までの JS click を実行する
- `x`: 通常表示と DOM 要約表示をトグルする
- `v`: 複数 pane として描画された block では他 pane を取り除いて現在 pane を広い表示幅で再描画し、もう一度押すと元に戻す。focused pane 表示中は Shift-Arrow の block 移動対象もその表示全体を 1 block として扱う
- `r`: 現在表示中の実効レンダラをトグルして再読み込みする。QuickJS 表示中なら Chrome 強制へ、Chrome fallback 表示中なら QuickJS 強制へ切り替える。`--browser-render auto` で起動していても、表示実態に合わせて 1 回で反転する
- 編集ポップアップの `Enter`: 単一行 input では保存し、`textarea` では改行を入力する
- 編集ポップアップの `Ctrl-S`: 保存
- 編集ポップアップの `Esc` / `Ctrl-G`: キャンセル
- 編集ポップアップの `Ctrl-C`: アプリ終了
- `Esc`: 読み込み中のリンク先取得、端末 resize 後の再描画、`rendering more...` の追加レンダリングをキャンセル
- `rendering more...` 中に通常の移動・リンク移動・表示切替・検索などのキー操作を始めたら、追加レンダリングはその時点で打ち切り、見えている partial page をそのまま操作対象にする。入力を優先し、あとから full render が割り込んでカーソル位置や表示内容が変わらないようにする
- `b`: 戻る。`h` の一覧とは別管理のナビゲーション履歴を 1 つ戻る
- `f`: 進む。`h` の一覧とは別管理のナビゲーション履歴を 1 つ進む
- `?`: ショートカットヘルプを表示する
- `Ctrl-C`: 終了

## 方針

- TUI の本文レンダリングは、同じ幅を与えた `text mode --link-style none` と常に整合する状態を保つ
- interactive span の start/end は renderer metadata を正本とし、TUI 側で plain text 再検索 fallback は持たない
- overlay link、CSS hidden anchor text、`<label>` / `aria-labelledby` 由来の control hit area も renderer metadata で表現し、`collect_visible_links()` と clickable 判定で同じ span 情報を共有する
- リンク一覧用の別ペインは持たず、本文とステータス行だけで現在位置を示す
- ページ内サーチは現在表示中のレンダリング結果を対象にし、通常表示と DOM 要約表示のどちらでも同じように動かす
- キーバインドは macOS の標準テキスト編集に近い Emacs 準拠を優先する
- TUI 詳細は README ではなくこのファイルに集約する

## 画像表示の抑制

`tw URL --no-images` で起動すると、通常表示で画像の `[altテキスト]` / `[image]` を省略します。再描画、ページ移動、ペインの拡大表示でも設定を維持します。`<figcaption>` のキャプションも省略します。本文中の文字のあるリンクは残し、画像だけのリンクは表示しません。DOM 表示では画像要素を引き続き検査できます。
