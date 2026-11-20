extends Node
## Wanted level and police response (Bible section 10), GTA-style and fictional:
##   * Crimes: hitting a car, hitting a person, ramming a police car, running a red light in front of police.
##     A crime counts if a police car sees it (within witness range) or a bystander reports it.
##   * Stars 1-5. Police units (stars + 1 at 3 stars and up) come after you with lights and sirens, re-routing to
##     where you were last seen.
##   * Escape: stay out of sight of every unit for search_s (longer at more stars); the stars blink while they search.
##   * Busted: a unit stops by you while you're stopped/on foot for bust_s -> one night in jail (Bible): released at
##     8 am outside the nearest police station, fined per star.
##   * Traffic stops: a patrol car that sees you speeding or running a red light lights up and follows you. Stop
##     and you get a ticket (or a warning); drive off and it becomes a 1-star chase ("failure to stop").
##   * Near you, units leave the road and drive straight at you; a helicopter joins at 4+ stars.
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
var stop: Dictionary = {}          # active traffic stop {cop, reason, over_mph, t, still_t, phase, talk_t}
var _stop_cd := 0.0
var _speed_t := 0.0
var heli: Node3D = null
var _heli_ang := 0.0
var tickets := 0

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
var _last_crime := {}
func report(kind: String, at: Vector3, force_seen := false) -> int:
	var sev: int = int(P["crimes"].get(kind, 1))
	var who := "police" if force_seen else witnessed(at)
	crimes.append([kind, who])
	if crimes.size() > 20: crimes.pop_front()
	if who == "": return stars
	var before := stars
	# the same kind of crime again within a few seconds (a burst of gunfire, a flurry of punches) is one incident
	var now := Time.get_ticks_msec() / 1000.0
	var recent: bool = now - float(_last_crime.get(kind, -99.0)) < 12.0
	_last_crime[kind] = now
	if kind in ["shots_fired", "shoot_ped", "shoot_police", "explosion", "armed_assault"]:
		stars = clampi(maxi(stars + (0 if recent else 1), sev), 1, 5)
	elif recent:
		stars = clampi(maxi(stars, sev), 1, 5)
	else:
		stars = clampi(stars + sev, 1, 5)
	last_seen = player_world(); _unseen_t = 0.0; searching = false
	if main.hud and stars > before:
		main.hud.flash({"hit_car": "Hit and run reported", "hit_ped": "You hit someone - police alerted", "ram_police": "You rammed a police car!",
			"run_red": "Ran a red light in front of police", "car_theft": "Car theft reported", "steal_police_car": "You stole a police car!",
			"flee_stop": "Failure to stop", "shots_fired": "Shots fired - police alerted", "shoot_ped": "You shot someone!",
			"shoot_police": "You shot a police officer!", "explosion": "Explosion reported", "assault": "Assault reported",
			"armed_assault": "Armed assault reported"}.get(kind, "Crime reported"))
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
	_stop_cd = maxf(0.0, _stop_cd - dt)
	_speed_t -= dt
	if _speed_t <= 0.0:
		_speed_t = 0.3
		_check_speeding()
	if not stop.is_empty(): _run_stop(dt)
	_update_heli(dt)
	if stars == 0: return
	_manage_units(dt)
	# seen?
	var pw := player_world()
	var seen := false
	var sight: float = float(P["sight_m"])
	for u in units():
		if (u["pos"] - pw).length() < sight: seen = true; break
	for p in main.peds.peds:
		if p.get("cop", false) and (p["pos"] - pw).length() < sight * 0.6: seen = true; break
	if heli != null and Vector2(heli.global_position.x + main.world_offset.x - pw.x, heli.global_position.z + main.world_offset.z - pw.z).length() < float(P["helicopter"]["sight_m"]):
		seen = true
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
		if p["state"] in ["fly", "down", "injured"]: continue
		if Vector2(p["pos"].x - cp.x, p["pos"].z - cp.z).length() < 2.3 and absf(p["pos"].y - cp.y) < 3.0:
			main.peds.knock_down(p, car.linear_velocity * 0.9)
			car.linear_velocity *= 0.93
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
				var cop := _patrol_near(cp, float(P["traffic_stop"]["witness_m"]))
				if not cop.is_empty():
					if stars > 0: report("run_red", cp, true)
					else: start_stop(cop, "run_red", 0.0)
			return
		return

