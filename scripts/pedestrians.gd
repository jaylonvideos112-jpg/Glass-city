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

const Humans := preload("res://scripts/humans.gd")

## a random person (humans.gd body, colours from pedestrians.json)
func _make_person() -> ArrayMesh:
	var look := {"h": rng.randf_range(0.92, 1.08), "w": rng.randf_range(0.9, 1.15),
		"skin": _pick("skin"), "hair": _pick("hair"), "top": _pick("tops"), "top2": _pick("tops").darkened(0.15),
		"bottom": _pick("bottoms"), "shoe": _pick("shoes"), "umbrella": _pick("umbrellas"),
		"sleeves": [0, 0, 1, 1, 2][rng.randi() % 5], "legs": 2 if rng.randf() < 0.12 else (1 if rng.randf() < 0.12 else 0),
		"hair_style": [0, 0, 1, 1, 2, 3, 4][rng.randi() % 7], "beard": rng.randf() < 0.22}
	var m := Humans.build(look)
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
	while peds.size() > want + 8:
		var vict: Dictionary = peds[0]
		for q in peds:
			if not (q["state"] in ["fly", "down", "injured", "flee"]): vict = q; break
		_despawn(vict)     # thin out (e.g. a storm starts, or the player went inside)
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
	# otherwise: no moving car coming at this corner on the street we're crossing (or turning into it)
	var np: Vector3 = tr.npos[n]
	for c in tr.cars:
		if float(c.get("dwell", 0.0)) > 0.0 or float(c["v"]) < 0.8: continue   # stopped / waiting cars let you go
		if (c["pos"] - np).length() > float(P["crossing_clear_m"]): continue
		var ce: Dictionary = tr.edges[c["edge"]]
		var on_street: bool = (ce["a"] == e["a"] and ce["b"] == e["b"]) or (ce["a"] == e["b"] and ce["b"] == e["a"])
		if on_street or ce["b"] == n or c.get("next", -1) == eid: return false
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
	# cross at random sometimes, and whenever where we're going is on the other side
	var goal_across := false
	if gp != null:
		var g3: Vector3 = gp
		goal_across = sidewalk_point(nk, sstart, -near_side, p["off"]).distance_to(g3) < sidewalk_point(nk, sstart, near_side, p["off"]).distance_to(g3) - 3.0 and rng.randf() < 0.6
	if intersection and close_corner and (rng.randf() < float(P["cross_chance"]) or goal_across) and side_block.get(nk, 0) != -near_side and lim.y - lim.x > 2.0: side = -near_side
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
## hit by a car: thrown along `vel`, lands, lies there, then gets up and runs - or stays down if it was a hard hit
func knock_down(p: Dictionary, vel: Vector3) -> void:
	if p["state"] in ["fly", "down", "injured"]: return
	p["state"] = "fly"; p["fly_v"] = vel + Vector3(0, 3.0 + vel.length() * 0.15, 0)
	p["hit_speed"] = vel.length(); p["fall_yaw"] = atan2(-vel.x, -vel.z)
	p["spin"] = 0.0
	knockdowns += 1
	# people nearby scatter
	for o in peds:
		if o != p and o["state"] in ["walk", "wait", "cross"] and (o["pos"] - p["pos"]).length() < 18.0:
			_flee(o, p["pos"])

func _flee(o: Dictionary, from: Vector3) -> void:
	o["state"] = "flee"; o["flee_t"] = rng.randf_range(10.0, 18.0)
	var away: Vector3 = o["pos"] - from; away.y = 0
	o["flee_dir"] = away.normalized() if away.length() > 0.1 else Vector3(1, 0, 0)

