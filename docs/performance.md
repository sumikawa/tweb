# performance.md

このドキュメントは、QuickJS 品質改善と性能改善の実行ログを 1 箇所へ集約するための台帳である。目的は 3 つある。

- どの site を canonical audit 対象として持っているかを固定する
- canonical cohort の各 site について、最新の分類と主要な論点をすぐ見返せるようにする
- 品質改善と性能改善を同じ文脈で追い、次回の着手点を早く決められるようにする

## 使い方 / Update Rules

- 新しい site を定常監査へ入れるときは、まず `tweb/data/quickjs_audit_sites.json` に追加し、このファイルの cohort 一覧にも反映する
- cohort の site 一覧を変えたら、このファイルの cohort 表も同じ commit で更新する
- 既存 site を再実行したときは、`Unified Cohort` の該当行を最新の classification / quality notes / performance notes / observed on に更新する
- rerun の結果、focused cohort の対象が変わったら `Unified Cohort` の active/reserve 配置と `tweb/data/quickjs_audit_sites.json` の `active_site_ids` を同じ変更で更新する。table と manifest の片方だけを先行させない
- 同じ site を再度使うときは、まず `Unified Cohort` の `quality notes` / `performance notes` と関連 section を見て、既知の論点と直近の観測値を引き継ぐ
- 性能改善を branch 上で試しただけで merge していない場合も、その旨を明記して残す
- 実測値は揺れるので、1 回の数字を絶対値として扱わず、「対象」「コマンド」「観測したボトルネック」をセットで残す
- captcha / challenge / anti-bot interstitial を要求する page は、QuickJS 品質改善や性能改善の canonical benchmark から外し、このファイルの「Skipped Targets」に理由つきで残す
- captcha / challenge 理由で外した site は、manifest から消すだけで終わらせず、必ず「Skipped Targets」に追加する
- 速度改善が synthetic にしか効いていない場合は、その旨を必ず書く
- live site で数字が悪化したときは、即 revert する前に「どの phase が増えたか」を `javascript_debug()` で残す
- link 比較は control と同様に visible 要素だけを数える。responsive menu や modal 内の hidden link 数を本文欠落の根拠にしない
- 別 registrable domain の script は、同一hostの stylesheet と2段以上のpath prefixを共有し、かつ初期HTMLに明示された正確なURLだけを first-party app asset として許可する。CDN host全体や実行時に追加された未知のURLは許可しない

## Classification の読み方

- `match`: title、本文、link、入力 control、DOM が Chrome と十分近い
- `minor_gap`: 主要本文には到達しているが、本文量、link、control、DOM の一部に小さな不足または差が残る
- `major_gap`: 可視本文や主要 UI が大きく欠落し、Chrome と同等の利用可能な内容へ到達していない
- `quickjs_error`: QuickJS 側の実行が例外、crash、timeout などで比較可能な結果を返せない
- `challenge_branch`: challenge / captcha / interstitial に到達しており、通常本文の品質比較になっていない
- `alternate_content_branch`: QuickJS と Chrome が異なる表示 branch に到達したが、QuickJS 側は欠落しているのではなく、Chrome より豊富な branch、または本文量・link・control・DOM coverage が同等な別 branch を回収している

`alternate_content_branch` は成功・失敗の中間という意味ではない。QuickJS 側が carousel の全 slide、collapsed section、別の hydration branch などを保持し、Chrome が active slide や現在表示中の section だけを返す場合、両者の本文 similarity は下がる。また transport/search page では、QuickJS が route UI、Chrome が current discovery feed のように、同程度の情報量と構造を持つ別 branch に分かれることがある。QuickJS 側の情報量または coverage が十分なら、これを `minor_gap` / `major_gap` として欠落修正の対象にはしない。一方でChromeと同じ表示状態ではないため、完全一致の `match` とも分けて記録する。

現在の監査実装では、QuickJS の可視本文が十分長く、Chrome比でvisible linkが極端に少なくないことを前提に、可視本文がChromeの約1.5倍以上、または長い本文とより多いlinkを持つ場合を richer branch の候補とする。加えて本文量・link・control・DOM coverage が同等で本文 similarity だけが低い場合も、locale 差でなければ comparable alternate branch とする。Chrome 側だけ同じ card / accessibility 文言を反復する場合は、QuickJS が Chrome の unique token を98%以上保持し、visible link・control・DOM coverage も十分なときに限り重複差として `match` にできる。title・本文・link・control・DOMがほぼ一致する場合は、過剰に `alternate_content_branch` へ倒さず `match` とする。代表例は `jica-home` の全carousel slide保持、`soumu-home` / `kunaicho-home` / `digital-home` のricher app mount、`nta-home` の別navigation branchである。

## Skip Policy

### captcha / challenge pages

以下に当てはまる page は、原則として canonical audit target に入れない。

- reCAPTCHA や画像認証の突破を前提にしないと本文へ到達できない
- raw fetch か QuickJS 実行のどちらかで、本文の代わりに challenge / anti-bot / interstitial を高頻度で返す
- Chrome forced benchmark を使っても、QuickJS の汎用改善ではなく bot 判定の揺れしか見えない
- login wall や country gate と同様に、generic runtime / DOM / hydration / interaction 改善の効果測定に向かない

