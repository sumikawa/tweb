[English](performance.md) | [日本語](performance.ja.md)

# performance.md

This ledger consolidates QuickJS quality and performance improvement records in 1 place for 3 purposes.

- Define which sites belong to the canonical audit inventory.
- Make it possible to quickly review the latest classification and main points for each canonical cohort site.
- Track quality and performance improvements together to identify the next work quickly.

## Usage / Update Rules

- When adding a site to regular audits, first add it to `tweb/data/quickjs_audit_sites.json` and this file's cohort inventory.
- When changing the cohort's site inventory, update the cohort table in this file in the same commit.
- When rerunning a site, update its `Unified Cohort` row with the latest classification/quality notes/performance notes/observed-on date.
- If reruns change the focused cohort, update the active/reserve placement in `Unified Cohort` and `active_site_ids` in `tweb/data/quickjs_audit_sites.json` in the same change. Keep the table and manifest synchronized.
- Before reusing a site, consult `quality notes` / `performance notes` in `Unified Cohort` and related sections to carry forward known issues and recent observations.
- State explicitly when performance improvements were tested only on a branch and have not been merged.
- Measurements vary: record the target, command, and observed bottleneck together rather than treating 1 run as an absolute value.
- Pages that require captcha / challenge / anti-bot interstitial will be removed from the canonical benchmark for QuickJS quality improvement and performance improvement, and will be left in "Skipped Targets" of this file with a reason.
- Always add sites excluded for captcha/challenge reasons to "Skipped Targets"; removing them from the manifest alone is insufficient.
- State explicitly when speed improvements apply only to synthetic cases.
- When live-site measurements worsen, record which phases increased using `javascript_debug()` before immediately reverting.
- Count only visible links, as with controls. Do not use hidden links in responsive menus or modals as evidence of missing body content.
- Allow scripts on another registrable domain as first-party app assets only when their exact URLs are present in initial HTML and share a path prefix of at least 2 segments with a stylesheet on the same host. Do not allow the entire CDN host or unknown runtime-added URLs.

## How to read Classification

- `match`: title, body, link, input control, DOM are close enough to Chrome
- `minor_gap`: The main body has been reached, but small gaps or differences remain in the body volume, links, controls, and parts of the DOM.
- `major_gap`: Visible text and main UI are largely missing, not reaching usable content equivalent to Chrome.
- `quickjs_error`: QuickJS side execution cannot return comparable results due to exceptions, crashes, timeouts, etc.
- `challenge_branch`: Challenge / captcha / interstitial has been reached and the quality of the normal text is not compared.
- `alternate_content_branch`: QuickJS and Chrome display different branches, but QuickJS is not missing, but rather retrieves a branch that is richer than Chrome, or another branch with the same amount of text, links, control, and DOM coverage.

`alternate_content_branch` does not mean something in between success and failure. If QuickJS retains all slides, collapsed sections, another hydration branch, etc. of the carousel, and Chrome returns only the active slide or the currently displayed section, the body similarity between the two will decrease. Also, the transport/search page may be divided into separate branches with the same amount of information and structure, such as QuickJS's route UI and Chrome's current discovery feed. If the amount of information or coverage on the QuickJS side is sufficient, this will not be targeted for deletion correction as `minor_gap` / `major_gap`. On the other hand, since the display state is not the same as in Chrome, it is recorded separately from the exact match `match`.

The current audit considers richer-branch candidates when QuickJS has sufficient visible content and not drastically fewer visible links than Chrome, with at least approximately 1.5 times Chrome's visible body length or long content and more links. Comparable body/link/control/DOM coverage with low body similarity also qualifies as an alternate branch unless caused by locale differences. If only Chrome repeats identical card/accessibility text, classify it as duplicate-only `match` only when QuickJS retains at least 98% of Chrome's unique tokens and sufficient visible link/control/DOM coverage. When title/body/link/control/DOM nearly match, prefer `match` rather than overclassifying as `alternate_content_branch`. Examples include all carousel slides on `jica-home`, richer app mounts on `soumu-home` / `kunaicho-home` / `digital-home`, and an alternate navigation branch on `nta-home`.

## Skip Policy

### captcha / challenge pages

As a rule, do not include pages meeting these conditions as canonical audit targets.

- Body content cannot be reached without solving reCAPTCHA or image challenges.
- Raw fetches or QuickJS execution frequently return challenges, anti-bot pages, or interstitials instead of normal body content.
- Even if you use the Chrome forced benchmark, you can only see fluctuations in the bot judgment, not general improvements in QuickJS.
- Like login walls and country gates, these are unsuitable for measuring generic runtime/DOM/hydration/interaction improvements.

Treat these pages as audit exclusions rather than repair targets. The audit implementation may record `challenge_branch` when needed, but do not retain them in the canonical cohort for regular comparison.

### Exceptions

- If a cohort site starts returning challenges, first record that in its `Unified Cohort` row and `Skipped Targets`.
- Check several times to see if the challenge is temporary or permanent, and if it is permanent, remove it in the next cohort revision.
- Sites with occasional raw-fetch 403 responses may remain if normal body retrieval is otherwise stable and benchmark value is high. Document variability in `quality notes` or `performance notes`.

## Canonical Audit Cohorts

### Unified Cohort

Reference manifest: `tweb/data/quickjs_audit_sites.json`

#### Active Focus Sites

