# GLASS CITY

An open-world action game set in a near 1:1 Toledo, Ohio, and the surrounding region. Built first in **Godot 4**,
with an Unreal Engine 5 rebuild planned later. The design source of truth is
[`docs/GLASS_CITY_Development_Bible_v1.0.pdf`](docs/GLASS_CITY_Development_Bible_v1.0.pdf).

**Docs:** [Build](docs/BUILD.md) · [Architecture](docs/ARCHITECTURE.md) · [Data sources & licences](docs/DATA_SOURCES.md) ·
[Performance budgets](docs/PERF_BUDGETS.md) · [Coding standards](docs/CODING_STANDARDS.md) · [Changelog](docs/CHANGELOG.md)

The current map is a 20.8 km × 17.8 km area (41.571–41.731 N, 83.70–83.45 W): every Toledo neighbourhood, plus
the parts of Ottawa Hills, Sylvania Township, Maumee, Rossford, Northwood and Oregon that fall inside it.

## Run it
1. Install **Godot 4.3** or newer (standard build).
2. Open Godot, click **Import**, pick `project.godot`, and press **F5**.
   The first open takes a minute or two while textures import.

You start downtown at **Summit St & Madison Ave** next to five parked cars.

## Controls
| | On foot | In a car |
|---|---|---|
| W A S D / arrows | move | throttle / brake-reverse / steer |
| Mouse | look (click to capture) | look around |
| Shift | sprint | |
| Space | jump | handbrake |
| E or F | get in nearest car / enter or leave a bar | get out |
| R | | flip car upright |
| Wheel | zoom camera | |
| H | toggle help | |
| F3 | performance overlay | |
| Esc | free mouse | |

Drive into the Maumee or the lake and you respawn ("WASTED").

## What's new in v0.3: real-looking Toledo
* **Every building measured from LiDAR.** Heights come from the USGS 2016 Lower Maumee laser scan
  (`USGS_LPC_OH_LowerMaumee_B16_2016`): 145,527 buildings got their real measured height. The scan also detects
  roof shapes (gable, cross-gable, hip, flat) for about 57,000 buildings, and its 3 m height grid turns big
  buildings into stepped tiers (towers, setbacks, wings).
* **Skyline landmarks with real heights and materials:**
  * One SeaGate (125 m glass)
  * Tower on the Maumee (122 m, dark International Style)
  * PNC Bank Building (112 m Art Deco limestone on black granite, with setbacks and a stepped pyramid crown)
  * Government Center (100 m, Yamasaki narrow-window facade)
  * Riverfront Apartments, Edison Plaza, the Nicholas, Ohio and Spitzer buildings, Four SeaGate, Pythian Castle
    and more
* **Civic landmarks:** the Lucas County Courthouse with its dome and copper roofs, the Toledo Museum of Art with
  its marble colonnade, and the Main Library.
* **Anthony Wayne Bridge.** A suspension bridge rebuilt to its real numbers: 239 m main span, sky-blue X-braced
  towers 61 m above the river, deck 32 m up, and main cables with paired suspenders every 20 ft.
* **Veterans' Glass City Skyway.** A single 122 m pylon with a glowing glass top, one plane of fan stays over two
  187 m spans, and the deck 40 m above the Maumee on long approach viaducts.
* **Ballparks and stadiums.** Fifth Third Field and 15 other stadiums get tiered seating bowls and light towers.
* **Neighborhoods:**
  * front porches facing the street on most houses
  * gable and hip roofs from LiDAR or OSM tags
  * storefront ground floors with awnings downtown and on commercial strips
  * OSM roof colors and shapes honored (copper green, domes and so on)

## What changed in v0.2 (whole city)
* **Whole city.** The generator now works region by region (1 km at a time), so the full city builds in about
  2 minutes on a normal PC.
