extends Node
## Automated game tests. Run: godot --headless --path . -- --test[=tests/out/results.json]
## (tools/run_tests.sh does this plus the Python data tests). Exit code = number of failed tests.
##
## Each test is a coroutine returning [ok: bool, detail: String]. Tests run in order against the live game
## (real streamed city data), so they catch integration breakage, not just unit logic.

var main: Node
var out_path := "res://tests/out/results.json"
var results: Array = []

func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--test="): out_path = a.substr(7)
	main.input_enabled = false
	_run.call_deferred()

func _frames(n: int) -> void:
	for i in n: await get_tree().physics_frame

func _record(name: String, r: Array, ms: int) -> void:
	results.append({"test": name, "pass": r[0], "detail": r[1], "ms": ms})
	print("[test] %s %s  (%s, %d ms)" % ["PASS" if r[0] else "FAIL", name, r[1], ms])

func _run() -> void:
	await _frames(10)
	var tests := [
		["manifest_and_world_bounds", t_manifest],
		["chunk_data_schema", t_chunk_schema],
		["streaming_loads_around_player", t_streaming],
		["player_spawns_on_ground", t_spawn],
		["player_can_walk", t_walk],
		["car_enter_drive_exit", t_car],
		["bar_enter_exit", t_bar_roundtrip],
		["bar_exit_after_origin_rebase", t_bar_rebase],
		["respawn_from_river", t_respawn],
		["clock_one_real_hour_per_day", t_clock],
		["sun_path_by_season", t_sun],
		["night_lights_switch_on", t_night],
		["weather_respects_seasons", t_weather_seasons],
		["weather_changes_the_look", t_weather_look],
		["world_state_save_load", t_persist],
		["street_lamps_light_at_night", t_lamps],
		["car_headlights_at_night", t_headlights],
		["rain_wets_and_dries_the_ground", t_wet],
		["snow_builds_and_melts", t_snow],
		["traffic_road_graph", t_tr_graph],
		["traffic_density_follows_hour", t_tr_density],
		["traffic_spawns_and_moves_in_lanes", t_tr_move],
		["traffic_no_overlapping_cars", t_tr_overlap],
		["traffic_stops_at_red_light", t_tr_red],
		["traffic_stops_for_player", t_tr_player],
		["peds_density_follows_hour", t_pd_density],
		["peds_spawn_and_walk_on_sidewalks", t_pd_walk],
		["peds_cross_only_at_intersections", t_pd_cross],
		["traffic_stops_for_crossing_ped", t_pd_car_stops],
		["peds_umbrellas_in_rain", t_pd_umbrella],
	]
	for t in tests:
		var t0 := Time.get_ticks_msec()
		var r = await t[1].call()
		if not (r is Array) or r.size() < 2:
			r = [false, "test crashed (script error, see log above)"]
		_record(t[0], r, Time.get_ticks_msec() - t0)
	if results.size() != tests.size():
		_record("all_tests_ran", [false, "%d of %d tests reported" % [results.size(), tests.size()]], 0)
	var failed := results.filter(func(x): return not x["pass"]).size()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(out_path).get_base_dir())
	var f := FileAccess.open(out_path, FileAccess.WRITE)
	f.store_string(JSON.stringify({"when": Time.get_datetime_string_from_system(), "passed": results.size() - failed,
		"failed": failed, "results": results}, "  "))
	f.close()
	print("[test] %d passed, %d failed" % [results.size() - failed, failed])
	get_tree().quit(failed)

# ------------------------------------------------------------------ tests
func t_manifest() -> Array:
	var m: Dictionary = main.streamer.manifest
	for k in ["chunk_size", "chunks", "bbox", "spawn", "origin_lat", "origin_lon"]:
		if not m.has(k): return [false, "manifest missing " + k]
	var bb: Array = m["bbox"]
	var w: float = bb[2] - bb[0]; var h: float = bb[3] - bb[1]
	if w < 2000 or h < 2000: return [false, "bbox too small %dx%d m" % [w, h]]
	return [true, "%d chunks, %.1f x %.1f km" % [m["chunks"].size(), w / 1000.0, h / 1000.0]]