この種の page は「直す対象」ではなく「監査対象から外す対象」として扱う。必要なら audit 実装側では `challenge_branch` として記録するが、定常比較の canonical cohort には残さない。

### 例外

- 既に cohort に入っている site が後から challenge を返すようになった場合は、まず `Unified Cohort` の該当行と `Skipped Targets` にその事実を書く
- challenge が一時的か恒常的かを数回見て、恒常的なら次の cohort 改訂で外す
- raw fetch ではときどき 403 でも、通常時は本文が安定して取れて benchmark 価値が高い site は残してよい。ただし `quality notes` か `performance notes` に揺れを明記する

## Canonical Audit Cohorts

### Unified Cohort

基準 manifest: `tweb/data/quickjs_audit_sites.json`

#### Active Focus Sites

現在のアクティブ監査セット。manifest の `active_site_ids` で明示した current focus で、件数は固定しない。`match` になったsiteはOther Canonical Sitesへ戻し、`minor_gap` / `major_gap` / `quickjs_error` / `unverified_recently` はここへ移してfocused auditを進める。追加時はOther Canonical Sitesに残る未解消siteを優先し、それで不足するときだけ過去に監査済みの未解消siteを再導入する。challengeやaccess-controlで通常本文を比較できないsiteも重点対象から外す。

