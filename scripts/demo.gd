extends Node
## Scripted demo / capture modes (used for testing and trailers).
## Run:  godot --path . -- --demo=drive     (modes: walk, drive, shots, fly)
## Optional: --out=/abs/dir for screenshots, --seconds=N to auto-quit.

var main: Node
var mode := "drive"
var t := 0.0
var out_dir := "user://shots"
var seconds := 40.0
var cur_name := ""
var shot_i := 0
var shot_wait := 0.0
var stats := {"max_speed": 0.0, "dist": 0.0, "streets": {}}
var _last_pos = null
var log_t := 0.0
var busy := false
var street_cam: Array = []
var shots: Array = SHOTS
var fly_center := Vector3(230, 0, 180)
var fly_r0 := 620.0
var fly_h0 := 190.0

const SHOTS := [
	# name, camera world pos, look-at world pos  (x east, z south, meters from downtown origin)
	["01_downtown_aerial", Vector3(-380, 240, 820), Vector3(260, 20, 120)],
	["02_skyline_from_river", Vector3(820, 28, 420), Vector3(200, 55, 60)],
	["03_street_level", null, null],     # filled at runtime from spawn
	["04_warehouse_district", Vector3(-300, 90, 1000), Vector3(-50, 0, 560)],
	["05_maumee_bridges", Vector3(900, 140, 900), Vector3(300, 0, 0)],
	["06_top_down", Vector3(0, 1400, 1), Vector3(0, 0, 0)],
]

func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--out="): out_dir = a.substr(6)
		if a.begins_with("--seconds="): seconds = float(a.substr(10))
		if a.begins_with("--shotlist="):
			var j = JSON.parse_string(FileAccess.get_file_as_string(a.substr(11)))
			shots = []
			for s in j:
				shots.append([s[0], null if s[1] == null else Vector3(s[1][0], s[1][1], s[1][2]), null if s[2] == null else Vector3(s[2][0], s[2][1], s[2][2])])
		if a.begins_with("--fly="):
			var f := a.substr(6).split(",")
			fly_center = Vector3(float(f[0]), 0, float(f[1])); fly_r0 = float(f[2]); fly_h0 = float(f[3])
	DirAccess.make_dir_recursive_absolute(out_dir)
	main.hud.help_label.visible = false
	if mode == "shots" or mode == "fly":
		main.cam_override = true
		main.hud.visible = false
		main.camera.far = 25000.0
	if mode == "fly" and fly_h0 > 800.0:
		# high flyover: stream in everything the camera can see before the clip starts
		main.streamer.load_radius_m = fly_r0 + fly_h0 * 3.0
		main.focus_override = fly_center
		main.streamer.load_now(fly_center)
	if mode == "bars":
		main.cam_override = true
		main.hud.visible = false
		_bar_tour()
		return
	if mode == "drive":
		await get_tree().create_timer(1.2).timeout
		main.player.global_position = main.cars[0].global_position + Vector3(-2, 0.5, 0)
		main.toggle_vehicle()

func _physics_process(dt: float) -> void:
	t += dt
	match mode:
		"tour": _tour(dt)
		"drive": _drive(dt)
		"walk": _walk(dt)
	var p: Vector3 = main.focus_world()
	if _last_pos != null:
		stats["dist"] += Vector2(p.x - _last_pos.x, p.z - _last_pos.z).length()
	_last_pos = p
	if main.current_car:
		stats["max_speed"] = max(stats["max_speed"], main.current_car.speed_mps())
	if main.hud.cur_street != "":
		stats["streets"][main.hud.cur_street] = true
	log_t += dt
	if log_t > 2.0:
		log_t = 0.0
		print("[demo] t=%.1f pos=(%.0f, %.1f, %.0f) street=%s speed=%.1f chunks=%d fps=%d" % [t, p.x, p.y, p.z, main.hud.cur_street,
			main.current_car.speed_mps() if main.current_car else main.player.velocity.length(), main.streamer.loaded.size(), Engine.get_frames_per_second()])
	if t > seconds and mode != "shots":
		_finish()