func t_chunk_schema() -> Array:
	var ks: Array = main.streamer.available.keys()
	if ks.is_empty(): return [false, "no chunks available"]
	var rng := RandomNumberGenerator.new(); rng.seed = 7
	var checked := 0; var facade := 0
	var sample: Array = []
	var sp: Array = main.streamer.manifest["spawn"]
	var ck: Vector2i = main.streamer.key_for_world(Vector3(sp[0], 0, sp[1]))
	for dx in range(-2, 3):
		for dz in range(-2, 3):
			if main.streamer.available.has(ck + Vector2i(dx, dz)): sample.append(ck + Vector2i(dx, dz))   # downtown: facade layers
	for i in 40: sample.append(ks[rng.randi() % ks.size()])
	for k in sample:
		var d: Dictionary = main.streamer.read_chunk(k)
		if d.is_empty(): return [false, "chunk %s unreadable" % k]
		for key in ["layers", "col", "props", "labels", "streets"]:
			if not d.has(key): return [false, "chunk %s missing %s" % [k, key]]
		for L in d["layers"]:
			var nv: int = L["v"].size()
			if nv % 3 != 0: return [false, "chunk %s layer %s: %d verts not a triangle list" % [k, L["mat"], nv]]
			if L["n"].size() != nv or L["uv"].size() != nv: return [false, "chunk %s layer %s: n/uv length mismatch" % [k, L["mat"]]]
			if L.has("color"):
				facade += 1
				if L["uv2"].size() != nv or L["color"].size() != nv or L["c0"].size() != nv * 4:
					return [false, "chunk %s facade layer: attribute length mismatch" % k]
		if d["col"].size() % 3 != 0: return [false, "chunk %s collision not triangles" % k]
		checked += 1
	if facade == 0: return [false, "no facade layers found in downtown chunks"]
	return [true, "%d chunks ok, %d facade layers" % [checked, facade]]

func t_streaming() -> Array:
	var t0 := Time.get_ticks_msec()
	while not main.streamer.is_idle() and Time.get_ticks_msec() - t0 < 30000:
		await _frames(5)
	var n: int = main.streamer.loaded.size()
	return [n >= 9, "%d chunks loaded around spawn" % n]

func _on_ground(p: Vector3) -> bool:
	var q := PhysicsRayQueryParameters3D.create(p + Vector3(0, 1.0, 0), p + Vector3(0, -3.0, 0))
	return not main.get_world_3d().direct_space_state.intersect_ray(q).is_empty()

func t_spawn() -> Array:
	await _frames(60)
	var p: Vector3 = main.player.global_position
	if abs(p.y) > 3.0: return [false, "player at y=%.2f (expected street level)" % p.y]
	if not main.player.is_on_floor() and not _on_ground(p): return [false, "player not on the ground at %s" % p]
	return [true, "at %s" % p.snapped(Vector3(0.1, 0.1, 0.1))]

func t_walk() -> Array:
	var best := 0.0
	for yaw in [0.0, PI * 0.5, PI, -PI * 0.5]:
		main.cam_yaw = yaw
		var p0: Vector3 = main.player.global_position
		main.player.input_dir = Vector2(0, 1)
		await _frames(240)   # 2 s
		main.player.input_dir = Vector2.ZERO
		var d := Vector2(main.player.global_position.x - p0.x, main.player.global_position.z - p0.z).length()
		best = max(best, d)
		if d > 5.0 and abs(main.player.global_position.y - p0.y) < 2.0:
			return [true, "walked %.1f m in 2 s" % d]
	return [false, "best distance %.1f m in 2 s (blocked?)" % best]

func t_car() -> Array:
	var c = main.cars[0]
	if main.traffic:   # this test is about the player's car, not about traffic jams
		for tc in main.traffic.cars.duplicate():
			if (tc["pos"] - (c.global_position + main.world_offset)).length() < 80.0: main.traffic._despawn(tc)
	main.player.global_position = c.global_position + c.global_transform.basis.x * 2.0
	await _frames(5)
	main.toggle_vehicle()
	if main.current_car == null: return [false, "could not enter car"]
	var p0: Vector3 = c.global_position
	c.throttle = 1.0
	await _frames(360)   # 3 s
	c.throttle = 0.0
	var d: float = (c.global_position - p0).length()
	var up: float = c.global_transform.basis.y.y
	main.toggle_vehicle()
	if main.current_car != null: return [false, "could not exit car"]
	if d < 8.0: return [false, "car moved only %.1f m in 3 s" % d]
	if up < 0.7: return [false, "car flipped (up=%.2f)" % up]
	return [true, "drove %.1f m in 3 s, exited" % d]

func _a_door(far_from := Vector3.INF, min_dist := 0.0) -> Dictionary:
	# find a bar from the data, stream it in, return its door
	var j = JSON.parse_string(FileAccess.get_file_as_string("res://data/bars_index.json"))
	if j == null: return {}
	var here: Vector3 = main.player.global_position + main.world_offset
	var bb: Array = main.streamer.manifest["bbox"]
	for b in j:
		var at := Vector3(b["x"], 0, -b["y"])
		if at.x < bb[0] or at.x > bb[2] or at.z < bb[1] or at.z > bb[3]: continue
		if min_dist > 0.0 and Vector2(at.x - here.x, at.z - here.z).length() < min_dist: continue
		main.focus_override = at
		main.streamer.load_now(at)
		await _frames(3)
		var d: Dictionary = main.bars.nearest_door(at - main.world_offset, 90.0)
		if not d.is_empty(): return d
	return {}

