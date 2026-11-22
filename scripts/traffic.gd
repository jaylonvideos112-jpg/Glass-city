extends Node
## Ambient traffic (Bible §5, §8). Cars follow the real road network exported by the pipeline (chunk "roads":
## segments with OSM node ids, class, lanes, one-way, speed) and obey intersection controls (chunk "ix": signals,
## stop signs, yields). Car following uses the Intelligent Driver Model. Only cars near the player exist
## (simulation tier 1); density follows the hour, weekday and weather from source_data/traffic.json.
##
## Coordinates: the graph is kept in WORLD coordinates (local + main.world_offset) so origin rebasing never
## invalidates it; car bodies are placed at world - world_offset each frame.

const DATA_PATH := "res://source_data/traffic.json"

var main: Node
var T: Dictionary
var rng := RandomNumberGenerator.new()

# graph (world coords, metres)
var npos := {}          # node id -> Vector3 (y = 0; cars raycast for height)
var nout := {}          # node id -> Array of edge ids leaving it
var edges: Array = []   # edge id -> {a, b, len, dir, cls, lanes, speed, oneway}
var ix := {}            # node id -> {ctrl, major, axis(rad), phase_off}
var _dirty := true
var _rebuild_t := 0.0

var cars: Array = []    # active agents (Dictionary each)
var _mesh_cache := {}
var _head_mat: StandardMaterial3D
var _tail_mat: StandardMaterial3D
var _body_mat: ShaderMaterial
var enabled := true
var time_s := 0.0       # signal clock (real seconds)
var spawned_total := 0
var graph_version := 0

## civilian vehicle types from the roster (source_data/vehicles.json), in the shape traffic.gd uses
static func roster_types() -> Array:
	var V = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/vehicles.json"))
	var CAB := {"sedan": [0.22, 0.48], "hatch": [0.2, 0.55], "suv": [0.15, 0.62], "pickup": [0.1, 0.3], "van": [0.1, 0.2],
		"box": [0.1, 0.2], "coupe": [0.28, 0.4], "sports": [0.3, 0.36], "wagon": [0.2, 0.66]}
	var out: Array = []
	for m in V["models"]:
		out.append({"id": m["id"], "name": "%s %s" % [m["make"], m["model"]], "share": float(m["traffic_share"]), "size": m["size"],
			"cabin": CAB.get(m["body"], [0.2, 0.5]), "body": m["body"], "old": m.get("old", false)})
	return out

const WheelMesh := preload("res://scripts/wheel_mesh.gd")

func _ready() -> void:
	T = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
	T["vehicles"] = roster_types() + T["vehicles"]
	rng.seed = 1977
	main.streamer.chunk_loaded.connect(func(_k): _dirty = true)
	_body_mat = ShaderMaterial.new(); _body_mat.shader = load("res://shaders/car_paint.gdshader")
	_head_mat = StandardMaterial3D.new(); _head_mat.albedo_color = Color(1.0, 0.96, 0.85)
	_head_mat.emission_enabled = true; _head_mat.emission = Color(1.0, 0.95, 0.82)
	_tail_mat = StandardMaterial3D.new(); _tail_mat.albedo_color = Color(0.7, 0.04, 0.03)
	_tail_mat.emission_enabled = true; _tail_mat.emission = Color(1.0, 0.05, 0.02)
	for a in OS.get_cmdline_user_args():
		if a == "--no-traffic": enabled = false

# ------------------------------------------------------------------ graph
func rebuild_graph() -> void:
	npos.clear(); nout.clear(); edges.clear(); ix.clear()
	var seen := {}
	for k in main.streamer.loaded:
		var root: Node3D = main.streamer.loaded[k]
		if not root.has_meta("roads"): continue
		var o: Vector3 = root.position + main.world_offset
		for r in root.get_meta("roads"):
			var a: int = r[0]; var b: int = r[1]
			var key := "%d_%d" % [a, b]
			if seen.has(key): continue
			seen[key] = true
			var pa := Vector3(r[2], 0, r[3]) + o; var pb := Vector3(r[4], 0, r[5]) + o
			npos[a] = Vector3(pa.x, Terrain.height(pa), pa.z); npos[b] = Vector3(pb.x, Terrain.height(pb), pb.z)   # ground level: 3D distances and lane points sit on the terrain
			var ow: int = r[8]
			if ow >= 0: _add_edge(a, b, r)
			if ow <= 0: _add_edge(b, a, r)
		if root.has_meta("ix"):
			for q in root.get_meta("ix"):
				ix[q[0]] = {"ctrl": q[3], "major": q[4], "axis": -1.0, "phase_off": rng.randf() * 40.0}
	# signal axis = bearing of the most important road through the node
	for nid in ix:
		var best := 99; var ax := 0.0
		for eid in nout.get(nid, []):
			var e: Dictionary = edges[eid]
			if e["cls"] < best: best = e["cls"]; ax = atan2(e["dir"].x, e["dir"].z)
		ix[nid]["axis"] = ax
	_dirty = false
	graph_version += 1
	# cars whose edge vanished (chunk unloaded) are removed
	for c in cars.duplicate():
		if c["edge"] >= edges.size() or edges[c["edge"]]["a"] != c["ea"] or edges[c["edge"]]["b"] != c["eb"]:
			var ne := _find_edge(c["ea"], c["eb"])
			if ne < 0: _despawn(c)
			else: c["edge"] = ne; c["next"] = _choose_next(c)
		elif c["next"] >= edges.size() or (c["next"] >= 0 and edges[c["next"]]["a"] != c["eb"]):
			c["next"] = _choose_next(c)      # edge ids are renumbered on every graph rebuild

func _add_edge(a: int, b: int, r: Array) -> void:
	var pa: Vector3 = npos[a]; var pb: Vector3 = npos[b]
	var L := pa.distance_to(pb)
	if L < 0.05: return
	var e := {"a": a, "b": b, "len": L, "dir": (pb - pa) / L, "cls": int(r[6]), "lanes": max(1, int(r[7])),
		"oneway": int(r[8]) != 0, "speed": float(r[9]),
		"w": float(r[10]) if r.size() > 10 else 8.0, "walk": (int(r[11]) == 1) if r.size() > 11 else int(r[6]) >= 2}
	var id := edges.size()
	edges.append(e)
	if not nout.has(a): nout[a] = []
	nout[a].append(id)

func _find_edge(a: int, b: int) -> int:
	for eid in nout.get(a, []):
		if edges[eid]["b"] == b: return eid
	return -1

## Lane centre line point (world) on edge e at distance s.
func lane_point(e: Dictionary, s: float, lane: int) -> Vector3:
	var lw: float = T["driver"]["lane_width"]
	var right: Vector3 = Vector3(-e["dir"].z, 0, e["dir"].x)   # right-hand side of travel direction
	var off: float
	if e["oneway"]:
		off = (lane - (e["lanes"] - 1) * 0.5) * lw
	else:
		var per_dir: int = max(1, e["lanes"] / 2)
		off = (min(lane, per_dir - 1) + 0.5) * lw
	return npos[e["a"]] + e["dir"] * s + right * off

# ------------------------------------------------------------------ signals
## Is the approach along edge e allowed to enter node n now? Returns "go", "stop" or "yield".
func control_for(e: Dictionary, approaching_node: int) -> String:
	if not ix.has(approaching_node): return "go"
	var q: Dictionary = ix[approaching_node]
	match q["ctrl"]:
		"signal":
			var S: Dictionary = T["signals"]
			var g: float = S["green_s"]; var y: float = S["yellow_s"]; var r: float = S["all_red_s"]
			var cyc := 2.0 * (g + y + r)
			var t: float = fmod(time_s + float(q["phase_off"]), cyc)
			var ang: float = atan2(e["dir"].x, e["dir"].z)
			var d: float = absf(wrapf(ang - float(q["axis"]), -PI, PI))
			var on_axis: bool = d < PI * 0.25 or d > PI * 0.75
			var phase_t: float = t if on_axis else fmod(t + g + y + r, cyc)
			if phase_t < g: return "go"
			if phase_t < g + y: return "yellow"
			return "stop"
		"stop_minor":
			return "stopsign" if e["cls"] > q["major"] or e["cls"] >= 5 and q["major"] <= 4 else "go"
		"all_stop":
			return "stopsign"
		"yield":
			return "yield"
	return "go"

