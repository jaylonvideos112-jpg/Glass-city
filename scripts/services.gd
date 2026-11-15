extends Node
## Public services (Bible stage 3), on top of traffic.gd's AI cars:
##   * Glass City Transit buses run the routes in source_data/bus_routes.json (made by
##     tools/pipeline/make_bus_routes.py) and stop at each stop for a few seconds; stops get a sign post.
##   * Emergency dispatch: every few minutes an incident happens near the player; a police car, ambulance or fire
##     engine drives there with lights and siren (through red lights, carefully), stays on scene, then drives on.
##     Other cars slow down and move right when a siren comes up behind them (traffic.gd _update_pull_over).
##   * Police cruisers also patrol as ordinary traffic.
## Settings: traffic.json "services".

var main: Node
var tr: Node
var S: Dictionary
var routes: Array = []
var operator := "Glass City Transit"
var rng := RandomNumberGenerator.new()
var _bus_t := 0.0
var _dispatch_t := 0.0
var incidents: Array = []        # {node, type, car, t}
var _stop_signs := {}            # node id -> Node3D
var _sign_t := 0.0
var _sign_mesh: ArrayMesh
var _flash_t := 0.0

func _ready() -> void:
	tr = main.traffic
	S = tr.T["services"]
	rng.seed = 4242
	if FileAccess.file_exists("res://source_data/bus_routes.json"):
		var d = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/bus_routes.json"))
		routes = d["routes"]; operator = d.get("operator", operator)
		for r in routes:
			var st := {}
			for n in r["stops"]: st[int(n)] = true
			r["stop_set"] = st
			r["nodes"] = r["nodes"].map(func(x): return int(x))
	_dispatch_t = rng.randf_range(float(S["dispatch_every_s"][0]) * 0.3, float(S["dispatch_every_s"][0]))
	_sign_mesh = _make_sign()
	tr.scene_cleared.connect(_on_cleared)

func buses() -> Array:
	return tr.cars.filter(func(c): return c.has("route"))

func responders() -> Array:
	return tr.cars.filter(func(c): return c.get("siren", false))

func _process(dt: float) -> void:
	if tr == null or not tr.enabled or tr.edges.is_empty(): return
	_bus_t -= dt
	if _bus_t <= 0.0:
		_bus_t = float(S["bus_spawn_every_s"])
		if buses().size() < int(S["max_buses"]): spawn_bus()
	_dispatch_t -= dt
	if _dispatch_t <= 0.0:
		_dispatch_t = rng.randf_range(float(S["dispatch_every_s"][0]), float(S["dispatch_every_s"][1]))
		dispatch()
	_sign_t -= dt
	if _sign_t <= 0.0:
		_sign_t = 2.0
		_update_stop_signs()
	_flash_t += dt
	for c in tr.cars:
		var l: OmniLight3D = c.get("beacon")
		if l == null or not is_instance_valid(l): continue
		l.visible = c.get("siren", false)
		var red := fmod(_flash_t * 3.0, 1.0) < 0.5
		l.light_color = Color(1.0, 0.1, 0.05) if red or c["type"] == "firetruck" else Color(0.15, 0.3, 1.0)

# ------------------------------------------------------------------ buses
## put a bus on a random route, on a stretch of it that is loaded and in spawn range. Returns the car or {}.
func spawn_bus(force_near := false) -> Dictionary:
	if routes.is_empty(): return {}
	var focus: Vector3 = main.focus_world()
	var B: Dictionary = tr.T["budget"]
	var lo: float = 30.0 if force_near else float(B["spawn_min_m"])
	for attempt in 12:
		var r: Dictionary = routes[rng.randi() % routes.size()]
		var ns: Array = r["nodes"]
		var cand := []
		for i in ns.size() - 1:
			if not tr.npos.has(ns[i]) or not tr.npos.has(ns[i + 1]): continue
			var p: Vector3 = tr.npos[ns[i]]
			var d := Vector2(p.x - focus.x, p.z - focus.z).length()
			if d < lo or d > float(B["spawn_max_m"]): continue
			var eid: int = tr._find_edge(ns[i], ns[i + 1])
			if eid >= 0 and not tr._occupied(eid, 0.0, 16.0): cand.append([i, eid])
		if cand.is_empty(): continue
		var pick: Array = cand[rng.randi() % cand.size()]
		var c: Dictionary = tr._spawn_on(pick[1], 0.0, "bus")
		c["route"] = r["ref"]; c["route_name"] = r["name"]
		c["path"] = ns; c["pi"] = pick[0] + 1; c["loop"] = true
		c["stops"] = r["stop_set"]
		c["next"] = tr._choose_next(c)
		return c
	return {}

func _make_sign() -> ArrayMesh:
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	tr._box(st, Vector3(0.08, 2.6, 0.08), Vector3(0, 1.3, 0), Color(0.45, 0.47, 0.5))
	tr._box(st, Vector3(0.05, 0.55, 0.45), Vector3(0, 2.45, 0), Color(0.1, 0.35, 0.75))
	tr._box(st, Vector3(0.06, 0.12, 0.42), Vector3(0, 2.62, 0), Color(0.95, 0.95, 0.95))
	var m := st.commit()
	var mat := StandardMaterial3D.new(); mat.vertex_color_use_as_albedo = true; mat.roughness = 0.6
	m.surface_set_material(0, mat)
	return m

