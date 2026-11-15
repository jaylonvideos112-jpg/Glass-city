# Changelog

## Island countryside and town names (2026-11-15)
* The island is now real data in the middle and made-up countryside around it: about 690 farmsteads (house, barn,
  some silos, driveways), 160 woodlots, 4 villages, 101 real roads continued outward and a 166 km coast road.
* Real data is clipped to the real box (roads split at the edge so made-up roads join the traffic graph).
* New parody town names (Glass City, Pinewick, Kingsferry, ...) and river/lake names (Stone Ridge River, Northfork River,
  Mallard Creek, Lake Glassmere), from `source_data/place_names.json`.
* Build box grown to the whole island (`tools/build.sh`); all real tiles are staged in `osm/city_all`.
* Known limits: no aerial imagery or LiDAR for the made-up land yet (plain green ground); fields are not drawn.

## v0.5 (in progress), Step 3a: time of day and weather
* **Clock and calendar:** 1 real hour per game day (decision log 2026-11-14); 4 seasons × 12 days, weekdays, years.
  HUD shows time, date and weather. F6 = time ×60.
* **Sun path:** computed from Toledo's latitude and the season (DST honoured), so a June sunset is around 9:10 pm and a
  December one about 5:10 pm. A moonlight takes over at night.
* **Sky:** night, dusk and day palettes; a cloud layer that thickens with the weather; golden-hour colours.
* **Night lighting:** lit windows on every textured building (emission masks made by `make_textures.py`) and on
  facade-shader buildings (per-room warm and cool light, occupancy by hour), plus glowing street lamps.
* **Weather:** clear, partly cloudy, overcast, rain, thunderstorm (with lightning), fog and snow; spells follow
  per-season odds from `source_data/climate.json`; rain and snow particles; looks blend over about 45 game minutes.
  F7 cycles the weather.
* **Persistence:** time and weather are saved on quit (`user://world_state.json`).
* 6 new in-game tests and 1 new data test (23 total).
* **Street lamps:** about 4× more downtown (the map builder had been dropping every lamp that stood on a sidewalk);
  each casts a warm pool of light, and the 24 nearest the camera give off real light.
* **Car lights:** headlights at night or in dark weather (real spotlights on the driven car); tail lights brighten
  when braking.
* **Wet and snowy ground:** rain darkens roads and makes them glossy (lamp light reflects), then they dry over a few
  hours. Snow builds on flat ground and roofs, roads stay clearer than sidewalks (plowed), it melts by season, and
  melting leaves slush.
* **Traffic (step 3b part 1):**
  * The pipeline exports the drivable road network per chunk (segments with OSM node ids, road class, lanes,
    one-way, speed limit) and 11,030 intersection controls.
  * Controls are inferred from road classes: signals where major roads meet, stop signs on side streets,
    all-way stops on 4-way residential corners. Real OSM signal data replaces this automatically once
    `osm/extra/signals.json` downloads (Overpass was overloaded).
  * Up to 60 cars around the player (`source_data/traffic.json`), with density by hour, weekend and weather.
    The mix is ordinary Toledo traffic (sedans, SUVs, pickups, minivans, vans, box trucks, transit buses, rare
    sports cars and police cruisers; fictional makers).
  * Cars keep their lane, follow at safe gaps (Intelligent Driver Model), slow for turns, stop at red lights and
    stop signs, yield, drive slower in rain and snow, and stop for the player and the player's cars.
  * Headlights and tail lights glow at night. Cars are one draw call each plus their lights.
  * 6 traffic tests.
* **Pedestrians (step 3b part 2):**
  * Up to 80 people walk the real sidewalks (road widths now exported per segment). They turn at the
    corners and never walk down the median of a divided road.
  * They cross only at intersections: on the walk phase at signals, otherwise when no car is close. Cars
    stop for anyone in the crosswalk.
  * 32 procedural people (skin tones, clothes, heights, builds, some in dresses), with walk cycles animated
    in the shader (one draw call each). About half put up umbrellas in the rain.
  * Density by hour, weekday, weather and area (downtown vs. elsewhere); `source_data/pedestrians.json`.
  * 5 pedestrian tests.
* **Names:** all 184 schools in the full region have fictional names (`source_data/school_names.json`); University of
  Toledo is the University of Glass City. Every street has a parody name (`source_data/street_names.json`, 4,416
  names); numbered streets and routes keep their numbers.
* Test harness now fails a test that crashes instead of silently skipping it.
* Fix: window emission masks lit whole walls (Godot's emission ADD operator); now MULTIPLY.

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
