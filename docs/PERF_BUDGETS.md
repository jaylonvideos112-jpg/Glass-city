# Performance budgets

Bible §2: set budgets before expanding content; scale features by hardware setting.

**Reference PC:** GTX 1080 Ti (11 GB), 1080p, default settings. Target **60 fps** (16.7 ms).
Entry-level target (later, "Low" preset): 30 fps on GTX 1060 / RX 580 class at 1080p.

| metric | budget (reference PC) | where it's measured |
|---|---|---|
| frame time, average | ≤ 16.7 ms | F3 overlay; benchmark `overall.avg_ms` |
| frame time, 95th percentile | ≤ 25 ms (pass line: 1.5 × budget) | benchmark `p95_ms` |
| draw calls per frame | ≤ 3,000 | F3; benchmark `peaks.draw_calls_max` |
| primitives per frame | ≤ 6 M | F3 |
| video memory | ≤ 6 GB | F3; benchmark `peaks.vram_mb_max` |
| system RAM (engine static) | ≤ 6 GB | F3 |
| loaded chunks | ≤ 400 (street level), wider only for aerial views | F3 |
| chunk build hitch | ≤ 4 ms per chunk on the main thread | (to instrument) |

Values are mirrored in `scripts/perf.gd` (`BUDGET`), which colours the overlay red when over budget.
| traffic cars (full simulation) | ≤ 60 within 280 m (`source_data/traffic.json` budget) | test `traffic_spawns_and_moves_in_lanes` |
| pedestrians | ≤ 80 within 185 m, 1 draw call each | test `peds_spawn_and_walk_on_sidewalks` |
| real lamp lights | 24 nearest the camera | `climate.json` lights |

Future budgets (set before each system ships): NPCs within 150 m, physics bodies, audio voices,
and network bandwidth per player (multiplayer).

## How to benchmark (on your PC)
```
godot --path . -- --benchmark=user://benchmark.json
```
or run `tools/run_benchmark.bat` on Windows. It flies a fixed 54-second route (downtown street, riverfront,
skyline orbit, a neighbourhood street, high aerial), then writes a JSON report and quits. The report holds the
GPU name, average and 1%-low fps, p95 frame time and peak draw calls/VRAM, broken down by segment.
Send the JSON back so results can be tracked in `docs/benchmarks/`.

The build machine used for development renders on the CPU (no GPU), so its numbers are **not** meaningful for
these budgets. Only benchmarks from real GPUs count.

## Known heavy spots (to optimise)
* Every chunk is one mesh with one surface per material. Far away, merged low-detail region meshes (HLOD,
  `scripts/hlod.gd`) take over: 1 draw call per 400 m region. Measured 2026-11-15 (CPU renderer, counts only): peak
  draw calls 4,699 -> 2,711; the busiest view is now a neighbourhood street (2,711). Next: per-chunk mid LOD that drops
  porches/details at 300 m+.
* Facade shader runs on all exact downtown buildings. Cheap now, but needs a distance LOD with plain colour.
* Trees and lamps are MultiMesh per chunk (good). Labels are Label3D (few).