# ------------------------------------------------------------------ response
var _cop_look: ArrayMesh
## at 3+ stars (or 2 if you're armed) officers get out of cars that are close and come at you on foot, armed
func _deploy_officers() -> void:
	var armed: bool = main.get("weapons") and main.weapons.armed_gun()
	if stars < 3 and not (armed and stars >= 2): return
	var pw := player_world()
	var on_foot := 0
	for p in main.peds.peds:
		if p.get("cop", false): on_foot += 1
	for u in units():
		if on_foot >= 2 + stars * 2: return
		if u.get("deployed", false) or (u["pos"] - pw).length() > 45.0 or float(u["v"]) > 4.0: continue
		u["deployed"] = true
		for k in 2:
			var e: int = u["edge"]
			var p: Dictionary = main.peds._spawn(e, float(u["s"]), 1 if k == 0 else -1)
			p["pos"] = u["pos"] + Vector3(-sin(float(u["yaw"])), 0, -cos(float(u["yaw"]))).cross(Vector3.UP) * (1.6 if k == 0 else -1.6)
			p["cop"] = true; p["gun"] = "rifle" if stars >= 5 else "pistol"; p["style"] = "boxer"
			p["hp"] = 120.0; p["hp_max"] = 120.0
			if p["node"] is RigChar:
				(p["node"] as RigChar).dress({"uniform": Color(0.32, 0.38, 0.62)})     # navy over the clothes' weave
			elif _cop_look == null:
				var look := {"h": 1.02, "w": 1.05, "skin": Color(0.62, 0.47, 0.36), "hair": Color(0.12, 0.1, 0.08), "top": Color(0.12, 0.16, 0.3),
					"top2": Color(0.1, 0.13, 0.25), "bottom": Color(0.1, 0.12, 0.2), "shoe": Color(0.05, 0.05, 0.05), "sleeves": 1, "legs": 0, "hair_style": 4, "beard": false}
				_cop_look = preload("res://scripts/humans.gd").build(look)
				_cop_look.surface_set_material(0, main.peds._mat)
			if p["node"] is MeshInstance3D: (p["node"] as MeshInstance3D).mesh = _cop_look
			main.combat.start_fight(p)
			on_foot += 1

func _manage_units(dt: float) -> void:
	_deploy_officers()
	var want: int = stars + (1 if stars >= 2 else 0) + (1 if stars >= 4 else 0)
	var have := units()
	for u in have:
		if _unseen_t < 1.0: _approach(u, player_world(), float(P["approach_stand_m"]))
		elif u.has("free_to"): u["free_to"] = last_seen
	if have.size() < want and rng.randf() < dt * 3.0: _spawn_unit()
	_repath_t -= dt
	if _repath_t <= 0.0:
		_repath_t = 2.0
		var target: int = _nearest_node(last_seen)
		for u in have:
			if u.has("free_to"): continue
			var e: Dictionary = traffic().edges[u["edge"]]
			var pth: Array = main.services.route_path(e["b"], target, 3000) if target >= 0 else []
			if pth.size() >= 2:
				u["path"] = pth; u["pi"] = 0; u["next"] = traffic()._choose_next(u)
			u["target"] = target          # stop when they get there (they look around / wait)

## units close to a player they can see leave the road and drive straight at them
func _approach(u: Dictionary, target: Vector3, stand: float) -> void:
	var d: float = (u["pos"] - target).length()
	if not u.has("free_to"):
		if d < float(P["approach_m"]):
			u["free_pos"] = u["pos"]; u["free_yaw"] = u["yaw"]; u["free_to"] = target; u["free_stand"] = stand
	elif d > float(P["approach_release_m"]):
		traffic().snap_to_graph(u)
	else:
		u["free_to"] = target; u["free_stand"] = stand

func _nearest_node(p: Vector3) -> int:
	var best := -1; var bd := 1e9
	for n in traffic().npos:
		var q: Vector3 = traffic().npos[n]
		var d := Vector2(q.x - p.x, q.z - p.z).length()
		if d < bd and not traffic().nout.get(n, []).is_empty(): bd = d; best = n
	return best

func _spawn_unit(rmin := -1.0, rmax := -1.0) -> Dictionary:
	var t = traffic()
	var pw := player_world()
	var lo: float = rmin if rmin > 0.0 else float(P["unit_spawn_m"][0])
	var hi: float = rmax if rmax > 0.0 else float(P["unit_spawn_m"][1])
	for i in 400 if rmin > 0.0 else 120:
		var eid: int = rng.randi() % t.edges.size()
		var e: Dictionary = t.edges[eid]
		if e["cls"] > 5 or e["len"] < 10.0: continue
		var d := Vector2(t.npos[e["a"]].x - pw.x, t.npos[e["a"]].z - pw.z).length()
		if d < lo or d > hi: continue
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
		if u.has("free_to"): traffic().snap_to_graph(u)
		u.erase("chase"); u.erase("keep"); u.erase("target"); u.erase("path")
		u["siren"] = false

