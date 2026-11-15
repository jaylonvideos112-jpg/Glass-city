extends Node
## Pedestrians (Bible §5): people walking the real sidewalks (both sides of every street that has them, using the
## road widths exported by the pipeline), crossing only at intersections, on the walk phase or when the road is
## clear. Cars stop for people in the crosswalk (traffic.gd reads crossing_points()). Data: source_data/pedestrians.json.
## Positions are WORLD coordinates (survive origin rebasing). One MeshInstance (one draw call) per person.

const DATA_PATH := "res://source_data/pedestrians.json"

var main: Node
var P: Dictionary
var rng := RandomNumberGenerator.new()
var peds: Array = []
var walk_edges: Array = []        # canonical traffic edge ids that have sidewalks
var node_walk := {}               # node id -> [edge ids]
var side_block := {}              # edge id -> side (+1/-1) that faces the other carriageway of a divided road
var node_r := {}                  # node id -> corner set-back (m): walk/cross outside the intersection box
var _graph_version := -1
var _mat: ShaderMaterial
var _meshes: Array = []
var enabled := true
var crossings_started := 0

func _ready() -> void:
	P = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
	rng.seed = 4141
	_mat = ShaderMaterial.new()
	_mat.shader = load("res://shaders/pedestrian.gdshader")
	for i in 32: _meshes.append(_make_person())
	if FileAccess.file_exists("res://source_data/npc_schedules.json"):
		SCH = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/npc_schedules.json"))
	for a in OS.get_cmdline_user_args():
		if a == "--no-peds": enabled = false

# ------------------------------------------------------------------ mesh
func _box(st: SurfaceTool, size: Vector3, pos: Vector3, col: Color, part: int, pivot: float) -> void:
	var bm := BoxMesh.new(); bm.size = size
	var arr := bm.get_mesh_arrays()
	var v: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]; var n: PackedVector3Array = arr[Mesh.ARRAY_NORMAL]
	for i in arr[Mesh.ARRAY_INDEX]:
		st.set_color(col); st.set_normal(n[i]); st.set_uv2(Vector2(part, pivot)); st.add_vertex(v[i] + pos)

func _pick(key: String) -> Color:
	var a: Array = P[key]
	return Color(a[rng.randi() % a.size()])

func _make_person() -> ArrayMesh:
	var h := rng.randf_range(0.92, 1.08)          # height scale
	var w := rng.randf_range(0.9, 1.15)           # build
	var skin := _pick("skin"); var hair := _pick("hair"); var top := _pick("tops"); var bot := _pick("bottoms"); var shoe := _pick("shoes")
	var dress := rng.randf() < 0.12
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var hip := 0.92 * h; var sh := 1.42 * h
	_box(st, Vector3(0.42 * w, 0.58 * h, 0.24 * w), Vector3(0, (hip + sh) * 0.5 + 0.02, 0), top, 0, 0)     # torso
	if dress: _box(st, Vector3(0.46 * w, 0.4 * h, 0.3 * w), Vector3(0, hip - 0.12 * h, 0), top, 0, 0)
	_box(st, Vector3(0.1, 0.1, 0.1), Vector3(0, sh + 0.06 * h, 0), skin, 0, 0)                              # neck
	_box(st, Vector3(0.21, 0.25 * h, 0.23), Vector3(0, sh + 0.22 * h, 0), skin, 0, 0)                        # head
	_box(st, Vector3(0.23, 0.08 + rng.randf() * 0.07, 0.25), Vector3(0, sh + 0.36 * h, 0.01), hair, 0, 0)   # hair
	for sgn in [-1, 1]:
		var leg := 1 if sgn < 0 else 2
		_box(st, Vector3(0.15 * w, hip - 0.08, 0.17 * w), Vector3(0.1 * sgn * w, hip * 0.5 + 0.04, 0), skin if dress else bot, leg, hip)
		_box(st, Vector3(0.15 * w, 0.08, 0.27), Vector3(0.1 * sgn * w, 0.04, -0.04), shoe, leg, hip)
		var arm := 3 if sgn < 0 else 4
		_box(st, Vector3(0.11, 0.6 * h, 0.12), Vector3(0.28 * sgn * w, sh - 0.28 * h, 0), top, arm, sh - 0.02)
		_box(st, Vector3(0.09, 0.09, 0.09), Vector3(0.28 * sgn * w, sh - 0.62 * h, 0), skin, arm, sh - 0.02)
	# umbrella (in the right hand, raised): canopy + shaft; hidden by the shader unless raining
	var uc := _pick("umbrellas")
	_box(st, Vector3(0.025, 0.75, 0.025), Vector3(0.28 * w, sh + 0.2, -0.32), Color(0.2, 0.2, 0.2), 5, 0)
	_box(st, Vector3(1.0, 0.06, 1.0), Vector3(0.2 * w, sh + 0.6, -0.2), uc, 5, 0)
	_box(st, Vector3(0.7, 0.08, 0.7), Vector3(0.2 * w, sh + 0.66, -0.2), uc, 5, 0)
	var m := st.commit()
	m.surface_set_material(0, _mat)
	return m

