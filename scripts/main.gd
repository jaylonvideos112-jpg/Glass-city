extends Node3D
## Game bootstrap: world, streaming, player/car control, camera, HUD, origin rebasing.

const Streamer := preload("res://scripts/city_streamer.gd")
const Player := preload("res://scripts/player.gd")
const Car := preload("res://scripts/car.gd")
const Hud := preload("res://scripts/hud.gd")
const Demo := preload("res://scripts/demo.gd")
const Bars := preload("res://scripts/bars.gd")
const Perf := preload("res://scripts/perf.gd")
const TimeOfDay := preload("res://scripts/time_of_day.gd")
const Weather := preload("res://scripts/weather.gd")

const REBASE_DIST := 1000.0   # shift the world back to the origin past this distance

var world: Node3D           # everything in the game world lives under here (rebasing root)
var streamer: Node3D
var player: CharacterBody3D
var cars: Array = []
var current_car: VehicleBody3D = null
var camera: Camera3D
var hud: CanvasLayer
var world_offset := Vector3.ZERO   # world coords = local coords + world_offset

var cam_yaw := 0.0
var cam_pitch := -0.25
var cam_dist := 5.0
var mouse_captured := false
var last_safe := Vector3.ZERO
var safe_timer := 0.0
var demo: Node = null
var bars: Node = null
var perf: CanvasLayer = null
var tod: Node = null
var weather: Node3D = null
var traffic: Node = null
var audio: Node = null
var world_state: Node = null
var services: Node = null
var stats: Node = null
var money: Node = null
var police: Node = null
var jobs: Node = null
var business: Node = null
var homes: Node = null
var peds: Node = null
var input_enabled := true
var env: Environment
var cam_override := false
var focus_override = null   # world-space Vector3 when the demo camera drives streaming