| site_id | domain | tags | latest status | quality notes | performance notes | observed on |
| --- | --- | --- | --- | --- | --- | --- |
| `qiita-home` | `qiita.com` | `developer`, `interactive` | `alternate_content_branch` | visible body は同量域で、QuickJS は homepage の別 branch を保持しつつ links `386/360`、input controls `2/5`。similarity `0.699`、visible ratio `1.000`、DOM ratio `0.783`。 | QuickJS hydration 約 `0.76s`、Chrome browser render 約 `8.78s`。 | 2026-07-24 |
| `jalan-home` | `jalan.net` | `travel`, `service` | `quickjs_error` | current rerun では QuickJS/Chrome とも render subprocess が比較前に失敗した。 | QuickJS / Chrome とも `exit -11`。 | 2026-07-24 |
| `ndl-home` | `ndl.go.jp` | `government`, `knowledge` | `minor_gap` | 2026-08-09 の rerun でも本文と大半の links は維持しつつ input surface は `4/8` に留まった。残差は header search の scope selector と datepicker disclosure。visible ratio `0.597`、similarity `0.553`、visible links `29/34`、DOM ratio `0.966`。page-event は不要で、残差は raw/runtime DOM に存在しない picker surface。 | QuickJS embedded scripts total 約 `1.80s`、hydration 約 `140ms`。 | 2026-08-09 |
| `yahoo-news-jp-home` | `news.yahoo.co.jp` | `news`, `service` | `major_gap` | Monday, July 27, 2026 の live rerun では QuickJS 側 feed が Chrome より大きく短く、links と input surface も `107/154`, `2/4`。visible ratio `0.337`、similarity `0.363`、DOM ratio `0.764`。Chrome が持つ hero / recommended story branch を QuickJS がまだ十分回収できていない。 | QuickJS embedded scripts total 約 `0.97s`、hydration 約 `114ms`、`augment_exact_visible_body_text` 約 `99ms`。Chrome browser render は約 `7.96s`。 | 2026-07-27 |
| `gnavi-home` | `gnavi.co.jp` | `service`, `lifestyle` | `minor_gap` | 2026-08-09 の rerun では、runtime が load event を要求するページで page-event dispatch を維持する汎用修正により、本文 `2300`、links `275/310`、input controls `15/15`、DOM `234/271` まで改善した。visible ratio `0.627`、similarity `0.738`、DOM ratio `0.863`。残る差は discovery/feed の一部。 | QuickJS embedded scripts total 約 `3.98s`。script eval 約 `2.41s`、page event dispatch 約 `960ms`、async drain 約 `907ms`。 | 2026-08-09 |
| `env-home` | `env.go.jp` | `government`, `public` | `alternate_content_branch` | title・controls は一致し、QuickJS は Chrome より多い links `161/108` を持つ別 branch。visible ratio `1.000`、similarity `0.830`、DOM ratio `1.000`。 | QuickJS async drain 約 `0.28s`、Chrome browser render 約 `4.20s`。 | 2026-07-24 |
| `mlit-home` | `mlit.go.jp` | `government`, `public` | `alternate_content_branch` | visible coverage と controls は揃い、QuickJS が links `219/176` を持つ別 branch。visible ratio `1.000`、similarity `0.825`、DOM ratio `1.000`。 | QuickJS page-event dispatch 約 `2.57s`、Chrome browser render 約 `3.65s`。 | 2026-07-24 |
| `rakuten-travel-home` | `travel.rakuten.co.jp` | `travel`, `service` | `major_gap` | 検索 shell と input controls `108/112` は残るが、本文と links は Chrome に対して大きく不足する。visible ratio `0.264`、similarity `0.417`、visible links `157/358`、DOM ratio `0.577`。 | QuickJS embedded scripts total 約 `10.7s`、Chrome 約 `24.2s`。 | 2026-07-24 |
| `gihyo-home` | `gihyo.jp` | `developer`, `docs` | `alternate_content_branch` | body 量と controls は揃い、blog/feed branch の差が主。visible ratio `1.000`、similarity `0.713`、visible links `68/71`、DOM ratio `1.000`。 | QuickJS hydration 約 `1.10s`。 | 2026-07-24 |
| `walgreens-home` | `walgreens.com` | `shopping`, `health` | `minor_gap` | Sunday, July 26, 2026 の latest rerun では retail shell と links は維持しつつ、empty federated search shell に加えて empty store-selector shell も synthetic text control として回収し、QuickJS の input surface は Chrome と同量域まで到達した。残差は nearest-store/search overlay の richer branch と coupon/feed 起因の DOM coverage。visible ratio `0.692`、similarity `0.789`、visible links `113/120`、DOM ratio `0.400`。 | QuickJS embedded scripts total 約 `7.7s`。branch 上の search/location-shell recovery で control ratio は `0.0 -> 1.0` まで改善し、current `minor_gap` reason から user-input control shortfall は外れた。 | 2026-07-26 |
| `kayak-home` | `kayak.com` | `travel`, `service` | `minor_gap` | discovery shell は出るが、Chrome 側より links と DOM coverage が不足する。visible ratio `0.784`、similarity `0.679`、visible links `103/145`、input controls `3/2`、DOM ratio `0.643`。 | QuickJS hydration 約 `2.86s`。 | 2026-07-24 |
| `eventbrite-home` | `eventbrite.com` | `service`, `events` | `minor_gap` | locale branch が分かれ、QuickJS は本文が短い一方で links / controls は比較可能域にある。visible ratio `0.450`、similarity `0.114`、visible links `146/167`、input controls `4/4`、DOM ratio `0.630`。 | QuickJS embedded scripts total 約 `7.6s`。 | 2026-07-24 |
| `walmart-home` | `walmart.com` | `shopping`, `service` | `challenge_branch` | QuickJS は通常本文を返したが、Chrome policy は challenge / interstitial branch に解決した。visible ratio `1.000`、similarity `0.043`、visible links `19/0`、input controls `2/2`、DOM ratio `0.385`。 | Chrome browser render 約 `8.93s`。 | 2026-07-24 |
| `fsa-home` | `fsa.go.jp` | `public`, `government` | `minor_gap` | hidden news/tab branch 差が残り、visible body は Chrome より短いが input controls は一致する。visible ratio `0.519`、similarity `0.676`、visible links `117/141`、input controls `2/2`、DOM ratio `0.948`。 | QuickJS total 約 `2.3s`。 | 2026-07-24 |
| `navitime-home` | `navitime.co.jp` | `public`, `transport` | `major_gap` | route/search shell と input controls `13/13` は出るが、本文と links は Chrome に対して大きく不足する。visible ratio `0.171`、similarity `0.206`、visible links `90/189`、DOM ratio `0.867`。2026-08-09 の QuickJS-only rerun は links `58`、input controls `17`、DOM `268` を返したが、Chrome 比較を完走していないため classification は更新していない。 | 2026-08-09 の QuickJS-only rerun は embedded scripts total 約 `40.42s`。主因は script eval 約 `36.14s` と async / DOMContentLoaded 約 `32.36s`。 | 2026-08-09 |
| `jaxa-home` | `jaxa.jp` | `public`, `research` | `minor_gap` | 2026-08-09 の live rerun でも controls は `4/4` を維持。一方で注目キーワード / news feed 由来の本文・link coverage はまだ不足し、visible ratio `0.942`、similarity `0.760`、visible links `81/96`、DOM ratio `0.810`。 | QuickJS embedded scripts total 約 `10.13s`。script eval 約 `9.47s`、external script fetch 約 `1.93s`、page event dispatch 約 `421ms`。Chrome forced benchmark は約 `12.94s`。 | 2026-08-09 |
| `accuweather-home` | `accuweather.com` | `service`, `weather` | `chrome_error` | QuickJS は通常本文を回収したが、Chrome policy fetch は current rerun でも失敗した。QuickJS visible body `9281`、visible links `207`。 | Chrome は `403 Forbidden`。 | 2026-07-24 |
| `skyscanner-home` | `skyscanner.com` | `travel`, `service` | `challenge_branch` | QuickJS は通常本文を返すが、Chrome policy は current rerun でも challenge / interstitial branch に解決した。visible ratio `1.000`、similarity `0.095`、visible links `89/0`、input controls `2/2`、DOM ratio `1.000`。 | QuickJS total 約 `1.5s`、Chrome browser render 約 `7.46s`、Chrome total 約 `9.13s`。 | 2026-07-24 |
| `webmd-home` | `webmd.com` | `service`, `health` | `challenge_branch` | current rerun では QuickJS / Chrome とも challenge / interstitial branch に解決し、通常本文の品質比較にならない。visible ratio `1.000`、similarity `0.905`、visible links `112/112`、input controls `0/0`、DOM ratio `0.450`。 | QuickJS total 約 `3.6s`、Chrome browser render 約 `8.43s`、Chrome total 約 `11.1s`。 | 2026-07-24 |

#### Other Canonical Sites

canonical manifest には残しているが、現在の `active_site_ids` には含めていないsite群。