The current active audit set is explicitly listed in the manifest's `active_site_ids`; its size is not fixed. Return `match` sites to Other Canonical Sites and move `minor_gap` / `major_gap` / `quickjs_error` / `unverified_recently` here for focused audits. Prioritize unresolved sites already in Other Canonical Sites before reintroducing previously audited unresolved sites. Exclude sites whose normal body content cannot be compared because of challenges or access controls.

| site_id | domain | tags | latest status | quality notes | performance notes | observed on |
| --- | --- | --- | --- | --- | --- | --- |
| `qiita-home` | `qiita.com` | `developer`, `interactive` | `alternate_content_branch` | The visible body is the same amount, and QuickJS maintains a separate branch of the homepage with links `386/360` and input controls `2/5`. similarity `0.699`, visible ratio `1.000`, DOM ratio `0.783`. | QuickJS hydration approximately `0.76s`, Chrome browser render approximately `8.78s`. | 2026-07-24 |
| `jalan-home` | `jalan.net` | `travel`, `service` | `quickjs_error` | In the current rerun, render subprocess failed in both QuickJS/Chrome before comparison. | Both QuickJS / Chrome `exit -11`. | 2026-07-24 |
| `ndl-home` | `ndl.go.jp` | `government`, `knowledge` | `minor_gap` | Even in the rerun on 2026-08-09, the input surface remained at `4/8` while maintaining the main text and most of the links. The residuals are header search scope selector and datepicker disclosure. visible ratio `0.597`, similarity `0.553`, visible links `29/34`, DOM ratio `0.966`. Page events are unnecessary; the remaining picker surface does not exist in the raw/runtime DOM. | QuickJS embedded scripts total approximately `1.80s`, hydration approximately `140ms`. | 2026-08-09 |
| `yahoo-news-jp-home` | `news.yahoo.co.jp` | `news`, `service` | `major_gap` | In the live rerun on Monday, July 27, 2026, the QuickJS side feed was much shorter than Chrome, and the links and input surfaces were also `107/154`, `2/4`. visible ratio `0.337`, similarity `0.363`, DOM ratio `0.764`. QuickJS has not yet fully recovered the hero/recommended story branches that Chrome has. | QuickJS embedded scripts total approximately `0.97s`, hydration approximately `114ms`, `augment_exact_visible_body_text` approximately `99ms`. Chrome browser renders approximately `7.96s`. | 2026-07-27 |
| `gnavi-home` | `gnavi.co.jp` | `service`, `lifestyle` | `minor_gap` | In the 2026-08-09 rerun, the runtime has improved body `2300`, links `275/310`, input controls `15/15`, and DOM `234/271` with a general fix that maintains page-event dispatch on pages that request load event. visible ratio `0.627`, similarity `0.738`, DOM ratio `0.863`. The remaining difference is part of discovery/feed. | QuickJS embedded scripts total approximately `3.98s`. script eval about `2.41s`, page event dispatch about `960ms`, async drain about `907ms`. | 2026-08-09 |
| `env-home` | `env.go.jp` | `government`, `public` | `alternate_content_branch` | The title and controls match, and QuickJS is a separate branch with more links `161/108` than Chrome. visible ratio `1.000`, similarity `0.830`, DOM ratio `1.000`. | QuickJS async drain about `0.28s`, Chrome browser render about `4.20s`. | 2026-07-24 |
| `mlit-home` | `mlit.go.jp` | `government`, `public` | `alternate_content_branch` | Visible coverage and controls are available, and QuickJS is a separate branch with links `219/176`. visible ratio `1.000`, similarity `0.825`, DOM ratio `1.000`. | QuickJS page-event dispatch about `2.57s`, Chrome browser render about `3.65s`. | 2026-07-24 |
| `rakuten-travel-home` | `travel.rakuten.co.jp` | `travel`, `service` | `major_gap` | The search shell and input controls `108/112` remain, but the text and links are greatly lacking compared to Chrome. visible ratio `0.264`, similarity `0.417`, visible links `157/358`, DOM ratio `0.577`. | QuickJS embedded scripts total approximately `10.7s`, Chrome approximately `24.2s`. | 2026-07-24 |
| `gihyo-home` | `gihyo.jp` | `developer`, `docs` | `alternate_content_branch` | The body amount and controls are the same, but the main difference is the blog/feed branch. visible ratio `1.000`, similarity `0.713`, visible links `68/71`, DOM ratio `1.000`. | QuickJS hydration approx. `1.10s`. | 2026-07-24 |
| `walgreens-home` | `walgreens.com` | `shopping`, `health` | `minor_gap` | In the latest rerun on Sunday, July 26, 2026, while maintaining the retail shell and links, in addition to the empty federated search shell, the empty store-selector shell was also recovered as a synthetic text control, and the input surface of QuickJS has reached the same level as Chrome. The residual is DOM coverage due to richer branch of nearest-store/search overlay and coupon/feed. visible ratio `0.692`, similarity `0.789`, visible links `113/120`, DOM ratio `0.400`. | QuickJS embedded scripts total approximately `7.7s`. With search/location-shell recovery on branch, the control ratio improved to `0.0 -> 1.0`, and the user-input control shortfall was removed from the current `minor_gap` reason. | 2026-07-26 |
| `kayak-home` | `kayak.com` | `travel`, `service` | `minor_gap` | A discovery shell appears, but links and DOM coverage are lacking compared to Chrome. visible ratio `0.784`, similarity `0.679`, visible links `103/145`, input controls `3/2`, DOM ratio `0.643`. | QuickJS hydration approx. `2.86s`. | 2026-07-24 |
| `eventbrite-home` | `eventbrite.com` | `service`, `events` | `minor_gap` | The locale branches are separated, and while QuickJS has a shorter body, links / controls are in a comparable range. visible ratio `0.450`, similarity `0.114`, visible links `146/167`, input controls `4/4`, DOM ratio `0.630`. | QuickJS embedded scripts total approximately `7.6s`. | 2026-07-24 |
| `walmart-home` | `walmart.com` | `shopping`, `service` | `challenge_branch` | QuickJS returned normal body, but Chrome policy resolved to challenge / interstitial branch. visible ratio `1.000`, similarity `0.043`, visible links `19/0`, input controls `2/2`, DOM ratio `0.385`. | Chrome browser renders approximately `8.93s`. | 2026-07-24 |
| `fsa-home` | `fsa.go.jp` | `public`, `government` | `minor_gap` | The hidden news/tab branch difference remains, and the visible body is shorter than Chrome, but the input controls match. visible ratio `0.519`, similarity `0.676`, visible links `117/141`, input controls `2/2`, DOM ratio `0.948`. | QuickJS total approximately `2.3s`. | 2026-07-24 |
| `navitime-home` | `navitime.co.jp` | `public`, `transport` | `major_gap` | Route/search shell and input controls `13/13` are available, but the text and links are greatly lacking compared to Chrome. visible ratio `0.171`, similarity `0.206`, visible links `90/189`, DOM ratio `0.867`. QuickJS-only rerun on 2026-08-09 returned links `58`, input controls `17`, and DOM `268`, but the classification was not updated because the Chrome comparison was not completed. | QuickJS-only rerun on 2026-08-09 has embedded scripts total approximately `40.42s`. The main culprits are script eval about `36.14s` and async / DOMContentLoaded about `32.36s`. | 2026-08-09 |
| `jaxa-home` | `jaxa.jp` | `public`, `research` | `minor_gap` | Even in the live rerun on 2026-08-09, controls remain `4/4`. On the other hand, the main text/link coverage derived from hot keywords/news feed is still insufficient, with visible ratio `0.942`, similarity `0.760`, visible links `81/96`, and DOM ratio `0.810`. | QuickJS embedded scripts total approximately `10.13s`. script eval about `9.47s`, external script fetch about `1.93s`, page event dispatch about `421ms`. Chrome forced benchmark is approximately `12.94s`. | 2026-08-09 |
| `accuweather-home` | `accuweather.com` | `service`, `weather` | `chrome_error` | QuickJS normally retrieved the body, but Chrome policy fetch failed even on current rerun. QuickJS visible body `9281`, visible links `207`. | Chrome is `403 Forbidden`. | 2026-07-24 |
| `skyscanner-home` | `skyscanner.com` | `travel`, `service` | `challenge_branch` | QuickJS normally returns the body, but Chrome policy resolved it to challenge / interstitial branch even with current rerun. visible ratio `1.000`, similarity `0.095`, visible links `89/0`, input controls `2/2`, DOM ratio `1.000`. | QuickJS total about `1.5s`, Chrome browser render about `7.46s`, Chrome total about `9.13s`. | 2026-07-24 |
| `webmd-home` | `webmd.com` | `service`, `health` | `challenge_branch` | In the current rerun, both QuickJS and Chrome are resolved to challenge / interstitial branch, and the quality of the main text cannot usually be compared. visible ratio `1.000`, similarity `0.905`, visible links `112/112`, input controls `0/0`, DOM ratio `0.450`. | QuickJS total about `3.6s`, Chrome browser render about `8.43s`, Chrome total about `11.1s`. | 2026-07-24 |