# ------------------------------------------------------------------ sidewalk graph (from the traffic graph)
func _rebuild() -> void:
	var tr = main.traffic
	walk_edges.clear(); node_walk.clear()
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		if not e.get("walk", false): continue
		if not e["oneway"] and e["a"] > e["b"]: continue      # one canonical edge per two-way road
		walk_edges.append(i)
		for n in [e["a"], e["b"]]:
			if not node_walk.has(n): node_walk[n] = []
			node_walk[n].append(i)
	_graph_version = tr.graph_version
	# divided roads: a one-way carriageway with an opposite one-way carriageway close alongside has no sidewalk
	# on that side (it's the median)
	side_block.clear()
	for i in walk_edges:
		var e: Dictionary = tr.edges[i]
		if not e["oneway"]: continue
		var mid: Vector3 = tr.npos[e["a"]] + e["dir"] * float(e["len"]) * 0.5
		var right := Vector3(-e["dir"].z, 0, e["dir"].x)
		for j in tr.edges.size():
			var o: Dictionary = tr.edges[j]
			if j == i or not o["oneway"] or o["dir"].dot(e["dir"]) > -0.8: continue
			var cp := Geometry3D.get_closest_point_to_segment(mid, tr.npos[o["a"]], tr.npos[o["b"]])
			var dd: float = Vector2(cp.x - mid.x, cp.z - mid.z).length()
			if dd < (float(e["w"]) + float(o["w"])) * 0.5 + 14.0:
				side_block[i] = 1 if (cp - mid).dot(right) > 0.0 else -1
				break
	# any road whose sidewalk would land on another road (service lane alongside, tight bend, frontage road):
	# no sidewalk on that side. Sidewalk points along the edge are tested against every other nearby road.
	var soff: float = float(P["sidewalk_offset_from_curb"][1])
	for i in walk_edges:
		if side_block.has(i): continue
		var e: Dictionary = tr.edges[i]
		var a: Vector3 = tr.npos[e["a"]]
		var right := Vector3(-e["dir"].z, 0, e["dir"].x)
		var near: Array = []
		for j in tr.edges.size():
			if j == i: continue
			var o: Dictionary = tr.edges[j]
			if o["a"] == e["a"] or o["a"] == e["b"] or o["b"] == e["a"] or o["b"] == e["b"]: continue
			var oa: Vector3 = tr.npos[o["a"]]
			if Vector2(oa.x - a.x, oa.z - a.z).length() < float(o["len"]) + float(e["len"]) + 30.0: near.append(j)
		if near.is_empty(): continue
		for side in [1, -1]:
			var bad := false
			var hits := 0
			for t in [0.25, 0.5, 0.75]:
				var q: Vector3 = a + e["dir"] * float(e["len"]) * t + right * side * (float(e["w"]) * 0.5 + soff)
				for j in near:
					var o: Dictionary = tr.edges[j]
					var cp := Geometry3D.get_closest_point_to_segment(q, tr.npos[o["a"]], tr.npos[o["b"]])
					if Vector2(cp.x - q.x, cp.z - q.z).length() < float(o["w"]) * 0.5 + 0.5: hits += 1; break
			bad = hits >= 2      # along the road, not just at a corner
			if bad:
				side_block[i] = side
				break
	node_r.clear()
	for n in node_walk:
		var ways := 0; var r := 0.0
		for k in tr.nout.get(n, []):
			ways += 1; r = max(r, float(tr.edges[k].get("w", 8.0)) * 0.5)
		node_r[n] = (r + 1.2) if (ways >= 3 or tr.ix.has(n)) else 0.0
	for p in peds.duplicate():   # traffic graph was rebuilt: re-find each person's edge by its node ids
		var ne: int = tr._find_edge(p["ea"], p["eb"])
		if ne < 0: _despawn(p)
		else: p["edge"] = ne