func t_bar_roundtrip() -> Array:
	var d: Dictionary = await _a_door()
	if d.is_empty(): return [false, "no bar door found in the streamed data"]
	var n: Node3D = d["node"]
	main.player.global_position = n.global_transform * Vector3(0, 0.3, -1.6)
	await _frames(3)
	var pr: String = main.bars.prompt(main.player.global_position)
	if not pr.begins_with("Press E to enter"): return [false, "no enter prompt at the door (got '%s')" % pr]
	var door_world: Vector3 = n.global_position + main.world_offset
	if not main.bars.try_interact(main.player) or not main.bars.inside: return [false, "enter failed"]
	await _frames(60)
	if main.player.global_position.y > -2000.0: return [false, "player not in the interior (y=%.1f)" % main.player.global_position.y]
	if not main.player.is_on_floor(): return [false, "player not standing on the interior floor"]
	main.player.global_position = main.bars.interior.global_transform * main.bars.exit_point
	await _frames(3)
	if not main.bars.try_interact(main.player) or main.bars.inside: return [false, "exit failed"]
	await _frames(30)
	var back: Vector3 = main.player.global_position + main.world_offset
	var dist := Vector2(back.x - door_world.x, back.z - door_world.z).length()
	main.focus_override = null
	if dist > 4.0: return [false, "came out %.1f m from the door" % dist]
	return [true, "%s: in and out, %.1f m from door" % [d["theme"], dist]]

func t_bar_rebase() -> Array:
	# enter a bar far from the current origin, then let the world re-centre while inside, then leave
	var off0: Vector3 = main.world_offset
	var d: Dictionary = await _a_door(Vector3.INF, 2500.0)
	if d.is_empty(): return [false, "no far bar door found"]
	var n: Node3D = d["node"]
	main.focus_override = null
	main.player.global_position = n.global_transform * Vector3(0, 0.3, -1.6)
	var door_world: Vector3 = n.global_position + main.world_offset
	if not main.bars.try_interact(main.player): return [false, "enter failed"]
	await _frames(30)   # origin rebase happens here (player is > 1 km from the old origin)
	var shifted: bool = main.world_offset != off0
	main.player.global_position = main.bars.interior.global_transform * main.bars.exit_point
	await _frames(3)
	if not main.bars.try_interact(main.player): return [false, "exit failed"]
	await _frames(30)
	var back: Vector3 = main.player.global_position + main.world_offset
	var dist := Vector2(back.x - door_world.x, back.z - door_world.z).length()
	if not shifted: return [false, "origin did not rebase during the test (test setup)"]
	if dist > 4.0: return [false, "after rebase came out %.1f m from the door" % dist]
	return [true, "%s: rebased while inside, came out %.1f m from door" % [d["theme"], dist]]

func t_respawn() -> Array:
	var safe: Vector3 = main.last_safe
	main.player.global_position = Vector3(main.player.global_position.x, -10.0, main.player.global_position.z)
	await _frames(20)
	var y: float = main.player.global_position.y
	return [y > -3.0, "respawned to y=%.1f (last safe %s)" % [y, safe.snapped(Vector3.ONE)]]

# ------------------------------------------------------------------ time of day / weather
func t_clock() -> Array:
	var tod = main.tod
	var h0: float = tod.total_hours
	var ts: float = tod.time_scale
	tod.time_scale = 1.0
	for i in 3600: tod.total_hours += 1.0 * 24.0 / tod.sec_per_day * tod.time_scale   # same formula as _process
	var dh: float = tod.total_hours - h0
	tod.total_hours = h0; tod.time_scale = ts
	if abs(dh - 24.0) > 0.001: return [false, "3600 real seconds advanced %.3f game hours" % dh]
	return [true, "1 real hour = 24 game hours (sec_per_day=%d)" % tod.sec_per_day]

