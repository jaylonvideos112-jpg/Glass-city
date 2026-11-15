extends Node
## Wanted level and police response (Bible section 10), GTA-style and fictional:
##   * Crimes: hitting a car, hitting a person, ramming a police car, running a red light in front of police.
##     A crime counts if a police car sees it (within witness range) or a bystander reports it.
##   * Stars 1-5. Police units (stars + 1 at 3 stars and up) come after you with lights and sirens, re-routing to
##     where you were last seen.
##   * Escape: stay out of sight of every unit for search_s (longer at more stars); the stars blink while they search.
##   * Busted: a unit stops by you while you're stopped/on foot for bust_s -> one night in jail (Bible): released at
##     8 am outside the nearest police station, fined per star.
## Settings: source_data/police.json. Stars aren't saved (a fresh start after loading, like GTA).

var main: Node
var P: Dictionary
var stars := 0
var searching := false
var last_seen := Vector3.ZERO      # world
var _unseen_t := 0.0
var _bust_t := 0.0
var _repath_t := 0.0
var _crime_t := 0.0
var _red_t := 0.0
var stations: Array = []
var rng := RandomNumberGenerator.new()
var busted_count := 0
var crimes: Array = []             # recent [kind, witnessed_by]

func _ready() -> void:
	P = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/police.json"))
	var st = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/stations.json"))
	stations = st["stations"]["police"]
	rng.seed = 911

func traffic() -> Node:
	return main.traffic

func units() -> Array:
	return traffic().cars.filter(func(c): return c.get("chase", false))

func player_world() -> Vector3:
	return main.focus_world()

func player_speed() -> float:
	return main.current_car.speed_mps() if main.current_car else main.player.velocity.length()

# ------------------------------------------------------------------ crimes
## who saw it: "police" (a cop in range), "witness" (a bystander called it in) or ""
func witnessed(at: Vector3) -> String:
	var wr: float = float(P["witness_police_m"])
	for c in traffic().cars:
		if c["type"] == "police" and (c["pos"] - at).length() < wr: return "police"
	if main.peds:
		for p in main.peds.peds:
			if (p["pos"] - at).length() < float(P["witness_ped_m"]) and rng.randf() < float(P["witness_ped_chance"]): return "witness"
	return ""

## report a crime at a world position. Returns the new star count.
func report(kind: String, at: Vector3, force_seen := false) -> int:
	var sev: int = int(P["crimes"].get(kind, 1))
	var who := "police" if force_seen else witnessed(at)
	crimes.append([kind, who])
	if crimes.size() > 20: crimes.pop_front()
	if who == "": return stars
	var before := stars
	stars = clampi(stars + sev, 1, 5)
	last_seen = player_world(); _unseen_t = 0.0; searching = false
	if main.hud and stars > before:
		main.hud.flash({"hit_car": "Hit and run reported", "hit_ped": "You hit someone - police alerted", "ram_police": "You rammed a police car!",
			"run_red": "Ran a red light in front of police"}.get(kind, "Crime reported"))
	return stars

## the player's car touching an AI car at speed (box overlap in the AI car's frame)
func _check_car_hits() -> void:
	var car = main.current_car
	if car == null or _crime_t > 0.0: return
	var sp: float = car.speed_mps()
	var cp: Vector3 = car.global_position + main.world_offset
	for c in traffic().cars:
		var rel: Vector3 = cp - c["pos"]
		if rel.length() > 9.0: continue
		var rv: float = (car.linear_velocity - Vector3(-sin(c["yaw"]), 0, -cos(c["yaw"])) * float(c["v"])).length()
		if rv < float(P["min_hit_speed"]): continue
		var lx := rel.rotated(Vector3.UP, -float(c["yaw"]))
		var v: Dictionary = traffic()._type(c["type"])
		if absf(lx.x) < float(v["size"][1]) * 0.5 + 1.05 and absf(lx.z) < float(v["size"][0]) * 0.5 + 2.35:
			_crime_t = 2.0
			report("ram_police" if c["type"] == "police" else "hit_car", cp, c["type"] == "police")
			return

# ------------------------------------------------------------------ per frame
func _physics_process(dt: float) -> void:
	if traffic() == null or traffic().edges.is_empty() or main.cam_override: return
	_crime_t = maxf(0.0, _crime_t - dt)
	_check_peds_hit()
	_check_car_hits()
	_red_t -= dt
	if _red_t <= 0.0:
		_red_t = 0.25
		_check_red_light()
	if stars == 0: return
	_manage_units(dt)
	# seen?
	var pw := player_world()
	var seen := false
	var sight: float = float(P["sight_m"])
	for u in units():
		if (u["pos"] - pw).length() < sight: seen = true; break
	if seen:
		last_seen = pw; _unseen_t = 0.0; searching = false
	else:
		_unseen_t += dt
		searching = _unseen_t > 2.0
		if _unseen_t > float(P["search_s"]) + float(P["search_s_per_star"]) * stars:
			lose_them()
			return
	# busted: a unit right by you and you're stopped
	var close := false
	for u in units():
		if (u["pos"] - pw).length() < float(P["bust_m"]) and float(u["v"]) < 3.0: close = true
	if close and player_speed() < 1.5: _bust_t += dt
	else: _bust_t = maxf(0.0, _bust_t - dt * 0.5)
	if _bust_t > float(P["bust_s"]): bust()