var knockdowns := 0
func _step_special(p: Dictionary, dt: float) -> bool:
	var mi: MeshInstance3D = p["node"]
	if p.has("react_t"): p["react_t"] = maxf(0.0, float(p["react_t"]) - dt)
	var cb = main.get("combat")
	if cb and (p["state"] == "fight" or float(p.get("react_t", 0.0)) > 0.0 or p.get("posed", false)):
		var pose: Array = cb.ped_pose(p)
		if is_instance_valid(mi):
			mi.set_instance_shader_parameter("act", pose[0]); mi.set_instance_shader_parameter("act_t", pose[1])
		p["posed"] = pose[0] > 0.0
	match p["state"]:
		"fight":
			if cb: cb.step_fighter(p, dt)
			_ground(p, false)
		"fly":
			var v: Vector3 = p["fly_v"]
			v.y -= 18.0 * dt; v.x *= 1.0 - dt * 0.6; v.z *= 1.0 - dt * 0.6
			p["fly_v"] = v
			p["pos"] = p["pos"] + v * dt
			p["spin"] = minf(PI * 0.5, p["spin"] + dt * 6.0)
			_ground(p, true)
			if p["pos"].y <= p["y"] + 0.05 and v.y < 0.0:
				var lp: Vector3 = p["pos"]; lp.y = p["y"]; p["pos"] = lp
				p["state"] = "down" if p["hit_speed"] < 14.0 else "injured"
				p["down_t"] = rng.randf_range(4.0, 8.0)
				if p["state"] == "injured" and main.services and main.services.has_method("dispatch_to"):
					main.services.dispatch_to("ambulance", p["pos"])
		"down":
			p["down_t"] -= dt
			p["spin"] = PI * 0.5
			if p["down_t"] <= 0.0:
				_flee(p, p["pos"] - Vector3(sin(p["fall_yaw"]), 0, cos(p["fall_yaw"])))
				p["spin"] = 0.0
		"injured":
			p["spin"] = PI * 0.5
			p["down_t"] -= dt
			if p["down_t"] < -90.0 and (p["pos"] - main.focus_world()).length() > 40.0:
				_despawn(p); return true          # taken away by the ambulance
		"flee":
			p["flee_t"] -= dt
			var fd: Vector3 = p["flee_dir"]
			var np: Vector3 = p["pos"] + fd * p["speed"] * 2.4 * dt
			p["pos"] = np
			p["yaw"] = lerp_angle(p["yaw"], atan2(-fd.x, -fd.z), clampf(dt * 8.0, 0.0, 1.0))
			p["phase"] = fmod(p["phase"] + dt * p["speed"] * 2.4 * 5.2, TAU)
			_ground(p, false)
			if p["flee_t"] <= 0.0:
				# back to a normal walk on the nearest sidewalk
				p["state"] = "walk"
				var e: Dictionary = main.traffic.edges[p["edge"]]
				p["s"] = clampf((p["pos"] - main.traffic.npos[e["a"]]).dot(e["dir"]), 0.0, float(e["len"]))
		_:
			return false
	if is_instance_valid(mi):
		var lying: float = p.get("spin", 0.0)
		var b := Basis(Vector3.UP, p.get("fall_yaw", p["yaw"]) if not (p["state"] in ["flee", "fight"]) else p["yaw"])
		if lying > 0.0: b = b * Basis(Vector3(1, 0, 0), -lying)
		var yoff := 0.18 if lying > 1.2 else 0.0
		mi.global_transform = Transform3D(b, Vector3(p["pos"].x, p["y"] + yoff, p["pos"].z) - main.world_offset)
		mi.set_instance_shader_parameter("phase", p["phase"])
		var mv: float = 1.3 if p["state"] == "flee" else 0.0
		if p["state"] == "fight": mv = 0.0
		mi.set_instance_shader_parameter("swing", mv)
	return true

func _step(p: Dictionary, dt: float) -> void:
	var tr = main.traffic
	p["umbrella"] = move_toward(p["umbrella"], 1.0 if _raining and p["has_umb"] else 0.0, dt * 2.0)
	if p["edge"] >= tr.edges.size(): return
	if _step_special(p, dt): return
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