| site_id | domain | tags | latest status | quality notes | performance notes | observed on |
| --- | --- | --- | --- | --- | --- | --- |
| `publickey-home` | `publickey1.jp` | `developer`, `news` | `match` | 2026-07-20 の focused audit では title・visible body・link・DOM が QuickJS/Chrome で一致し、前日まで残っていた ranking/widget 系の差分は再現しなかった。visible ratio `1.000`、similarity `1.000`、links `286/286`、DOM ratio `1.000`。 | ignored script error `1` でも runtime reset は `0`。 | 2026-07-20 |
| `egov-home` | `e-gov.go.jp` | `government`, `service` | `match` | visible-link 監査へ統一した結果、Chrome の非表示ナビゲーションを欠落として数えていた差が解消。visible body・link・controls は一致。visible ratio / similarity `1.000`、visible links `110/110`、input controls `5/5`、DOM ratio `0.939`。 | – | 2026-07-20 |
| `mynavi-baito-home` | `baito.mynavi.jp` | `jobs`, `service` | `match` | hidden modal checkbox を監査の visible control 比較から除外し、visible UI の control 差分を解消した。visible ratio `0.996`、similarity `0.998`、links `1443/1455`、visible controls `7/7`。 | – | 2026-07-19 |
| `mhlw-home` | `mhlw.go.jp` | `government`, `public` | `match` | link-dense page の lifecycle 最適化が `window.load` まで省略し、`main.l-content` の load gate が解除されていなかった。substantial main が90%以上隠れる場合は load event を実行する汎用 recovery で解消。visible ratio `0.989`、similarity `0.977`、full similarity `0.993`、visible links `166/167`、controls `6/6`、DOM `124/124`。 | QuickJS page-event dispatch 約 `699ms`。 | 2026-07-20 |
| `yahoo-travel-home` | `travel.yahoo.co.jp` | `travel`, `service` | `match` | 2026-07-20 の focused follow-up で travel 検索 shell の synthetic picker 抽出を追加し、date/people/pricing toggle/pagination 系の visible launcher を input-like control として回収した。visible body と link は従来どおり near-match を維持。visible ratio `0.991`、similarity `0.914`、links `693/693`、DOM ratio `0.672`。QuickJS visible controls `42`、input-like controls `18`。 | – | 2026-07-20 |
| `ikyu-home` | `ikyu.com` | `travel`, `service` | `match` | 2026-07-20 の focused follow-up で travel 検索 shell の synthetic picker 抽出を追加し、date/people/pricing toggle/pagination 系の visible launcher を input-like control として回収した。本文は引き続き near-match。visible ratio `1.000`、similarity `0.966`、links `552/567`、DOM ratio `0.703`。QuickJS visible controls `45`、input-like controls `20`。 | – | 2026-07-20 |
| `ipa-home` | `ipa.go.jp` | `government`, `developer` | `match` | QuickJS は目的別カードを各1回保持し、Chrome は同じ4カードを2回と「別ウィンドウで開く」を反復していた。unique-token coverage による重複本文判定で、実欠落ではないことを確認。visible ratio `0.756`、similarity `0.748`、Chrome unique-token coverage `0.990`、visible links `79/85`、input controls `2/2`、DOM ratio `0.892`。 | – | 2026-07-20 |
| `zexy-home` | `zexy.net` | `service`, `lifestyle` | `match` | 2026-07-20 の focused audit では visible body・link・controls が実質一致し、前日まで `minor_gap` として残していた low-input page の DOM coverage 差は `match` 判定を妨げなかった。visible ratio `0.987`、similarity `0.988`、links `314/316`、DOM ratio `0.626`。visible DOM は `274/288`。 | – | 2026-07-20 |
| `zenn-home` | `zenn.dev` | `developer`, `interactive` | `match` | 2026-07-20 の focused audit では QuickJS/Chrome の title・visible body・link・DOM が一致し、`__next_f` feed 回収後の残差は再現しなかった。visible ratio `1.000`、similarity `1.000`、DOM ratio `1.000`、links `137/137`。 | QuickJS total 約 `1.3s`、Chrome forced benchmark 約 `21.3s`。 | 2026-07-20 |
| `costco-home` | `costco.com` | `shopping`, `service` | `match` | focused auditでtitle・visible body・link・DOMが一致。visible body `2240/2240`、links `102/102`、DOM ratio `1.000`。 | – | 2026-07-20 |
| `trivago-home` | `trivago.com` | `travel`, `service` | `match` | focused auditで旅行検索本文とnavigationが一致。visible body `8713/8713`、links `380/380`、DOM ratio `1.000`。 | – | 2026-07-20 |
| `rightmove-home` | `rightmove.co.uk` | `service`, `real-estate` | `match` | 再監査では物件検索shell・本文・linkが一致し、初回の小差は再現しなかった。 | visible body `2713/2713`、links `112/112`、token coverage `1.000`。 | 2026-07-20 |
| `ticketmaster-home` | `ticketmaster.com` | `service`, `events` | `match` | focused auditでイベント検索本文・link・DOMが一致。 | visible body `4245/4245`、links `118/118`、DOM ratio `1.000`。 | 2026-07-20 |
| `metoffice-home` | `metoffice.gov.uk` | `service`, `weather` | `match` | Chromeだけに出るTCF vendor cookie dialogを監査比較から除外し、通常の天気・forecast本文が実質一致することを確認。 | visible ratio `1.000`、similarity `0.997`、visible body `2599/2584`、links `69/69`、DOM ratio `0.996`。 | 2026-07-20 |
| `itmedia-news-home` | `itmedia.co.jp/news` | `news`, `developer` | `match` | visible body・link・input・DOM が live rerun で一致し、前回残っていた listing 差は再現しなかった。 | visible ratio `1.000`、similarity `1.000`、links `82/82`、DOM ratio `1.000`。ignored script error `7` でも match。 | 2026-07-23 |
| `cao-home` | `cao.go.jp` | `public`, `government` | `match` | visible body・link・input・DOM が live rerun で一致し、前回 minor として残っていた delayed navigation 差は再現しなかった。 | visible ratio `1.000`、similarity `1.000`、links `57/57`、DOM ratio `1.000`。 | 2026-07-23 |
| `epark-home` | `epark.jp` | `service`, `lifestyle` | `match` | runtime reset 後に安全な定数/bootstrap script を再適用し、後続 Vue bundle の `API_PATH` 欠落を解消。検索 UI と control が展開された。 | visible similarity `0.894`、visible ratio `0.821`、visible links `147/185`、input controls `6/6`、DOM ratio `0.750`。runtime reset `5` 回に対し bootstrap replay `5` 回。 | 2026-07-20 |
| `bbc-weather-home` | `bbc.com/weather` | `service`, `weather` | `match` | 安定 benchmark。same-site navigation probe も有効。 | same-site nav probe 成功。 | 2026-07-16 |
| `weathercom-home` | `weather.com` | `service`, `weather` | `match` | title・visible body・links・input controls・DOM が Friday, July 24, 2026 の current rerun で一致した。visible ratio `1.000`、similarity `1.000`、visible links `70/70`、input controls `1/1`、DOM ratio `1.000`。 | QuickJS total 約 `13.8s`、Chrome total 約 `38.7s`。 | 2026-07-24 |
| `weather-gov-home` | `weather.gov` | `service`, `weather` | `match` | Friday, July 24, 2026 の live rerun でも title・visible body・link・controls・DOM は一致。 | QuickJS total は約 `3.2s` まで低下し、`external_script_fetch` 約 `1.5s`、`script_eval` 約 `1.9s`、`page_event_dispatch` 約 `1.1s`。Chrome benchmark でも比較結果は `match` を維持。 | 2026-07-24 |
| `allrecipes-home` | `allrecipes.com` | `service`, `lifestyle` | `match` | 安定 benchmark。 | 回帰確認先として使いやすい。 | 2026-07-16 |
| `mapquest-home` | `mapquest.com` | `service`, `maps` | `match` | map/search 系の軽量 benchmark。 | 軽量 benchmark。 | 2026-07-16 |
| `ikea-us-home` | `ikea.com/us/en` | `shopping`, `service` | `match` | Sunday, July 26, 2026 の rerun では retail shell と主要 links を維持したまま `match` 判定へ戻った。visible ratio `0.849`、similarity `0.867`、visible links `189/184`、input controls `22/28`、DOM ratio `0.389`。current reason は `quickjs DOM tree is much smaller than chrome` だけだが、visible body・link・controls は benchmark 許容域に収まった。 | QuickJS embedded scripts total 約 `17.5s`、Chrome browser render 約 `10.2s`。current branch の synthetic search/control recovery 後も `match` を維持。 | 2026-07-26 |
| `target-home` | `target.com` | `shopping`, `service` | `match` | Sunday, July 26, 2026 の rerun でも title・visible body・link・controls・DOM は一致を維持。本文がすでに読める moderately rich page では 40 本超の delayed external script を fetch 前に generic skip できる状態を保ち、QuickJS は Chrome より richer branch を返した。 | QuickJS-only rerun で `embedded_delayed_scripts=56` の全件が `skipped_delayed_external_scripts=56`。`_prune_inline_loading_placeholders()` の hotspot 改善後ベース `14.0s` から、2026-07-26 の branch-only follow-up では static-page 判定の execution-scope metrics cache により `embedded_scripts_total` が同日 main 比で約 `5.60s -> 5.33s`。`script_eval` は約 `0.21s`、hydration は約 `1.60s`。残る cold cost は主に fetch と post-script DOM cleanup。 | 2026-07-26 |
| `zillow-home` | `zillow.com` | `service`, `real-estate` | `match` | 安定 benchmark。 | real-estate 系 benchmark。 | 2026-07-16 |