## Signal state as seen from an edge (for tests and debug).
func signal_state(eid: int) -> String:
	return control_for(edges[eid], edges[eid]["b"])

# ------------------------------------------------------------------ vehicles
func _type(id: String) -> Dictionary:
	for v in T["vehicles"]:
		if v["id"] == id: return v
	return T["vehicles"][0]

func _pick_type() -> Dictionary:
	var vs: Array = T["vehicles"]
	var tot := 0.0
	for v in vs: tot += float(v["share"])
	var r := rng.randf() * tot
	for v in vs:
		r -= float(v["share"])
		if r <= 0.0: return v
	return vs[0]

func _box(st: SurfaceTool, size: Vector3, pos: Vector3, col: Color) -> void:
	var bm := BoxMesh.new(); bm.size = size
	var arr := bm.get_mesh_arrays()
	var v: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]; var n: PackedVector3Array = arr[Mesh.ARRAY_NORMAL]; var idx: PackedInt32Array = arr[Mesh.ARRAY_INDEX]
	for i in idx:
		st.set_color(col); st.set_normal(n[i]); st.add_vertex(v[i] + pos)

## low-level helpers for car shapes: a convex "slab" from 8 corner points (bottom 4, top 4), flat shaded
const GLASS := Color(0.07, 0.09, 0.12)
var _glass_st: SurfaceTool = null     # while set, glass faces go here (a see-through surface for drivable cars)
var _glass_mat: StandardMaterial3D

func _hexa(st: SurfaceTool, b: Array, t: Array, cols: Dictionary) -> void:
	# b, t: [front-left, front-right, rear-right, rear-left] (front is -Z); cols: side/top/front/rear/bottom colours
	var faces := [[b[0], b[1], t[1], t[0], "front"], [b[2], b[3], t[3], t[2], "rear"], [b[1], b[2], t[2], t[1], "side"],
		[b[3], b[0], t[0], t[3], "side"], [t[0], t[1], t[2], t[3], "top"], [b[3], b[2], b[1], b[0], "bottom"]]
	for f in faces:
		var col: Color = cols.get(f[4], cols["side"])
		var dst := _glass_st if (_glass_st != null and col == GLASS) else st
		var a: Vector3 = f[0]; var bb: Vector3 = f[1]; var c: Vector3 = f[2]; var d: Vector3 = f[3]
		var n := (bb - a).cross(c - a).normalized()
		if n == Vector3.ZERO: n = (c - a).cross(d - a).normalized()
		for v in [a, bb, c, a, c, d]:
			dst.set_color(col); dst.set_normal(-n); dst.add_vertex(v)

## Smooth car body lofted through rounded cross-sections along the length: bonnet and boot that curve down at
## the ends, a raked windscreen and rear window, side glass that leans in (tumblehome), a B pillar, and wheel
## arches cut out of the lower body. Quads take one colour each (paint / glass / dark) so window edges stay crisp;
## normals are smoothed across the surface so the paint reflects like a real panel.
func _loft_body(st: SurfaceTool, v: Dictionary, paint: Color, paint_dark: Color, glass: Color, dark: Color, trim: Color, sill: float, belt: float, wr: float) -> void:
	var L: float = v["size"][0]; var W: float = v["size"][1]; var H: float = v["size"][2]
	var body: String = v["body"]
	var hw := W * 0.5; var zf := -L * 0.5
	var cab: Array = v["cabin"]
	var c0: float = L * cab[0]; var cl: float = L * cab[1]
	var c1: float = c0 + cl
	if body in ["hatch", "suv", "wagon"]: c1 = minf(L - 0.25, c1)
	var rake_f: float = cl * (0.34 if body in ["coupe", "sports"] else 0.28)
	var rake_r: float = cl * (0.34 if body in ["sedan", "coupe", "sports"] else 0.08)
	var hood: float = belt + 0.04
	var trunk: float = belt + (0.06 if body in ["sedan", "coupe", "sports"] else 0.0)
	var wz: float = L * 0.33
	var axles := [-wz, wz]
	var NZ := 34
	var zs: Array = []
	for i in NZ + 1:
		var t := float(i) / NZ
		zs.append(t * t * (3.0 - 2.0 * t) * 0.3 + t * 0.7)     # a little denser at the ends
	# profile point count per side (bottom centre -> roof centre)
	var NP := 11
	var grid: Array = []      # [i][j] Vector3, j over the full ring 0..2*NP-2 (right side then left side mirrored)
	var kind: Array = []      # [i] -> per-band tags along the ring for colouring
	for i in zs.size():
		var z: float = float(zs[i]) * L                    # 0..L from the front
		var tf := clampf(z / 0.45, 0.0, 1.0); var tr2 := clampf((L - z) / 0.4, 0.0, 1.0)
		var endw: float = 0.86 + 0.14 * sin(minf(tf, tr2) * PI * 0.5)     # rounded corners in plan
		var endh: float = 1.0 - 0.1 * (1.0 - sin(tf * PI * 0.5)) - 0.06 * (1.0 - sin(tr2 * PI * 0.5))
		var w := hw * endw
		# top line: bonnet -> windscreen -> roof -> rear window -> boot
		var top: float
		if z < c0: top = hood * endh
		elif z < c0 + rake_f: top = lerpf(hood, H, smoothstep(0.0, 1.0, (z - c0) / rake_f))
		elif z < c1 - rake_r: top = H
		elif z < c1: top = lerpf(H, trunk, smoothstep(0.0, 1.0, (z - (c1 - rake_r)) / rake_r))
		else: top = trunk * endh
		var in_cab: bool = z > c0 + rake_f * 0.15 and z < c1 - rake_r * 0.1
		var gh: float = clampf(top - belt, 0.0, 1.0)       # greenhouse height here
		var bot := sill + 0.06 * (1.0 - minf(tf, tr2))
		# wheel arch: lift the side bottom over the tyre
		var arch := 0.0
		for az in axles:
			var dz: float = (z - L * 0.5) - az
			var rr: float = wr * 1.12
			if absf(dz) < rr: arch = maxf(arch, sqrt(rr * rr - dz * dz) + wr - bot + 0.02)
		var side_bot: float = bot + arch
		var pts := [
			Vector3(0.0, bot - 0.02, 0), Vector3(w * 0.85, bot, 0), Vector3(w * 0.97, side_bot + 0.03, 0),
			Vector3(w, maxf(side_bot + 0.08, lerpf(bot, belt, 0.42)), 0), Vector3(w * 0.995, lerpf(bot, belt, 0.8), 0),
			Vector3(w * 0.965, belt, 0),
			Vector3(w * (0.93 - 0.02 * minf(gh * 3.0, 1.0)), belt + minf(gh, 0.04), 0),
			Vector3(w * (0.92 - 0.2 * minf(gh / 0.45, 1.0)), belt + gh * 0.55 + minf(gh, 0.04) * 0.45, 0),
			Vector3(w * (0.9 - 0.25 * minf(gh / 0.45, 1.0)), top - 0.04 * minf(gh * 4.0, 1.0), 0),
			Vector3(w * (0.6 - 0.12 * minf(gh / 0.45, 1.0)), top, 0),
			Vector3(0.0, top + 0.015, 0)]
		if not in_cab and gh < 0.05:    # bonnet / boot: flatten the greenhouse points onto a crowned panel
			pts[6] = Vector3(w * 0.9, top - 0.01, 0); pts[7] = Vector3(w * 0.75, top + 0.008, 0); pts[8] = Vector3(w * 0.55, top + 0.016, 0); pts[9] = Vector3(w * 0.3, top + 0.02, 0)
			pts[10] = Vector3(0.0, top + 0.022, 0)
		var ring: Array = []
		for j in NP: ring.append(Vector3(pts[j].x, pts[j].y, zf + z))
		for j in range(NP - 2, -1, -1): ring.append(Vector3(-pts[j].x, pts[j].y, zf + z))
		grid.append(ring)
		kind.append({"z": z, "cab": in_cab, "wind": z > c0 and z < c0 + rake_f, "rear": z > c1 - rake_r and z < c1 and body in ["sedan", "coupe", "sports"],
			"hatchback": z > c1 - 0.05 and body in ["hatch", "suv", "wagon"], "bpil": absf(z - (c0 + cl * 0.5)) < 0.06,
			"cpil": absf(z - (c1 - rake_r - 0.05)) < 0.06 and body in ["suv", "wagon"]})
	var nr: int = grid[0].size()
	# smooth normals
	var nrm: Array = []
	for i in grid.size():
		var row: Array = []
		for j in nr:
			var a: Vector3 = grid[mini(i + 1, grid.size() - 1)][j] - grid[maxi(i - 1, 0)][j]
			var b: Vector3 = grid[i][(j + 1) % nr] - grid[i][(j - 1 + nr) % nr]
			var n := b.cross(a).normalized()
			if n == Vector3.ZERO: n = Vector3.UP
			row.append(n)
		nrm.append(row)
	for i in grid.size() - 1:
		var k0: Dictionary = kind[i]; var k1: Dictionary = kind[i + 1]
		for j in nr - 1:
			var band: int = mini(j, nr - 2 - j)
			var col := paint
			if band <= 1: col = dark
			elif band == 6 or band == 7:          # side glass band
				if k0["cab"] and k1["cab"] and not k0["bpil"] and not k1["bpil"] and not k0["cpil"]: col = glass
			elif band >= 8:                         # roof region: windscreen / rear window
				if (k0["wind"] and k1["wind"]) or (k0["rear"] and k1["rear"]): col = glass
			if band >= 6 and (k0["hatchback"] or k1["hatchback"]) and band < 9 and k0["cab"]: col = glass
			var dst := _glass_st if (_glass_st != null and col == glass) else st
			var q := [grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]]
			var qn := [nrm[i][j], nrm[i + 1][j], nrm[i + 1][j + 1], nrm[i][j + 1]]
			for k in [0, 1, 2, 0, 2, 3]:
				dst.set_color(col); dst.set_normal(qn[k]); dst.add_vertex(q[k])
	# end caps (front and rear faces)
	for e in [0, grid.size() - 1]:
		var ring: Array = grid[e]; var c := Vector3(0, 0, 0)
		for p in ring: c += p
		c /= ring.size()
		var fn := Vector3(0, 0, -1) if e == 0 else Vector3(0, 0, 1)
		for j in nr - 1:
			for tri in [[c, ring[j], ring[j + 1]], [c, ring[j + 1], ring[j]]]:     # both windings: caps are tiny
				for p in tri:
					st.set_color(paint_dark); st.set_normal(fn); st.add_vertex(p)

