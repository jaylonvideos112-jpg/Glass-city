# Coding standards

## Task discipline (Bible §18)
* One small, verifiable feature per task. Before coding, write down scope, dependencies, files likely to change
  and acceptance criteria. After coding, report files changed, tests run, known limitations and doc updates.
* Don't silently change a LOCKED decision in the bible. Mark unknowns as undecided.
* Don't build on a failing foundation: `tools/run_tests.sh` must pass before a change is committed.

## GDScript
* Godot 4.3, static typing wherever the type is known (`var x: float = ...`); `:=` only when the right side is typed.
* One responsibility per script; file header `##` doc comment says what it owns.
* Data tables (`const THEMES := {...}`) instead of hard-coded branches, so content ports to Unreal.
* Positions kept across frames are **world coordinates** (see ARCHITECTURE.md, origin rebasing).
* No per-frame allocations in hot paths; reuse materials (`bars.gd` caches by key).
* Tabs for indentation (Godot default).

## Python pipeline
* Python 3.11+, dependencies in `tools/pipeline/requirements.txt`.
* Each script starts with a docstring holding a `usage:` line. Inputs are arguments or env vars, never hard-coded paths.
* Never put personal data (emails, owner names) into requests, headers or outputs.
* Outside data: add it to `docs/DATA_SOURCES.md` first.

## Naming
* Files: `snake_case`. Godot nodes: `PascalCase`. Constants: `UPPER_SNAKE`.
* Chunk keys: `X_Z` (e.g. `-10_3`). Facade/LiDAR keys: OSM style `w<way id>` (county footprints are ids 8e9+n).
* Bar brands: exact display names are the keys (`"Tipsy Tom's"`).
* Voice files (future): `m<mission>_<character>_<line>.wav`, e.g. `m01_niko_03.wav`.

## Git
* Branch `main` always passes tests. Commit messages: imperative summary line, then what/why.
* Generated data (`data/`) is never committed. Regenerate with `tools/build.sh`.
* Every user-visible change gets a line in `docs/CHANGELOG.md`.