#### Other Canonical Sites

A group of sites that are left in the canonical manifest but not included in the current `active_site_ids`.

| site_id | domain | tags | latest status | quality notes | performance notes | observed on |
| --- | --- | --- | --- | --- | --- | --- |
| `publickey-home` | `publickey1.jp` | `developer`, `news` | `match` | In the focused audit on 2026-07-20, the title, visible body, link, and DOM matched in QuickJS/Chrome, and the differences in ranking/widget that remained until the previous day were not reproduced. visible ratio `1.000`, similarity `1.000`, links `286/286`, DOM ratio `1.000`. | ignored script error `1` but runtime reset is `0`. | 2026-07-20 |
| `egov-home` | `e-gov.go.jp` | `government`, `service` | `match` | As a result of unifying visible-link auditing, the difference in counting hidden navigation in Chrome as missing has been resolved. visible body, link, and controls match. visible ratio / similarity `1.000`, visible links `110/110`, input controls `5/5`, DOM ratio `0.939`. | – | 2026-07-20 |
| `mynavi-baito-home` | `baito.mynavi.jp` | `jobs`, `service` | `match` | Exclude hidden modal checkbox from visible control comparison in audit and resolve visible UI control differences. visible ratio `0.996`, similarity `0.998`, links `1443/1455`, visible controls `7/7`. | – | 2026-07-19 |
| `mhlw-home` | `mhlw.go.jp` | `government`, `public` | `match` | Lifecycle optimization of link-dense page was omitted up to `window.load`, and the load gate of `main.l-content` was not released. If more than 90% of substantial main is hidden, it can be resolved by general-purpose recovery that executes load event. visible ratio `0.989`, similarity `0.977`, full similarity `0.993`, visible links `166/167`, controls `6/6`, DOM `124/124`. | QuickJS page-event dispatch about `699ms`. | 2026-07-20 |
| `yahoo-travel-home` | `travel.yahoo.co.jp` | `travel`, `service` | `match` | In focused follow-up on 2026-07-20, synthetic picker extraction for travel search shell was added, and date/people/pricing toggle/pagination visible launcher was collected as input-like control. visible body and link remain near-match as before. visible ratio `0.991`, similarity `0.914`, links `693/693`, DOM ratio `0.672`. QuickJS visible controls `42`, input-like controls `18`. | – | 2026-07-20 |
| `ikyu-home` | `ikyu.com` | `travel`, `service` | `match` | In focused follow-up on 2026-07-20, synthetic picker extraction for travel search shell was added, and date/people/pricing toggle/pagination visible launcher was collected as input-like control. The body is still near-match. visible ratio `1.000`, similarity `0.966`, links `552/567`, DOM ratio `0.703`. QuickJS visible controls `45`, input-like controls `20`. | – | 2026-07-20 |
| `ipa-home` | `ipa.go.jp` | `government`, `developer` | `match` | QuickJS kept each purpose-specific card 1 time, while Chrome repeated the same 4 cards 2 times and repeated "open in new window". By checking duplicate text using unique-token coverage, we confirmed that it was not actually missing. visible ratio `0.756`, similarity `0.748`, Chrome unique-token coverage `0.990`, visible links `79/85`, input controls `2/2`, DOM ratio `0.892`. | – | 2026-07-20 |
| `zexy-home` | `zexy.net` | `service`, `lifestyle` | `match` | In the focused audit on 2026-07-20, the visible body, links, and controls virtually matched, and the difference in DOM coverage of the low-input page, which had been left as `minor_gap` until the previous day, did not interfere with the `match` determination. visible ratio `0.987`, similarity `0.988`, links `314/316`, DOM ratio `0.626`. visible DOM is `274/288`. | – | 2026-07-20 |
| `zenn-home` | `zenn.dev` | `developer`, `interactive` | `match` | In the focused audit on 2026-07-20, the title, visible body, link, and DOM of QuickJS/Chrome matched, and the residual after collecting the `__next_f` feed was not reproduced. visible ratio `1.000`, similarity `1.000`, DOM ratio `1.000`, links `137/137`. | QuickJS total about `1.3s`, Chrome forced benchmark about `21.3s`. | 2026-07-20 |
| `costco-home` | `costco.com` | `shopping`, `service` | `match` | Title, visible body, link, and DOM match in focused audit. visible body `2240/2240`, links `102/102`, DOM ratio `1.000`. | – | 2026-07-20 |
| `trivago-home` | `trivago.com` | `travel`, `service` | `match` | The travel search text and navigation match in focused audit. visible body `8713/8713`, links `380/380`, DOM ratio `1.000`. | – | 2026-07-20 |
| `rightmove-home` | `rightmove.co.uk` | `service`, `real-estate` | `match` | In the re-audit, the property search shell, text, and link matched, and the small differences from the first time were not reproduced. | visible body `2713/2713`, links `112/112`, token coverage `1.000`. | 2026-07-20 |
| `ticketmaster-home` | `ticketmaster.com` | `service`, `events` | `match` | Event search text, link, and DOM match in focused audit. | visible body `4245/4245`, links `118/118`, DOM ratio `1.000`. | 2026-07-20 |
| `metoffice-home` | `metoffice.gov.uk` | `service`, `weather` | `match` | Exclude the TCF vendor cookie dialog that only appears in Chrome from the audit comparison and confirm that the normal weather/forecast text actually matches. | visible ratio `1.000`, similarity `0.997`, visible body `2599/2584`, links `69/69`, DOM ratio `0.996`. | 2026-07-20 |
| `itmedia-news-home` | `itmedia.co.jp/news` | `news`, `developer` | `match` | The visible body, link, input, and DOM matched in live rerun, and the listing difference that remained from last time was not reproduced. | visible ratio `1.000`, similarity `1.000`, links `82/82`, DOM ratio `1.000`. Match even ignored script error `7`. | 2026-07-23 |
| `cao-home` | `cao.go.jp` | `public`, `government` | `match` | visible body, link, input, and DOM matched in live rerun, and the delayed navigation difference that remained as minor last time was not reproduced. | visible ratio `1.000`, similarity `1.000`, links `57/57`, DOM ratio `1.000`. | 2026-07-23 |
| `epark-home` | `epark.jp` | `service`, `lifestyle` | `match` | Reapply safe constants/bootstrap script after runtime reset to eliminate missing `API_PATH` in subsequent Vue bundles. Search UI and controls expanded. | visible similarity `0.894`, visible ratio `0.821`, visible links `147/185`, input controls `6/6`, DOM ratio `0.750`. bootstrap replay `5` times for runtime reset `5` times. | 2026-07-20 |
| `bbc-weather-home` | `bbc.com/weather` | `service`, `weather` | `match` | Stable benchmark. same-site navigation probe is also valid. | same-site nav probe successful. | 2026-07-16 |
| `weathercom-home` | `weather.com` | `service`, `weather` | `match` | Title, visible body, links, input controls, and DOM matched in current rerun on Friday, July 24, 2026. visible ratio `1.000`, similarity `1.000`, visible links `70/70`, input controls `1/1`, DOM ratio `1.000`. | QuickJS total about `13.8s`, Chrome total about `38.7s`. | 2026-07-24 |
| `weather-gov-home` | `weather.gov` | `service`, `weather` | `match` | Even in the live rerun on Friday, July 24, 2026, the title, visible body, link, controls, and DOM match. | QuickJS total drops to around `3.2s`, `external_script_fetch` around `1.5s`, `script_eval` around `1.9s`, `page_event_dispatch` around `1.1s`. The comparison result remains `match` even on Chrome benchmark. | 2026-07-24 |
| `allrecipes-home` | `allrecipes.com` | `service`, `lifestyle` | `match` | Stable benchmark. | Easy to use as a regression confirmation destination. | 2026-07-16 |
| `mapquest-home` | `mapquest.com` | `service`, `maps` | `match` | A lightweight map/search benchmark. | Lightweight benchmark. | 2026-07-16 |
| `ikea-us-home` | `ikea.com/us/en` | `shopping`, `service` | `match` | In the rerun on Sunday, July 26, 2026, we returned to the `match` judgment while maintaining the retail shell and main links. visible ratio `0.849`, similarity `0.867`, visible links `189/184`, input controls `22/28`, DOM ratio `0.389`. The current reason is only `quickjs DOM tree is much smaller than chrome`, but the visible body, links, and controls are within the benchmark tolerance range. | QuickJS embedded scripts total approximately `17.5s`, Chrome browser render approximately `10.2s`. Keep `match` after synthetic search/control recovery of current branch. | 2026-07-26 |
| `target-home` | `target.com` | `shopping`, `service` | `match` | Title, visible body, link, controls, and DOM remain consistent even on rerun on Sunday, July 26, 2026. On a moderately rich page where the main text is already readable, more than 40 delayed external scripts can be generic skipped before being fetched, and QuickJS returns a richer branch than Chrome. | All items of `embedded_delayed_scripts=56` are `skipped_delayed_external_scripts=56` with QuickJS-only rerun. From `_prune_inline_loading_placeholders()`'s hotspot improved base `14.0s`, in branch-only follow-up on 2026-07-26, `embedded_scripts_total` is about `5.60s -> 5.33s` compared to main on the same day due to static-page judgment execution-scope metrics cache. `script_eval` is about `0.21s`, hydration is about `1.60s`. The remaining cold costs are mainly fetch and post-script DOM cleanup. | 2026-07-26 |
| `zillow-home` | `zillow.com` | `service`, `real-estate` | `match` | Stable benchmark. | real-estate benchmark. | 2026-07-16 |