## mark each vertex's surface type in its colour alpha for shaders/car_paint.gdshader (paint 1, glass .5, chrome .3)
func _code_surfaces(am: ArrayMesh, paints: Array, chromes: Array) -> ArrayMesh:
	var arr := am.surface_get_arrays(0)
	var cols: PackedColorArray = arr[Mesh.ARRAY_COLOR]
	for i in cols.size():
		var c: Color = cols[i]; c.a = 0.0
		for p in paints:
			if c.is_equal_approx(Color(p.r, p.g, p.b, 0.0)): c.a = 1.0
		if c.is_equal_approx(Color(GLASS.r, GLASS.g, GLASS.b, 0.0)): c.a = 0.5
		for ch in chromes:
			if c.is_equal_approx(Color(ch.r, ch.g, ch.b, 0.0)): c.a = 0.3
		cols[i] = c
	arr[Mesh.ARRAY_COLOR] = cols
	var out := ArrayMesh.new()
	out.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arr)
	return out

func _corners(x: float, y: float, zf: float, zr: float) -> Array:
	return [Vector3(-x, y, zf), Vector3(x, y, zf), Vector3(x, y, zr), Vector3(-x, y, zr)]

func _wheel(st: SurfaceTool, c: Vector3, r: float, w: float, tire: Color, hub: Color) -> void:
	var n := 10
	var side := 1.0 if c.x > 0 else -1.0
	for i in n:
		var a0 := TAU * i / n; var a1 := TAU * (i + 1) / n
		var p0 := Vector3(0, sin(a0) * r, cos(a0) * r); var p1 := Vector3(0, sin(a1) * r, cos(a1) * r)
		var o := Vector3(w * 0.5, 0, 0); var nrm := Vector3(0, sin((a0 + a1) * 0.5), cos((a0 + a1) * 0.5))
		for v in [c - o + p0, c + o + p0, c + o + p1, c - o + p0, c + o + p1, c - o + p1]:
			st.set_color(tire); st.set_normal(nrm); st.add_vertex(v)
		# outer face: hub (inner 60%) + tyre wall
		var oc := c + Vector3(side * w * 0.5, 0, 0)
		for v in [oc, oc + p0 * 0.6, oc + p1 * 0.6]:
			st.set_color(hub); st.set_normal(Vector3(side, 0, 0)); st.add_vertex(v)
		for v in [oc + p0 * 0.6, oc + p0, oc + p1, oc + p0 * 0.6, oc + p1, oc + p1 * 0.6]:
			st.set_color(tire); st.set_normal(Vector3(side, 0, 0)); st.add_vertex(v)

## One mesh per (type, paint): body surface (vertex colours) + headlight and taillight surfaces (emissive at night).
## Shapes by body type: a lower body with a sloped nose and tail and chamfered shoulders, a glasshouse with raked
## windscreen and tumblehome, wheels with hubs, bumpers, grille, mirrors, plate, lights.
## Blender-built bodies (tools/blender/cars.py): canonical size each was modelled at, scaled to the roster size.
const BODY_CANON := {"sedan": Vector3(1.85, 1.45, 4.8), "coupe": Vector3(1.9, 1.3, 4.8), "sports": Vector3(1.9, 1.2, 4.4),
	"hatch": Vector3(1.75, 1.46, 4.2), "wagon": Vector3(1.8, 1.5, 4.8), "suv": Vector3(1.92, 1.8, 4.8),
	"pickup": Vector3(2.02, 1.92, 5.85), "van": Vector3(2.05, 2.4, 5.6), "box": Vector3(2.4, 3.3, 7.4), "bus": Vector3(2.6, 3.2, 12.2)}
const ModelLib := preload("res://scripts/model_lib.gd")
var use_models := true

func has_model(v: Dictionary) -> bool:
	return use_models and BODY_CANON.has(v.get("body", "")) and ResourceLoader.exists("res://assets/models/car_%s.glb" % v["body"])