func t_sun() -> Array:
	var tod = main.tod
	var keep: float = tod.total_hours
	var out := []
	for se in ["spring", "summer", "fall", "winter"]:
		tod.set_date(se, 6, 0.0); var mid: float = tod.sun_position().x
		tod.set_date(se, 6, 13.0); var noon: float = tod.sun_position().x
		out.append("%s noon %.0f°" % [se, noon])
		if mid > -5.0: tod.total_hours = keep; return [false, "%s: sun at %.1f° at midnight" % [se, mid]]
		if noon < 20.0: tod.total_hours = keep; return [false, "%s: sun only %.1f° at 1 pm" % [se, noon]]
	tod.set_date("summer", 1, 21.0); var ss: float = tod.sun_position().x   # ~June 21: Toledo sunset about 9:12 pm
	tod.set_date("winter", 1, 17.5); var ws: float = tod.sun_position().x   # ~Dec 21: Toledo sunset about 5:08 pm
	tod.total_hours = keep; tod.apply_now()
	if ss < -1.0: return [false, "summer 9 pm sun already down (%.1f°): no long Ohio summer evenings" % ss]
	if ws > 0.0: return [false, "winter 5:30 pm sun still up (%.1f°)" % ws]
	return [true, ", ".join(out)]

func t_night() -> Array:
	var tod = main.tod
	var keep: float = tod.total_hours
	tod.set_date("fall", 3, 23.0)
	var n: float = tod.night
	var fac: ShaderMaterial = main.streamer.materials["facade"]
	var fn: float = fac.get_shader_parameter("night")
	var em := 0.0
	for m in tod._night_mats: em = max(em, m.emission_energy_multiplier)
	var lamp: float = tod._lamp_mat.emission_energy_multiplier if tod._lamp_mat else 0.0
	var amb_night: float = main.env.ambient_light_energy
	tod.set_date("fall", 3, 13.0)
	var day_n: float = tod.night
	var amb_day: float = main.env.ambient_light_energy
	var day_em := 0.0
	for m in tod._night_mats: day_em = max(day_em, m.emission_energy_multiplier)
	tod.total_hours = keep; tod.apply_now()
	if n < 0.9 or fn < 0.9: return [false, "11 pm not night (night=%.2f, facade=%.2f)" % [n, fn]]
	if em <= 0.05 or lamp <= 0.5: return [false, "lights not on at night (windows %.2f, lamps %.2f)" % [em, lamp]]
	if tod._night_mats.size() < 10: return [false, "only %d window materials registered" % tod._night_mats.size()]
	if day_n > 0.05 or day_em > 0.01: return [false, "lights still on at 1 pm"]
	if amb_night >= amb_day * 0.5: return [false, "night not darker (ambient %.2f vs %.2f)" % [amb_night, amb_day]]
	return [true, "%d window materials + facade + lamps on at night, off by day" % tod._night_mats.size()]

func t_weather_seasons() -> Array:
	var w = main.weather
	for i in 3000:
		if w.next_state("summer") == "snow": return [false, "snow chosen in summer"]
		if w.next_state("spring") == "snow": return [false, "snow chosen in spring"]
		if w.next_state("winter") == "storm": return [false, "thunderstorm chosen in winter"]
	var seen := {}
	for i in 3000: seen[w.next_state("winter")] = true
	if not seen.has("snow"): return [false, "winter never snows"]
	return [true, "3000 draws per season, winter states: %s" % ", ".join(seen.keys())]

func t_weather_look() -> Array:
	var w = main.weather; var tod = main.tod
	var keep_state: String = w.state; var keep: float = tod.total_hours
	tod.set_date("summer", 5, 13.0)
	w.set_state("clear"); w.snap(); tod.apply_now()
	var fog_clear: float = main.env.fog_density; var sun_clear: float = main.get_node("Sun").light_energy
	w.set_state("fog"); w.snap(); tod.apply_now()
	var fog_fog: float = main.env.fog_density
	w.set_state("storm"); w.snap(); tod.apply_now()
	var sun_storm: float = main.get_node("Sun").light_energy
	await _frames(5)
	var raining: bool = w.rain.emitting
	w.set_state(keep_state); w.snap(); tod.total_hours = keep; tod.apply_now()
	if fog_fog < fog_clear * 5.0: return [false, "fog state barely changes fog (%.5f vs %.5f)" % [fog_fog, fog_clear]]
	if sun_storm > sun_clear * 0.3: return [false, "storm sunlight %.2f vs clear %.2f" % [sun_storm, sun_clear]]
	if not raining: return [false, "no rain particles in a storm"]
	return [true, "fog x%.0f, storm sun %.0f%%, rain falling" % [fog_fog / fog_clear, 100.0 * sun_storm / sun_clear]]