## Skipped Targets

Collect examples excluded, or to be excluded, from canonical audits because of captchas, challenges, or anti-bot checks here.

| site_id or label | domain | observed on | status | reason |
| --- | --- | --- | --- | --- |
| `jreast-home` | `jreast.co.jp` | 2026-07-16 | skip | raw fetch is based on `403 Access Denied` shell and is unstable as a benchmark for generic QuickJS improvement. |
| `tokyometro-home` | `tokyometro.jp` | 2026-07-16 | skip | Raw fetch is closer to `403 Access Denied` shell, and the fluctuation of access control is more dominant than the difference in quality. |
| `rikunabi-home` | `job.rikunabi.com` | 2026-07-19 | skip | QuickJS/Chrome both resolve to challenge/interstitial branch and cannot be compared for generic runtime improvements. |
| `google-search` | `google.com/search` | 2026-07-16 Previous regression corpus | skip | Both modes tend to lean toward challenge/interstitial, making them unsuitable for canonical benchmarks for quality comparison. |
| `booking-home` | `booking.com` | 2026-07-16 Previous regression corpus | skip | A typical example of a challenge/interstitial branch that is easy to enter only on the QuickJS side. The fluctuation of bot judgment is more dominant than general improvement. |
| anti-bot-heavy commercial homepages removed during cohort curation | multiple | 2026-07-16 | skip | Raw fetch shows 403 / 429 / access denied shell sites. Site names that have been finalized will be added individually to this table in the future. |