## Skipped Targets

captcha / challenge / anti-bot 理由で canonical audit から外した、または外すべき実例をここに集約する。

| site_id or label | domain | observed on | status | reason |
| --- | --- | --- | --- | --- |
| `jreast-home` | `jreast.co.jp` | 2026-07-16 | skip | raw fetch が `403 Access Denied` shell に寄り、generic QuickJS 改善の benchmark として不安定。 |
| `tokyometro-home` | `tokyometro.jp` | 2026-07-16 | skip | raw fetch が `403 Access Denied` shell に寄り、品質差より access control の揺れが支配的。 |
| `rikunabi-home` | `job.rikunabi.com` | 2026-07-19 | skip | QuickJS/Chromeともchallenge/interstitial branchへ解決し、generic runtime改善の比較対象にならない。 |
| `google-search` | `google.com/search` | 2026-07-16 以前の regression corpus | skip | 両モードとも challenge / interstitial へ寄りやすく、品質比較の canonical benchmark に向かない。 |
| `booking-home` | `booking.com` | 2026-07-16 以前の regression corpus | skip | QuickJS 側だけ challenge/interstitial branch に入りやすい代表例。汎用改善より bot 判定の揺れが支配的。 |
| anti-bot-heavy commercial homepages removed during cohort curation | multiple | 2026-07-16 | skip | raw fetch で 403 / 429 / access denied shell に寄る site 群。 site 名が確定したものは今後この表へ個別追加する。 |