func _process(dt: float) -> void:
	if mode == "shots":
		_shots(dt)
	elif mode == "fly":
		_fly()

func _finish() -> void:
	print("[demo] DONE dist=%.0fm max_speed=%.1fm/s streets=%s" % [stats["dist"], stats["max_speed"], ", ".join(stats["streets"].keys())])
	get_tree().quit()

# ------------------------------------------------------------------ road following autopilot
func _pick_segment(pos: Vector3, fwd: Vector3) -> Array:
	var best = null
	var best_score := 1e9
	for s in main.streamer.segments_near(pos, 60.0):
		var a := Vector3(s[0].x, 0, s[0].y)
		var b := Vector3(s[1].x, 0, s[1].y)
		if a.distance_to(b) < 0.5:
			continue
		var q := Geometry3D.get_closest_point_to_segment(Vector3(pos.x, 0, pos.z), a, b)
		var d := q.distance_to(Vector3(pos.x, 0, pos.z))
		if d > 30.0:
			continue
		var dir := (b - a).normalized()
		if dir.dot(fwd) < 0:
			dir = -dir
		var score := d + (1.0 - dir.dot(fwd)) * 40.0 + (0.0 if s[2] == cur_name else 6.0)
		if score < best_score:
			best_score = score
			best = [q, dir, s[2]]
	return best if best != null else []

func _steer_target(pos: Vector3, fwd: Vector3, lane_offset: float, lookahead: float) -> Variant:
	var seg := _pick_segment(pos, fwd)
	if seg.is_empty():
		return null
	cur_name = seg[2]
	var dir: Vector3 = seg[1]
	var right := dir.cross(Vector3.UP).normalized()
	return seg[0] + dir * lookahead + right * lane_offset

func _drive(_dt: float) -> void:
	var c: VehicleBody3D = main.current_car
	if c == null:
		return
	var pos: Vector3 = c.global_position + main.world_offset
	var fwd: Vector3 = -c.global_transform.basis.z
	fwd.y = 0; fwd = fwd.normalized()
	var spd: float = c.speed_mps()
	var target = _steer_target(pos, fwd, 2.6, 10.0 + spd * 0.8)
	if target == null:
		c.throttle = 0.3; c.steer_in = 0.0
		return
	var to: Vector3 = (target - pos); to.y = 0
	var ang := fwd.signed_angle_to(to.normalized(), Vector3.UP)
	c.steer_in = clamp(ang * 2.2, -1.0, 1.0)
	var want_speed: float = lerp(19.0, 7.0, clamp(abs(ang) * 2.5, 0.0, 1.0))
	c.throttle = clamp((want_speed - spd) * 0.4, -1.0, 1.0)
	c.handbrake = false

func _walk(dt: float) -> void:
	var p: CharacterBody3D = main.player
	var pos: Vector3 = p.global_position + main.world_offset
	var fwd := Vector3(-sin(main.cam_yaw), 0, -cos(main.cam_yaw))
	var target = _steer_target(pos, fwd, 7.5, 6.0)
	if target != null:
		var to: Vector3 = target - pos
		var want := atan2(-to.x, -to.z)
		main.cam_yaw = lerp_angle(main.cam_yaw, want, 1.0 - exp(-2.5 * dt))
	main.cam_pitch = -0.22
	p.input_dir = Vector2(0, 1)
	p.sprint = fmod(t, 14.0) > 8.0

