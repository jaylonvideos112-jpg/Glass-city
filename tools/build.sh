#!/bin/sh
# GLASS CITY data pipeline. Raw inputs (OSM tiles, LiDAR, county records) live in a work folder outside git
# (default: the folder that contains this repo; override with GLASSCITY_WORK). Hand-authored inputs live in
# source_data/ inside the repo. Output goes to data/ (git-ignored, regenerable).
#
#   tools/build.sh city        rebuild data/ from the existing intermediates (about 3 minutes)
#   tools/build.sh downtown    rebuild only the downtown test box into data/ (about 20 seconds)
#   tools/build.sh massing     recompute exact downtown LiDAR massing + hand overrides, then city
#   tools/build.sh textures    regenerate procedural textures
#   tools/build.sh fetch       re-download OSM tiles (slow; Overpass)
# Full from-scratch order is documented in docs/BUILD.md.
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${GLASSCITY_WORK:-$(dirname "$REPO")}"
P="$REPO/tools/pipeline"
BBOX="41.4560 -83.9160 41.7900 -83.2400"            # S W N E: the whole island (source_data/island.json) plus sea margin
DT_BBOX="41.6420 -83.5510 41.6625 -83.5280"         # downtown test box
cd "$WORK"
export COUNTY=osm LIDAR=lidar/buildings.pkl LIDAR2=lidar/county.pkl LIDAR3=lidar/downtown_exact.pkl LTREES=lidar/trees.json
export HWINGS=lidar/house_wings.pkl HLOOKS=lidar/house_looks_keys.json HPAL=lidar/house_palette.json DEM=lidar/dem BLOOKS=lidar/bld_looks_keys.json VACANT=lidar/vacant_keys.json
export BARS="$REPO/source_data/bars.json" FACADES="$REPO/source_data/facades.json"
build() {   # $1 = bbox
  rm -rf /tmp/glasscity_build && python3 "$P/build_city.py" "${OSMSRC:-osm/city_all}" /tmp/glasscity_build $1
  [ -d "$REPO/data/aerial" ] && mv "$REPO/data/aerial" /tmp/glasscity_aerial_keep || true
  rm -rf "$REPO/data" && mkdir -p "$REPO/data" && cp -r /tmp/glasscity_build/* "$REPO/data/"
  [ -d /tmp/glasscity_aerial_keep ] && mv /tmp/glasscity_aerial_keep "$REPO/data/aerial" || true
  cp "$REPO/source_data/bars.json" "$REPO/data/bars_index.json"
  [ -d "$WORK/lidar/dem" ] && python3 "$P/terrain_export.py" "$WORK/lidar/dem" "$REPO/data/manifest.json" "$REPO/data/terrain.bin" 16 || true
  [ -d "$REPO/data/aerial" ] || echo "NOTE: no aerial imagery in data/aerial; run: python3 $P/aerial_fetch.py data/manifest.json data/aerial"
}
case "${1:-city}" in
  city)     build "$BBOX" ;;
  downtown) build "$DT_BBOX" ;;
  massing)  python3 "$P/downtown_massing.py" lidar_dt/laz osm/county_osm.json osm/city "$REPO/source_data/downtown_ring.json" lidar/downtown_exact.pkl
            python3 "$P/dt_overrides.py" lidar/downtown_exact.pkl
            build "$BBOX" ;;
  textures) python3 "$P/make_textures.py" "$REPO/textures" ;;
  fetch)    python3 "$P/fetch_city.py" 41.5050 -83.8130 41.7330 -83.3040 8 12 osm/city ;;
  *) echo "unknown stage: $1"; exit 2 ;;
esac
echo "done: $1"
