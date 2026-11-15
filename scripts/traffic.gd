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
var _body_mat: StandardMaterial3D
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

func _ready() -> void:
	T = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
	T["vehicles"] = roster_types() + T["vehicles"]
	rng.seed = 1977
	main.streamer.chunk_loaded.connect(func(_k): _dirty = true)
	_body_mat = StandardMaterial3D.new()
	_body_mat.vertex_color_use_as_albedo = true
	_body_mat.roughness = 0.45
	_body_mat.metallic = 0.25
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
			npos[a] = Vector3(pa.x, 0, pa.z); npos[b] = Vector3(pb.x, 0, pb.z)
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
			else: c["edge"] = ne

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

## One mesh per (type, paint): body surface (vertex colours) + lights surface (emissive at night).
func vehicle_mesh(v: Dictionary, paint: Color) -> ArrayMesh:
	var key := "%s|%s" % [v["id"], paint.to_html()]
	if _mesh_cache.has(key): return _mesh_cache[key]
	var L: float = v["size"][0]; var W: float = v["size"][1]; var H: float = v["size"][2]
	var cab: Array = v["cabin"]
	var glass := Color(0.08, 0.1, 0.13); var dark := Color(0.06, 0.06, 0.06); var tire := Color(0.04, 0.04, 0.04)
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var body: String = v["body"]
	var floor_y := 0.32
	var low_h: float = H * (0.45 if body in ["sedan", "hatch", "suv", "pickup", "wagon"] else (0.5 if body in ["coupe", "sports"] else 0.92))
	_box(st, Vector3(W, low_h - floor_y, L), Vector3(0, (low_h + floor_y) * 0.5, 0), paint)
	match body:
		"sedan", "hatch", "suv", "wagon", "coupe", "sports":
			var cl: float = L * cab[1]; var cz: float = L * (cab[0] - 0.5) + cl * 0.5 - L * 0.08
			_box(st, Vector3(W * 0.88, H - low_h, cl), Vector3(0, (H + low_h) * 0.5, cz + (0.15 if body == "hatch" else 0.0)), glass)
			_box(st, Vector3(W * 0.9, 0.07, cl * 0.92), Vector3(0, H, cz), paint)
		"pickup":
			var cl2: float = L * 0.32
			_box(st, Vector3(W * 0.9, H - low_h, cl2), Vector3(0, (H + low_h) * 0.5, -L * 0.12), glass)
			_box(st, Vector3(W * 0.92, 0.07, cl2), Vector3(0, H, -L * 0.12), paint)
			_box(st, Vector3(W, 0.45, L * 0.38), Vector3(0, low_h + 0.2, L * 0.29), paint)   # bed walls
			_box(st, Vector3(W * 0.84, 0.4, L * 0.36), Vector3(0, low_h + 0.24, L * 0.29), dark)
		"van", "box", "bus":
			_box(st, Vector3(W * 0.96, H * 0.22, 0.05), Vector3(0, H * 0.72, -L * 0.5 - 0.01), glass)   # windscreen
			if body == "bus":
				for sgn in [-1, 1]: _box(st, Vector3(0.04, H * 0.28, L * 0.8), Vector3(sgn * W * 0.5, H * 0.66, 0.4), glass)
			if body == "box": _box(st, Vector3(W * 1.02, H * 0.02, L * 0.7), Vector3(0, H * 0.94, L * 0.13), Color(0.9, 0.9, 0.88))
	if v.get("livery", "") == "police":
		_box(st, Vector3(W * 0.94, 0.12, L * 0.24), Vector3(0, low_h * 0.7, -L * 0.05), Color(0.95, 0.95, 0.95))
		_box(st, Vector3(1.0, 0.12, 0.25), Vector3(0, H + 0.1, -L * 0.05), Color(0.1, 0.1, 0.12))
	if v.get("livery", "") == "ambulance":
		for sgn in [-1, 1]: _box(st, Vector3(0.03, 0.3, L * 0.9), Vector3(sgn * (W * 0.5 + 0.01), H * 0.55, 0), Color(0.8, 0.1, 0.08))
		_box(st, Vector3(W * 0.96, H * 0.22, 0.05), Vector3(0, H * 0.72, -L * 0.5 - 0.01), glass)
	if v.get("livery", "") == "fire":
		for sgn in [-1, 1]: _box(st, Vector3(0.03, 0.18, L * 0.95), Vector3(sgn * (W * 0.5 + 0.01), H * 0.4, 0), Color(0.95, 0.85, 0.2))
		_box(st, Vector3(W * 0.7, 0.2, L * 0.55), Vector3(0, H + 0.1, L * 0.12), Color(0.75, 0.75, 0.78))   # ladder
	_box(st, Vector3(W + 0.02, 0.2, 0.25), Vector3(0, 0.42, -L * 0.5), dark)
	_box(st, Vector3(W + 0.02, 0.2, 0.25), Vector3(0, 0.42, L * 0.5), dark)
	for sx in [-1, 1]:
		for sz in [-1, 1]:
			_box(st, Vector3(0.24, 0.66, 0.66), Vector3(sx * (W * 0.5 - 0.1), 0.33, sz * L * 0.33), tire)
	var am := st.commit()
	am.surface_set_material(0, _body_mat)
	var st2 := SurfaceTool.new(); st2.begin(Mesh.PRIMITIVE_TRIANGLES)
	var st3 := SurfaceTool.new(); st3.begin(Mesh.PRIMITIVE_TRIANGLES)
	for sx in [-1, 1]:
		_box(st2, Vector3(0.32, 0.13, 0.04), Vector3(sx * W * 0.34, low_h * 0.78, -L * 0.5 - 0.03), Color.WHITE)
		_box(st3, Vector3(0.32, 0.13, 0.04), Vector3(sx * W * 0.34, low_h * 0.78, L * 0.5 + 0.03), Color.WHITE)
	st2.commit(am); am.surface_set_material(1, _head_mat)
	st3.commit(am); am.surface_set_material(2, _tail_mat)
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
	main.world.add_child(body)
	var per_dir: int = e["lanes"] if e["oneway"] else max(1, e["lanes"] / 2)
	var c := {"node": body, "type": v["id"], "paint": paint, "len": float(v["size"][0]), "edge": eid, "ea": e["a"], "eb": e["b"], "s": s,
		"lane": rng.randi() % per_dir, "v": 0.0, "pers": 1.0 + rng.randf_range(-1.0, 1.0) * float(T["driver"]["speed_jitter"]),
		"y": 0.0, "ray_t": 0.0, "wait": 0.0, "stopped_at": -1, "next": -1, "pos": Vector3.ZERO, "yaw": 0.0}
	c["v"] = e["speed"] * 0.6
	c["next"] = _choose_next(c)
	cars.append(c)
	spawned_total += 1
	_place(c, 1.0, true)
	return c

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
	if tod.weekday_name() in ["Saturday", "Sunday"]: d *= float(T["weekend_factor"])
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
	if ctrl == "yellow":
		# go if we can't stop comfortably
		ctrl = "go" if c["v"] * c["v"] / (2.0 * float(D["decel"])) > stop_line else "stop"
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
	var s0: float = D["min_gap_m"]; var Tg: float = D["headway_s"]
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