func t_persist() -> Array:
	var tod = main.tod; var w = main.weather
	var keep: float = tod.total_hours; var ks: String = w.state
	tod.set_date("winter", 7, 18.25); w.set_state("snow", 3.0)
	var saved: float = tod.total_hours
	tod.save_state()
	tod.set_date("summer", 2, 9.0); w.set_state("clear")
	var ok: bool = tod.load_state()
	var back: float = tod.total_hours; var bs: String = w.state
	tod.total_hours = keep; w.set_state(ks); w.snap(); tod.apply_now()
	if not ok: return [false, "load_state failed"]
	if abs(back - saved) > 0.001 or bs != "snow": return [false, "restored %.2f h / %s, expected %.2f h / snow" % [back, bs, saved]]
	return [true, "time and weather restored"]

func t_lamps() -> Array:
	var tod = main.tod
	var keep: float = tod.total_hours
	var pools := 0; var heads := 0
	for k in main.streamer.loaded:
		var r: Node3D = main.streamer.loaded[k]
		if r.has_node("lamp_pools"): pools += (r.get_node("lamp_pools") as MultiMeshInstance3D).multimesh.instance_count
		if r.has_meta("lamp_heads"): heads += r.get_meta("lamp_heads").size()
	tod.set_date("fall", 3, 23.0)
	var gn: float = tod.globals["night_level"]
	var sl = main.get_node("StreetLights")
	sl._t = 0.0; sl._process(0.0)
	var lit := 0
	for o in sl.lights: if o.visible: lit += 1
	tod.set_date("fall", 3, 13.0)
	var gd: float = tod.globals["night_level"]
	sl._t = 0.0; sl._process(0.0)
	var lit_day := 0
	for o in sl.lights: if o.visible: lit_day += 1
	tod.total_hours = keep; tod.apply_now()
	if pools < 50: return [false, "only %d lamp light pools in %d loaded chunks" % [pools, main.streamer.loaded.size()]]
	if gn < 0.9 or gd > 0.05: return [false, "pool glow night=%.2f day=%.2f" % [gn, gd]]
	if lit < 8 or lit_day > 0: return [false, "real lamp lights: %d at night, %d by day" % [lit, lit_day]]
	return [true, "%d lamp pools, %d real lights at night, none by day" % [pools, lit]]

func t_headlights() -> Array:
	var tod = main.tod; var w = main.weather
	var keep: float = tod.total_hours; var ks: String = w.state
	w.set_state("clear"); w.snap()
	var c = main.cars[0]
	tod.set_date("summer", 4, 23.0)
	await _frames(2)
	var on_n: bool = c.lights_on; var e_n: float = c._hl_mat.emission_energy_multiplier
	tod.set_date("summer", 4, 12.0)
	await _frames(2)
	var on_d: bool = c.lights_on
	w.set_state(ks); w.snap(); tod.total_hours = keep; tod.apply_now()
	if not on_n or e_n < 1.0: return [false, "headlights off at 11 pm"]
	if on_d: return [false, "headlights on at noon in clear weather"]
	return [true, "on at night, off at noon"]

func t_wet() -> Array:
	var tod = main.tod; var w = main.weather
	var ks: String = w.state; var kw: float = tod.wetness; var kn: float = tod.snow_cover
	tod.wetness = 0.0; tod.snow_cover = 0.0
	w.set_state("rain"); tod.step_surface(1.0)
	var wet: float = tod.wetness
	tod.apply_now()
	var g: float = tod.globals["wetness"]
	var asphalt: StandardMaterial3D = main.streamer.materials["asphalt"]
	var r_wet: float = asphalt.roughness
	w.set_state("clear"); for i in 12: tod.step_surface(1.0)
	var dry: float = tod.wetness
	tod.apply_now()
	var r_dry: float = asphalt.roughness
	tod.wetness = kw; tod.snow_cover = kn; w.set_state(ks); w.snap(); tod.apply_now()
	if wet < 0.9 or g < 0.9: return [false, "after 1 h of rain wetness=%.2f (shader %.2f)" % [wet, g]]
	if r_wet > r_dry - 0.3: return [false, "wet asphalt not glossier (%.2f vs %.2f)" % [r_wet, r_dry]]
	if dry > 0.05: return [false, "still wet (%.2f) 12 h after rain" % dry]
	return [true, "1 h rain -> %.2f wet, dry again after 12 h" % wet]