func _ready() -> void:
	_setup_input()
	_setup_environment()
	world = Node3D.new(); world.name = "World"; add_child(world)
	bars = Bars.new(); bars.name = "Bars"; bars.main = self; add_child(bars)
	streamer = Streamer.new(); streamer.name = "City"; streamer.bars = bars; world.add_child(streamer)
	_build_outskirts()
	var sp: Array = streamer.manifest["spawn"]
	var spawn := Vector3(sp[0], 0, sp[1])
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--at="):
			var xz := a.substr(5).split(",")
			spawn = Vector3(float(xz[0]), 0, float(xz[1]))
	streamer.load_now(spawn)
	var snap: Dictionary = streamer.street_at(spawn, 250.0)
	if snap["name"] != "":
		spawn = snap["point"]
		streamer.load_now(spawn)
	# spawn player on the sidewalk next to the intersection
	player = Player.new(); player.name = "Player"; world.add_child(player)
	var st: Dictionary = streamer.street_at(spawn, 60.0)
	var road_dir: Vector3 = st["dir"] if st["name"] != "" else Vector3(0, 0, -1)
	var side := road_dir.cross(Vector3.UP).normalized()
	player.global_position = _clear_spot(spawn - road_dir * 18.0, road_dir, [8.0, 9.0, 7.0, -8.0, -9.0, -7.0]) + Vector3(0, 0.1, 0)
	cam_yaw = atan2(-road_dir.x, -road_dir.z)
	# a drivable car parked at the curb + a few more parked down the block
	var colors := [Color(0.65, 0.1, 0.1), Color(0.1, 0.25, 0.55), Color(0.85, 0.85, 0.82), Color(0.15, 0.15, 0.15), Color(0.2, 0.45, 0.25)]
	var names := ["Vapid Stallion", "Declasse Mercury", "Albany Prairie", "Karin Meridian", "Bravado Boulder"]
	for i in 5:
		var c := Car.new()
		c.body_color = colors[i]
		c.model_name = names[i]
		world.add_child(c)
		var p := spawn - road_dir * (12.0 + i * 9.0)
		var d2 := road_dir
		var st2: Dictionary = streamer.street_at(p, 20.0)
		if st2["name"] != "":
			d2 = st2["dir"] if st2["dir"].dot(road_dir) >= 0 else -st2["dir"]
			p = st2["point"] + d2.cross(Vector3.UP).normalized() * 2.4
		var g := _ground_from(p, 60.0)
		c.global_transform = Transform3D(Basis(Vector3.UP, atan2(-d2.x, -d2.z)), Vector3(p.x, (g.y if g.y < 90.0 else 0.1), p.z) + Vector3(0, 0.6, 0))
		cars.append(c)
	last_safe = player.global_position
	camera = Camera3D.new(); camera.far = 8000.0; camera.near = 0.1; camera.fov = 70
	world.add_child(camera)
	camera.current = true
	hud = Hud.new(); hud.main = self; add_child(hud)
	tod = TimeOfDay.new(); tod.name = "TimeOfDay"; tod.main = self; add_child(tod)
	weather = Weather.new(); weather.name = "Weather"; weather.main = self; add_child(weather)
	for m in streamer.materials.values():
		if m is StandardMaterial3D and m.emission_texture != null: tod.register_night_material(m)
	streamer._lamp_mesh()
	tod.register_lamp_material(streamer.lamp_bulb_mat)
	tod.register_ground_materials(streamer.materials)
	var sl = load("res://scripts/street_lights.gd").new(); sl.name = "StreetLights"; sl.main = self; add_child(sl)
	traffic = load("res://scripts/traffic.gd").new(); traffic.name = "Traffic"; traffic.main = self; add_child(traffic)
	peds = load("res://scripts/pedestrians.gd").new(); peds.name = "Pedestrians"; peds.main = self; add_child(peds)
	services = load("res://scripts/services.gd").new(); services.name = "Services"; services.main = self; add_child(services)
	audio = load("res://scripts/audio.gd").new(); audio.name = "Audio"; audio.main = self; add_child(audio)
	world_state = load("res://scripts/world_state.gd").new(); world_state.name = "WorldState"; world_state.main = self; add_child(world_state)
	world_state.register("clock", tod)
	world_state.register("player", self)
	stats = load("res://scripts/stats.gd").new(); stats.name = "Stats"; stats.main = self; add_child(stats)
	world_state.register("stats", stats)
	money = load("res://scripts/money.gd").new(); money.name = "Money"; money.main = self; add_child(money)
	world_state.register("money", money)
	police = load("res://scripts/police.gd").new(); police.name = "Police"; police.main = self; add_child(police)
	jobs = load("res://scripts/jobs.gd").new(); jobs.name = "Jobs"; jobs.main = self; add_child(jobs)
	world_state.register("job", jobs)
	business = load("res://scripts/business.gd").new(); business.name = "Business"; business.main = self; add_child(business)
	world_state.register("business", business)
	homes = load("res://scripts/homes.gd").new(); homes.name = "Homes"; homes.main = self; add_child(homes)
	world_state.register("home", homes)
	if OS.get_cmdline_user_args().has("--load-world") or (world_state.enabled and not OS.get_cmdline_user_args().has("--new-game")):
		world_state.load_file()
	player.collision_mask |= 2      # bump into traffic
	for c in cars: c.collision_mask |= 2
	tod.apply_now()
	perf = Perf.new(); perf.main = self; add_child(perf)
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--test"):
			var tr = load("res://tests/test_runner.gd").new(); tr.main = self; add_child(tr)
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--demo="):
			demo = Demo.new(); demo.main = self; demo.mode = a.substr(7); add_child(demo)
			input_enabled = false

## Beyond the generated area: open Lake Glassmere (Lake Erie) all the way to the horizon (the map is an island).
func _build_outskirts() -> void:
	var bb: Array = streamer.manifest["bbox"]   # [minx, minz, maxx, maxz]
	var m: Material = streamer.materials.get("water")
	if m == null:
		var sm := StandardMaterial3D.new(); sm.albedo_color = Color(0.2, 0.32, 0.4); sm.roughness = 0.1; m = sm
	var wy: float = streamer.manifest.get("water_y", -1.6)
	var far := 12000.0
	var x0: float = bb[0]; var z0: float = bb[1]; var x1: float = bb[2]; var z1: float = bb[3]
	var rects := [
		Rect2(x0 - far, z0 - far, (x1 - x0) + 2 * far, far),   # north
		Rect2(x0 - far, z1, (x1 - x0) + 2 * far, far),         # south
		Rect2(x0 - far, z0, far, z1 - z0),                     # west
		Rect2(x1, z0, far, z1 - z0),                           # east
	]
	for r in rects:
		var mi := MeshInstance3D.new()
		var pm := PlaneMesh.new()
		pm.size = r.size
		mi.mesh = pm
		mi.material_override = m
		mi.position = Vector3(r.position.x + r.size.x * 0.5, wy, r.position.y + r.size.y * 0.5)
		world.add_child(mi)
		# deep lakebed under the open water (the water shader shades by depth and needs a floor)
		var bed := MeshInstance3D.new(); bed.mesh = pm
		var bm := StandardMaterial3D.new(); bm.albedo_color = Color(0.08, 0.12, 0.13); bm.roughness = 1.0
		bed.material_override = bm
		bed.position = mi.position - Vector3(0, 9.0, 0)
		world.add_child(bed)

