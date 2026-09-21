# ComfyUI Prompt Builder V2

A preset and wildcard prompt builder for Krea 2 style prompts. You build a prompt from a large library of ready-made
phrases (subject, clothing, pose, setting, camera, lighting, style), by hand or with one press of a **Wildcard** button, and
copy the finished, well-formed prompt into ComfyUI.

There is **no AI model** involved. Prompts are assembled with fixed sentence patterns, so it is instant, works offline, and
gives the same wording for the same picks. Everything runs on your own computer and nothing is sent anywhere.

A prompt looks like this (one Wildcard press):

```
Subject: A woman in her fifties with deep brown skin and hazel eyes. She has a classic French twist with smooth polished vivid red hair and an elegant vertical silhouette. She wears bold red lipstick with clean defined brows. She has a focused expression.

Clothing: She wears a fitted charcoal grey corset worn with black high-waisted jeans, silver chain necklace, hoop earrings and combat boots.

Action: She is lying diagonally across the bed with one arm beneath her head and the other resting loosely on the mattress.

Environment: The setting is a modern apartment.

Camera: The camera is positioned at approximately the model's seated chest height, entire seated figure visible including feet and surrounding furniture.

Lighting: The scene is lit by golden hour sunlight.

Style Details: The image has rose-gold color grading, warm pink highlights, creamy skin tones, subtle bronze shadows, luxurious romantic editorial finish.
```

## What it does

- **Builder** - one row per part of the prompt, each with **Lock**, **Choose...**, **Reroll** and **Clear**. The **Wildcard**
  button fills everything that is not locked. It picks a pose first, then a setting and clothing that fit it (bed poses get
  bedrooms, pool poses get pools, swimwear only appears by the water, and so on). Options: how much detail to add, which
  levels of list to use, and whether to allow presets that describe a whole scene.
- **Character LoRA friendly** - the eye colour row can be set to **None**, so nothing about eye colour appears in the prompt.
- **Saved** - keep prompts with notes, load them back into the Builder exactly as they were, search them, export them.
- **Library** - browse all the presets (about 9,000, in 117 lists), filter by level, switch lists and entries on or off, and
  **add your own lists and entries**. Your additions survive updates.
- **Reset library** - one button puts the library back exactly as it was on a first install (a backup is made first).
- **Image Analyser** - browse a folder of generated PNGs and see the prompt, negative prompt, model, LoRAs, seed and sampler
  settings stored in each image (ComfyUI and Automatic1111-style images), with a **Copy prompt** button.
- **Help** - a full guide inside the app. Press F1.

Adult content is included but **off by default**: the adult lists are hidden and never used until you tick **Adult content**.
(A release built with `--strip-adult` has no adult lists at all; see "Building a release".)

## Requirements

