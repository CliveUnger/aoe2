# AoE2:DE Replay Analysis Workspace

Parses `.aoe2record` replays (Feral macOS port, under
`~/Library/Application Support/Feral Interactive/.../Age of Empires 2 DE/<steamid>/savegame/`)
using [mgz](https://github.com/happyleavesaoc/aoc-mgz).

## Setup
mgz is checked out as an **editable clone** at `./aoc-mgz` on branch
`support-save-version-68`, which carries our save_version 68 fix (see below).
```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ./aoc-mgz        # editable: edits in ./aoc-mgz are live + git-tracked
```
To recreate the clone: `git clone https://github.com/happyleavesaoc/aoc-mgz.git`
then `git checkout -b support-save-version-68` and apply the patch below.

## Usage
```bash
source venv/bin/activate
python analyze.py "<path to .aoe2record>"   # human-readable game summary
python parse.py   "<path to .aoe2record>"   # JSON header dump
```

## ⚠️ Local patch: save_version 68 support (mid-2026 DE patch)

Our replays are DE **save_version 68.0** (build v101.103.48987 / 48086, `VER 9.4`).
As of 2026-07-22, **no released mgz (PyPI 1.8.51 == git HEAD) supports 68** — it only
reaches ~66.3/67. We reverse-engineered the delta and patched the installed mgz.
The v68 format adds exactly two things vs 66.3:

1. **One trailing `de_string` per player** (empty; likely a clan-tag/decoration field).
2. **8 trailing bytes** at the end of the `de` header block, right before the `ai` section.

These are applied in the venv in **both** parser paths:

- `mgz/header/de.py` (full/construct parser)
  - in `player` struct, after `unknown_de_64_3`:
    `"unknown_de_68"/If(lambda ctx: find_save_version(ctx) >= 67.5, de_string),`
  - at end of `de` struct, after `ver37`:
    `If(lambda ctx: find_save_version(ctx) >= 67.5, Bytes(8)),`
- `mgz/fast/header.py` (fast parser — this is the one `Summary`/`parse_match` use)
  - in `parse_de` player loop, after `if save >= 64.3: data.read(4)`:
    `if save >= 67.5: de_string(data)`
  - in `parse_de`, inside `if not skip:` after the `ver37` unpack:
    `if save >= 67.5: data.read(8)`

These now live as a **git commit** on `aoc-mgz` branch `support-save-version-68`
(editable-installed), so they survive reinstalls and are PR-ready. `git -C aoc-mgz show`
displays the exact diff. (`de.py.bak` / `patches/` are the earlier standalone-patch
artifacts, kept for reference.)

The clean path forward is to submit these upstream (extends open PRs #139/#142 which
only reached save 67). The full construct parser still fails later in `initial` object
parsing for v68, but `parse_match` (fast path) fully works: header + body + actions.