## Suggested Next Targets

- `jalan-home`
  The current rerun on 2026-07-24 is `exit -11` and `quickjs_error` for both QuickJS and Chrome. In the code path as of Monday, July 27, 2026, the isolated audit subprocess now leaves the previous phase such as `fetch` / `parse` / `execute_embedded_scripts` / `snapshot` on stderr, so the next time you rerun, first determine in which phase the crash / segfault occurred.
- `navitime-home`
  In QuickJS-only rerun on 2026-08-09, embedded scripts total dropped to about `40.42s`, but script eval about `36.14s` and async / DOMContentLoaded about `32.36s` are still dominant. Chrome comparison has not been completed, so the quality classification remains unchanged. Next time, we will re-measure large same-origin bundle and post-load async drain under the same conditions including Chrome comparison.
- `rakuten-travel-home`
  The current rerun reports `major_gap`. The search shell and input controls `108/112` are present, but visible links `157/358` and body content are insufficient. Investigate missing travel feed/listing branches in runtime/hydration.
- `walmart-home`
  The current rerun reports `challenge_branch`. QuickJS returns body content, while the Chrome policy reaches an interstitial. Reassess whether this remains valuable as an active canonical benchmark.
- `skyscanner-home`
  The current rerun still reports `challenge_branch`. QuickJS returns normal body content, while the Chrome policy reaches a challenge. Return it to active focus and assess whether it remains worth tracking as a benchmark.
- `webmd-home`
  The current rerun still reports `challenge_branch`. Both QuickJS and Chrome enter challenge/interstitial branches. After returning it to active focus, reassess whether normal body content can be compared.