func t_snow() -> Array:
	var tod = main.tod; var w = main.weather
	var keep: float = tod.total_hours; var ks: String = w.state; var kw: float = tod.wetness; var kn: float = tod.snow_cover
	tod.snow_cover = 0.0
	tod.set_date("winter", 3, 10.0); w.set_state("snow")
	for i in 6: tod.step_surface(1.0)
	var built: float = tod.snow_cover
	w.set_state("clear"); for i in 6: tod.step_surface(1.0)
	var winter_keep: float = tod.snow_cover
	tod.set_date("spring", 2, 12.0)
	for i in 6: tod.step_surface(1.0)
	var spring: float = tod.snow_cover
	tod.total_hours = keep; tod.wetness = kw; tod.snow_cover = kn; w.set_state(ks); w.snap(); tod.apply_now()
	if built < 0.9: return [false, "6 h of snow gave only %.2f cover" % built]
	if winter_keep < 0.6: return [false, "snow melted too fast in winter (%.2f left after 6 h)" % winter_keep]
	if spring > 0.1: return [false, "snow still %.2f after 6 spring hours" % spring]
	return [true, "6 h snow -> %.2f, winter 6 h later %.2f, spring melts to %.2f" % [built, winter_keep, spring]]

# ------------------------------------------------------------------ traffic
func _tr_reset_to_spawn() -> void:
	var sp: Array = main.streamer.manifest["spawn"]
	main.focus_override = null
	if main.current_car: main.toggle_vehicle()
	main.player.global_position = Vector3(sp[0], 0, sp[1]) - main.world_offset
	main.streamer.load_now(Vector3(sp[0], 0, sp[1]))
	main.player.global_position = main._clear_spot(Vector3(sp[0], 0, sp[1]), Vector3(0, 0, -1), [8.0, -8.0, 12.0]) - main.world_offset + Vector3(0, 0.2, 0)
	await _frames(10)

func t_tr_graph() -> Array:
	await _tr_reset_to_spawn()
	var tr = main.traffic
	tr.rebuild_graph()
	var sig := 0
	for n in tr.ix: if tr.ix[n]["ctrl"] == "signal": sig += 1
	if tr.edges.size() < 300: return [false, "only %d lane edges" % tr.edges.size()]
	if sig < 5: return [false, "only %d signalised intersections downtown" % sig]
	return [true, "%d directed edges, %d nodes, %d controlled intersections (%d signals)" % [tr.edges.size(), tr.npos.size(), tr.ix.size(), sig]]

func t_tr_density() -> Array:
	var tod = main.tod; var keep: float = tod.total_hours
	tod.set_date("fall", 3, 3.0); var night: int = main.traffic.target_count()
	tod.set_date("fall", 3, 17.0); var rush: int = main.traffic.target_count()
	tod.total_hours = keep; tod.apply_now()
	if rush < 20 or night > rush * 0.3: return [false, "3 am %d cars vs 5 pm %d" % [night, rush]]
	return [true, "3 am %d cars, 5 pm %d cars" % [night, rush]]

func t_tr_move() -> Array:
	var tod = main.tod; var keep: float = tod.total_hours
	tod.set_date("fall", 3, 17.0)
	await _frames(360)   # 3 s
	var tr = main.traffic
	var n: int = tr.count()
	if n < 10: tod.total_hours = keep; return [false, "only %d cars after 3 s (want %d)" % [n, tr.target_count()]]
	if n > int(tr.T["budget"]["max_cars"]): tod.total_hours = keep; return [false, "%d cars exceeds budget" % n]
	var start := {}
	for c in tr.cars: start[c["node"]] = c["pos"]
	await _frames(1200)  # 10 s
	var moved := 0; var worst_lane := 0.0; var tot := 0.0; var m := 0
	for c in tr.cars:
		if not start.has(c["node"]): continue
		var d: float = (c["pos"] - start[c["node"]]).length()
		tot += d; m += 1
		if d > 10.0: moved += 1
		var lp: Vector3 = tr.lane_point(tr.edges[c["edge"]], c["s"], c["lane"])
		worst_lane = max(worst_lane, Vector2(c["pos"].x - lp.x, c["pos"].z - lp.z).length())
	tod.total_hours = keep; tod.apply_now()
	if m == 0: return [false, "all cars despawned"]
	if moved < m * 0.4: return [false, "only %d of %d cars moved more than 10 m in 10 s" % [moved, m]]
	if worst_lane > 3.0: return [false, "a car is %.1f m off its lane" % worst_lane]
	return [true, "%d cars, %d moved >10 m in 10 s (avg %.1f m/s), worst lane error %.1f m" % [n, moved, tot / m / 10.0, worst_lane]]

func t_tr_overlap() -> Array:
	var tr = main.traffic
	var worst := 1e9; var pair := ""
	for i in tr.cars.size():
		for j in range(i + 1, tr.cars.size()):
			var a: Dictionary = tr.cars[i]; var b: Dictionary = tr.cars[j]
			var d: float = (a["pos"] - b["pos"]).length()
			if d < worst: worst = d; pair = "%s/%s" % [a["type"], b["type"]]
	if worst < 2.2: return [false, "two cars %.1f m apart (%s)" % [worst, pair]]
	return [true, "closest pair %.1f m apart" % worst]

