# Building GLASS CITY

## Run the game
1. Install **Godot 4.3** (standard build).
2. The game data folder `data/` is generated and not in git. Get it from a release zip, or build it (below).
3. Open `project.godot` in Godot and press F5.

## Rebuild the city data
Needs Python 3.11+ and `pip install -r tools/pipeline/requirements.txt`.

Raw inputs live in a **work folder** next to the repo (override with `GLASSCITY_WORK=/path`):
```
work/
  osm/city/*.json          OSM tiles (fetch_city.py)
  osm/county_osm.json, county_drop.json, county_attach.json   (county_join.py)
  lidar/buildings.pkl      LiDAR per OSM building   (lidar_fetch.py + lidar_process.py)
  lidar/county.pkl         LiDAR per county footprint (lidar_county.py)
  lidar_dt/laz/            full-res downtown LiDAR tiles (lidar_fetch.py, depth 10)
  lidar/downtown_exact.pkl exact downtown massing (downtown_massing.py + dt_overrides.py)
  county/                  Lucas County downloads (footprints shapefile, AREIS database)
  <repo>/                  this repository
```

Common commands (from the repo):
| command | what | time |
|---|---|---|
| `tools/build.sh city` | rebuild `data/` for the whole map from existing intermediates | ~3 min |
| `tools/build.sh downtown` | rebuild only the downtown box (fast iteration) | ~20 s |
| `tools/build.sh massing` | recompute exact downtown massing + overrides, then city | ~15 min |
| `tools/build.sh textures` | regenerate procedural textures (then open Godot or run `godot --headless --import`) | ~1 min |
| `tools/build.sh fetch` | re-download OpenStreetMap tiles | ~30 min+ |
| `python3 tools/pipeline/aerial_fetch.py data/manifest.json data/aerial` | aerial imagery per chunk | ~1 h |

`tools/build.sh city` keeps an existing `data/aerial` folder.

### From scratch (order)
1. `fetch_city.py 41.5706 -83.70 41.7306 -83.45 5 5 osm/city`: OSM tiles.
2. Download Lucas County BuildingFootprints, ParcelsAddress and AREIS from the county Downloads page into `county/`
   (`aspnet.py` automates the page postbacks), then `county_join.py county osm osm`.
3. `lidar_fetch.py S W N E 8 lidar/laz`, then `lidar_process.py lidar/laz osm/city lidar/buildings.pkl` and `lidar_county.py`.
4. Downtown: `lidar_fetch.py <downtown box> 10 lidar_dt/laz`, then `tools/build.sh massing`.
5. `assign_bars.py`: bar placement (writes bars.json; copy into `source_data/`).
6. `tools/build.sh city`, then `aerial_fetch.py`.

## Tests
```
tools/run_tests.sh /path/to/godot        # Linux/macOS
tools\run_tests.bat                       # Windows (set GODOT=C:\path\Godot.exe)
```
Python data tests check the hand-authored data and the build output. In-game tests (headless Godot) check
loading, chunk format, spawning, walking, driving, bar enter/exit (including after an origin rebase) and respawn.
Results go to `tests/out/results.json`.

## Benchmark
See `docs/PERF_BUDGETS.md`.