## The modelled body re-coloured into the engine's conventions: one vertex-coloured car-paint surface (alpha codes
## paint/glass/chrome/trim), headlights as surface 1, taillights as surface 2, and (drivable cars) see-through glass last.
func _model_mesh(v: Dictionary, paint: Color, with_wheels: bool) -> ArrayMesh:
	var src := ModelLib.mesh("car_" + str(v["body"]))
	if src == null: return null
	var canon: Vector3 = BODY_CANON[v["body"]]
	var sc := Vector3(float(v["size"][1]) / canon.x, float(v["size"][2]) / canon.y, float(v["size"][0]) / canon.z)
	var inv := Vector3(1.0 / sc.x, 1.0 / sc.y, 1.0 / sc.z)
	var body := SurfaceTool.new(); body.begin(Mesh.PRIMITIVE_TRIANGLES)
	var head := SurfaceTool.new(); head.begin(Mesh.PRIMITIVE_TRIANGLES)
	var tail := SurfaceTool.new(); tail.begin(Mesh.PRIMITIVE_TRIANGLES)
	var glass: SurfaceTool = null
	if not with_wheels:
		glass = SurfaceTool.new(); glass.begin(Mesh.PRIMITIVE_TRIANGLES)
	var lv: String = v.get("livery", "")
	for i in src.get_surface_count():
		var mname: String = src.surface_get_material(i).resource_name if src.surface_get_material(i) else "paint"
		var arr := src.surface_get_arrays(i)
		var vs: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]; var ns: PackedVector3Array = arr[Mesh.ARRAY_NORMAL]
		var idx: PackedInt32Array = arr[Mesh.ARRAY_INDEX]
		var st: SurfaceTool = body
		var col := paint
		match mname:
			"glass":
				col = Color(GLASS, 0.5)
				if glass != null: st = glass
			"chrome": col = Color(0.62, 0.64, 0.66, 0.3)
			"trim": col = Color(0.05, 0.05, 0.055, 0.0)
			"head": st = head; col = Color.WHITE
			"tail": st = tail; col = Color.WHITE
			_: col = Color(paint, 1.0)
		var order: Array = range(vs.size()) if idx.is_empty() else Array(idx)
		for k in order:
			var p: Vector3 = vs[k] * sc
			var c := col
			if mname == "paint" and lv == "police" and absf(p.y - float(v["size"][2]) * 0.45) < float(v["size"][2]) * 0.15 and absf(p.z) < float(v["size"][0]) * 0.22:
				c = Color(0.93, 0.93, 0.92, 1.0)      # white door panels
			st.set_color(c); st.set_normal((ns[k] * inv).normalized()); st.add_vertex(p)
	var am := ArrayMesh.new()
	body.commit(am); am.surface_set_material(0, _body_mat)
	head.commit(am); am.surface_set_material(1, _head_mat)
	tail.commit(am); am.surface_set_material(2, _tail_mat)
	if glass != null:
		if _glass_mat == null:
			_glass_mat = StandardMaterial3D.new(); _glass_mat.albedo_color = Color(0.015, 0.02, 0.025, 0.9)
			_glass_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA; _glass_mat.roughness = 0.05; _glass_mat.metallic_specular = 0.45
			_glass_mat.cull_mode = BaseMaterial3D.CULL_DISABLED
		glass.commit(am); am.surface_set_material(3, _glass_mat)
	return am