## Find a spot near p (sliding along the road, trying several side offsets) that is open ground, not a roof.
func _clear_spot(p: Vector3, road_dir: Vector3, sides: Array) -> Vector3:
	var right := road_dir.cross(Vector3.UP).normalized()
	for along in [0.0, 6.0, -6.0, 12.0, -12.0, 20.0, -20.0, 30.0, -30.0]:
		for sd in sides:
			var q: Vector3 = p + road_dir * along + right * sd
			var g := _ground_from(q, 60.0)
			if g.y < 0.5:
				return g
	return Vector3(p.x, 0.1, p.z)

func _ground_from(p: Vector3, h: float) -> Vector3:
	var space := get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(p - world_offset + Vector3(0, h, 0), p - world_offset + Vector3(0, -20, 0))
	var r := space.intersect_ray(q)
	if r.is_empty():
		return Vector3(p.x, 99.0, p.z)
	return r["position"] + world_offset

func _ground(p: Vector3) -> Vector3:
	var space := get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(p - world_offset + Vector3(0, 200, 0), p - world_offset + Vector3(0, -20, 0))
	var r := space.intersect_ray(q)
	if r.is_empty():
		return Vector3(p.x, 0.1, p.z)
	return r["position"] + world_offset

# ------------------------------------------------------------------ input
func _add_key(action: String, keys: Array) -> void:
	if not InputMap.has_action(action):
		InputMap.add_action(action)
	for k in keys:
		var ev := InputEventKey.new(); ev.physical_keycode = k
		InputMap.action_add_event(action, ev)

func _setup_input() -> void:
	_add_key("forward", [KEY_W, KEY_UP])
	_add_key("back", [KEY_S, KEY_DOWN])
	_add_key("left", [KEY_A, KEY_LEFT])
	_add_key("right", [KEY_D, KEY_RIGHT])
	_add_key("sprint", [KEY_SHIFT])
	_add_key("jump", [KEY_SPACE])
	_add_key("enter", [KEY_E, KEY_F])
	_add_key("reset_car", [KEY_R])
	_add_key("toggle_help", [KEY_H])

func _unhandled_input(e: InputEvent) -> void:
	if not input_enabled:
		return
	if e is InputEventMouseButton and e.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		if e.button_index == MOUSE_BUTTON_WHEEL_UP: cam_dist = max(2.5, cam_dist - 0.5)
		if e.button_index == MOUSE_BUTTON_WHEEL_DOWN: cam_dist = min(14.0, cam_dist + 0.5)
	if e is InputEventKey and e.pressed and e.keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	if e is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		cam_yaw -= e.relative.x * 0.0035
		cam_pitch = clamp(cam_pitch - e.relative.y * 0.0035, -1.2, 0.5)
	if e.is_action_pressed("enter"):
		if current_car == null and jobs and jobs.try_interact(player.global_position):
			return
		if current_car == null and money and money.try_withdraw(player.global_position):
			return
		if current_car == null and bars.try_interact(player):
			return
		if not bars.inside:
			toggle_vehicle()
	if e.is_action_pressed("reset_car") and current_car:
		current_car.reset_upright()
	elif e.is_action_pressed("reset_car") and money:
		money.try_deposit(player.global_position)
	if e.is_action_pressed("toggle_help"):
		hud.toggle_help()

func nearest_car(max_d := 5.0) -> VehicleBody3D:
	var best: VehicleBody3D = null
	var bd := max_d
	for c in cars:
		var d: float = c.global_position.distance_to(player.global_position)
		if d < bd:
			bd = d; best = c
	return best