## Walkable range [lo, hi] along an edge: stops short of intersections by their corner set-back.
func _limits(eid: int) -> Vector2:
	var e: Dictionary = main.traffic.edges[eid]
	var lo: float = node_r.get(e["a"], 0.0); var hi: float = float(e["len"]) - node_r.get(e["b"], 0.0)
	if hi < lo: lo = float(e["len"]) * 0.5; hi = lo
	return Vector2(lo, hi)

func sidewalk_point(eid: int, s: float, side: int, off: float) -> Vector3:
	var e: Dictionary = main.traffic.edges[eid]
	var right := Vector3(-e["dir"].z, 0, e["dir"].x)
	return main.traffic.npos[e["a"]] + e["dir"] * s + right * side * (float(e.get("w", 8.0)) * 0.5 + off)

# ------------------------------------------------------------------ population
## NPC schedules (source_data/npc_schedules.json): who is out here, now
var SCH: Dictionary = {}

## "downtown", "nightlife" (near a bar door) or "residential"
func area_at(p: Vector3) -> String:
	if main.bars:
		var r: float = float(SCH.get("nightlife_radius_m", 220.0))
		for d in main.bars.doors:
			if is_instance_valid(d["node"]):
				var q: Vector3 = d["node"].global_position + main.world_offset
				if Vector2(q.x - p.x, q.z - p.z).length() < r: return "nightlife"
	if Vector2(p.x, p.z).length() < float(P["area"]["downtown_radius_m"]): return "downtown"
	return "residential"

## role -> how many of that role are out here now (share x activity x weekend factor)
func role_weights(area: String, hour: float) -> Dictionary:
	var out := {}
	var h := int(hour) % 24
	var weekend: bool = main.tod.weekday_name() in ["Saturday", "Sunday"]
	for r in SCH.get("roles", {}):
		var R: Dictionary = SCH["roles"][r]
		var w: float = float(R["share"]) * float(R[area][h]) * (float(R.get("weekend", 1.0)) if weekend else 1.0)
		out[r] = w
	return out

## the hour-keyed goal of a role ("downtown", "home", "bar", "wander")
func goal_for(role: String, hour: float) -> String:
	var g: Dictionary = SCH["roles"][role].get("goal", {})
	var best := "wander"; var bh := -1
	var h := int(hour) % 24
	for k in g:   # latest key at or before now (wrapping round midnight)
		var kh := int(k)
		var dh := (h - kh + 24) % 24
		if bh < 0 or dh < bh: bh = dh; best = g[k]
	return best

func target_count() -> int:
	var tod = main.tod
	var d: float
	var f: Vector3 = main.focus_world()
	if SCH.has("roles"):
		d = 0.0
		var ws := role_weights(area_at(f), tod.hour())
		for r in ws: d += ws[r]
		d = minf(d / 0.75, 1.0)          # a busy downtown lunchtime ~ fills the budget
	else:
		d = P["density_by_hour"][int(tod.hour()) % 24]
		if tod.weekday_name() in ["Saturday", "Sunday"]: d *= float(P["weekend_factor"])
		if Vector2(f.x, f.z).length() > float(P["area"]["downtown_radius_m"]): d *= float(P["area"]["outside_factor"])
	if main.weather: d *= float(P["weather_density"].get(main.weather.state, 1.0))
	if main.bars and main.bars.inside: d = 0.0
	return int(round(float(P["budget"]["max_peds"]) * d))