func t_tr_red() -> Array:
	var tr = main.traffic
	# find a signal approach long enough to test on
	var eid := -1
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		var near: float = (tr.npos[e["b"]] - main.focus_world()).length()
		if near < 160.0 and e["len"] > 28.0 and tr.ix.has(e["b"]) and tr.ix[e["b"]]["ctrl"] == "signal" and not tr._occupied(i, e["len"] * 0.5, e["len"]):
			eid = i; break
	if eid < 0: return [false, "no clear signal approach found"]
	var e2: Dictionary = tr.edges[eid]
	# wind the signal clock until this approach has just turned red
	var guard := 0
	while tr.signal_state(eid) != "stop" and guard < 2000: tr.time_s += 0.1; guard += 1
	var c: Dictionary = tr._spawn_on(eid, 1.0)
	c["v"] = 6.0
	var stop_at: float = e2["len"] - float(tr.T["driver"]["stop_line_m"])
	var crossed := false
	for f in 600:   # 5 s while red
		await get_tree().physics_frame
		if not tr.cars.has(c): return [false, "test car vanished"]
		if c["ea"] != e2["a"] or c["eb"] != e2["b"] or c["s"] > stop_at + 0.8: crossed = true; break
		if tr.signal_state(c["edge"]) != "stop": break
	if crossed: return [false, "car ran the red light"]
	return [true, "stopped %.1f m before the line, speed %.1f m/s" % [stop_at - c["s"], c["v"]]]

func t_tr_player() -> Array:
	var tr = main.traffic
	var eid := -1
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		var near: float = (tr.npos[e["b"]] - main.focus_world()).length()
		if near < 160.0 and e["len"] > 35.0 and not tr._occupied(i, e["len"] * 0.5, e["len"]) and e["cls"] >= 2 and e["cls"] <= 5:
			var g: Vector3 = main._ground_from(tr.lane_point(e, e["len"] - 4.0, 0), 30.0)
			if absf(g.y) < 1.0:   # street level (not a bridge over the river, where the player would fall in)
				eid = i; break
	if eid < 0: return [false, "no clear straight edge"]
	var e2: Dictionary = tr.edges[eid]
	var block: Vector3 = tr.lane_point(e2, e2["len"] - 4.0, 0)
	main.player.global_position = block - main.world_offset + Vector3(0, 0.5, 0)
	var c: Dictionary = tr._spawn_on(eid, max(1.0, e2["len"] - 50.0))
	c["lane"] = 0; c["v"] = 5.0
	for f in 1440:
		await get_tree().physics_frame   # 12 s
	main.player.global_position = block - main.world_offset + Vector3(0, 0.5, 0)
	if not tr.cars.has(c): return [false, "test car vanished"]
	if c["ea"] != e2["a"] or c["eb"] != e2["b"]: return [false, "car drove past the player onto the next road"]
	var gap: float = (e2["len"] - 4.0) - c["s"] - c["len"] * 0.5
	if gap < 0.5: return [false, "drove into the player (gap %.1f m)" % gap]
	if c["v"] > 0.5: return [false, "still moving at %.1f m/s next to the player" % c["v"]]
	return [true, "stopped %.1f m short of the player" % gap]

# ------------------------------------------------------------------ pedestrians
func t_pd_density() -> Array:
	var tod = main.tod; var keep: float = tod.total_hours
	tod.set_date("fall", 3, 3.0); var night: int = main.peds.target_count()
	tod.set_date("fall", 3, 12.5); var noon: int = main.peds.target_count()
	tod.total_hours = keep; tod.apply_now()
	if noon < 30 or night > noon * 0.25: return [false, "3 am %d people vs 12:30 pm %d" % [night, noon]]
	return [true, "3 am %d people, 12:30 pm %d" % [night, noon]]

## Distance from a world point to the nearest drivable road surface (negative = inside the carriageway).
func _off_road(q: Vector3) -> float:
	var tr = main.traffic
	var best := 1e9
	for e in tr.edges:
		var a: Vector3 = tr.npos[e["a"]]; var b: Vector3 = tr.npos[e["b"]]
		if (a - q).length() > 200.0 and (b - q).length() > 200.0: continue
		var cp := Geometry3D.get_closest_point_to_segment(Vector3(q.x, 0, q.z), a, b)
		best = min(best, Vector2(cp.x - q.x, cp.z - q.z).length() - float(e.get("w", 8.0)) * 0.5)
	return best