## bus stop signs on the curb at stops near the player (pooled by node)
func _update_stop_signs() -> void:
	var focus: Vector3 = main.focus_world()
	var want := {}
	for r in routes:
		for n in r["stop_set"]:
			if want.has(n) or not tr.npos.has(n): continue
			var p: Vector3 = tr.npos[n]
			if Vector2(p.x - focus.x, p.z - focus.z).length() < 320.0: want[n] = true
	for n in _stop_signs.keys():
		if not want.has(n):
			if is_instance_valid(_stop_signs[n]): _stop_signs[n].queue_free()
			_stop_signs.erase(n)
	for n in want:
		if _stop_signs.has(n): continue
		var outs: Array = tr.nout.get(n, [])
		var p: Vector3 = tr.npos[n]
		var off := Vector3(3.0, 0, 0)
		if not outs.is_empty():
			var e: Dictionary = tr.edges[outs[0]]
			off = Vector3(-e["dir"].z, 0, e["dir"].x) * (float(e["w"]) * 0.5 + 1.2) - e["dir"] * 4.0
		var mi := MeshInstance3D.new(); mi.mesh = _sign_mesh
		mi.set_meta("stop_node", n)
		main.world.add_child(mi)
		var y := _ground_y(p + off)
		mi.global_position = p + off + Vector3(0, y, 0) - main.world_offset
		_stop_signs[n] = mi

func _ground_y(p: Vector3) -> float:
	var sp: PhysicsDirectSpaceState3D = main.get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(p - main.world_offset + Vector3(0, 40, 0), p - main.world_offset + Vector3(0, -40, 0), 1)
	var hit := sp.intersect_ray(q)
	return (hit["position"].y + main.world_offset.y) if not hit.is_empty() else 0.0

# ------------------------------------------------------------------ emergencies
## shortest node path from a to b over the loaded, drivable, directed road graph
func route_path(a: int, b: int, max_nodes := 6000) -> Array:
	var dist := {a: 0.0}; var prev := {}
	var open := [[0.0, a]]
	var seen := 0
	while not open.is_empty() and seen < max_nodes:
		var best := 0
		for i in open.size():
			if open[i][0] < open[best][0]: best = i
		var cur: Array = open[best]; open.remove_at(best)
		var n: int = cur[1]
		if n == b: break
		if cur[0] > dist.get(n, 1e18): continue
		seen += 1
		for eid in tr.nout.get(n, []):
			var e: Dictionary = tr.edges[eid]
			if e["cls"] > 6: continue
			var nd: float = cur[0] + float(e["len"])
			if nd < dist.get(e["b"], 1e18):
				dist[e["b"]] = nd; prev[e["b"]] = n; open.append([nd, e["b"]])
	if not prev.has(b): return []
	var out := [b]
	while out[-1] != a: out.append(prev[out[-1]])
	out.reverse()
	return out

func _pick_kind() -> String:
	var mix: Dictionary = S["dispatch_mix"]
	var tot := 0.0
	for k in mix: tot += float(mix[k])
	var r := rng.randf() * tot
	for k in mix:
		r -= float(mix[k])
		if r <= 0.0: return k
	return "police"

## start an emergency near the player. Returns the incident or {} if no road layout fits right now.
func dispatch(kind := "") -> Dictionary:
	if kind == "": kind = _pick_kind()
	var focus: Vector3 = main.focus_world()
	var nodes: Array = tr.npos.keys()
	if nodes.is_empty(): return {}
	for attempt in 30:
		var inc: int = nodes[rng.randi() % nodes.size()]
		var ip: Vector3 = tr.npos[inc]
		var di := Vector2(ip.x - focus.x, ip.z - focus.z).length()
		if di < float(S["incident_m"][0]) or di > float(S["incident_m"][1]): continue
		if tr.nout.get(inc, []).is_empty(): continue
		# responder starts on a road edge in range of the player, a good way from the scene
		for a2 in 20:
			var eid: int = rng.randi() % tr.edges.size()
			var e: Dictionary = tr.edges[eid]
			if e["cls"] > 5 or e["len"] < 10.0: continue
			var sp: Vector3 = tr.npos[e["a"]]
			var ds := Vector2(sp.x - focus.x, sp.z - focus.z).length()
			if ds < float(S["responder_start_m"][0]) or ds > float(S["responder_start_m"][1]): continue
			if Vector2(sp.x - ip.x, sp.z - ip.z).length() < 120.0: continue
			if tr._occupied(eid, 0.0, 14.0): continue
			var pth := route_path(e["b"], inc)
			if pth.size() < 3: continue
			var c: Dictionary = tr._spawn_on(eid, 0.0, kind)
			c["path"] = pth; c["pi"] = 0; c["target"] = inc; c["siren"] = true; c["keep"] = true
			c["next"] = tr._choose_next(c)
			var l := OmniLight3D.new(); l.omni_range = 14.0; l.light_energy = 2.5; l.position = Vector3(0, float(tr._type(kind)["size"][2]) + 0.4, 0)
			c["node"].add_child(l); c["beacon"] = l
			var incd := {"node": inc, "type": kind, "car": c, "t": 0.0}
			incidents.append(incd)
			if main.hud and main.hud.has_method("flash"):
				main.hud.flash({"police": "Police responding nearby", "ambulance": "Ambulance on the way", "firetruck": "Fire engine responding"}[kind])
			return incd
	return {}

func _on_cleared(c: Dictionary) -> void:
	c.erase("keep")
	incidents = incidents.filter(func(i): return i["car"] != c)

## distance from a world point to the nearest siren (for audio); INF when none
func nearest_siren(p: Vector3) -> float:
	var best := INF
	for c in tr.cars:
		if c.get("siren", false): best = minf(best, (c["pos"] - p).length())
	return best