- Windows 10 or 11 (the launcher is a Windows batch file; the app itself is plain Python and Qt).
- **Python 3.10 to 3.14** from [python.org](https://www.python.org/downloads/windows/). During setup, tick
  **Add python.exe to PATH**. Python 3.9 or older, and 3.15 or newer, will not work.
- An internet connection **once**, on the first start, to download PySide6 (a few hundred MB). After that the app works
  offline.
- About 0.7 GB of disk space for the app's private environment.

Nothing else needs installing: the launcher takes care of it.

## Install and run

1. Install Python (see above).
2. Extract the zip anywhere you like. Keep the whole folder together.
3. Double-click **`run_promptbuilder.bat`**.

The first start takes a few minutes: it finds Python, creates a private `.venv` folder inside the app folder, installs PySide6
into it, builds your library and opens the app. Every later start opens straight away.

To start it from a terminal instead: `.venv\Scripts\python.exe main.py`.

## Your data

Everything of yours lives in one folder, `data/`, next to the app:

| File | Contents |
| --- | --- |
| `data/library.db` | your own lists and entries, saved prompts, on/off choices and settings |
| `data/backups/` | a backup of the library, made automatically before every **Reset library** (the newest 10 are kept) |

Back up `data/library.db` if your own presets or saved prompts matter to you. To go back to an earlier copy, close the app
and replace `library.db` with a file from `data/backups/` (keep the name `library.db`).

The preset data that ships with the app is in `build/out/` and is never changed by the app.

## Updating

There is no automatic updater: you swap in the new files yourself. Your own data lives in `data/` and the installed PySide6
in `.venv/`, and a release zip contains neither, so updating never touches them. To see which version you have, open
**Help → About**.

**Simplest: extract over the top.**

1. Close the app. (Optional: copy `data\library.db` somewhere as a backup.)
2. Extract the new zip. It holds one top-level folder, `ComfyUI-Prompt-Builder-V2-<version>`; copy the *contents* of that
   folder into your existing app folder, so you do not end up with a folder inside a folder.
3. Choose **Replace the files in the destination** when Windows asks.
4. Start the app with `run_promptbuilder.bat` as usual. The existing `.venv` is reused, so nothing is downloaded again.

**Or start fresh:** extract the new version into a new folder and copy your old `data` folder into it. This downloads
PySide6 again, because the new folder has no `.venv`.

Either way, your own lists, entries, saved prompts, on/off choices and settings are kept. If the new version ships changed
presets, it notices at its first start and refreshes the library, keeping all of that. (To force a refresh at any time:
`.venv\Scripts\python.exe main.py --rebuild-library`.)

## Rebuilding the library from your own text files (advanced)

The presets ship pre-built. If you have the source text files (the release built with `--with-sources` includes them), the
importer turns them into the library:

1. `.venv\Scripts\python.exe -m pip install -r build\requirements-build.txt` (a spell-checker used for typo reports).
2. Put your preset text files under `Pre-sets\`, in folders named for what they hold (for example `Clothing`, `Pose`,
   `Camera`, `Lighting`, `Enviroments`). One preset per line. Files you draft yourself can go in `Drafted Presets\`.
3. `.venv\Scripts\python.exe build\import_presets.py`. It never modifies your text files, and writes the library data to
   `build\out\` together with a report of anything it dropped or fixed.
4. Two spreadsheets you can edit control how each file is treated: `build\files_map.csv` (section, level, group, whether it
   covers other sections, and so on) and `build\text_fixes.csv` (approved typo fixes). They are created on the first run and
   never overwritten.
5. Start the app. It sees the changed data and refreshes the library.

## Building a release

```
.venv\Scripts\python.exe build\make_release.py
```

This writes `dist\ComfyUI-Prompt-Builder-V2-<version>.zip` (and a `.sha256` file), then unpacks it in a temporary folder and
checks that it starts and produces prompts. It only packs an explicit list of files, so your `.venv`, your `data` folder and
your example prompts can never end up in it. Options:

- `--strip-adult` builds a clean release with no adult lists at all.
- `--with-sources` also includes the preset text files, the importer and the tests.

## Tests

Each suite builds its own throwaway database and never touches `data/`. Run any of them with the app's Python, for example
`.venv\Scripts\python.exe tests\builder_test.py`:

| Suite | Covers |
| --- | --- |
| `smoke_test.py` | the library database and browser |
| `builder_test.py` | the Builder, wildcard, locks, rerolls, eye colour None |
| `user_presets_test.py` | your own lists and entries |
| `reset_test.py` | Reset library and its backups |
| `saved_prompts_test.py` | saving, loading, notes, export |
| `help_test.py` | the Help tab (every button it names exists, its example sentences are true) |
| `analyser_test.py` | the Image Analyser |
| `startup_test.py` | first start, updates, and the real `main.py` |
| `release_test.py` | the release builder |

## Project layout

```
main.py                  starts the app
run_promptbuilder.bat    the Windows launcher (creates .venv, installs PySide6, starts the app)
app/                     the application (PySide6)
build/out/               the shipped preset data
build/import_presets.py  turns preset text files into build/out (advanced)
build/make_release.py    builds the release zip
tests/                   the test suites
data/                    created on first start: your library, saved prompts and backups
```

## Licence

Copyright (C) 2026 Ezdub69.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as
published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. It is
distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. The full text is in the file `LICENSE`. The preset library is provided
under the same terms.

Built with [PySide6](https://doc.qt.io/qtforpython-6/) (Qt for Python).