func t_pd_walk() -> Array:
	var tod = main.tod; var keep: float = tod.total_hours
	tod.set_date("fall", 3, 12.5)
	await _frames(360)
	var pd = main.peds
	var n: int = pd.count()
	if n < 20: tod.total_hours = keep; return [false, "only %d people after 3 s (want %d)" % [n, pd.target_count()]]
	if n > int(pd.P["budget"]["max_peds"]) + 8: tod.total_hours = keep; return [false, "%d people exceeds budget" % n]
	var start := {}
	for p in pd.peds: start[p["node"]] = p["pos"]
	var in_road := 0; var worst := 1e9
	for f in 8:
		await _frames(150)
		for p in pd.peds:
			if p["state"] == "cross": continue
			var d := _off_road(p["pos"])
			worst = min(worst, d)
			if d < -0.3: in_road += 1
	var moved := 0; var m := 0
	for p in pd.peds:
		if start.has(p["node"]):
			m += 1
			if (p["pos"] - start[p["node"]]).length() > 5.0: moved += 1
	tod.total_hours = keep; tod.apply_now()
	if moved < m * 0.5: return [false, "only %d of %d people walked more than 5 m in 10 s" % [moved, m]]
	if in_road > 0: return [false, "%d samples of people walking in the road (worst %.1f m inside)" % [in_road, -worst]]
	return [true, "%d people, %d of %d walked >5 m in 10 s, closest to traffic %.1f m from the curb" % [n, moved, m, worst]]

func t_pd_cross() -> Array:
	var pd = main.peds; var tr = main.traffic
	var c0: int = pd.crossings_started
	var bad := 0; var seen := 0
	for f in 20:
		await _frames(120)
		for p in pd.peds:
			if p["state"] != "cross": continue
			seen += 1
			var n: int = p["cross"][3]
			if pd.node_walk.get(n, []).size() < 3 and not tr.ix.has(n): bad += 1
	var started: int = pd.crossings_started - c0
	if started == 0: return [false, "nobody crossed a street in 20 s"]
	if bad > 0: return [false, "%d crossings away from intersections" % bad]
	return [true, "%d crossings started in 20 s, all at intersections" % started]

func t_pd_car_stops() -> Array:
	var tr = main.traffic; var pd = main.peds
	var eid := -1
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		var near: float = (tr.npos[e["b"]] - main.focus_world()).length()
		if near < 160.0 and e["len"] > 40.0 and e["cls"] >= 2 and e["cls"] <= 5 and not tr._occupied(i, e["len"] * 0.5, e["len"]):
			eid = i; break
	if eid < 0: return [false, "no clear edge"]
	var e2: Dictionary = tr.edges[eid]
	# a person standing in the crosswalk in the car's lane
	var p: Dictionary = pd._spawn(pd.walk_edges[0], 0.0, 1)
	var spot: Vector3 = tr.lane_point(e2, e2["len"] - 5.0, 0)
	p["state"] = "cross"; p["cross"] = [spot, spot, eid, e2["b"]]; p["pos"] = spot
	var c: Dictionary = tr._spawn_on(eid, max(1.0, e2["len"] - 40.0))
	c["lane"] = 0; c["v"] = 5.0
	for f in 1080:
		await get_tree().physics_frame
		p["state"] = "cross"; p["pos"] = spot; p["cross"] = [spot, spot, eid, e2["b"]]
	var ok: bool = tr.cars.has(c) and c["ea"] == e2["a"] and c["eb"] == e2["b"]
	var gap: float = (e2["len"] - 5.0) - c["s"] - c["len"] * 0.5
	pd._despawn(p)
	if not ok: return [false, "car drove through the crosswalk"]
	if gap < 0.5 or c["v"] > 0.5: return [false, "car gap %.1f m, speed %.1f m/s" % [gap, c["v"]]]
	return [true, "car stopped %.1f m before the person" % gap]

func t_pd_umbrella() -> Array:
	var w = main.weather; var pd = main.peds; var tod = main.tod
	var keep: float = tod.total_hours; var ks: String = w.state
	tod.set_date("fall", 3, 12.5)
	w.set_state("rain"); w.snap()
	await _frames(240)
	var up := 0
	for p in pd.peds: if p["umbrella"] > 0.9: up += 1
	w.set_state("clear"); w.snap()
	await _frames(240)
	var dry := 0
	for p in pd.peds: if p["umbrella"] > 0.1: dry += 1
	w.set_state(ks); w.snap(); tod.total_hours = keep; tod.apply_now()
	if pd.count() == 0: return [false, "no people"]
	if up < pd.count() * 0.25: return [false, "only %d of %d umbrellas up in the rain" % [up, pd.count()]]
	if dry > 0: return [false, "%d umbrellas still up when dry" % dry]
	return [true, "%d of %d umbrellas up in rain, all down after" % [up, pd.count()]]