* **Neighborhood styling.**
  * Houses get pitched shingle roofs and clapboard siding in 6 tints, with some brick.
  * The **Old West End** gets taller Victorian houses in darker siding and brick.
  * Industrial areas get metal-sided buildings and gravel yards.
  * Residential streets get street trees. Woods, cemeteries, golf courses and parks are filled in.
* **Real neighborhood names** on the HUD, from OSM place data (Old West End, Point Place, Library Village,
  Five Points, Birmingham, Westgate and more).
* **Large-world fix.** The 1 km origin re-centering now handles newly streamed chunks correctly. It was tested by
  teleporting to six spots across the city, up to 13 km from downtown.
* **Compressed chunks.** City data is about 160 MB on disk instead of about 600 MB.

## How the city is built
`tools/` holds the generator pipeline (Python 3 + shapely + numpy + pillow). The raw OpenStreetMap download
for this build is included in `osm/city/` (25 tiles), so you can tweak the generator and rebuild offline:

```
tools\regenerate_city.bat          (Windows: rebuild data from osm\city + lidar\buildings.pkl, ~2 min)
tools\regenerate_city.bat fresh    (re-download Toledo from OpenStreetMap first)
```
or by hand:
```
pip install -r tools/requirements.txt
python tools/build_city.py osm/city data 41.575 -83.700 41.735 -83.450
```

* **1:1 scale:** lat/lon are projected to meters around downtown (41.6528, -83.5379); +X is east, -Z is north.
* **Roads** are buffered to real-ish widths and merged, so intersections are clean. Sidewalks run along city
  streets, arterials get double-yellow lines, and street lamps line the roads.
* **Bridges and overpasses** become elevated decks with ramps solved across connected bridge segments, plus
  railings, fascia and pillars. Rivers and the lake are lowered basins with seawalls.
* **Buildings** use OSM `height`, `building:levels`, `min_height` and `building:part` where present. Otherwise
  height is estimated from building type, footprint and neighborhood.
* **Names:** real street names show on the HUD and radar. Business and brand names on buildings are parodies
  (e.g. "Huntingdon Centre", "The Toledo Edge", "ProMedix", "Jeepers Assembly").

## Engine side
* `scripts/city_streamer.gd` streams 200 m chunks around you. Decompression and decoding run on worker
  threads, mesh building is time-budgeted on the main thread, and chunks unload past about 1.1 km.
* **Large-world precision:** everything lives under a `World` node that re-centers (origin rebasing) whenever you
  get more than 1 km from the origin, so physics and rendering stay precise anywhere in the 21 km map.
* `scripts/demo.gd` holds scripted test and capture modes:
  `godot --path . -- --demo=drive|walk|fly|shots|tour [--at=x,z] [--seconds=N] [--out=dir]`
  `--demo=tour` is the large-world stress test.

## Rebuilding with LiDAR
```
python tools/lidar_fetch.py 41.575 -83.700 41.735 -83.450 8 lidar     # ~1.5 GB of USGS EPT point data
python tools/lidar_process.py lidar/laz osm/city lidar/buildings.pkl   # measures every building (~4 min)
LIDAR=lidar/buildings.pkl python tools/build_city.py osm/city data 41.575 -83.700 41.735 -83.450
```
(On Windows: `set LIDAR=lidar\buildings.pkl` before the last command.) The measured result is included as
`lidar/buildings.pkl`, so you can rebuild without downloading the point cloud.

## Known gaps / next up
* Facades are still per-style textures, not each building's real facade. Smaller landmarks (the zoo, the
  Jeep plant, churches) still use generic styles.
* No traffic or pedestrians yet. Trees and lamps have no collision yet.
* Land outside the box is flat placeholder ground.

## Credits
Map data © OpenStreetMap contributors, available under the Open Database License (ODbL): https://www.openstreetmap.org/copyright
Elevation data: U.S. Geological Survey 3D Elevation Program (3DEP), Lower Maumee 2016 LiDAR (public domain).
Landmark heights: CTBUH Skyscraper Center and Wikipedia's list of tallest buildings in Toledo.
