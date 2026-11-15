# Data sources and licence register

Every outside dataset or asset used by GLASS CITY, where it came from, its licence, how we use it, and what
the game must do to comply. **Add a row before using anything new.** (Bible §3 "Geographic data and reference
pipeline", §17 guardrails.)

Status key: **In game** = shipped inside the built data · **Pipeline only** = used to compute numbers that ship
(heights, colours) but the source itself does not ship · **Reference only** = looked at by a person/Claude, never
shipped.

| # | Source | What we take | Licence / terms | Status | Obligations |
|---|---|---|---|---|---|
| 1 | **OpenStreetMap** via the Overpass API (`overpass-api.de`) | Streets, street names, building footprints (outside the county set), water, parks, rail, POIs, neighbourhood names, building tags | **ODbL 1.0** (Open Database License) | In game (derived database) | Credit "© OpenStreetMap contributors" in the game credits and on any map screen. The built chunk data is a *Produced Work*; if we ever publish the derived database itself, it must be ODbL. |
| 1b | **OpenStreetMap** traffic signals / stop signs (`osm/extra/signals.json`, Overpass) | Intersection controls (when available; otherwise inferred) | ODbL 1.0 | In game (derived) | Same as #1. |
| 2 | **USGS 3DEP LiDAR**, `USGS_LPC_OH_LowerMaumee_B16_2016` (Entwine/EPT on AWS `usgs-lidar-public`) | Building heights, roof shapes, stepped tiers, exact downtown massing | US Government work, **public domain** | Pipeline only | None required; credit "USGS 3D Elevation Program" in credits as courtesy. |
| 3 | **Lucas County, Ohio**: `lucapps.co.lucas.oh.us/Downloads`: BuildingFootprints.shp, ParcelsAddress.shp, AREIS property records (Access DB) | Building footprints for the whole county; wall material, stories, year built, garage, porch and class used to style houses and buildings | Public records published by the county for download. No explicit open licence stated on the page | In game (footprint geometry); Pipeline only (attributes) | **Action:** confirm reuse terms with the Lucas County Auditor before commercial release. Credit "Lucas County Auditor (AREIS)". Owner names are never imported. |
| 4 | **Ohio OSIP** (Ohio Statewide Imagery Program) via `maps.ohio.gov` ImageServer `osip_most_current` | Ground aerial texture under streets and lots (`data/aerial`) | State of Ohio public imagery (OGRIP) | In game | Credit "Ohio Statewide Imagery Program (OGRIP)". **Action:** re-check terms for commercial redistribution before release. |
| 5 | **Toledo / Lucas County GIS** ArcGIS REST (parcels, land use) | Cross-checks only | Public GIS service | Reference only | None. |
| 6 | **Wikimedia Commons** (category pages under "Downtown Toledo, Ohio" etc.) | Photos looked at to set facade colour, floor height, window style (`source_data/facades.json`, `src: "photo"`) | Mixed (CC BY, CC BY-SA, public domain) | Reference only | Photos are **never** shipped or traced into textures. Facade specs are our own numbers. |
| 7 | **Wikipedia**, "List of tallest buildings in Toledo, Ohio"; Structurae; Skyscraper Center | Published heights and floor counts (`src: "facts"`) | Facts (not copyrightable) | Reference only | None. |
| 8 | Commercial listing pages (LoopNet etc.) | Floor counts and years for single buildings | Facts | Reference only | None. |
| 9 | Procedural textures (`tools/pipeline/make_textures.py`) | All textures in `textures/` | Original, made by this project | In game | None. |

## Names and brands
Business, bar, vehicle, sports and media names are **fictional parodies** (`source_data/sign_names.csv`, bar brands
in `scripts/bars.gd`). Real names are kept only in the `real` column for placement and are never displayed. The
trademark screening of names was done informally. **Action:** do a proper clearance pass before release
(Bible §1, §17).

## Credits block (put in the game's credits screen)
```
Map data © OpenStreetMap contributors (ODbL)
Elevation data: USGS 3D Elevation Program
Building records: Lucas County Auditor (AREIS)
Aerial imagery: Ohio Statewide Imagery Program (OGRIP)
```
