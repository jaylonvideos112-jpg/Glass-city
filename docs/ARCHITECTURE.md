# Architecture

GLASS CITY is split into an **offline data pipeline** (Python) that turns real-world data into compact chunk files,
and a **runtime** (Godot 4.3, GDScript) that streams those chunks around the player and runs gameplay. The split
is deliberate (Bible §2, "cross-engine preparation"): everything the pipeline produces is engine-neutral data, so
the Unreal 5 rebuild can reuse the pipeline and its JSON/intermediate outputs.

```
 raw inputs (work folder, not in git)          hand-authored (source_data/, in git)
  osm/city/*.json  lidar/*.pkl  county/         facades.json  bars.json  downtown_ring.json  sign_names.csv
            \            |           /                    |
             +---- tools/pipeline/build_city.py ----------+
                               |
                 data/  (git-ignored, rebuilt by tools/build.sh)
                   manifest.json          bbox, chunk list, spawn, places
                   chunks/X_Z.bin         one 200 m x 200 m chunk each
                   aerial/X_Z.jpg         ground imagery per chunk
                   bars_index.json        bar list (copy of source_data/bars.json)
                               |
            scripts/city_streamer.gd  (threads decode, main thread builds meshes)
                               |
     main.gd ── player.gd, car.gd, bars.gd, hud.gd, perf.gd, demo.gd, tests/test_runner.gd
```

## Coordinates and units
* Metres everywhere. Godot +Y is up.
* **Plan coordinates** (pipeline): equirectangular around downtown (lat 41.6528, lon −83.5379). x = east, y = north.
* **World coordinates** (game): x = plan x, z = **−plan y**, y = height. Chunk key `(i, j)` covers
  x ∈ [200i, 200i+200], plan y ∈ [200j, 200j+200].
* **Origin rebasing:** the game keeps the player near (0,0,0) for float precision. `main.world_offset` is the
  world position of the local origin: `world = local + world_offset`. **Anything that stores a position across
  frames must store world coordinates** (the bar-exit bug of 2026-11-14 was a local position kept across a rebase).

## Chunk file format (`data/chunks/X_Z.bin`)
`"TCZ1"` + uint32 raw size + zlib(Godot `var_to_bytes` of a Dictionary):

| key | type | meaning |
|---|---|---|
| `x`, `z`, `ox`, `oz` | int/float | chunk key and its world origin |
| `layers` | Array of Dict | one mesh surface per material: `mat` name, `v`, `n` (PackedVector3Array), `uv` (PackedVector2Array) |
| facade layers | | also `uv2` (floor height, bay width), `color` (wall rgb + material), `c0` (PackedFloat32Array ×4: window w/h, base height, style+8·glass) |
| `col` | PackedVector3Array | collision triangles |
| `props` | Array | `[kind, x, z, ...]` trees, lamps, signs |
| `labels` | Array | `[text, x, z, y]` landmark names |
| `streets` | Array | street segments for the radar and street-name HUD |
| `bars` | Array | `[brand, x, z, yaw, wall_h, wall_len]` bar doors (local −Z points out of the building) |
| `roads` | Array | `[node_a, node_b, x0, z0, x1, z1, class, lanes, oneway(1/0/−1), speed m/s, width m, sidewalk 1/0]` drivable segments (OSM node ids, class 0 motorway … 6 living street) |
| `ix` | Array | `[node, x, z, control, major_class]` intersection control: `signal`, `stop_minor`, `all_stop`, `yield` |

The test `chunk_data_schema` (tests/test_runner.gd) enforces this.

## Runtime modules
| file | responsibility |
|---|---|
| `scripts/main.gd` | bootstrap, input map, camera rig, vehicle enter/exit, respawn, origin rebasing |
| `scripts/city_streamer.gd` | which chunks to load/unload around a focus point; `read_chunk(k)`; mesh/collision/props build; materials |
| `scripts/player.gd`, `scripts/car.gd` | on-foot controller; VehicleBody3D car |
| `scripts/bars.gd` | bar exteriors per chunk, enter/exit, procedural themed interiors (data table `THEMES`) |
| `scripts/hud.gd` | radar, street/district names, prompts |
| `scripts/perf.gd` | F3 overlay, `--benchmark` mode, budgets |
| `scripts/time_of_day.gd` | clock and calendar, sun and moon, sky colours, night lights (windows, lamps), save/load of world state |
| `scripts/traffic.gd` | road graph from loaded chunks (world coords), signal timing, car spawning/despawning, IDM car following, procedural vehicle meshes |
| `scripts/pedestrians.gd` | sidewalk graph from the traffic graph, corner set-backs, divided-road detection, walking/crossing, umbrellas, population |
| `scripts/street_lights.gd` | pool of real lights moved to the lamps nearest the camera |
| `scripts/weather.gd` | seasonal weather chain, blended looks, rain/snow particles, lightning |
| `scripts/demo.gd` | scripted capture modes for screenshots/videos (`--demo=shots/fly/drive/walk/bars`) |
| `shaders/facade.gdshader` | parametric facades (windows, brick/stone, storefronts, curtain wall) from per-vertex data |
| `tests/test_runner.gd` | in-game automated tests (`--test`) |

## Building appearance pipeline (realism)
1. Footprint: Lucas County footprint (or OSM for landmarks and parts).
2. Height and roof: LiDAR per building (`lidar/buildings.pkl`, `lidar/county.pkl`); downtown uses exact 0.5 m-grid
   massing tiers (`lidar/downtown_exact.pkl`) plus hand overrides (`tools/pipeline/dt_overrides.py`, each with its source).
3. Material and style: county wall code, year and class drive era textures for houses. Downtown exact buildings use
   the facade shader, with `default_facade()` guesses replaced by photo- or fact-matched specs from `source_data/facades.json`.

## Engine-neutral vs Godot-specific
* Neutral: everything under `tools/pipeline/` and `source_data/` (including `climate.json`: clock, sun, sky, weather odds), the intermediates, `manifest.json`, the bar theme table.
* Godot-specific: the chunk binary (Godot Variant encoding), `.gd` scripts, `.gdshader`. For Unreal, add an exporter
  that writes the same chunk content as glTF + JSON; the facade shader logic is documented in its header comment.

## Far city (HLOD)
`scripts/hlod.gd`, child of the streamer. Regions are 2x2 chunks. A region's merged mesh is built on a worker thread
from the chunk files (skipping small-detail materials, colouring aerial ground layers from a 16x16 shrink of the photo)
and shown until all of that region's chunks are loaded in detail. The streamer loads detail by whole region.

## Audio
`scripts/audio.gd`: five AudioStreamGenerator channels filled each frame (engine, rain, wind, city, thunder).
`targets()` is the pure mix decision (tested); levels in `source_data/audio.json`.

## World state
`scripts/world_state.gd`: `register(id, obj)`; obj implements `get_save_data()` / `apply_save_data(d)`.
File `user://world_state.json` = `{version, saved_at, sections: {id: data}}`. Add `_migrate` steps when a section changes.

## Public services
`scripts/services.gd` drives special traffic.gd cars: buses carry `path` (route node ids), `loop`, `stops`;
responders carry `path`, `target`, `siren`, `keep`. traffic.gd's `_choose_next` follows `path`, `_step` handles stop
dwell, siren behaviour and scene arrival (signal `scene_cleared`), `_update_pull_over` moves cars aside.

## NPC schedules
`pedestrians.gd`: `area_at()`, `role_weights(area, hour)`, `goal_for(role, hour)`, `goal_point(goal, from)`; data in
`source_data/npc_schedules.json`.