func _check_peds_hit() -> void:
	var car = main.current_car
	if car == null or main.peds == null or car.speed_mps() < 4.0: return
	var cp: Vector3 = car.global_position + main.world_offset
	for p in main.peds.peds.duplicate():
		if Vector2(p["pos"].x - cp.x, p["pos"].z - cp.z).length() < 2.3 and absf(p["pos"].y - cp.y) < 3.0:
			main.peds._despawn(p)
			report("hit_ped", cp)
			return

## running a red light near a police car
func _check_red_light() -> void:
	var car = main.current_car
	if car == null or car.speed_mps() < 6.0: return
	var t = traffic()
	var cp: Vector3 = car.global_position + main.world_offset
	var vel: Vector3 = car.linear_velocity; vel.y = 0
	if vel.length() < 1.0: return
	for n in t.ix:
		if t.ix[n]["ctrl"] != "signal": continue
		var np: Vector3 = t.npos.get(n, Vector3.INF)
		if Vector2(np.x - cp.x, np.z - cp.z).length() > 7.0: continue
		# the approach we're on: an edge into n pointing the way we drive
		for e in t.edges:
			if e["b"] != n or e["dir"].dot(vel.normalized()) < 0.85: continue
			if t.control_for(e, n) == "stop" and _crime_t <= 0.0:
				_crime_t = 4.0
				var w := witnessed(cp)
				if w == "police": report("run_red", cp, true)
			return
		return

# ------------------------------------------------------------------ response
func _manage_units(dt: float) -> void:
	var want: int = stars + (1 if stars >= 3 else 0)
	var have := units()
	if have.size() < want and rng.randf() < dt * 1.5: _spawn_unit()
	_repath_t -= dt
	if _repath_t <= 0.0:
		_repath_t = 2.0
		var target: int = _nearest_node(last_seen)
		for u in have:
			var e: Dictionary = traffic().edges[u["edge"]]
			var pth: Array = main.services.route_path(e["b"], target, 3000) if target >= 0 else []
			if pth.size() >= 2:
				u["path"] = pth; u["pi"] = 0; u["next"] = traffic()._choose_next(u)
			u["target"] = target          # stop when they get there (they look around / wait)

func _nearest_node(p: Vector3) -> int:
	var best := -1; var bd := 1e9
	for n in traffic().npos:
		var q: Vector3 = traffic().npos[n]
		var d := Vector2(q.x - p.x, q.z - p.z).length()
		if d < bd and not traffic().nout.get(n, []).is_empty(): bd = d; best = n
	return best

func _spawn_unit() -> Dictionary:
	var t = traffic()
	var pw := player_world()
	for i in 30:
		var eid: int = rng.randi() % t.edges.size()
		var e: Dictionary = t.edges[eid]
		if e["cls"] > 5 or e["len"] < 10.0: continue
		var d := Vector2(t.npos[e["a"]].x - pw.x, t.npos[e["a"]].z - pw.z).length()
		if d < float(P["unit_spawn_m"][0]) or d > float(P["unit_spawn_m"][1]): continue
		if t._occupied(eid, 0.0, 14.0): continue
		var c: Dictionary = t._spawn_on(eid, 0.0, "police")
		c["chase"] = true; c["siren"] = true; c["keep"] = true
		var l := OmniLight3D.new(); l.omni_range = 14.0; l.light_energy = 2.5; l.position = Vector3(0, 2.0, 0)
		c["node"].add_child(l); c["beacon"] = l
		_repath_t = 0.0
		return c
	return {}

func _release_units() -> void:
	for u in units():
		u.erase("chase"); u.erase("keep"); u.erase("target"); u.erase("path")
		u["siren"] = false

## lost them: wanted level clears, units go back to patrol
func lose_them() -> void:
	stars = 0; searching = false; _unseen_t = 0.0; _bust_t = 0.0
	_release_units()
	if main.hud: main.hud.flash("You lost the police")

## one night in jail: released at 8 am outside the nearest police station, fined per star
func bust() -> void:
	var fine_amt: int = int(P["bust_fine_per_star"]) * maxi(stars, 1)
	var paid: int = main.money.fine(fine_amt, "Jail fine") if main.money else 0
	busted_count += 1
	var pw := player_world()
	var best: Dictionary = {}; var bd := 1e18
	for s in stations:
		var d := Vector2(float(s["x"]) - pw.x, float(s["z"]) - pw.z).length()
		if d < bd: bd = d; best = s
	stars = 0; searching = false; _bust_t = 0.0; _unseen_t = 0.0
	_release_units()
	if main.current_car: main.toggle_vehicle()       # out of the car
	# the clock moves on to the release hour the next morning
	var tod = main.tod
	var h: float = fposmod(tod.total_hours, 24.0)
	var rel: float = float(P["jail_release_hour"])
	tod.total_hours += (24.0 - h + rel) if h >= rel - 0.01 else (rel - h)
	tod.apply_now()
	if not best.is_empty():
		var sp := Vector3(float(best["x"]), 0, float(best["z"]))
		main.streamer.load_now(sp)
		var y: float = main.services._ground_y(sp) if main.services else 0.0
		main.player.global_position = Vector3(sp.x, y + 1.0, sp.z) - main.world_offset
		main.player.velocity = Vector3.ZERO
		main.last_safe = main.player.global_position + main.world_offset
	if main.hud: main.hud.flash("BUSTED - a night in jail, fined $%d" % paid)
	if main.stats: main.stats.times_busted += 1