func toggle_vehicle() -> void:
	if current_car == null:
		var c := nearest_car()
		if c == null:
			return
		current_car = c
		c.driven = true
		player.visible = false
		player.process_mode = Node.PROCESS_MODE_DISABLED
		player.get_child(0).disabled = true
		cam_yaw = c.global_rotation.y
	else:
		var c := current_car
		c.driven = false
		c.throttle = 0; c.steer_in = 0
		current_car = null
		var exit_pos: Vector3 = c.global_position - c.global_transform.basis.x * 2.0 + Vector3(0, 0.5, 0)
		player.global_position = exit_pos
		player.velocity = Vector3.ZERO
		player.process_mode = Node.PROCESS_MODE_INHERIT
		player.get_child(0).disabled = false
		player.visible = true

# ------------------------------------------------------------------ loop
func focus_local() -> Vector3:
	return current_car.global_position if current_car else player.global_position

# ------------------------------------------------------------------ save section "player": you, and your cars
func get_save_data() -> Dictionary:
	var vs := []
	for c in cars:
		if not is_instance_valid(c): continue
		var p: Vector3 = c.global_position + world_offset
		vs.append({"model": c.model_name, "color": c.body_color.to_html(false), "pos": [p.x, p.y, p.z], "yaw": c.global_rotation.y})
	var pp: Vector3 = (current_car.global_position if current_car else player.global_position) + world_offset
	return {"pos": [pp.x, pp.y, pp.z], "cam_yaw": cam_yaw, "driving": cars.find(current_car) if current_car else -1, "vehicles": vs}

func apply_save_data(d: Dictionary) -> void:
	if current_car: return                       # never yank the player out of a moving car
	var pw := Vector3(d["pos"][0], d["pos"][1], d["pos"][2])
	streamer.load_now(pw)
	var vs: Array = d.get("vehicles", [])
	for i in mini(vs.size(), cars.size()):
		var c = cars[i]; var v: Dictionary = vs[i]
		c.model_name = v.get("model", c.model_name)
		var vp := Vector3(v["pos"][0], v["pos"][1] + 0.3, v["pos"][2]) - world_offset
		c.global_transform = Transform3D(Basis(Vector3.UP, float(v.get("yaw", 0.0))), vp)
		c.linear_velocity = Vector3.ZERO; c.angular_velocity = Vector3.ZERO
	var drv := int(d.get("driving", -1))
	# you come back standing next to where you left off (beside the car if you were driving)
	player.global_position = pw - world_offset + (Vector3(2.5, 0.6, 0) if drv >= 0 else Vector3(0, 0.3, 0))
	player.velocity = Vector3.ZERO
	cam_yaw = float(d.get("cam_yaw", cam_yaw))
	last_safe = player.global_position + world_offset

func focus_world() -> Vector3:
	if focus_override != null:
		return focus_override
	return focus_local() + world_offset

func _physics_process(dt: float) -> void:
	if input_enabled:
		var mv := Vector2(Input.get_axis("left", "right"), Input.get_axis("back", "forward"))
		if current_car:
			current_car.throttle = mv.y
			current_car.steer_in = -mv.x
			current_car.handbrake = Input.is_action_pressed("jump")
		else:
			player.input_dir = mv
			player.sprint = Input.is_action_pressed("sprint")
			if Input.is_action_just_pressed("jump"):
				player.want_jump = true
	player.cam_yaw = cam_yaw
	# fell in the river / out of the world -> respawn at last safe spot
	var f := focus_local()
	if bars.inside:
		pass
	elif f.y < -2.2 and not cam_override:
		_respawn()
	else:
		safe_timer += dt
		if safe_timer > 1.0 and f.y > -0.5 and (current_car == null or current_car.speed_mps() < 30):
			safe_timer = 0.0
			var on_ground := player.is_on_floor() if current_car == null else true
			if on_ground:
				last_safe = f + world_offset

func _respawn() -> void:
	hud.flash("WASTED... you can't swim in the Stone Ridge.")
	var p := last_safe - world_offset + Vector3(0, 1.0, 0)
	if current_car:
		current_car.global_position = p + Vector3(0, 0.5, 0)
		current_car.linear_velocity = Vector3.ZERO
		current_car.angular_velocity = Vector3.ZERO
		current_car.reset_upright()
	else:
		player.global_position = p
		player.velocity = Vector3.ZERO