# ------------------------------------------------------------------ large-world stress test
var tour_pts := [Vector3(-12000, 0, 6000), Vector3(6500, 0, -8500), Vector3(-9000, 0, -8000), Vector3(4000, 0, 7500), Vector3(-2004, 0, -1987), Vector3(336, 0, 217)]
var tour_i := -1
var tour_wait := 0.0
func _tour(dt: float) -> void:
	if main.current_car == null:
		main.player.global_position = main.cars[0].global_position + Vector3(-2, 0.5, 0)
		main.toggle_vehicle()
		return
	tour_wait += dt
	if tour_i >= 0 and tour_wait > 3.0 and main.streamer.is_idle():
		var c: VehicleBody3D = main.current_car
		var space: PhysicsDirectSpaceState3D = main.get_world_3d().direct_space_state
		var q := PhysicsRayQueryParameters3D.create(c.global_position + Vector3(0, 50, 0), c.global_position + Vector3(0, -50, 0))
		q.exclude = [c.get_rid()]
		var hit: Dictionary = space.intersect_ray(q)
		print("[demo] TOUR %d world=(%.0f,%.0f) local=(%.0f,%.0f) offset=(%.0f,%.0f) car_y=%.2f ground=%s chunks=%d street=%s" % [tour_i,
			c.global_position.x + main.world_offset.x, c.global_position.z + main.world_offset.z, c.global_position.x, c.global_position.z,
			main.world_offset.x, main.world_offset.z, c.global_position.y, ("%.2f" % hit["position"].y) if not hit.is_empty() else "NONE",
			main.streamer.loaded.size(), main.hud.cur_street])
	if tour_i < 0 or (tour_wait > 3.0 and main.streamer.is_idle()):
		tour_i += 1
		tour_wait = 0.0
		if tour_i >= tour_pts.size():
			_finish(); return
		var target: Vector3 = tour_pts[tour_i]
		var st: Dictionary = main.streamer.street_at(target, 300.0)
		main.streamer.load_now(target)
		st = main.streamer.street_at(target, 300.0)
		if st["name"] != "": target = st["point"]
		var c: VehicleBody3D = main.current_car
		c.global_position = target - main.world_offset + Vector3(0, 1.0, 0)
		c.linear_velocity = Vector3.ZERO
		c.sleeping = false

# ------------------------------------------------------------------ cameras
func _fly() -> void:
	# slow orbit around downtown, then a low pass along the river
	var ang := t * 0.11 - 0.2
	var r := fly_r0 * (1.0 - t * 0.008)
	var cam: Camera3D = main.camera
	var center := fly_center
	var pos := center + Vector3(cos(ang) * r, fly_h0 * (1.0 - t * 0.01), sin(ang) * r)
	if fly_h0 <= 800.0:
		main.focus_override = center + (pos - center) * 0.4
		main.streamer.load_radius_m = max(700.0, fly_h0 * 2.2)
	cam.global_position = pos - main.world_offset
	cam.look_at(center + Vector3(0, 30, 0) - main.world_offset, Vector3.UP)
	main.env.fog_density = 0.00022 * clamp(300.0 / max(pos.y, 1.0), 0.04, 1.0)

func _shots(dt: float) -> void:
	if busy:
		return
	if shot_i >= shots.size():
		_finish()
		return
	var s: Array = shots[shot_i]
	var cam: Camera3D = main.camera
	var pos = s[1]
	var look = s[2]
	if pos == null and look != null and shot_wait == 0.0:
		# street-level shot at a map location: snap to the nearest street and look down it
		main.streamer.load_now(look)
		var st: Dictionary = main.streamer.street_at(look, 300.0)
		if st["name"] != "":
			var dir: Vector3 = st["dir"]
			var right := dir.cross(Vector3.UP).normalized()
			street_cam = [st["point"] - dir * 4.0 + right * 3.5 + Vector3(0, 1.8, 0), st["point"] + dir * 70.0 + right * 1.0 + Vector3(0, 4.0, 0)]
	if pos == null and look != null and not street_cam.is_empty():
		pos = street_cam[0]; look = street_cam[1]
	elif pos == null:
		var pl: Vector3 = main.player.global_position + main.world_offset
		var fwd := Vector3(-sin(main.cam_yaw), 0, -cos(main.cam_yaw))
		pos = pl - fwd * 6.0 + Vector3(0, 2.2, 0)
		look = pl + fwd * 60.0 + Vector3(0, 6, 0)
	if shot_wait == 0.0:
		main.focus_override = look.lerp(pos, 0.3) * Vector3(1, 0, 1)
		main.streamer.load_radius_m = 16000.0 if pos.y > 2000 else clamp(pos.y * 2.2, 700.0, 5000.0)
		main.streamer.load_now(main.focus_override)
		cam.far = 25000.0
	cam.global_position = pos - main.world_offset
	cam.look_at(look - main.world_offset, Vector3.UP)
	main.env.fog_density = 0.00022 * clamp(300.0 / max(pos.y, 1.0), 0.12, 1.0)
	shot_wait += dt
	if shot_wait > 1.5 and main.streamer.is_idle():
		busy = true
		await RenderingServer.frame_post_draw
		busy = false
		var img := get_viewport().get_texture().get_image()
		var path: String = out_dir.path_join(s[0] + ".png")
		img.save_png(path)
		print("[demo] saved ", path)
		shot_i += 1
		shot_wait = 0.0
		street_cam = []