- `accuweather-home`
  The current rerun still reports `chrome_error` with `403 Forbidden`. QuickJS recovers the body, but Chrome comparison is unstable. Decide whether to retain it in active focus or move it to `Skipped Targets`.
- `ndl-home`
  `minor_gap` in live rerun on Monday, July 27, 2026. Even after the current branch's generic picker/select launcher recovery, the input surface remained at `4/8`, and the residuals were the header search's scope selector and 3 datepicker disclosures. Next, instead of extracting the empty launcher, we will carve out a path that leaves the entity control in the visible tree after the delayed widget mount.
- `yahoo-news-jp-home`
  `major_gap` in live rerun on Monday, July 27, 2026. QuickJS has links `107/154` and input controls `2/4`, and has not been able to fully recover the hero / recommended story branches that Chrome has. The hydration cost itself is small, about `114ms`, so next time, prioritize the insufficient extraction of the discovery/news feed branch over the runtime/hydration speed.
- `walgreens-home`
  The current rerun reports `minor_gap`. Compared with links `114/122`, input controls `0/4` and DOM ratio `0.396` are weak. Use this as a representative target for recovering hidden/synthetic retail input surfaces.
- `jaxa-home`
  `minor_gap` in live rerun on 2026-08-09. Although controls `4/4` was maintained, links `81/96` did not generate the "featured keyword"/feed node itself in the QuickJS DOM. Next, we will determine whether it is possible to collect the network payload / discovery container after executing the large webpack bundle without adding a site-specific fallback using the general-purpose runtime.
  Although it is not a canonical cohort, it is fixed as a target for continuous performance improvement. The target URL is `https://ja.wikipedia.org/wiki/%E3%82%B5%E3%83%B3%E3%83%89%E3%83%9E%E3%83%B3_(%E3%83%B4%E3%82%A1%E3%83%BC%E3%83%86%E3%82%A3%E3%82%B4)`. As a long article in the Japanese version of Wikipedia, it is used to observe DOM construction, text extraction, and CSS application costs on a live page.
- `FreeBSD` (Wikipedia article benchmark)
  Although not a canonical cohort, it is useful as a target for continuous runtime performance observation. The target URL is `https://ja.wikipedia.org/wiki/FreeBSD`. In the branch experiment on 2026-07-27, named window property sync was run only when dirty, and on the same live page `execute_embedded_scripts()`, the embedded scripts total was about `44.67s -> 44.42s`, and the script eval was about `564ms -> 555ms`. In the QuickJS runtime unit measurement, the first full sync was about `463ms`, and the 10 clean skips was about `0.018ms` in total, and we were able to almost eliminate all DOM rescanning of unchanged eval.
  A subsequent branch experiment added a cheap gate for post-hydration restoration, avoiding full visible-text probes on healthy marker bodies. On the same live page, embedded scripts fell to about `35.54s -> 27.02s`, hydration to `14.81s -> 6.59s`, and `should_restore_initial_body_after_hydration` to `8.99s -> 0.72s`. Later, deferred hidden-DOM recovery when substantial content exists and replaced exact visible-text scans in expensive page-event/DOMContentLoaded decisions with inline previews.
  Finally, added a generic early return that does not start embedded scripts/hydration on static-rich pages with sufficient initial body content, links, and controls. On the same live `FreeBSD` page, `embedded_scripts_total` fell to about `741ms`, `hydration` to `0ms`, and `embedded_scripts_skipped_for_static_page=1`. In current benchmarks, triggering static-rich detection is the largest performance improvement, almost eliminating QuickJS runtime costs on Wikipedia articles with sufficient initial readable HTML.
  Later live reproduction still showed rendering hanging after QuickJS had finished. Measurements identified full-DOM rescans for normal-renderer `aria-labelledby` resolution and full CSS selector matching, including external stylesheets, as dominant costs. A 2026-07-27 branch experiment cached renderer-side `id` / `aria-labelledby` indexes in state and added a lightweight static-rich rendering path using only inline styles and hidden attributes. It also replaced expensive `form_controls()` calls in `execute_embedded_scripts()` static-rich detection with a cheap control scan.
  In a further follow-up that day, added per-document `label[for]` / `id` / generated-control-ID indexes to `interactions` so synthetic-button checks and `_control_label()` no longer return to `find_all()` / full-DOM traversal every time. On the same live page, `render_normal_with_metadata()` fell to about `914.939ms -> 87.882ms` while preserving body length `64534`, links `1508`, and controls `21`.
  Direct API measurements that day (`fetch_resource` -> `parse_document` -> `execute_embedded_scripts` -> `render_normal`) reduced `execute_embedded_scripts()` on the same live `FreeBSD` page to about `21.253ms`, normal rendering to `87.882ms`, fetching to `539.825ms`, and parsing to `54.035ms`. The rendering bottleneck shifted from full stylesheet/CSS matching on static-rich pages to repeated full-tree interaction-metadata lookups. For pages such as Wikipedia with sufficient body HTML, lightweight rendering plus document-level interaction lookup caching was an effective first option.
  Do not consider API-only timings sufficient for performance acceptance; the final criterion is TUI responsiveness. If `--mode text` or `render_normal()` is fast but the TUI is slow, investigate downstream hot paths such as `_build_browser_page()`, pane detection, viewport updates, and buffer construction. If static-rich/lightweight detection does not trigger, include the `link_count` threshold in the investigation. Pages such as Athlon 64 can have sufficient readable content and stylesheets yet miss the lightweight path solely because of `link_count`, slowing both QuickJS and the TUI. Future reruns should use TUI responsiveness as the acceptance criterion and revisit the entire static-rich check, including `link_count`, on slow pages.