func vehicle_mesh(v: Dictionary, paint: Color, with_wheels := true) -> ArrayMesh:
	var key := "%s|%s|%s" % [v["id"], paint.to_html(), with_wheels]
	if _mesh_cache.has(key): return _mesh_cache[key]
	if has_model(v):
		var mm := _model_mesh(v, paint, with_wheels)
		if mm:
			_mesh_cache[key] = mm
			return mm
	var L: float = v["size"][0]; var W: float = v["size"][1]; var H: float = v["size"][2]
	var body: String = v["body"]
	var glass := GLASS; var dark := Color(0.06, 0.06, 0.07); var tire := Color(0.05, 0.05, 0.05)
	var trim := Color(0.12, 0.12, 0.13); var chrome := Color(0.62, 0.64, 0.66); var hub := Color(0.55, 0.57, 0.6)
	var paint_dark := paint.darkened(0.18)
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	if not with_wheels:      # drivable cars: tinted see-through windows (the driver shows through)
		_glass_st = SurfaceTool.new(); _glass_st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var hw := W * 0.5
	var zf := -L * 0.5; var zr := L * 0.5
	var floor_y := 0.3
	var tall := body in ["van", "box", "bus"]
	var belt: float = H * (0.56 if body in ["suv", "pickup"] else (0.5 if body in ["coupe", "sports"] else 0.52))
	if tall: belt = H * 0.5
	var nose := 0.12 if not tall else 0.04          # how far the nose/tail fall below the belt line
	var wr := 0.34 if H < 1.6 else 0.4
	if tall: wr = 0.46 if body == "bus" or body == "box" else 0.4
	var cols := {"side": paint, "top": paint, "front": paint_dark, "rear": paint_dark, "bottom": dark}
	# --- lower body: sill -> belt, with a sloped bonnet and boot and slightly narrower shoulders
	var sill := floor_y
	var nl := L * (0.12 if not tall else 0.03)      # nose length that slopes
	var lofted: bool = body in ["sedan", "coupe", "sports", "hatch", "suv", "wagon"]
	if not lofted:
		_hexa(st, _corners(hw, sill, zf + nl, zr - nl), _corners(hw * 0.97, belt, zf + nl, zr - nl), cols)
		_hexa(st, _corners(hw * 0.96, sill + 0.06, zf, zf + nl), _corners(hw * 0.94, belt - nose * H * 0.5, zf + 0.06, zf + nl), cols)   # nose
		_hexa(st, _corners(hw * 0.96, sill + 0.06, zr - nl, zr), _corners(hw * 0.94, belt - nose * H * 0.3, zr - nl, zr - 0.06), cols)   # tail
	# --- glasshouse / cargo box
	var roof_col := {"side": glass, "top": paint, "front": glass, "rear": glass, "bottom": paint}
	match body:
		"sedan", "coupe", "sports", "hatch", "suv", "wagon":
			_loft_body(st, v, paint, paint_dark, glass, dark, trim, sill, belt, wr)
		"pickup":
			var c0p: float = zf + L * 0.2; var c1p: float = zf + L * 0.48
			_hexa(st, _corners(hw * 0.94, belt, c0p, c1p), _corners(hw * 0.8, H, c0p + 0.32, c1p - 0.05), roof_col)
			_hexa(st, _corners(hw, belt, c1p + 0.08, zr - 0.05), _corners(hw, belt + 0.38, c1p + 0.08, zr - 0.05), {"side": paint, "top": dark, "front": paint_dark, "rear": paint_dark, "bottom": dark})   # bed
		"van", "box", "bus":
			var cabz: float = zf + (0.9 if body != "bus" else 0.05)
			var top_col := {"side": paint, "top": paint.lightened(0.05), "front": glass, "rear": paint_dark, "bottom": dark}
			if body == "box":
				_hexa(st, _corners(hw * 0.95, belt, zf + 0.1, cabz + 0.9), _corners(hw * 0.88, H * 0.82, zf + 0.5, cabz + 0.9), {"side": glass, "top": paint, "front": glass, "rear": paint, "bottom": dark})
				_hexa(st, _corners(hw * 1.02, sill + 0.2, cabz + 1.0, zr), _corners(hw * 1.02, H, cabz + 1.0, zr), {"side": Color(0.92, 0.92, 0.9), "top": Color(0.85, 0.85, 0.83), "front": Color(0.88, 0.88, 0.86), "rear": Color(0.8, 0.8, 0.78), "bottom": dark})
			else:
				_hexa(st, _corners(hw * 0.98, belt, zf + 0.06 + (0.25 if body == "van" else 0.0), zr - 0.05), _corners(hw * 0.95, H, zf + (0.6 if body == "van" else 0.12), zr - 0.08), top_col)
				# window band along the sides
				for sx in [-1, 1]:
					var x1: float = sx * (hw * 0.985 + 0.005)
					var wz0: float = zf + (0.7 if body == "van" else 0.4); var wz1: float = zr - (1.6 if body == "van" else 0.6)
					_hexa(st, [Vector3(x1, belt + 0.18, wz0), Vector3(x1 + sx * 0.01, belt + 0.18, wz0), Vector3(x1 + sx * 0.01, belt + 0.18, wz1), Vector3(x1, belt + 0.18, wz1)],
						[Vector3(x1, H * 0.9, wz0), Vector3(x1 + sx * 0.01, H * 0.9, wz0), Vector3(x1 + sx * 0.01, H * 0.9, wz1), Vector3(x1, H * 0.9, wz1)], {"side": glass})
	# --- liveries
	var liv: String = v.get("livery", "")
	if liv == "police":
		for sx in [-1, 1]:
			var x2: float = sx * (hw + 0.005)
			_hexa(st, [Vector3(x2, sill + 0.15, zf + L * 0.25), Vector3(x2 + sx * 0.01, sill + 0.15, zf + L * 0.25), Vector3(x2 + sx * 0.01, sill + 0.15, zr - L * 0.2), Vector3(x2, sill + 0.15, zr - L * 0.2)],
				[Vector3(x2, belt - 0.05, zf + L * 0.25), Vector3(x2 + sx * 0.01, belt - 0.05, zf + L * 0.25), Vector3(x2 + sx * 0.01, belt - 0.05, zr - L * 0.2), Vector3(x2, belt - 0.05, zr - L * 0.2)], {"side": Color(0.95, 0.95, 0.95)})
		_hexa(st, _corners(0.55, H, -0.15, 0.15), _corners(0.5, H + 0.12, -0.12, 0.12), {"side": dark, "top": Color(0.2, 0.2, 0.25), "front": Color(0.9, 0.1, 0.1), "rear": Color(0.1, 0.2, 0.9)})
	elif liv == "ambulance":
		for sx in [-1, 1]:
			var x3: float = sx * (hw * 1.02 + 0.005)
			_hexa(st, [Vector3(x3, belt + 0.25, zf + 1.2), Vector3(x3 + sx * 0.01, belt + 0.25, zf + 1.2), Vector3(x3 + sx * 0.01, belt + 0.25, zr - 0.1), Vector3(x3, belt + 0.25, zr - 0.1)],
				[Vector3(x3, belt + 0.55, zf + 1.2), Vector3(x3 + sx * 0.01, belt + 0.55, zf + 1.2), Vector3(x3 + sx * 0.01, belt + 0.55, zr - 0.1), Vector3(x3, belt + 0.55, zr - 0.1)], {"side": Color(0.85, 0.1, 0.08)})
		_hexa(st, _corners(hw * 0.8, H, zf + 0.9, zf + 1.25), _corners(hw * 0.8, H + 0.14, zf + 0.92, zf + 1.23), {"side": Color(0.9, 0.1, 0.1), "top": Color(0.9, 0.9, 0.9)})
	elif liv == "fire":
		_hexa(st, _corners(hw * 0.7, H, zf + 2.0, zr - 0.6), _corners(hw * 0.7, H + 0.22, zf + 2.0, zr - 0.6), {"side": Color(0.75, 0.75, 0.78), "top": Color(0.65, 0.65, 0.68)})   # ladder
		for sx in [-1, 1]:
			var x4: float = sx * (hw * 0.985 + 0.01)
			_hexa(st, [Vector3(x4, sill + 0.3, zf + 0.2), Vector3(x4 + sx * 0.01, sill + 0.3, zf + 0.2), Vector3(x4 + sx * 0.01, sill + 0.3, zr - 0.2), Vector3(x4, sill + 0.3, zr - 0.2)],
				[Vector3(x4, sill + 0.45, zf + 0.2), Vector3(x4 + sx * 0.01, sill + 0.45, zf + 0.2), Vector3(x4 + sx * 0.01, sill + 0.45, zr - 0.2), Vector3(x4, sill + 0.45, zr - 0.2)], {"side": Color(0.95, 0.85, 0.2)})
	# --- bumpers, grille, plates, mirrors
	var bw: float = hw * (0.86 if lofted else 0.98)
	_hexa(st, _corners(bw, sill, zf - 0.03, zf + 0.1), _corners(bw, sill + 0.14, zf - 0.03, zf + 0.1), {"side": trim})
	_hexa(st, _corners(bw, sill, zr - 0.1, zr + 0.03), _corners(bw, sill + 0.14, zr - 0.1, zr + 0.03), {"side": trim})
	var gy: float = belt - nose * H * 0.5 - 0.08
	_hexa(st, _corners(hw * 0.38, sill + 0.24, zf + 0.02, zf + 0.05), _corners(hw * 0.38, minf(gy, sill + 0.5), zf + 0.02, zf + 0.05), {"side": dark, "front": dark})
	_hexa(st, _corners(0.26, sill + 0.24, zr - 0.04, zr - 0.01), _corners(0.26, sill + 0.38, zr - 0.04, zr - 0.01), {"side": Color(0.9, 0.9, 0.85), "rear": Color(0.92, 0.92, 0.88)})
	if not tall or body == "van":
		for sx in [-1, 1]:
			var mz: float = zf + L * (v["cabin"][0] if v.has("cabin") else 0.2) + 0.15
			_hexa(st, _corners(0.08, belt + 0.02, mz, mz + 0.12).map(func(p): return p + Vector3(sx * (hw + 0.06), 0, 0)),
				_corners(0.08, belt + 0.16, mz, mz + 0.12).map(func(p): return p + Vector3(sx * (hw + 0.06), 0, 0)), {"side": paint_dark})
	# --- wheels in dark arches
	var wz: float = L * (0.33 if not tall else 0.36)
	var axles := [-wz, wz]
	if body == "bus" or (body == "box" and L > 7.0): axles = [-L * 0.33, L * 0.28, L * 0.38] if body == "box" else [-L * 0.36, L * 0.3]
	for az in axles:
		for sx in [-1, 1]:
			var wc := Vector3(sx * (hw - 0.12), wr, az)
			if not lofted:
				_hexa(st, _corners(0.13, wr + 0.02, az - wr * 1.05, az + wr * 1.05).map(func(p): return p + Vector3(sx * (hw - 0.12), 0, 0)),
					_corners(0.13, wr * 2.05, az - wr * 0.9, az + wr * 0.9).map(func(p): return p + Vector3(sx * (hw - 0.12), 0, 0)), {"side": dark})
			if with_wheels and not lofted: _wheel(st, wc, wr, 0.24, tire, hub)
	var am := _code_surfaces(st.commit(), [paint, paint_dark, paint.lightened(0.05), paint.darkened(0.1)], [chrome, hub])
	am.surface_set_material(0, _body_mat)
	# lights: headlights (white, surface 1) and taillights (red, surface 2)
	var st2 := SurfaceTool.new(); st2.begin(Mesh.PRIMITIVE_TRIANGLES)
	var st3 := SurfaceTool.new(); st3.begin(Mesh.PRIMITIVE_TRIANGLES)
	var ly: float = minf(gy, belt - 0.12)
	for sx in [-1, 1]:
		var lz: float = 0.012 if lofted else -0.03
		_box(st2, Vector3(W * 0.2, 0.12, 0.05), Vector3(sx * hw * 0.62, ly, zf - lz), Color.WHITE)
		_box(st3, Vector3(W * 0.18, 0.14, 0.05), Vector3(sx * hw * 0.64, belt - nose * H * 0.3 - 0.1 if not tall else sill + 0.5, zr + lz), Color.WHITE)
	st2.commit(am); am.surface_set_material(1, _head_mat)
	st3.commit(am); am.surface_set_material(2, _tail_mat)
	if _glass_st != null:
		if _glass_mat == null:
			_glass_mat = StandardMaterial3D.new(); _glass_mat.albedo_color = Color(0.015, 0.02, 0.025, 0.9)
			_glass_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA; _glass_mat.roughness = 0.05; _glass_mat.metallic_specular = 0.45
			_glass_mat.cull_mode = BaseMaterial3D.CULL_DISABLED
		_glass_st.commit(am); am.surface_set_material(am.get_surface_count() - 1, _glass_mat)
		_glass_st = null
	_mesh_cache[key] = am
	return am