## Suggested Next Targets

- `jalan-home`
  2026-07-24 の current rerun では QuickJS / Chrome とも `exit -11` で `quickjs_error`。Monday, July 27, 2026 時点の code path では isolated audit subprocess が `fetch` / `parse` / `execute_embedded_scripts` / `snapshot` など直前 phase を stderr に残すようになったので、次回 rerun ではまず crash / segfault がどの phase で起きたかを確定する。
- `navitime-home`
  2026-08-09 の QuickJS-only rerun では embedded scripts total 約 `40.42s` まで下がったが、script eval 約 `36.14s` と async / DOMContentLoaded 約 `32.36s` が依然支配的。Chrome 比較は未完了のため quality classification は据え置く。次回は large same-origin bundle と post-load async drain を、Chrome 比較を含む同一条件で再計測する。
- `rakuten-travel-home`
  current rerun では `major_gap`。search shell と input controls `108/112` は揃う一方、visible links `157/358` と本文量が不足しているため、travel feed / listing branch の回収不足を runtime / hydration 側で確認する。
- `walmart-home`
  current rerun では `challenge_branch`。QuickJS 本文は出ている一方で Chrome policy が interstitial へ倒れたため、canonical benchmark として active に置き続ける価値があるかを再確認する。
- `skyscanner-home`
  current rerun でも `challenge_branch`。QuickJS は通常本文を返す一方で Chrome policy が challenge に倒れるため、active へ戻したうえで benchmark として追い続ける価値があるかを判断する。
- `webmd-home`
  current rerun でも `challenge_branch`。QuickJS / Chrome とも challenge / interstitial branch に入るため、active に戻した状態で通常本文へ寄せる余地があるかを再確認する。
- `accuweather-home`
  current rerun でも `chrome_error` で `403 Forbidden`。QuickJS 側は本文を回収できているが、Chrome 比較が不安定なため、active focus に残すか `Skipped Targets` 側へ寄せるかを判断する候補。
- `ndl-home`
  Monday, July 27, 2026 の live rerun でも `minor_gap`。current branch の generic picker/select launcher recovery 後も input surface は `4/8` に留まり、残差は header search の scope selector と 3 つの datepicker disclosure だった。次は empty launcher 抽出ではなく、delayed widget mount 後に実体 control を visible tree へ残す経路を切り分ける。
- `yahoo-news-jp-home`
  Monday, July 27, 2026 の live rerun では `major_gap`。QuickJS は links `107/154`、input controls `2/4` で、Chrome が持つ hero / recommended story branch を十分に回収できていない。hydration cost 自体は約 `114ms` と小さいため、次は runtime/hydration の速度よりも discovery/news feed branch の抽出不足を優先して切り分ける。
- `walgreens-home`
  current rerun では `minor_gap`。links `114/122` に対して input controls `0/4` と DOM ratio `0.396` が弱く、retail 系の hidden / synthetic input surface 回収の代表 target とする。
- `jaxa-home`
  2026-08-09 の live rerun でも `minor_gap`。controls `4/4` は維持したが links `81/96` で、QuickJS DOM に「注目キーワード」/feed ノード自体が生成されていない。次は site-specific fallback を足さず、large webpack bundle 実行後の network payload / discovery container 回収が汎用 runtime で可能かを切り分ける。
  canonical cohort ではないが、継続的な性能改善対象として固定する。対象URLは `https://ja.wikipedia.org/wiki/%E3%82%B5%E3%83%B3%E3%83%89%E3%83%9E%E3%83%B3_(%E3%83%B4%E3%82%A1%E3%83%BC%E3%83%86%E3%82%A3%E3%82%B4)`。Wikipedia 日本語版の長文記事として、live page での DOM 構築・本文抽出・CSS 適用コストの観測先に使う。