## lost them: wanted level clears, units go back to patrol
func lose_them() -> void:
	stars = 0; searching = false; _unseen_t = 0.0; _bust_t = 0.0
	_release_units()
	if main.get("combat") and main.combat: main.combat.dismiss_cops()
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
	if main.get("combat") and main.combat: main.combat.dismiss_cops()
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

# ------------------------------------------------------------------ traffic stops
func _patrol_near(p: Vector3, r: float) -> Dictionary:
	for c in traffic().cars:
		if c["type"] == "police" and not c.get("chase", false) and not c.get("siren", false) and (c["pos"] - p).length() < r: return c
	return {}

## the speed limit of the road you're on (m/s), or -1 off-road
func speed_limit_here() -> float:
	var car = main.current_car
	if car == null: return -1.0
	var t = traffic()
	var cp: Vector3 = car.global_position + main.world_offset
	var vel: Vector3 = car.linear_velocity; vel.y = 0
	var best := -1.0; var bd := 9.0
	for e in t.edges:
		var a: Vector3 = t.npos[e["a"]]
		if Vector2(a.x - cp.x, a.z - cp.z).length() > float(e["len"]) + 10.0: continue
		var q := Geometry3D.get_closest_point_to_segment(cp, a, t.npos[e["b"]])
		var d := Vector2(q.x - cp.x, q.z - cp.z).length()
		if d < bd and (vel.length() < 1.0 or e["dir"].dot(vel.normalized()) > 0.6): bd = d; best = float(e["speed"])
	return best

func _check_speeding() -> void:
	var car = main.current_car
	if car == null or stars > 0 or not stop.is_empty() or _stop_cd > 0.0: return
	var lim := speed_limit_here()
	if lim <= 0.0: return
	var over: float = car.speed_mps() - lim
	if over < float(P["traffic_stop"]["speeding_over_mps"]): return
	var cp: Vector3 = car.global_position + main.world_offset
	var cop := _patrol_near(cp, float(P["traffic_stop"]["witness_m"]))
	if not cop.is_empty(): start_stop(cop, "speeding", over * 2.237)

func start_stop(cop: Dictionary, reason: String, over_mph: float) -> void:
	if not stop.is_empty(): return
	cop["siren"] = true; cop["keep"] = true; cop["stopping"] = true
	if not cop.has("beacon"):
		var l := OmniLight3D.new(); l.omni_range = 14.0; l.light_energy = 2.5; l.position = Vector3(0, 2.0, 0)
		cop["node"].add_child(l); cop["beacon"] = l
	stop = {"cop": cop, "reason": reason, "over_mph": over_mph, "t": 0.0, "still_t": 0.0, "phase": "signal", "talk_t": 0.0}
	if main.hud: main.hud.flash("Police: pull over!  (%s)" % ("speeding, %d mph over" % int(over_mph) if reason == "speeding" else "ran a red light"))

func ticket_amount(reason: String, over_mph: float) -> int:
	var T: Dictionary = P["traffic_stop"]["tickets"]
	if reason == "speeding": return int(T["speeding_base"]) + int(T["speeding_per_mph"]) * int(maxf(over_mph - 10.0, 0.0))
	return int(T.get(reason, 100))

func _run_stop(dt: float) -> void:
	var TS: Dictionary = P["traffic_stop"]
	var cop: Dictionary = stop["cop"]
	if not traffic().cars.has(cop): stop = {}; return
	stop["t"] += dt
	var pw := player_world()
	var d: float = (cop["pos"] - pw).length()
	match stop["phase"]:
		"signal":
			# follow you: straight at you when close, else along the roads
			_approach(cop, pw, float(TS["follow_stand_m"]))
			if not cop.has("free_to"):
				_repath_t -= dt
				if _repath_t <= 0.0:
					_repath_t = 1.5
					var tn := _nearest_node(pw)
					var e: Dictionary = traffic().edges[cop["edge"]]
					var pth: Array = main.services.route_path(e["b"], tn, 2000)
					if pth.size() >= 2: cop["path"] = pth; cop["pi"] = 0; cop["next"] = traffic()._choose_next(cop)
			if player_speed() < 1.0 and d < 30.0: stop["still_t"] += dt
			else: stop["still_t"] = 0.0
			if stop["still_t"] > float(TS["stop_s"]):
				stop["phase"] = "talk"
				if main.hud: main.hud.flash("The officer is checking your license...")
			elif d > float(TS["flee_m"]) or stop["t"] > float(TS["flee_s"]):
				_end_stop()
				report("flee_stop", pw, true)
				if main.hud: main.hud.flash("You didn't stop for the police!")
		"talk":
			stop["talk_t"] += dt
			if player_speed() > 3.0:
				_end_stop(); report("flee_stop", pw, true)
			elif stop["talk_t"] > float(TS["talk_s"]):
				resolve_stop()