func _spawn_on(eid: int, s: float, type_id := "") -> Dictionary:
	var e: Dictionary = edges[eid]
	var v := _pick_type() if type_id == "" else _type(type_id)
	var LIV := {"police": Color(0.1, 0.12, 0.2), "ambulance": Color(0.95, 0.95, 0.93), "fire": Color(0.72, 0.06, 0.05)}
	var paint: Color = Color(T["bus_paint"]) if v["id"] == "bus" else (LIV[v["livery"]] if LIV.has(v.get("livery", "")) else Color(T["paint"][rng.randi() % T["paint"].size()]))
	var body := AnimatableBody3D.new()
	body.sync_to_physics = false
	body.collision_layer = 2
	body.collision_mask = 0
	var cs := CollisionShape3D.new(); var bx := BoxShape3D.new()
	bx.size = Vector3(v["size"][1], v["size"][2] * 0.8, v["size"][0])
	cs.shape = bx; cs.position.y = v["size"][2] * 0.45
	body.add_child(cs)
	var mi := MeshInstance3D.new(); mi.mesh = vehicle_mesh(v, paint)
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	body.add_child(mi)
	if v.get("body", "") in ["sedan", "coupe", "sports", "hatch", "suv", "wagon"] or has_model(v):     # wheels under modelled/smooth bodies
		var vh: float = v["size"][2]; var wr2: float = 0.34 if vh < 1.6 else 0.4
		if v.get("body", "") in ["van", "box", "bus"]: wr2 = 0.46 if v["body"] != "van" else 0.4
		for az in [-1.0, 1.0]:
			for sx in [-1.0, 1.0]:
				var wm := MeshInstance3D.new(); wm.mesh = WheelMesh.make(wr2, 0.24)
				wm.position = Vector3(sx * (float(v["size"][1]) * 0.5 - 0.12), wr2, az * float(v["size"][0]) * (0.32 if has_model(v) else 0.33))
				body.add_child(wm)
	main.world.add_child(body)
	var per_dir: int = e["lanes"] if e["oneway"] else max(1, e["lanes"] / 2)
	var c := {"node": body, "type": v["id"], "paint": paint, "len": float(v["size"][0]), "edge": eid, "ea": e["a"], "eb": e["b"], "s": s,
		"lane": rng.randi() % per_dir, "v": 0.0, "pers": 1.0 + rng.randf_range(-1.0, 1.0) * float(T["driver"]["speed_jitter"]),
		"y": 0.0, "ray_t": 0.0, "wait": 0.0, "stopped_at": -1, "next": -1, "pos": Vector3.ZERO, "yaw": 0.0}
	c["style"] = _pick_style()
	var st_: Dictionary = T.get("driver_styles", {}).get(c["style"], {})
	c["pers"] = float(c["pers"]) * float(st_.get("speed", 1.0))
	c["v"] = e["speed"] * 0.6
	c["next"] = _choose_next(c)
	cars.append(c)
	spawned_total += 1
	_place(c, 1.0, true)
	return c

## Toledo driver mix (source_data/traffic.json driver_styles): calm, rushed, reckless, elderly, and impaired drivers
## (mostly at night, 22-04 h)
func _pick_style() -> String:
	var DS: Dictionary = T.get("driver_styles", {})
	if DS.is_empty(): return "calm"
	var h := int(main.tod.hour()) % 24 if main.tod else 12
	var key := "night" if (h >= 22 or h < 4) else "day"
	var tot := 0.0
	for k in DS: if k != "_doc": tot += float(DS[k].get(key, 0.0))
	var r := rng.randf() * tot
	for k in DS:
		if k == "_doc": continue
		r -= float(DS[k].get(key, 0.0))
		if r <= 0.0: return k
	return "calm"

func _despawn(c: Dictionary) -> void:
	if is_instance_valid(c["node"]): c["node"].queue_free()
	cars.erase(c)

func _choose_next(c: Dictionary) -> int:
	var e: Dictionary = edges[c["edge"]]
	if c.has("path"):           # buses and responders follow a node path (services.gd)
		var pth: Array = c["path"]; var i: int = c["pi"]
		if i + 1 < pth.size() and pth[i] == e["b"]:
			var nx := _find_edge(pth[i], pth[i + 1])
			if nx >= 0: return nx
		if c.get("loop", false) and i + 1 >= pth.size() and pth.size() > 1 and pth[0] == e["b"]:
			c["pi"] = 0
			var nx2 := _find_edge(pth[0], pth[1])
			if nx2 >= 0: return nx2
		c.erase("path")         # left the known roads: drive on like anyone else
	var opts: Array = []
	for eid in nout.get(e["b"], []):
		var n: Dictionary = edges[eid]
		if n["b"] == e["a"]: continue                       # no U-turns
		if n["cls"] > 6: continue
		var turn: float = e["dir"].dot(n["dir"])            # 1 straight, 0 right angle, -1 back
		var w: float = 1.0 + 3.0 * maxf(turn, 0.0)                 # prefer going straight
		if n["cls"] < e["cls"]: w *= 1.5                    # drift toward bigger roads
		opts.append([eid, w])
	if opts.is_empty():
		for eid in nout.get(e["b"], []): return eid         # dead end: U-turn
		return -1
	var tot := 0.0
	for o in opts: tot += o[1]
	var r := rng.randf() * tot
	for o in opts:
		r -= o[1]
		if r <= 0.0: return o[0]
	return opts[0][0]

# ------------------------------------------------------------------ simulation
func target_count() -> int:
	var tod = main.tod
	var h := int(tod.hour()) % 24
	var d: float = T["density_by_hour"][h]
	if T.has("day_of_week"): d *= float(T["day_of_week"].get(tod.weekday_name(), 1.0))
	elif tod.weekday_name() in ["Saturday", "Sunday"]: d *= float(T["weekend_factor"])
	d *= float(T["weather_density"].get(main.weather.state, 1.0)) if main.weather else 1.0
	var cap := float(T["budget"]["max_cars"])
	if Time.get_ticks_msec() - _road_km_ms > 1500 and not edges.is_empty(): _update_road_km(main.focus_world())   # stale (sim paused)
	# (no roads measured yet = graph still building: don't cap)
	if T["budget"].has("cars_per_road_km") and _road_km_near > 0.05: cap = minf(cap, maxf(2.0, _road_km_near * float(T["budget"]["cars_per_road_km"])))
	return int(round(cap * d))

## km of drivable road within spawn range of the focus (refreshed once a second)
var _road_km_near := 999.0
var _road_km_t := 0.0
var _road_km_ms := -100000
func _update_road_km(focus: Vector3) -> void:
	var r: float = float(T["budget"]["spawn_max_m"])
	var tot := 0.0
	for e in edges:
		if e["cls"] > 6: continue
		var a: Vector3 = npos[e["a"]]
		var dd := Vector2(a.x - focus.x, a.z - focus.z).length()
		if dd < r: tot += float(e["len"]) * (1.0 if e["oneway"] else 0.5)   # two-way roads appear as two edges
	_road_km_near = tot / 1000.0
	_road_km_ms = Time.get_ticks_msec()

func _physics_process(dt: float) -> void:
	if not enabled: return
	time_s += dt
	_rebuild_t -= dt
	if _dirty and _rebuild_t <= 0.0:
		_rebuild_t = 1.0
		rebuild_graph()
	if edges.is_empty(): return
	var focus: Vector3 = main.focus_world()
	_road_km_t -= dt
	if _road_km_t <= 0.0:
		_road_km_t = 1.0
		_update_road_km(focus)
	_manage_population(focus)
	var wspeed: float = T["weather_speed"].get(main.weather.state, 1.0) if main.weather else 1.0
	if main.tod and main.tod.has_method("ai_speed_factor"): wspeed *= main.tod.ai_speed_factor()   # wet/snowy roads
	# spatial buckets for leader search (per directed edge)
	var on_edge := {}
	for c in cars:
		if c.has("free_to"): continue        # off-road police aren't in anyone's lane
		if not on_edge.has(c["edge"]): on_edge[c["edge"]] = []
		on_edge[c["edge"]].append(c)
	_update_pull_over(dt)
	for c in cars:
		_step(c, dt, wspeed, on_edge)
	for c in cars:
		_place(c, dt, false)