- `FreeBSD` (Wikipedia article benchmark)
  canonical cohort ではないが、継続的な runtime performance の観測先として有用。対象URLは `https://ja.wikipedia.org/wiki/FreeBSD`。2026-07-27 の branch 実験では named window property sync を dirty 時だけ走らせ、同一 live page の `execute_embedded_scripts()` で embedded scripts total は約 `44.67s -> 44.42s`、script eval は約 `564ms -> 555ms`。QuickJS runtime 単体計測では初回 full sync が約 `463ms`、clean skip 10回は合計約 `0.018ms` で、無変更 eval の全DOM再走査をほぼ除去できた。
  続く branch 実験では hydration 後 restore 判定の cheap gate を追加し、healthy marker body で full visible-text probe を避けた。同一 live page の phase timing は embedded scripts total 約 `35.54s -> 27.02s`、hydration 約 `14.81s -> 6.59s`、`should_restore_initial_body_after_hydration` 約 `8.99s -> 0.72s` まで低下した。その後、hidden DOM recovery を substantial body では遅延化し、expensive page-event / DOMContentLoaded 判定も exact visible-text scan から inline preview ベースへ置き換えた。
  最後に、本文・links・controls が初期HTMLに十分ある static-rich page では embedded scripts / hydration 自体を起動しない generic early return を追加し、同一 `FreeBSD` live page は `embedded_scripts_total` 約 `741ms`、`hydration` `0ms`、`embedded_scripts_skipped_for_static_page=1` まで低下した。current benchmark では、まず static-rich 判定を取ること自体が最大の性能改善方針であり、初期HTMLの readable body が十分な Wikipedia 記事に対して QuickJS runtime cost をほぼ除去できている。
  ただしその後の live repro で、「QuickJS は終わっているのに render が返らない」症状が残り、実測では通常レンダラ内の `aria-labelledby` 解決が全DOM再走査、さらに external stylesheet を含む full CSS selector matching が支配的だった。2026-07-27 の追加 branch 実験では renderer 側で `id` / `aria-labelledby` 索引を state にキャッシュし、static-rich page では inline style と hidden 属性だけを見る lightweight render path を追加した。加えて `execute_embedded_scripts()` の static-rich 判定から高価な `form_controls()` 呼び出しを外し、cheap control scan に置き換えた。
  さらに同日の follow-up では `interactions` 側にも document 単位の `label[for]` / `id` / generated control id 索引を追加し、synthetic button 判定や `_control_label()` が毎回 `find_all()` / 全DOM走査へ戻らないようにした。これで同一 live page の `render_normal_with_metadata()` は約 `914.939ms -> 87.882ms` まで低下し、本文長 `64534`、links `1508`、controls `21` は維持できた。
  同日 API 直測 (`fetch_resource` -> `parse_document` -> `execute_embedded_scripts` -> `render_normal`) では、同一 `FreeBSD` live page の `execute_embedded_scripts()` は約 `21.253ms`、通常レンダラは約 `87.882ms`、fetch 約 `539.825ms`、parse 約 `54.035ms` まで低下した。render 側のボトルネックは「static-rich page で full stylesheet/CSS selector matching が本当に必要か」から、「interactive metadata 用 lookup を何度も全木再計算していないか」へ移っていたため、Wikipedia のように本文HTMLが十分あるページでは lightweight render と document-level interaction lookup cache の組み合わせが first-line option として有効だった。
  ただし性能評価は API 直測だけで完了扱いにせず、最終的には TUI で十分速いかどうかを基準にする。`--mode text` や `render_normal()` 単体が速くても TUI が遅いなら、`_build_browser_page()`、pane detection、viewport 更新、buffer 構築のような後段 hot path を疑う。逆に static-rich / lightweight render 判定が期待どおり発火していない場合は、その原因として `link_count` 閾値も必ず候補に入れる。Athlon 64 のように readable body と stylesheet 数は十分でも `link_count` 条件だけで lightweight path が外れ、QuickJS / TUI 両方の体感遅延へつながるケースがあるため、今後の rerun でも「TUI で速いか」を正本にしつつ、性能が出ない page では `link_count` を含む static-rich 判定全体を見直す。
- `note-home`
  canonical cohort ではないが、runtime performance の stress test としては引き続き有用。 async drain、external script fetch、huge bundle eval の切り分けに使う。

## 2026-10-19: Phase 16 TUI page assembly

対象は canonical audit cohort 外の TUI 性能検証。品質分類と `active_site_ids` は変更していない。

### 計測条件

- 比較元は `7809c38`。対象は `https://www.python.org/about/`（HTTP 200、41,239 bytes）と `https://docs.python.org/3/tutorial/`（HTTP 200、37,315 bytes）からこの日に取得した HTML
- 同一取得 HTML を `Resource` として再生し、width=80 で `_render_document()` → `_build_browser_page()` → `_rebuild_current_page_view()` を直測した。QuickJS 実行・初回 HTML fetch は計測に含まない。CSS 取得・解析は各処理の通常経路を使う
- 下表は各版 1 回の参考値。ネットワーク/CSS cache の揺れがあるため、初回 renderer / build の小差を改善率として扱わない

| 対象 | renderer 変更前→変更後 | page build 変更前→変更後 | 同一ページの view rebuild 変更前→変更後 | pane groups |
| --- | --- | --- | --- | --- |
| Python About | 287.3 → 301.2ms | 1.75 → 2.10ms | 1.77 → 0.46ms | 0 |
| Python Tutorial | 131.8 → 140.3ms | 72.13 → 81.53ms | 57.84 → 0.52ms | 3 |

単一カラムの Python About では後段 page build は約2msで、renderer との時間差は後段処理に起因しない。Python Tutorial では初回の pane detection / region 統合コストが残る一方、view rebuild での再検出・source buffer 再生成・pane の再描画は除去できた。

### Textual TUI での確認

同じ Python Tutorial HTML を 100 columns × 30 rows の Textual `run_test()` で再生した。HTML fetch と埋め込み JS 実行を差し替え、Phase 16 の表示経路に限定して、描画された pane の行へカーソルを置き `pilot.press("v")` で focus / restore した。