func _process(dt: float) -> void:
	streamer.update_focus(focus_world())
	Car.surface_grip = tod.road_grip()
	_rebase_if_needed()
	if not cam_override:
		_update_camera(dt)

func _rebase_if_needed() -> void:
	var f := focus_local()
	if Vector2(f.x, f.z).length() < REBASE_DIST:
		return
	var shift := Vector3(snappedf(f.x, 100.0), 0, snappedf(f.z, 100.0))
	for child in world.get_children():
		if child == streamer:
			# chunks are placed at (world origin - world_offset) when built, so shift them, not the streamer
			for ch in streamer.get_children():
				if ch is Node3D:
					ch.position -= shift
		elif child is Node3D:
			child.position -= shift
	world_offset += shift
	streamer.world_offset = world_offset

func _update_camera(dt: float) -> void:
	if current_car:
		var c := current_car
		var car_yaw := c.global_rotation.y
		var spd: float = c.speed_mps()
		# chase cam swings behind the car unless the mouse is moving it
		if Input.mouse_mode != Input.MOUSE_MODE_CAPTURED or spd > 3.0:
			cam_yaw = lerp_angle(cam_yaw, car_yaw, 1.0 - exp(-3.0 * dt))
		var dist: float = 7.5 + spd * 0.06
		var target := c.global_position + Vector3(0, 1.6, 0)
		var back := Vector3(sin(cam_yaw), 0, cos(cam_yaw))
		var desired := target + back * dist * cos(-0.18) + Vector3(0, dist * sin(0.18) + 0.6, 0)
		var cq := PhysicsRayQueryParameters3D.create(target, desired)
		cq.exclude = [c.get_rid()]
		var ch := get_world_3d().direct_space_state.intersect_ray(cq)
		var blocked := not ch.is_empty()
		if blocked:
			desired = ch["position"] + (target - desired).normalized() * 0.4
		camera.global_position = desired if blocked else camera.global_position.lerp(desired, 1.0 - exp(-10.0 * dt))
		camera.look_at(target, Vector3.UP)
		camera.fov = lerp(camera.fov, 70.0 + clamp(spd * 0.35, 0.0, 14.0), 0.05)
	else:
		var target := player.global_position + Vector3(0, 1.6, 0)
		var dir := Vector3(sin(cam_yaw) * cos(cam_pitch), -sin(cam_pitch), cos(cam_yaw) * cos(cam_pitch))
		var desired := target + dir * cam_dist
		# keep the camera out of walls
		var q := PhysicsRayQueryParameters3D.create(target, desired)
		q.exclude = [player.get_rid()]
		var hit := get_world_3d().direct_space_state.intersect_ray(q)
		if not hit.is_empty():
			desired = hit["position"] - dir * 0.3
		camera.global_position = desired
		camera.look_at(target, Vector3.UP)
		camera.fov = lerp(camera.fov, 70.0, 0.1)

# ------------------------------------------------------------------ environment
func _setup_environment() -> void:
	env = Environment.new()
	var sky := Sky.new()
	var sm := ProceduralSkyMaterial.new()
	sm.sky_top_color = Color(0.32, 0.5, 0.75)
	sm.sky_horizon_color = Color(0.72, 0.76, 0.8)
	sm.ground_horizon_color = Color(0.62, 0.66, 0.6)
	sm.ground_bottom_color = Color(0.4, 0.45, 0.38)
	sm.sun_angle_max = 20.0
	sky.sky_material = sm
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.9
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.fog_enabled = true
	env.fog_light_color = Color(0.72, 0.76, 0.82)
	env.fog_density = 0.00022
	env.fog_sky_affect = 0.15
	env.ssao_enabled = true
	env.glow_enabled = true
	env.glow_intensity = 0.3
	var we := WorldEnvironment.new(); we.environment = env; add_child(we)
	var sun := DirectionalLight3D.new()
	sun.name = "Sun"
	sun.rotation_degrees = Vector3(-42, -35, 0)
	sun.light_energy = 1.25
	sun.light_color = Color(1.0, 0.95, 0.86)
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 220.0
	add_child(sun)