## where a person with this goal is heading (world xz), or null to wander
func goal_point(goal: String, from: Vector3):
	match goal:
		"downtown": return Vector3(0, 0, 0)
		"home":
			var v := Vector3(from.x, 0, from.z)
			return from + (v.normalized() if v.length() > 1.0 else Vector3(1, 0, 0)) * 3000.0
		"bar":
			var best = null; var bd := 1e9
			if main.bars:
				for d in main.bars.doors:
					if not is_instance_valid(d["node"]): continue
					var q: Vector3 = d["node"].global_position + main.world_offset
					var dd := (q - from).length()
					if dd < bd: bd = dd; best = q
			return best
	return null

func _spawn(eid: int, s: float, side: int) -> Dictionary:
	var mi := MeshInstance3D.new()
	mi.mesh = _meshes[rng.randi() % _meshes.size()]
	main.world.add_child(mi)
	var e: Dictionary = main.traffic.edges[eid]
	var o: Array = P["sidewalk_offset_from_curb"]
	var sp: Array = P["walk_speed"]
	var raining: bool = main.weather != null and main.weather.W["states"][main.weather.state]["precip"] == "rain"
	var p := {"node": mi, "edge": eid, "ea": e["a"], "eb": e["b"], "s": s, "side": side, "dir": 1 if rng.randf() < 0.5 else -1,
		"off": rng.randf_range(o[0], o[1]), "speed": rng.randf_range(sp[0], sp[1]), "phase": rng.randf() * TAU,
		"state": "walk", "cross": [], "wait": 0.0, "y": 0.0, "ray_t": 0.0, "pos": Vector3.ZERO, "yaw": 0.0,
		"has_umb": rng.randf() < float(P["umbrella_share_in_rain"]), "umbrella": 0.0, "role": "", "goal": "wander"}
	if SCH.has("roles"):
		var ws := role_weights(area_at(main.traffic.npos[e["a"]]), main.tod.hour())
		var tot := 0.0
		for r in ws: tot += ws[r]
		var x := rng.randf() * tot
		for r in ws:
			x -= ws[r]
			if x <= 0.0: p["role"] = r; break
		if p["role"] == "": p["role"] = ws.keys()[0] if not ws.is_empty() else "resident"
		p["goal"] = goal_for(p["role"], main.tod.hour())
	p["umbrella"] = 1.0 if raining and p["has_umb"] else 0.0
	p["pos"] = sidewalk_point(eid, s, side, p["off"])
	peds.append(p)
	_ground(p, true)
	return p

func _despawn(p: Dictionary) -> void:
	if is_instance_valid(p["node"]): p["node"].queue_free()
	peds.erase(p)

func _manage(focus: Vector3) -> void:
	var B: Dictionary = P["budget"]
	for p in peds.duplicate():
		if Vector2(p["pos"].x - focus.x, p["pos"].z - focus.z).length() > float(B["despawn_m"]): _despawn(p)
	var want := target_count()
	while peds.size() > want + 8: _despawn(peds[0])     # thin out (e.g. a storm starts, or the player went inside)
	var tries := 0
	var first: bool = main.traffic.time_s < 6.0
	while peds.size() < want and tries < (80 if first else 6) and not walk_edges.is_empty():
		tries += 1
		var eid: int = walk_edges[rng.randi() % walk_edges.size()]
		var e: Dictionary = main.traffic.edges[eid]
		var lm := _limits(eid)
		if lm.y - lm.x < 2.0: continue
		var s: float = rng.randf_range(lm.x, lm.y)
		var side := 1 if rng.randf() < 0.5 else -1
		if side_block.get(eid, 0) == side: side = -side
		var q := sidewalk_point(eid, s, side, 1.5)
		var d := Vector2(q.x - focus.x, q.z - focus.z).length()
		if d < (12.0 if first else float(B["spawn_min_m"])) or d > float(B["spawn_max_m"]): continue
		_spawn(eid, s, side)