## Interior + exterior screenshots for every bar brand (--demo=bars --out=dir).
func _bar_tour() -> void:
	var bars = main.bars
	var cam: Camera3D = main.camera
	await get_tree().create_timer(0.5).timeout
	for theme in bars.THEMES:
		var th: Dictionary = bars.THEMES[theme]
		var sz: Array = th["size"]
		var room: Node3D = bars.build_interior(theme)
		main.world.add_child(room)
		room.global_position = Vector3(0, bars.INTERIOR_Y, 0)
		bars._set_indoor_env(true, th)
		for v in 2:
			var p: Vector3 = Vector3(sz[0] * (0.38 if v == 0 else -0.38), 1.75, sz[1] * 0.42)
			var l: Vector3 = Vector3(sz[0] * (-0.12 if v == 0 else 0.12), 1.2, -sz[1] * 0.5)
			cam.global_position = room.global_transform * p
			cam.look_at(room.global_transform * l, Vector3.UP)
			for f in 4: await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(out_dir.path_join("bar_%s_%d.png" % [theme.replace(" ", "_").replace("'", ""), v]))
		bars._set_indoor_env(false, {})
		room.queue_free()
	# exteriors: visit the bar locations from the data and frame each door
	var j = JSON.parse_string(FileAccess.get_file_as_string("res://data/bars_index.json")) if FileAccess.file_exists("res://data/bars_index.json") else []
	var done := {}
	for b in j:
		if done.has(b["theme"]) or done.size() >= 15: continue
		var at := Vector3(b["x"], 0, -b["y"])
		main.focus_override = at
		main.streamer.load_now(at)
		for f in 3: await RenderingServer.frame_post_draw
		var d: Dictionary = bars.nearest_door(at - main.world_offset, 80.0)
		if d.is_empty(): continue
		var n: Node3D = d["node"]
		cam.global_position = n.global_transform * Vector3(2.5, 2.4, -11.0)
		cam.look_at(n.global_transform * Vector3(0, 3.0, 0), Vector3.UP)
		for f in 4: await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(out_dir.path_join("ext_%s.png" % d["theme"].replace(" ", "_").replace("'", "")))
		done[d["theme"]] = true
		if done.size() == 1:
			# gameplay check: walk the player up to this door, press E, look around inside, press E at the exit
			main.cam_override = false
			main.player.global_position = n.global_transform * Vector3(0, 0.3, -1.6)
			for f in 5: await get_tree().physics_frame
			print("[bars] prompt outside: ", bars.prompt(main.player.global_position))
			print("[bars] enter ok: ", bars.try_interact(main.player), " inside=", bars.inside)
			for f in 30: await get_tree().physics_frame
			for f in 3: await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(out_dir.path_join("play_inside.png"))
			main.player.global_position = bars.interior.global_transform * bars.exit_point
			for f in 3: await get_tree().physics_frame
			print("[bars] prompt at exit: ", bars.prompt(main.player.global_position))
			print("[bars] exit ok: ", bars.try_interact(main.player), " inside=", bars.inside, " y=", main.player.global_position.y)
			for f in 30: await get_tree().physics_frame
			for f in 3: await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(out_dir.path_join("play_outside.png"))
			main.cam_override = true
	get_tree().quit()