## the officer's decision: a warning, or a ticket paid from your money
func resolve_stop() -> String:
	if stop.is_empty(): return ""
	var out := ""
	if rng.randf() < float(P["traffic_stop"]["warning_chance"]):
		out = "warning"
		if main.hud: main.hud.flash("Let off with a warning. Drive safe.")
	else:
		var amt := ticket_amount(stop["reason"], stop["over_mph"])
		var paid: int = main.money.fine(amt, "Ticket: " + stop["reason"]) if main.money else 0
		tickets += 1
		out = "ticket"
		if main.hud: main.hud.flash("Ticket: %s - $%d" % ["speeding" if stop["reason"] == "speeding" else "red light", paid])
	_end_stop()
	return out

func _end_stop() -> void:
	var cop: Dictionary = stop.get("cop", {})
	stop = {}
	_stop_cd = float(P["traffic_stop"]["cooldown_s"])
	if traffic().cars.has(cop):
		if cop.has("free_to"): traffic().snap_to_graph(cop)
		cop["siren"] = false; cop.erase("keep"); cop.erase("stopping"); cop.erase("path"); cop.erase("target")
		if stars > 0: cop["chase"] = true; cop["siren"] = true; cop["keep"] = true   # fled: this one is now chasing

# ------------------------------------------------------------------ helicopter
func _make_heli() -> Node3D:
	var root := Node3D.new(); root.name = "PoliceHelicopter"
	var mat := StandardMaterial3D.new(); mat.albedo_color = Color(0.12, 0.14, 0.2); mat.roughness = 0.5
	var stripe := StandardMaterial3D.new(); stripe.albedo_color = Color(0.9, 0.9, 0.9)
	var parts := [[Vector3(1.8, 1.6, 4.0), Vector3(0, 0, 0), mat], [Vector3(0.35, 0.35, 4.5), Vector3(0, 0.3, 4.0), mat],
		[Vector3(1.82, 0.25, 2.5), Vector3(0, -0.2, -0.2), stripe], [Vector3(0.1, 1.2, 0.8), Vector3(0, 0.9, 6.0), mat],
		[Vector3(0.12, 0.12, 3.0), Vector3(-0.8, -1.1, 0), mat], [Vector3(0.12, 0.12, 3.0), Vector3(0.8, -1.1, 0), mat]]
	for pt in parts:
		var mi := MeshInstance3D.new(); var bm := BoxMesh.new(); bm.size = pt[0]; mi.mesh = bm; mi.position = pt[1]; mi.material_override = pt[2]
		root.add_child(mi)
	var rotor := MeshInstance3D.new(); var rm := BoxMesh.new(); rm.size = Vector3(10.0, 0.06, 0.35); rotor.mesh = rm
	rotor.position = Vector3(0, 1.05, 0); rotor.name = "Rotor"; rotor.material_override = mat; root.add_child(rotor)
	var spot := SpotLight3D.new(); spot.name = "Searchlight"; spot.spot_range = 120.0; spot.spot_angle = 9.0; spot.light_energy = 6.0
	spot.position = Vector3(0, -1.0, -1.5); root.add_child(spot)
	main.world.add_child(root)
	return root

func _update_heli(dt: float) -> void:
	var H: Dictionary = P["helicopter"]
	if stars < int(H["from_stars"]):
		if heli != null:
			heli.queue_free(); heli = null
		return
	var pw := player_world()
	if heli == null:
		heli = _make_heli()
		var a := rng.randf() * TAU
		heli.global_position = pw + Vector3(cos(a) * 400.0, float(H["altitude_m"]) + 20.0, sin(a) * 400.0) - main.world_offset
	_heli_ang += dt * 0.35
	var aim: Vector3 = pw if not searching else last_seen
	var orbit: Vector3 = aim + Vector3(cos(_heli_ang), 0, sin(_heli_ang)) * float(H["orbit_m"])
	var target: Vector3 = Vector3(orbit.x, aim.y + float(H["altitude_m"]), orbit.z) - main.world_offset
	var to: Vector3 = target - heli.global_position
	var step: float = float(H["speed_mps"]) * dt
	heli.global_position += to.normalized() * minf(step, to.length())
	var flat := Vector3(to.x, 0, to.z)
	if flat.length() > 0.5: heli.rotation.y = lerp_angle(heli.rotation.y, atan2(-flat.x, -flat.z), dt * 2.0)
	heli.get_node("Rotor").rotation.y += dt * 25.0
	var spot: SpotLight3D = heli.get_node("Searchlight")
	spot.visible = main.tod.night > 0.3 if main.tod else false
	if spot.visible: spot.look_at(aim - main.world_offset, Vector3.UP)