# ------------------------------------------------------------------ behaviour
## Can a person cross the road of edge `eid` at node `n` right now?
func _can_cross(eid: int, n: int) -> bool:
	var tr = main.traffic
	var e: Dictionary = tr.edges[eid]
	if tr.ix.has(n) and tr.ix[n]["ctrl"] == "signal":
		# walk when traffic moving along this road has a red (either direction)
		for k in tr.nout.get(n, []):
			var o: Dictionary = tr.edges[k]
			if absf(o["dir"].dot(e["dir"])) > 0.7:
				var back: int = tr._find_edge(o["b"], n)
				if back >= 0 and tr.control_for(tr.edges[back], n) != "stop": return false
		return true
	# otherwise: no car close to the node on any road
	var np: Vector3 = tr.npos[n]
	for c in tr.cars:
		if float(c.get("dwell", 0.0)) > 0.0: continue     # a bus at its stop / responder on scene isn't coming through
		if (c["pos"] - np).length() < float(P["crossing_clear_m"]): return false
	return true

func _at_node(p: Dictionary) -> void:
	var tr = main.traffic
	var e: Dictionary = tr.edges[p["edge"]]
	var n: int = e["b"] if p["dir"] > 0 else e["a"]
	var here: Vector3 = p["pos"]
	var opts: Array = []
	for k in node_walk.get(n, []):
		var lk := _limits(k)
		if k != p["edge"] and lk.y - lk.x > 2.0: opts.append(k)
	if opts.is_empty(): opts = [p["edge"]]            # dead end: turn around
	var nk: int = opts[rng.randi() % opts.size()]
	if p.get("role", "") != "": p["goal"] = goal_for(p["role"], main.tod.hour())   # plans change with the hour
	var gp = goal_point(p.get("goal", "wander"), here) if opts.size() > 1 else null
	if gp != null and rng.randf() < float(SCH.get("goal_bias", 0.75)):
		# head roughly toward where this person is going (work, home, the bar)
		var bestd := -2.0
		for k in opts:
			var ok: Dictionary = tr.edges[k]
			var far_end: Vector3 = tr.npos[ok["b"]] if ok["a"] == n else tr.npos[ok["a"]]
			var nn: Vector3 = tr.npos[n]
			var dirv: Vector3 = far_end - nn; dirv.y = 0
			var to_g: Vector3 = (gp as Vector3) - nn; to_g.y = 0
			var sc: float = dirv.normalized().dot(to_g.normalized()) + rng.randf_range(0.0, 0.3)
			if sc > bestd: bestd = sc; nk = k
	var ne: Dictionary = tr.edges[nk]
	var ndir := 1 if ne["a"] == n else -1
	var lim := _limits(nk)
	var sstart: float = lim.x if ndir > 0 else lim.y
	# which side of the new street is on our side of the road (nearest), which is across?
	var near_side := 1
	if sidewalk_point(nk, sstart, -1, p["off"]).distance_to(here) < sidewalk_point(nk, sstart, 1, p["off"]).distance_to(here): near_side = -1
	if side_block.get(nk, 0) == near_side: near_side = -near_side   # never walk down a median
	var side := near_side
	var intersection: bool = node_walk.get(n, []).size() >= 3 or tr.ix.has(n)
	var close_corner: bool = sidewalk_point(nk, sstart, near_side, p["off"]).distance_to(here) < 6.0   # odd geometry: don't cross
	if intersection and close_corner and rng.randf() < float(P["cross_chance"]) and side_block.get(nk, 0) != -near_side and lim.y - lim.x > 2.0: side = -near_side
	p["edge"] = nk; p["ea"] = ne["a"]; p["eb"] = ne["b"]; p["dir"] = ndir; p["s"] = sstart
	if side != near_side:
		# cross the new street at the corner: from our side to the far side
		var a := sidewalk_point(nk, sstart, near_side, p["off"])
		var b := sidewalk_point(nk, sstart, side, p["off"])
		p["cross"] = [a, b, nk, n]
		p["state"] = "wait"
		p["wait"] = 0.0
	p["side"] = side