## cars with a siren behind them (same direction, close) slow down and move to the right
func _update_pull_over(dt: float) -> void:
	var sirens := cars.filter(func(x): return x.get("siren", false))
	var R2: float = float(T["services"]["pull_over_m"])
	for c in cars:
		var want := 0.0
		if not c.get("siren", false):
			var fwd := Vector3(sin(c["yaw"]), 0, cos(c["yaw"])) * -1.0
			for sr in sirens:
				var rel: Vector3 = c["pos"] - sr["pos"]
				if rel.length() > R2: continue
				var sf := Vector3(sin(sr["yaw"]), 0, cos(sr["yaw"])) * -1.0
				if rel.dot(sf) > 2.0 and fwd.dot(sf) > 0.5: want = 1.0
		c["pull"] = move_toward(float(c.get("pull", 0.0)), want, dt * 0.8)

func _manage_population(focus: Vector3) -> void:
	var B: Dictionary = T["budget"]
	for c in cars.duplicate():
		if Vector2(c["pos"].x - focus.x, c["pos"].z - focus.z).length() > float(B["despawn_m"]) * (2.5 if c.get("keep", false) else 1.0): _despawn(c)
	var want := target_count()
	var tries := 0
	while cars.size() < want and tries < (60 if time_s < 6.0 else 6):
		tries += 1
		var eid := rng.randi() % edges.size()
		var e: Dictionary = edges[eid]
		if e["cls"] > 6 or e["len"] < 8.0: continue
		var s: float = rng.randf() * float(e["len"])
		var p := lane_point(e, s, 0)
		var d := Vector2(p.x - focus.x, p.z - focus.z).length()
		var dmin: float = 40.0 if time_s < 6.0 else float(B["spawn_min_m"])   # first fill on load can be near
		if d < dmin or d > float(B["spawn_max_m"]): continue
		if _occupied(eid, s, 12.0): continue
		var blocked := false
		for pc in main.cars:   # never spawn on top of / right in front of the player's cars
			if is_instance_valid(pc) and (pc.global_position + main.world_offset - p).length() < 25.0: blocked = true
		if blocked: continue
		_spawn_on(eid, s)

func _occupied(eid: int, s: float, gap: float) -> bool:
	for c in cars:
		if c["edge"] == eid and absf(c["s"] - s) < gap: return true
	return false

## Gap to the vehicle (or stop line) ahead, its speed, along this edge and the next one.
func _leader(c: Dictionary, on_edge: Dictionary) -> Array:
	var e: Dictionary = edges[c["edge"]]
	var best_gap := 1e9; var best_v := 0.0
	var siren: bool = c.get("siren", false)
	for o in on_edge.get(c["edge"], []):
		if o == c: continue
		if siren and float(o.get("pull", 0.0)) > 0.5: continue    # they've moved over: drive past
		var ds: float = o["s"] - c["s"]
		if ds > 0.0 and (o["lane"] == c["lane"] or not e["oneway"]):
			var gap: float = ds - (o["len"] + c["len"]) * 0.5
			if gap < best_gap: best_gap = gap; best_v = o["v"]
	if c["next"] >= 0:
		for o in on_edge.get(c["next"], []):
			if siren and float(o.get("pull", 0.0)) > 0.5: continue
			var gap2: float = (e["len"] - c["s"]) + o["s"] - (o["len"] + c["len"]) * 0.5
			if gap2 < best_gap: best_gap = gap2; best_v = o["v"]
	# the player (on foot or driving) and the player-usable cars (parked or driven) in our lane ahead
	var here := lane_point(e, c["s"], c["lane"])
	var right := Vector3(-e["dir"].z, 0, e["dir"].x)
	var obst: Array = [main.focus_local() + main.world_offset]
	if main.peds: obst.append_array(main.peds.crossing_points())
	for pc in main.cars:
		if is_instance_valid(pc) and pc != main.current_car: obst.append(pc.global_position + main.world_offset)
	for pl in obst:
		var to: Vector3 = pl - here; to.y = 0.0
		var along: float = to.dot(e["dir"])
		if along <= 0.0 or along > 40.0: continue
		if absf(to.dot(right)) > 1.9: continue
		var gp: float = along - c["len"] * 0.5 - 2.6
		if gp < best_gap: best_gap = gp; best_v = 0.0
	return [best_gap, best_v]

signal scene_cleared(c)

func _step(c: Dictionary, dt: float, wspeed: float, on_edge: Dictionary) -> void:
	if c.has("free_to"):
		_step_free(c, dt)
		return
	var D: Dictionary = T["driver"]
	var e: Dictionary = edges[c["edge"]]
	var v0: float = e["speed"] * c["pers"] * wspeed
	var lead := _leader(c, on_edge)
	var gap: float = lead[0]; var lv: float = lead[1]
	# intersection control at the end of this edge
	var to_end: float = e["len"] - c["s"]
	var stop_line: float = to_end - float(D["stop_line_m"]) * (1.0 if ix.has(e["b"]) else 0.0)
	var ctrl := control_for(e, e["b"])
	var SV: Dictionary = T["services"]
	if c.get("siren", false):
		v0 *= float(SV["siren_speed_factor"])
		if ctrl != "go": ctrl = "yield"           # lights and siren: through red lights and stop signs, carefully
	elif c.get("pull", 0.0) > 0.0:
		v0 = minf(v0, float(SV["pull_over_speed"]))
	# a halt at the end of this edge: bus stop, or the emergency scene
	var halt := false
	if c.has("stops") and c["stops"].has(e["b"]) and c.get("served", -1) != e["b"]: halt = true
	if c.get("target", -1) == e["b"]: halt = true
	if halt and c.get("chase", false):
		pass                    # police units hold where you were last seen until police.gd re-routes them
	elif halt:
		if to_end < 3.0 and c["v"] < 0.4:
			c["dwell"] = float(c.get("dwell", 0.0)) + dt
			var need: float = float(SV["on_scene_s"]) if c.get("target", -1) == e["b"] else float(SV["bus_dwell_s"])
			if c["dwell"] >= need:
				c["dwell"] = 0.0
				if c.get("target", -1) == e["b"]:
					c.erase("target"); c["siren"] = false; c.erase("path"); c["next"] = _choose_next(c)
					emit_signal("scene_cleared", c)
				else: c["served"] = e["b"]
	if halt:
		var g3: float = maxf(to_end - 1.5, 0.0)
		if g3 < gap: gap = g3; lv = 0.0
	var ST: Dictionary = T.get("driver_styles", {}).get(c.get("style", "calm"), {})
	if ctrl == "yellow":
		# go if we can't stop comfortably; rushed / reckless drivers push it from further back
		ctrl = "go" if c["v"] * c["v"] / (2.0 * float(D["decel"])) + float(ST.get("yellow_push", 0.0)) > stop_line else "stop"
	if ctrl == "stop" and c.get("ran_red", -1) != e["b"] and stop_line > 0.0 and stop_line < 14.0 and c["v"] > 6.0 \
			and control_for(e, e["b"]) == "stop" and float(ST.get("red_run", 0.0)) > 0.0:
		# a fresh red: some drivers blow it (decided once per light)
		if not c.has("red_roll") or c["red_roll"][0] != e["b"]: c["red_roll"] = [e["b"], rng.randf() < float(ST["red_run"])]
		if c["red_roll"][1]: ctrl = "go"; c["ran_red"] = e["b"]
	if ctrl == "stopsign" and c["stopped_at"] != e["b"] and float(ST.get("roll_stop", 0.0)) > 0.0:
		if not c.has("roll_sign") or c["roll_sign"][0] != e["b"]: c["roll_sign"] = [e["b"], rng.randf() < float(ST["roll_stop"])]
		if c["roll_sign"][1]:
			v0 = min(v0, 3.0)                       # a rolling stop: slow to walking pace, never fully stop
			if stop_line < 1.0: c["stopped_at"] = e["b"]
	if ctrl == "stopsign":
		if c["stopped_at"] == e["b"]:
			ctrl = "go"
		elif c["v"] < 0.3 and stop_line < 2.0:
			c["wait"] += dt
			if c["wait"] > float(D.get("stop_wait_s", T["signals"]["stop_wait_s"])):
				c["stopped_at"] = e["b"]; c["wait"] = 0.0; ctrl = "go"
			else: ctrl = "stop"
		else: ctrl = "stop"
	if ctrl == "yield": v0 = min(v0, 6.0)
	if ctrl == "stop" and stop_line > -1.0:
		var g2: float = max(stop_line, 0.0)
		if g2 < gap: gap = g2; lv = 0.0
	# turning: slow down for sharp turns ahead
	if c["next"] >= 0 and to_end < 25.0:
		var turn: float = e["dir"].dot(edges[c["next"]]["dir"])
		if turn < 0.7: v0 = min(v0, lerp(5.0, v0, clamp((turn + 0.2) / 0.9, 0.0, 1.0)))
	# Intelligent Driver Model
	var a_max: float = D["accel"]; var b: float = D["decel"]
	var s0: float = D["min_gap_m"]; var Tg: float = float(D["headway_s"]) * float(ST.get("headway", 1.0))
	var v: float = c["v"]
	var s_star: float = s0 + max(0.0, v * Tg + v * (v - lv) / (2.0 * sqrt(a_max * b)))
	var acc: float = a_max * (1.0 - pow(v / max(v0, 0.1), 4.0) - pow(s_star / max(gap, 0.1), 2.0))
	acc = clamp(acc, -9.0, a_max)
	v = max(0.0, v + acc * dt)
	if gap < 0.3: v = 0.0
	c["v"] = v
	c["braking"] = acc < -1.0 or v < 0.2
	c["s"] += v * dt
	# advance across nodes
	var guard := 0
	while c["s"] > edges[c["edge"]]["len"] and guard < 4:
		guard += 1
		var over: float = c["s"] - edges[c["edge"]]["len"]
		var nx: int = c["next"]
		if nx < 0:
			c["s"] = edges[c["edge"]]["len"]; c["v"] = 0.0
			break
		c["edge"] = nx; c["ea"] = edges[nx]["a"]; c["eb"] = edges[nx]["b"]; c["s"] = over
		var ne: Dictionary = edges[nx]
		var per_dir: int = ne["lanes"] if ne["oneway"] else max(1, ne["lanes"] / 2)
		c["lane"] = min(c["lane"], per_dir - 1)
		if c["stopped_at"] != ne["a"]: c["stopped_at"] = -1
		if c.has("path"): c["pi"] = int(c["pi"]) + 1
		c["next"] = _choose_next(c)

