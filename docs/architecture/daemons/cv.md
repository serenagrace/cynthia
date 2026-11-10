# Computer-vision daemon

**Source:** `cynthia/daemons/cv.py` — `CVDaemon`, `Scene`, `CV`, and
`HomeGameTitle`.

## Responsibility

`CVDaemon` reads captured frames, compares them with reference scenes using
SSIM, and publishes the strongest match, scores, and game/hunt state for
commands, overlays, and macros. Work runs at a capped CV frame rate, below
controller priority. OCR is initialized in the child process so its GPU
runtime does not interfere with other processes created by the parent.

`Scene` owns a reference image and crop/scale settings; its comparisons use
cached reference statistics, optional thumbnail rejection, and an optional
minimum interval between comparisons. `CV.scrape_text` OCRs a crop and retries
with inverted colors when the first pass returns no text.

## State and interactions

The daemon publishes the top scene scores and a `scene_matched` signal for a
macro ternary. Recognized home/AFK-home scenes update the selected game title
and `home`/`playing` flags. Bundled scenes also drive specific BDSP encounter
timing and possible-shiny stop behavior. Hunt log path and relevant selection
state are preserved across manager restarts; `set_hunt` changes the active
encounter log and `set_self_encounter` selects the self-encounter flow.

Home-screen title recognition uses a maintained catalog, not an exhaustive
game database. It strips Nintendo Classics/Switch Online branding, keeps
compatible fragments stable, debounces a new known selection for 0.8 seconds,
and preserves ambiguous or unknown OCR text rather than forcing a guessed
title. See [the OCR reference](../../development.md#home-screen-game-title-ocr)
for the catalog scope and example.

## Extension and tests

Add a reference scene only when its visual match and score semantics are
understood; define its crop and matching rate with `Scene`, then connect the
match to the smallest relevant state transition. Do not treat OCR or SSIM as
universal game-state detection. Use `tools/scene_setup.html` to inspect/crop
reference frames.

The targeted tests are `tests/test_cv_scenes.py` and
`tests/test_cv_game_titles.py`. CV state is consumed by
[`NXBTDaemon`](nxbt.md), [`StatusCog`](../cogs/status.md), and
[`TwitchInfoCog`](../cogs/twitchinfo.md).