- 全体表示は pane groups `3`。最終 page build 約 `188.4ms`（pane detection 約 `144.9ms`、pane region 統合約 `39.9ms`）
- focus 時の page build 約 `10.6ms`、restore 時約 `0.82ms`。全体本文が元と一致し、focus 中は他 pane を除去できた
- 同 run の viewport 更新は約 `0.9–7.5ms`。キー送信・イベントループの待ち時間は上記 phase timing に含まない
- 実ターミナルでの体感・視認確認は未実施。Wikipedia `Athlon_64` は HTTP 403 で取得できず、この日の live 比較には使っていない

### 回帰確認と残る境界

`python -m unittest tests.test_tui tests.test_normal_renderer tests.test_cli` は **271 tests 成功**。hidden/template 内だけの layout hint、static-rich page の検出省略、外部 CSS の true multi-pane、キャッシュ再利用と resize / DOM 更新時の破棄、timing 出力、キャンセルを含む。

`--debug` の `tui timing phase=... elapsed_ms=...` と `BrowserPage.build_timings_ms` で同じ段階を追える。`page_build` は子フェーズを含む合計で、renderer・controls/links・viewport は別計測。キャッシュは `v` による同一ページ・同一幅の切り替えだけで再利用する。新規 load、mutation 後の rerender、resize、background render は作り直す。

初回 multi-pane の full CSS 再評価、低 link 数記事への lightweight 判定拡大、単一フェーズ中の強制中断は今後の最適化候補として残す。

### main 統合時の回帰確認

`b5b5273` の main を統合し、画像省略オプションを pane subtree の描画・キャッシュにも引き継いだ。キャッシュ再利用条件に画像表示設定の一致を追加した。TUI / normal renderer / CLI / JS runtime の **504 tests 成功**に加え、画像表示設定変更時のキャッシュ破棄テスト **1 test 成功**。

## 2026-10-19: Apollo 参照解決の共通化

`1688457` のカクヨム目次抽出と、共通 resolver を使う変更後を、同じ QuickJS runtime 上の合成 Apollo cache で各1回比較した。作品・目次・章・episode entity を生成し、抽出された全項目の一致を確認した。実サイトの HTML 取得、bundle 実行、TUI 描画は含まない。canonical cohort の品質分類と `active_site_ids` は変更していない。

| 合成データ | 変更前 | 変更後 | 抽出結果 |
| --- | --- | --- | --- |
| 100 episodes | 0.82ms | 6.55ms | 100件一致 |
| 1,000 episodes | 5.16ms | 58.34ms | 1,000件一致 |

共通化後は entity ごとの runtime 読出しが増えるため、この抽出単体では遅くなる。cache 全体の転送は避け、対象作品から到達する entity の指定 field だけを読む。深さ・処理量・1 entity の転送文字数を制限する。実サイトの表示品質とページ全体の処理時間は未監査であり、上表から live 性能は判断しない。

## 2026-10-19: note 専用 API 補完と URL 推測の削除

canonical cohort 外の確認。`https://note.com/` と `https://note.com/topic/computer_it` から取得した HTML（それぞれ100,065文字 / 263,055文字）を保持し、`ed98f23` と変更後で同じ HTML を再生した。`browser_render_policy="never"`、ログイン Cookie の取込なし。外部 JS / CSS は通常の取得・cache 経路を使う。

| 対象 | 可視本文文字数 変更前→変更後 | links 総数 変更前→変更後 | 元 HTML の一意なリンクの保持 | 埋込記事タイトルの表示 |
| --- | --- | --- | --- | --- |
| note home | 1,694 → 1,970 | 106 → 39 | 27 / 27 | 20 / 20 |
| note computer_it topic | 3,481 → 2,739 | 139 → 97 | 85 / 85 | 24 / 43 |

一意なリンクは `(label, href)` で照合した。links 総数の減少には、`key` / `urlname` / `engName` からの URL 合成を廃止した分を含む。根拠となる URL を持たない記事はテキスト表示にする。元 HTML のリンクは両ページですべて保持した。topic は汎用の表示件数制限を維持しており、全43件の埋込記事を表示できたという結果ではない。

home の runtime JSON 記録に現れた固定 API 呼出しは6件から0件へ減った。topic も変更後の追加 API 記録は0件。ページが発行する fetch / XHR 自体は有効で、遅延 JSON fetch の回帰テストで共通 collector への回収を確認する。

両ページの bundle で発生した `SyntaxError: invalid property name` は class static block の構文変換で解消し、記録された script error は1件から0件になった。topic は runtime が削除した main を汎用処理で復元し、元の入力 UI も保持した。完全な React mount や、ログイン状態のフィードの再現を確認したものではない。

各1回の全体所要時間は home `4.781 → 11.016s`、topic `2.691 → 4.263s`。外部リソースの通信・cache 条件を固定していないため、性能改善率として扱わない。Chrome 比較・実ターミナルでの視認確認は未実施。canonical cohort の分類・`active_site_ids` は変更していない。

`make test` は864 tests 成功。URL 合成の抑止、一意な DOM anchor の採用、ページ発行の遅延 JSON fetch、URL を持たない Flight 記事の本文回収、main 消失時の復元と新規入力 UI の保持、class static block の初期化順 / private field / `super` / literal 保持を回帰対象に含めた。
