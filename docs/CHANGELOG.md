# Changelog

## v0.4 (in progress), Stage 0 foundation + realistic city
### Foundation (Bible stage 0)
* Project renamed **GLASS CITY**; development bible v1.0 added under `docs/`.
* Git repository; generated data kept out of git; pipeline scripts and hand-authored data moved into the repo
  (`tools/pipeline/`, `source_data/`).
* `tools/build.sh` (one-command city rebuild), `tools/run_tests.sh` / `.bat` (all tests),
  `tools/run_benchmark.bat`.
* Automated tests: 9 in-game tests and 7 data tests.
* F3 performance overlay and `--benchmark` mode with JSON report; budgets in `docs/PERF_BUDGETS.md`.
* Docs: architecture, build, coding standards, data sources and licence register, performance budgets.
### City
* Whole map rebuilt on Lucas County footprints (132k) with county records: era- and material-correct house
  siding/brick, porches, garages, roof shapes; apartments, offices, hotels, churches and schools styled by record.
* Downtown: exact LiDAR massing for 670 buildings (0.5 m grid) with squared-up outlines; hand overrides with sources
  (One SeaGate tower, DiSalle, Four SeaGate, ProMedica Senior Care, Hotel SeaGate removed, Secor carved out of the
  convention centre).
* Facade shader: parametric windows, brick/stone coursing (with distance fade), storefronts and curtain walls;
  25 buildings matched to photos or published facts; era brick palettes; Italianate arched windows on pre-1900 brick.
### Bars
* 48 bars, 15 brands: neon signs, awnings and doors on the street; an enterable themed interior per brand (E to enter/leave).
### Fixes
* Leaving a bar after the world had re-centred put the player in the wrong place. Fixed: the return point is now
  stored in world coordinates (covered by test `bar_exit_after_origin_rebase`).
* Standart Lofts facade had been put on the wrong building (now 34 S Erie).

## v0.3: real-looking Toledo
LiDAR heights and roofs, landmarks, Anthony Wayne Bridge and Skyway, ballparks, aerial imagery, parody sign names.

## v0.2: whole city
## v0.1: downtown prototype
