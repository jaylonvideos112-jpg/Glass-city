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
	]
	for t in tests:
		var t0 := Time.get_ticks_msec()
		var r: Array = await t[1].call()
		_record(t[0], r, Time.get_ticks_msec() - t0)
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