- `note-home`
  Although not a canonical cohort, it remains useful as a stress test for runtime performance. Used to separate async drain, external script fetch, and huge bundle eval.

## 2026-11-13: Phase 17 resource policy and body-stable termination

- Comparison was made with Python 3.12.15, QuickJS, no browser-render, and no script cache. There was a synchronization conflict with `.venv` in Dropbox, so the verification environment was separated into `UV_PROJECT_ENVIRONMENT=/private/tmp/tweb-phase17-venv`.
- Reproduced a page on a real local HTTP server with a body-content API, beacon, telemetry, image requests, and surrounding DOM updates every 50ms. Each unnecessary endpoint adds 30ms of latency. `render_efficiency=False` made 5 HTTP requests and ran 25 timers in about 136.48ms; default `True` made 2 HTTP requests and ran 21 timers in about 14.75ms. The body API remained enabled, while 3 unnecessary requests were blocked before fetching. Post-load drain ended with `body-stable` (800ms quiet time, 16 timers), and `main_only=True` output matched exactly at 1025 characters. This single comparison under artificial latency does not establish a general real-site speedup.
- In the live API comparison of `https://www.jaxa.jp/`, it takes about 34.91s when disabled and about 34.77s when enabled. Both had a visible body of 1142 characters, the same SHA-256, total links 278, and total controls 13. There were 0 cases of unnecessary communication cutoff and main text probe, and the existing timer budget was applied first. We do not judge that this optimization has reduced the cost of running large bundles on this site.
- This compares enabled/disabled behavior within QuickJS, not differences against Chrome. JAXA's canonical classification and cohort state were not updated; the active table and `quickjs_audit_sites.json` remain unchanged.
- Focused regressions cover body changes, replacements of equal length, delayed updates, continuing content API requests, hidden/sparse content, probe limits, debug limits under beacon floods, and fetch/XHR preservation. Verified body-stable termination through the API's embedded-script path.
- All 897 tests passed. A final adjustment then paused efficiency optimizations during explicit button operations to preserve existing network permissions; all 245 related tests passed (16 Phase 17 tests and 229 existing QuickJS tests).
- Remaining verification boundaries: early termination/excessive waiting on more JS-heavy sites, manual TUI operation, MIME/redirect-based classification, and completion checks without explicit main/article regions. This does not forcibly interrupt all normal script evaluation.

## 2026-10-19: Phase 16 TUI page assembly

This TUI performance verification is outside the canonical audit cohort. Quality classifications and `active_site_ids` are unchanged.

### Measurement conditions

- Baseline: `7809c38`. Targets are HTML fetched that day from `https://www.python.org/about/` (HTTP 200, 41,239 bytes) and `https://docs.python.org/3/tutorial/` (HTTP 200, 37,315 bytes).
- Replayed the same fetched HTML as `Resource` and directly measured `_render_document()` → `_build_browser_page()` → `_rebuild_current_page_view()` at width=80. QuickJS execution and initial HTML fetching are excluded. CSS fetching/parsing follows each operation's normal path.
- The table below contains 1 run per version as reference values. Network/CSS cache variability means small initial renderer/build differences should not be treated as improvement rates.

| subject | renderer Before change → After change | page build Before change → After change | view rebuild on the same page Before change → After change | pane groups |
| --- | --- | --- | --- | --- |
| Python About | 287.3 → 301.2ms | 1.75 → 2.10ms | 1.77 → 0.46ms | 0 |
| Python Tutorial | 131.8 → 140.3ms | 72.13 → 81.53ms | 57.84 → 0.52ms | 3 |

On single-column Python About, downstream page build took about 2ms, so downstream processing did not explain the gap from renderer timing. Python Tutorial still has initial pane detection/region merging costs, but view rebuilds no longer repeat detection, source-buffer generation, or pane rendering.

### Check with Textual TUI

Replayed the same Python Tutorial HTML at 100 columns × 30 rows using Textual `run_test()`. Replaced HTML fetching and embedded JS execution to isolate Phase 16 display processing, placed the cursor on a rendered pane row, and used `pilot.press("v")` to focus/restore.

- The full-page view had pane groups `3`. Final page build took about `188.4ms` (pane detection `144.9ms`, pane region merging `39.9ms`).
- Page build took about `10.6ms` on focus and `0.82ms` on restore. The full body matched the original, and other panes were removed while focused.
- Viewport updates in the same run took about `0.9–7.5ms`. Key delivery and event-loop waiting are excluded from the phase timings above.
- Responsiveness and visual checks in a real terminal were not performed. Wikipedia `Athlon_64` returned HTTP 403 and was not used for that day's live comparison.

### Regression verification and remaining boundaries

`python -m unittest tests.test_tui tests.test_normal_renderer tests.test_cli` has **271 tests passed**. Includes layout hint only in hidden/template, omitting detection of static-rich pages, true multi-pane for external CSS, cache reuse and resize/discard when updating DOM, timing output, and cancellation.

You can follow the same steps with `tui timing phase=... elapsed_ms=...` and `BrowserPage.build_timings_ms` of `--debug`. `page_build` is the total including child phases, and renderer, controls/links, and viewport are measured separately. The cache is reused only by switching between the same page and the same width using `v`. Recreate rerender, resize, and background render after new load and mutation.