func crossing_points() -> Array:
	var out: Array = []
	for p in peds:
		if p["state"] == "cross": out.append(p["pos"])
	return out

func _physics_process(dt: float) -> void:
	if not enabled or main.traffic == null or main.traffic.edges.is_empty(): return
	if _graph_version != main.traffic.graph_version: _rebuild()
	var focus: Vector3 = main.focus_world()
	_raining = main.weather != null and main.weather.W["states"][main.weather.state]["precip"] == "rain"
	_manage(focus)
	for p in peds:
		_step(p, dt)

var _raining := false
func _step(p: Dictionary, dt: float) -> void:
	var tr = main.traffic
	p["umbrella"] = move_toward(p["umbrella"], 1.0 if _raining and p["has_umb"] else 0.0, dt * 2.0)
	if p["edge"] >= tr.edges.size(): return
	var target: Vector3
	var moving := true
	match p["state"]:
		"walk":
			var e: Dictionary = tr.edges[p["edge"]]
			p["s"] += p["dir"] * p["speed"] * dt
			var lim := _limits(p["edge"])
			if p["s"] > lim.y or p["s"] < lim.x:
				p["s"] = clampf(p["s"], lim.x, lim.y)
				_at_node(p)
			target = sidewalk_point(p["edge"], p["s"], p["side"], p["off"])
		"wait":
			target = p["cross"][0]
			moving = (p["pos"] as Vector3).distance_to(target) > 0.3
			if not moving:
				p["wait"] += dt
				if _can_cross(p["cross"][2], p["cross"][3]) or p["wait"] > 45.0:
					p["state"] = "cross"; crossings_started += 1
		"cross":
			target = p["cross"][1]
			if (p["pos"] as Vector3).distance_to(target) < 0.4:
				p["state"] = "walk"; p["cross"] = []
	var to: Vector3 = target - p["pos"]; to.y = 0.0
	var dist := to.length()
	if dist > 0.001:
		var step: float = min(dist, p["speed"] * dt * (1.25 if p["state"] == "cross" else 1.0)) if p["state"] != "walk" else dist
		p["pos"] = p["pos"] + to / dist * step
		p["yaw"] = lerp_angle(p["yaw"], atan2(-to.x, -to.z), clampf(dt * 8.0, 0.0, 1.0))
	if moving and dist > 0.001: p["phase"] = fmod(p["phase"] + dt * p["speed"] * 5.2, TAU)
	_ground(p, false)
	var mi: MeshInstance3D = p["node"]
	if is_instance_valid(mi):
		mi.global_transform = Transform3D(Basis(Vector3.UP, p["yaw"]), Vector3(p["pos"].x, p["y"], p["pos"].z) - main.world_offset)
		mi.set_instance_shader_parameter("phase", p["phase"])
		mi.set_instance_shader_parameter("swing", 1.0 if moving and dist > 0.001 else 0.0)
		mi.set_instance_shader_parameter("umbrella", p["umbrella"])

func _ground(p: Dictionary, now: bool) -> void:
	p["ray_t"] -= 1.0 / 60.0
	if p["ray_t"] > 0.0 and not now: return
	p["ray_t"] = 0.5
	var sp: PhysicsDirectSpaceState3D = main.get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(p["pos"] - main.world_offset + Vector3(0, 20, 0), p["pos"] - main.world_offset + Vector3(0, -20, 0), 1)
	var hit := sp.intersect_ray(q)
	if not hit.is_empty(): p["y"] = hit["position"].y + main.world_offset.y

func count() -> int: return peds.size()