## off the road network: drive straight at a point (police closing in on the player), stopping short of it
func _step_free(c: Dictionary, dt: float) -> void:
	var fp: Vector3 = c.get("free_pos", c["pos"])
	var to: Vector3 = c["free_to"] - fp; to.y = 0
	var d := to.length()
	var stand: float = float(c.get("free_stand", 6.0))
	var want: float = clampf((d - stand) * 0.9, 0.0, 14.0)
	var v: float = c["v"]
	v = move_toward(v, want, (4.0 if want > v else 9.0) * dt)
	c["v"] = v; c["braking"] = want < v - 0.5
	if d > 0.1:
		var hd := atan2(-to.x, -to.z)
		c["free_yaw"] = lerp_angle(float(c.get("free_yaw", c["yaw"])), hd, clampf(dt * 2.5, 0.0, 1.0))
	var fwd := Vector3(-sin(c["free_yaw"]), 0, -cos(c["free_yaw"]))
	c["free_pos"] = fp + fwd * v * dt

## back onto the nearest road after driving free
func snap_to_graph(c: Dictionary) -> void:
	var fp: Vector3 = c.get("free_pos", c["pos"])
	var best := -1; var bd := 1e9; var bs := 0.0
	for k in edges.size():
		var e: Dictionary = edges[k]
		if e["cls"] > 6: continue
		var q := Geometry3D.get_closest_point_to_segment(fp, npos[e["a"]], npos[e["b"]])
		var dd := Vector2(q.x - fp.x, q.z - fp.z).length()
		if dd < bd: bd = dd; best = k; bs = (q - npos[e["a"]]).length()
	c.erase("free_to"); c.erase("free_pos"); c.erase("free_yaw")
	if best < 0: return
	c["edge"] = best; c["ea"] = edges[best]["a"]; c["eb"] = edges[best]["b"]; c["s"] = bs; c["lane"] = 0
	c.erase("path")
	c["next"] = _choose_next(c)

func _place(c: Dictionary, dt: float, snap: bool) -> void:
	if c.has("free_pos"):
		_place_free(c, dt)
		return
	var e: Dictionary = edges[c["edge"]]
	var p := lane_point(e, c["s"], c["lane"])
	if c.get("pull", 0.0) > 0.0:
		p += Vector3(-e["dir"].z, 0, e["dir"].x) * float(T["services"]["pull_over_shift_m"]) * float(c["pull"])
	# look ahead a few metres for a smooth heading through corners
	var ahead: float = float(c["s"]) + 4.0
	var pa: Vector3
	if ahead <= e["len"] or c["next"] < 0:
		pa = lane_point(e, min(ahead, e["len"]), c["lane"])
	else:
		pa = lane_point(edges[c["next"]], ahead - e["len"], c["lane"])
	var yaw := atan2(-(pa.x - p.x), -(pa.z - p.z))
	var body: AnimatableBody3D = c["node"]
	if not is_instance_valid(body): return
	c["ray_t"] -= dt
	if c["ray_t"] <= 0.0 or snap:
		c["ray_t"] = 0.3
		var sp: PhysicsDirectSpaceState3D = main.get_world_3d().direct_space_state
		var q := PhysicsRayQueryParameters3D.create(p - main.world_offset + Vector3(0, 30, 0), p - main.world_offset + Vector3(0, -30, 0), 1)
		var hit := sp.intersect_ray(q)
		if not hit.is_empty(): c["y"] = hit["position"].y + main.world_offset.y
	var target := Vector3(p.x, float(c["y"]), p.z)
	var k := 1.0 if snap else clampf(dt * 10.0, 0.0, 1.0)
	c["pos"] = target if snap else (c["pos"] as Vector3).lerp(target, k)
	c["yaw"] = yaw if snap else lerp_angle(c["yaw"], yaw, clampf(dt * 8.0, 0.0, 1.0))
	body.global_transform = Transform3D(Basis(Vector3.UP, c["yaw"]), c["pos"] - main.world_offset)

func _place_free(c: Dictionary, dt: float) -> void:
	var body: AnimatableBody3D = c["node"]
	if not is_instance_valid(body): return
	var p: Vector3 = c["free_pos"]
	c["ray_t"] -= dt
	if c["ray_t"] <= 0.0:
		c["ray_t"] = 0.2
		var sp: PhysicsDirectSpaceState3D = main.get_world_3d().direct_space_state
		var q := PhysicsRayQueryParameters3D.create(p - main.world_offset + Vector3(0, 30, 0), p - main.world_offset + Vector3(0, -30, 0), 1)
		var hit := sp.intersect_ray(q)
		if not hit.is_empty(): c["y"] = hit["position"].y + main.world_offset.y
	c["pos"] = Vector3(p.x, float(c["y"]), p.z)
	c["yaw"] = float(c["free_yaw"])
	body.global_transform = Transform3D(Basis(Vector3.UP, c["yaw"]), c["pos"] - main.world_offset)

func _process(_dt: float) -> void:
	var night: float = main.tod.night if main.tod else 0.0
	_head_mat.emission_energy_multiplier = 0.2 + 3.0 * night
	_tail_mat.emission_energy_multiplier = 0.2 + 1.8 * night

## Debug/tests: the live agents.
func count() -> int: return cars.size()