Future optimizations include initial multi-pane full-CSS reevaluation, lightweight detection for articles with fewer links, and forced interruption within individual phases.

### Regression verification when integrating main

Integrated main commit `b5b5273` and propagated the image-omission option to pane-subtree rendering and caching. Cache reuse now also requires matching image-display settings. All **504 tests passed** across TUI/normal renderer/CLI/JS runtime, plus **1 test passed** for cache invalidation when changing image-display settings.

## 2026-10-19: Common Apollo reference resolution

We compared the Kakuyomu table of contents extraction of `1688457` and the modified version using a common resolver 1 time each using a synthetic Apollo cache on the same QuickJS runtime. Works, table of contents, chapters, and episode entities were generated, and all extracted items were confirmed to match. Does not include HTML acquisition, bundle execution, or TUI rendering of the actual site. The canonical cohort quality classification and `active_site_ids` have not changed.

| synthetic data | Before change | After change | Extraction result |
| --- | --- | --- | --- |
| 100 episodes | 0.82ms | 6.55ms | 100 matches |
| 1,000 episodes | 5.16ms | 58.34ms | 1,000 matches |

After sharing the resolver, extraction alone is slower because it performs more per-entity runtime reads. Avoid transferring the entire cache; read only specified fields of entities reachable from the target work. Bound depth, work, and transferred characters per 1 entity. Real-site rendering quality and total page time were not audited, so the table does not establish live performance.

## 2026-10-19: Remove note-specific API supplementation and URL guessing

Confirmation outside the canonical cohort. The HTML obtained from `https://note.com/` and `https://note.com/topic/computer_it` (100,065 characters / 263,055 characters, respectively) was retained and the same HTML was played back after changes to `ed98f23`. `browser_render_policy="never"`, login cookies not captured. External JS/CSS uses the normal fetch/cache route.

| subject | Number of visible text characters Before change → After change | Total number of links Before change → After change | Preserve unique links in original HTML | Displaying embedded article titles |
| --- | --- | --- | --- | --- |
| note home | 1,694 → 1,970 | 106 → 39 | 27 / 27 | 20 / 20 |
| note computer_it topic | 3,481 → 2,739 | 139 → 97 | 85 / 85 | 24 / 43 |

Matched unique links by `(label, href)`. The decrease in total links includes removal of URL synthesis from `key` / `urlname` / `engName`. Display articles without supported URLs as text. All original HTML links remained on both pages. The topic page retains the generic item limit; this does not mean all 43 embedded articles were displayed.

Fixed API calls recorded in the home page's runtime JSON decreased from 6 to 0. The topic page also records 0 additional API calls after the change. Page-issued fetch/XHR remains enabled; delayed JSON fetch regressions verify collection through the shared collector.

Resolved `SyntaxError: invalid property name` in both page bundles through class static block syntax conversion, reducing recorded script errors from 1 to 0. On the topic page, generic processing restored the main element removed by the runtime and preserved the original input UI. This does not verify a complete React mount or reproduction of an authenticated feed.

Total times from 1 run each were home `4.781 → 11.016s` and topic `2.691 → 4.263s`. External-resource network/cache conditions were not fixed, so these are not performance improvement rates. Chrome comparison and real-terminal visual verification were not performed. Canonical cohort classifications and `active_site_ids` were unchanged.

`make test` passed 864 tests. Suppression of URL composition, adoption of a unique DOM anchor, JSON fetch delay in page publication, recovery of the main text of Flight articles that do not have a URL, restoration when main is lost and preservation of new input UI, and retention of class static block initialization order / private field / `super` / literal were included in the regression targets.

## 2026-10-19: Select body/navigation supplementation targets using HTML/ARIA/structure

After changing to `6745335`, I played the above note home / computer_it topic HTML that was acquired on the same day. Do not change the HTML and do not use Chrome fallback and login cookies. This was confirmed outside the canonical cohort, and the classification/`active_site_ids` has not been changed.

| subject | Number of visible text characters Before change → After change | Total number of links Before change → After change | Preserve unique links in original HTML | Display of article title Before change → After change |
| --- | --- | --- | --- | --- |
| note home | 1,970 → 1,708 | 39 → 40 | 27 / 27 | 20 / 20 → 20 / 20 |
| note computer_it topic | 2,739 → 2,690 | 97 → 97 | 85 / 85 | 24 / 43 → 24 / 43 |

The body-character decrease includes removal of links duplicated into supplementary body text after section classification. All previously displayed article titles and original HTML `(label, href)` pairs remain. The topic item limit is unchanged. Both pages recorded 0 script errors.

Directly measured only body/navigation target lookup on the raw-HTML DOM: home about `0.68ms`, topic `24.64ms`. During implementation, topic took about `134.82ms`; reduced redundant traversal that checked ancestors before excluding noncandidate nodes. These are 1-run reference values, not total-time improvement rates.

Reference total page-processing times were home `4.474 → 4.842s` and topic `2.448 → 2.793s`. External JS/CSS network and cache conditions were not fixed. Visual verification in a real terminal and Chrome comparison were not performed.

Regression fixtures declare purpose through HTML/ARIA and section roles, verifying consistent placement despite changes to domains, classes, and URL formats. Separate cases ensure unknown empty divs, equally ranked candidates, hidden regions, input UIs, and related-article lists are not mistaken for navigation. Unidentified panes are appended to main content; previous left/right placement based only on class names is not preserved.

Final `make test` verification passed 879 tests, including 15 new region-detection/supplementation tests.
