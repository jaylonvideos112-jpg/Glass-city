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
var grass: Node = null
var parked: Node = null
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
var vehicles: Node = null
var needs: Node = null
var inventory: Node = null
var activities: Node = null
var phone: Node = null
var peds: Node = null
var input_enabled := true
var env: Environment
var cam_override := false
var mouse_sens := 0.0035      # menu.gd settings
var base_fov := 70.0
var menu: Node = null
var focus_override = null   # world-space Vector3 when the demo camera drives streaming

func _ready() -> void:
	_setup_input()
	_setup_environment()
	world = Node3D.new(); world.name = "World"; add_child(world)
	bars = Bars.new(); bars.name = "Bars"; bars.main = self; add_child(bars)
	grass = preload("res://scripts/grass.gd").new(); grass.name = "Grass"; grass.main = self; add_child(grass)
	parked = preload("res://scripts/parked_cars.gd").new(); parked.name = "ParkedCars"; parked.main = self; add_child(parked)
	streamer = Streamer.new(); streamer.name = "City"; streamer.bars = bars; streamer.grass = grass; world.add_child(streamer)
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
	start_pos = player.global_position + world_offset
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
	vehicles = load("res://scripts/vehicles.gd").new(); vehicles.name = "Vehicles"; vehicles.main = self; add_child(vehicles)
	_roster_start_cars()
	world_state.register("vehicles", vehicles)
	needs = load("res://scripts/needs.gd").new(); needs.name = "Needs"; needs.main = self; add_child(needs)
	world_state.register("needs", needs)
	player.needs = needs
	player.hurt.connect(hurt)
	combat = load("res://scripts/combat.gd").new(); combat.name = "Combat"; combat.main = self; add_child(combat)
	weapons = load("res://scripts/weapons.gd").new(); weapons.name = "Weapons"; weapons.main = self; add_child(weapons)
	world_state.register("weapons", weapons)
	replicas = load("res://scripts/replicas.gd").new(); replicas.name = "Replicas"; add_child(replicas)
	gunstore = load("res://scripts/gunstore.gd").new(); gunstore.name = "GunStore"; gunstore.main = self; gunstore.wp = weapons; add_child(gunstore)
	world_state.register("combat", combat)
	Car.driver_hurt = hurt
	inventory = load("res://scripts/inventory.gd").new(); inventory.name = "Inventory"; inventory.main = self; add_child(inventory)
	world_state.register("inventory", inventory)
	activities = load("res://scripts/activities.gd").new(); activities.name = "Activities"; activities.main = self; add_child(activities)
	world_state.register("activities", activities)
	phone = load("res://scripts/phone.gd").new(); phone.name = "Phone"; phone.main = self; add_child(phone)
	world_state.register("phone", phone)
	if OS.get_cmdline_user_args().has("--load-world"):
		world_state.load_file()          # otherwise the title screen's Continue loads the save
	player.collision_mask |= 2      # bump into traffic
	for c in cars: c.collision_mask |= 2
	tod.apply_now()
	perf = Perf.new(); perf.main = self; add_child(perf)
	menu = load("res://scripts/menu.gd").new(); menu.name = "Menu"; menu.main = self; add_child(menu)
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
var start_pos := Vector3.ZERO      # world position the player first spawned at (tests reset to it)

func _clear_spot(p: Vector3, road_dir: Vector3, sides: Array) -> Vector3:
	var right := road_dir.cross(Vector3.UP).normalized()
	for along in [0.0, 6.0, -6.0, 12.0, -12.0, 20.0, -20.0, 30.0, -30.0]:
		for sd in sides:
			var q: Vector3 = p + road_dir * along + right * sd
			var g := _ground_from(q + Vector3(0, Terrain.height(q), 0), 60.0)
			if g.y < Terrain.height(q) + 0.5:
				return g
	return Vector3(p.x, Terrain.height(p) + 0.1, p.z)

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
		return Vector3(p.x, Terrain.height(p) + 0.1, p.z)
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
	_add_key("enter", [KEY_E])          # use / talk / apply / clock in / doors
	_add_key("vehicle", [KEY_F])        # get in / out of cars (GTA-style), never steals the E key
	_add_key("reset_car", [KEY_R])
	_add_key("toggle_help", [KEY_H])

func _unhandled_input(e: InputEvent) -> void:
	if not input_enabled:
		return
	if e is InputEventMouseButton and e.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		if e.button_index == MOUSE_BUTTON_WHEEL_UP: cam_dist = max(2.5, cam_dist - 0.5)
		if e.button_index == MOUSE_BUTTON_WHEEL_DOWN: cam_dist = min(14.0, cam_dist + 0.5)
	if e is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		cam_yaw -= e.relative.x * mouse_sens
		_cam_input_t = 0.0
		cam_pitch = clamp(cam_pitch - e.relative.y * mouse_sens, -1.2, 0.5)
	if e.is_action_pressed("vehicle"):
		if not bars.inside and not dying: toggle_vehicle()
		return
	if e.is_action_pressed("enter"):
		if current_car == null and jobs and jobs.try_interact(player.global_position):
			return
		if current_car == null and money and money.try_withdraw(player.global_position):
			return
		if current_car == null and bars.try_interact(player):
			return
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
		if not is_instance_valid(c) or not c.visible: continue
		var d: float = c.global_position.distance_to(player.global_position)
		if d < bd:
			bd = d; best = c
	return best

# ------------------------------------------------------------------ injury, death and the hospital
var dying := false
var _aim_k := 0.0
# GTA-style on-foot camera state: smoothed pivot, collision distance, idle time since the last mouse move
var _cam_t := Vector3.ZERO
var _cam_d := 5.0
var _cam_input_t := 10.0
var _sprint_k := 0.0
var _cam_shake_t := 0.0
var combat: Node
var weapons: Node
var gunstore: Node
var replicas: Node      # hand-made building replicas (scripts/replicas.gd)
var hospitals: Array = []
var times_wasted := 0
func hurt(amount: float, cause: String) -> void:
	if dying or needs == null or amount <= 0.0: return
	needs.health = maxf(0.0, needs.health - amount)
	if hud: hud.hit_flash = minf(1.0, hud.hit_flash + amount / 40.0)
	if needs.health <= 0.0: wasted(cause)

func wasted(cause: String) -> void:
	if dying: return
	dying = true
	input_enabled = false
	if hud: hud.flash("WASTED")
	if current_car: current_car.throttle = 0.0
	get_tree().create_timer(3.0).timeout.connect(_wake_in_hospital.bind(cause))

## nearest hospital: medical bill, half a day gone, wanted level cleared, health back
func _wake_in_hospital(cause: String) -> void:
	if hospitals.is_empty():
		hospitals = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/stations.json"))["stations"]["hospital"]
	if current_car: toggle_vehicle()
	var pw := focus_world(); var best: Dictionary = {}; var bd := 1e18
	for h in hospitals:
		var d := Vector2(float(h["x"]) - pw.x, float(h["z"]) - pw.z).length()
		if d < bd: bd = d; best = h
	var bill := 0
	if money: bill = money.fine(mini(500, 150 + int((money.cash + money.wallet) * 0.05)), "Hospital bill")
	if police and police.stars > 0:
		police.stars = 0; police.searching = false; police._release_units()
	if tod: tod.total_hours += 6.0; tod.apply_now()
	if not best.is_empty():
		var sp := Vector3(float(best["x"]), 0, float(best["z"]))
		streamer.load_now(sp)
		var y: float = services._ground_y(sp) if services else 0.0
		player.global_position = Vector3(sp.x, y + 1.0, sp.z) - world_offset
		player.velocity = Vector3.ZERO
		last_safe = player.global_position + world_offset
	needs.health = 100.0
	times_wasted += 1
	dying = false
	input_enabled = true
	if hud: hud.flash("You woke up in the hospital (%s) - medical bill $%d" % [{"fall": "bad fall", "crash": "car crash", "hit": "hit by a car", "drown": "nearly drowned", "shot": "gunshot wounds", "explosion": "caught in a blast", "fight": "beaten up"}.get(cause, cause), bill])

## people on foot get hit by traffic that can't stop in time
func _check_traffic_hits() -> void:
	if current_car or dying or traffic == null: return
	var pp: Vector3 = player.global_position + world_offset
	for c in traffic.cars:
		var v: float = float(c["v"])
		if v < 4.0: continue
		var d: Vector3 = c["pos"] - pp; d.y = 0
		if d.length() > float(c["len"]) * 0.5 + 0.6: continue
		var fwd := Vector3(-sin(float(c["yaw"])), 0, -cos(float(c["yaw"])))
		var lat: float = absf(d.cross(fwd).y)
		if lat > 1.25: continue
		if d.dot(fwd) > 0.0: continue       # the car is moving away from us
		hurt(v * 5.0, "hit")
		player.velocity = fwd * v * 0.8 + Vector3(0, 4.0, 0)
		c["v"] = v * 0.3
		break

var _park_fix_pending := true
var _fill: OmniLight3D
## after dark a soft light follows the player (camera side) so you're never a black silhouette
func _update_fill_light() -> void:
	if tod == null or player == null: return
	if _fill == null:
		_fill = OmniLight3D.new(); _fill.name = "PlayerFill"; _fill.omni_range = 5.0; _fill.shadow_enabled = false
		_fill.light_color = Color(0.85, 0.9, 1.0); _fill.light_specular = 0.1
		world.add_child(_fill)
	var target: Node3D = current_car if current_car else player
	var e: float = 0.9 * clampf(tod.night, 0.0, 1.0)
	_fill.visible = e > 0.02
	_fill.light_energy = e
	if camera and _fill.visible:
		var to_cam: Vector3 = camera.global_position - target.global_position; to_cam.y = 0
		_fill.global_position = target.global_position + to_cam.normalized() * 2.0 + Vector3(0, 2.2, 0)
## line the starting cars up in the parking lane of the nearest real street (once the road graph is in):
## centre-line + half the road width - 1.2 m, facing the way traffic flows on that side
func _park_at_curb() -> void:
	_park_fix_pending = false
	var used: Array = []
	for c in cars:
		if c == null or c.driven: continue
		var p: Vector3 = c.global_position + world_offset
		var best := -1; var bd := 1e9; var bq := Vector3.ZERO
		for k in traffic.edges.size():
			var e: Dictionary = traffic.edges[k]
			if e["cls"] > 6 or e["cls"] < 2: continue
			var a: Vector3 = traffic.npos[e["a"]]
			if Vector2(a.x - p.x, a.z - p.z).length() > float(e["len"]) + 60.0: continue
			var q := Geometry3D.get_closest_point_to_segment(p, a, traffic.npos[e["b"]])
			var dd := Vector2(q.x - p.x, q.z - p.z).length()
			if dd < bd: bd = dd; best = k; bq = q
		if best < 0 or bd > 40.0: continue
		var e2: Dictionary = traffic.edges[best]
		var dir: Vector3 = e2["dir"]; var right := dir.cross(Vector3.UP).normalized()
		var to := Vector3(p.x - bq.x, 0, p.z - bq.z)
		var sgn := 1.0 if to.dot(right) >= 0.0 else -1.0
		if e2["oneway"]: sgn = 1.0
		# clear of the outermost travel lane (so traffic isn't stuck behind it), at the curb where the road is wide enough
		var lw: float = float(traffic.T["driver"]["lane_width"])
		var outer: float = ((int(e2["lanes"]) - 1) * 0.5 * lw) if e2["oneway"] else ((maxi(1, int(e2["lanes"]) / 2) - 0.5) * lw)
		var q2: Vector3 = bq + right * sgn * maxf(float(e2["w"]) * 0.5 - 1.25, outer + lw * 0.5 + 1.15)
		for u in used:     # keep them a car length apart
			if Vector2(u.x - q2.x, u.z - q2.z).length() < 6.5: q2 += dir * 7.0
		used.append(q2)
		var fdir: Vector3 = dir * sgn
		var g := _ground_from(q2, 60.0)
		c.global_transform = Transform3D(Basis(Vector3.UP, atan2(-fdir.x, -fdir.z)), Vector3(q2.x, (g.y if g.y < 90.0 else 0.1), q2.z) - world_offset + Vector3(0, 0.6, 0))
	# your own car gets a clear run ahead (the others park behind it)
	var mine = cars[0] if not cars.is_empty() else null
	if mine == null or mine.driven: return
	var f0: Vector3 = -mine.global_transform.basis.z; f0.y = 0; f0 = f0.normalized()
	for c in cars:
		if c == mine or c.driven: continue
		var rel: Vector3 = c.global_position - mine.global_position
		var ahead := rel.dot(f0); var side := (rel - f0 * ahead).length()
		if ahead > -2.0 and ahead < 16.0 and side < 3.0:
			c.global_position -= f0 * (ahead + 9.0 + 8.0 * float(cars.find(c)))

## the demo cars at the curb become roster cars: the first one is yours (a beat-up used car), the rest are
## other people's parked cars (taking one is car theft if someone sees)
func _roster_start_cars() -> void:
	var ids := ["corvane_dutchess", "takumi_corsa", "halden_wayfarer", "hanzo_civet", "corvane_stockman"]
	var old := cars.duplicate()
	cars.clear()
	for i in old.size():
		var o = old[i]
		var col: Color = o.body_color
		var c = vehicles.make_car(ids[i % ids.size()], col, 720.0 if i == 0 else 1000.0)
		world.add_child(c)
		c.global_transform = o.global_transform
		cars.append(c)
		o.queue_free()
		if i == 0: vehicles.add_owned(c)

## the player shown in the driver's seat (head and shoulders through the windows)
func _seat_driver(c: Node, on: bool) -> void:
	var d: Node = c.get_node_or_null("Driver")
	if not on:
		if d: d.queue_free()
		return
	if d or player.get("_body") == null: return
	if player.get("rig"):
		var sr: Node3D = player.make_seated()
		sr.name = "Driver"
		var Hc: float = float(c.spec["size"][2]) if not c.spec.is_empty() else 1.45
		var Lc: float = float(c.spec["size"][0]) if not c.spec.is_empty() else 4.5
		sr.position = Vector3(-0.4, minf(0.15, Hc - 1.45) - 0.12, -Lc * 0.5 + Lc * (0.2 + 0.24))
		c.add_child(sr)
		return
	var mi := MeshInstance3D.new(); mi.name = "Driver"; mi.mesh = player.seated_mesh
	var H: float = float(c.spec["size"][2]) if not c.spec.is_empty() else 1.45
	var L: float = float(c.spec["size"][0]) if not c.spec.is_empty() else 4.5
	var cab0: float = 0.2
	mi.position = Vector3(-0.4, minf(0.32, H - 1.42) - 0.93 * 1.04 + 0.1, -L * 0.5 + L * (cab0 + 0.24))
	c.add_child(mi)

func toggle_vehicle() -> void:
	if current_car == null:
		var c := nearest_car()
		if c == null and vehicles: c = vehicles.try_carjack(player.global_position)
		if c == null:
			return
		if vehicles: vehicles.on_enter_car(c)
		current_car = c
		c.driven = true
		player.visible = false
		_seat_driver(c, true)
		player.process_mode = Node.PROCESS_MODE_DISABLED
		player.get_child(0).disabled = true
		cam_yaw = c.global_rotation.y
	else:
		var c := current_car
		_seat_driver(c, false)
		c.driven = false
		c.throttle = 0; c.steer_in = 0
		current_car = null
		var exit_pos := _free_exit_spot(c)
		var bail_speed: float = c.speed_mps()
		player.global_position = exit_pos
		player.velocity = Vector3.ZERO
		if bail_speed > 6.0:              # bailing out of a moving car: you tumble out and it hurts
			player.velocity = c.linear_velocity * 0.45
			hurt(bail_speed * 1.6, "crash")
		player.process_mode = Node.PROCESS_MODE_INHERIT
		player.get_child(0).disabled = false
		player.visible = true

## driver's door first, then the passenger side, then out over the roof - never into a wall or another car
func _free_exit_spot(c: Node3D) -> Vector3:
	var space := get_world_3d().direct_space_state
	var cap := CapsuleShape3D.new(); cap.radius = 0.35; cap.height = 1.7
	var q := PhysicsShapeQueryParameters3D.new(); q.shape = cap; q.collision_mask = 1 | 2
	q.exclude = [c.get_rid()]
	var bx: Vector3 = c.global_transform.basis.x
	for cand in [-bx * 2.0, bx * 2.1, -bx * 2.8, bx * 2.8, -c.global_transform.basis.z * 3.6, c.global_transform.basis.z * 3.6]:
		var p: Vector3 = c.global_position + cand + Vector3(0, 1.1, 0)
		q.transform = Transform3D(Basis(), p)
		if space.intersect_shape(q, 1).is_empty(): return p - Vector3(0, 0.55, 0)
	return c.global_position + Vector3(0, 2.2, 0)       # boxed in: climb out on top

# ------------------------------------------------------------------ loop
func focus_local() -> Vector3:
	return current_car.global_position if current_car else player.global_position

# ------------------------------------------------------------------ save section "player": you, and your cars
func get_save_data() -> Dictionary:
	var pp: Vector3 = (current_car.global_position if current_car else player.global_position) + world_offset
	return {"pos": [pp.x, pp.y, pp.z], "cam_yaw": cam_yaw, "driving": cars.find(current_car) if current_car else -1}

func apply_save_data(d: Dictionary) -> void:
	if current_car: return                       # never yank the player out of a moving car
	var pw := Vector3(d["pos"][0], d["pos"][1], d["pos"][2])
	streamer.load_now(pw)
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
	_check_traffic_hits()
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
	if bars.inside or (gunstore and gunstore.inside):
		pass
	elif f.y < minf(Terrain.height(f + world_offset), -1.6) - 2.2 and not cam_override:
		_respawn()
	else:
		safe_timer += dt
		if safe_timer > 1.0 and f.y > Terrain.height(f + world_offset) - 0.5 and (current_car == null or current_car.speed_mps() < 30):
			safe_timer = 0.0
			var on_ground := player.is_on_floor() if current_car == null else true
			if on_ground:
				last_safe = f + world_offset

func _respawn() -> void:
	hud.flash("You dragged yourself out of the water")
	if needs: needs.health = maxf(1.0, needs.health - 25.0)
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
	if _park_fix_pending and traffic and not traffic.edges.is_empty(): _park_at_curb()
	_update_fill_light()
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
		var vo = vehicles.view_offset(c) if vehicles else null
		if vo != null:
			camera.global_position = c.global_transform * (vo[0] as Vector3)
			camera.look_at(c.global_transform * (vo[1] as Vector3), c.global_transform.basis.y)
			camera.fov = lerp(camera.fov, 75.0 + clamp(spd * 0.3, 0.0, 12.0), 0.05)
			return
		var dist: float = (7.5 + spd * 0.06) * (vehicles.chase_distance_mult() if vehicles else 1.0)
		var target := c.global_position + Vector3(0, 1.6, 0)
		var back := Vector3(sin(cam_yaw), 0, cos(cam_yaw))
		var desired := target + back * dist * cos(-0.18) + Vector3(0, dist * sin(0.18) + 0.6, 0)
		var cq := PhysicsRayQueryParameters3D.create(target, desired)
		cq.exclude = [c.get_rid()]; cq.collision_mask = 1      # only the city, not passing traffic

		var ch := get_world_3d().direct_space_state.intersect_ray(cq)
		var blocked := not ch.is_empty()
		if blocked:
			desired = ch["position"] + (target - desired).normalized() * 0.4
		camera.global_position = desired if blocked else camera.global_position.lerp(desired, 1.0 - exp(-10.0 * dt))
		camera.look_at(target, Vector3.UP)
		camera.fov = lerp(camera.fov, base_fov + clamp(spd * 0.35, 0.0, 14.0), 0.05)
	else:
		# pivot follows the player with a little lag (smooth over steps and kerbs, no jitter)
		var raw := player.global_position + Vector3(0, 1.55, 0)
		if _cam_t == Vector3.ZERO or _cam_t.distance_to(raw) > 6.0: _cam_t = raw
		_cam_t.x = lerpf(_cam_t.x, raw.x, 1.0 - exp(-14.0 * dt)); _cam_t.z = lerpf(_cam_t.z, raw.z, 1.0 - exp(-14.0 * dt))
		_cam_t.y = lerpf(_cam_t.y, raw.y, 1.0 - exp(-7.0 * dt))
		var hv := Vector2(player.velocity.x, player.velocity.z).length()
		_cam_input_t += dt
		# auto-swing behind the player while running and not steering the camera with the mouse
		if hv > 2.0 and _cam_input_t > 1.2 and not (weapons != null and weapons.aiming):
			cam_yaw = lerp_angle(cam_yaw, player.model.rotation.y, 1.0 - exp(-1.2 * dt))
		_sprint_k = move_toward(_sprint_k, 1.0 if hv > 6.0 else 0.0, dt * 2.0)
		var dir := Vector3(sin(cam_yaw) * cos(cam_pitch), -sin(cam_pitch), cos(cam_yaw) * cos(cam_pitch))
		var aim: bool = weapons != null and weapons.aiming
		_aim_k = move_toward(_aim_k, 1.0 if aim else 0.0, dt * 6.0)
		var crouch_drop: float = 0.45 if weapons != null and weapons.crouch else 0.0
		var target := _cam_t
		# always a little over the right shoulder (more when aiming), like GTA V
		target += Vector3(cos(cam_yaw), 0, -sin(cam_yaw)) * lerpf(0.38, 0.75, _aim_k) - Vector3(0, crouch_drop, 0)
		var want_d: float = lerpf(cam_dist + _sprint_k * 0.6, 2.1, _aim_k)
		# keep the camera out of walls: snap in fast, ease back out slowly
		var q := PhysicsRayQueryParameters3D.create(target, target + dir * (want_d + 0.3))
		q.exclude = [player.get_rid()]; q.collision_mask = 1
		var hit := get_world_3d().direct_space_state.intersect_ray(q)
		var free_d: float = want_d if hit.is_empty() else maxf(0.6, target.distance_to(hit["position"]) - 0.35)
		_cam_d = free_d if free_d < _cam_d else lerpf(_cam_d, free_d, 1.0 - exp(-3.0 * dt))
		var desired := target + dir * _cam_d
		# a faint handheld sway when sprinting
		_cam_shake_t += dt * (1.0 + _sprint_k * 7.0)
		desired += Vector3(sin(_cam_shake_t * 1.7), sin(_cam_shake_t * 2.3) * 0.6, 0) * 0.025 * _sprint_k
		camera.global_position = desired
		camera.look_at(target, Vector3.UP)
		var zoom: float = 0.72 * (float(weapons._mods().get("zoom", 1.0)) if weapons else 1.0)
		camera.fov = lerp(camera.fov, lerpf(base_fov + _sprint_k * 6.0, base_fov * zoom, _aim_k), 0.15)

# ------------------------------------------------------------------ environment
## 32^3 colour-grading LUT: slight S-curve, warm highlights, faintly teal shadows, protected skin tones.
func _grade_lut() -> ImageTexture3D:
	var N := 32
	var imgs: Array[Image] = []
	for b in N:
		var im := Image.create(N, N, false, Image.FORMAT_RGB8)
		for g in N:
			for r in N:
				var c := Color(r / float(N - 1), g / float(N - 1), b / float(N - 1))
				var l := c.r * 0.2126 + c.g * 0.7152 + c.b * 0.0722
				var s := l * l * (3.0 - 2.0 * l)                       # S-curve on luminance
				var k := lerpf(1.0, (s + 0.002) / (l + 0.002), 0.35)
				var o := Color(c.r * k, c.g * k, c.b * k)
				var hi := clampf((l - 0.45) * 1.8, 0.0, 1.0); var lo := clampf((0.4 - l) * 2.2, 0.0, 1.0)
				o.r += 0.035 * hi - 0.015 * lo; o.g += 0.012 * hi + 0.004 * lo; o.b += -0.03 * hi + 0.022 * lo
				im.set_pixel(r, g, Color(clampf(o.r, 0, 1), clampf(o.g, 0, 1), clampf(o.b, 0, 1)))
		imgs.append(im)
	var t := ImageTexture3D.new()
	t.create(Image.FORMAT_RGB8, N, N, N, false, imgs)
	return t

func _setup_environment() -> void:
	env = Environment.new()
	var sky := Sky.new()
	var sm := ShaderMaterial.new()                  # shaders/sky.gdshader: atmosphere, sunlit clouds, stars (time_of_day drives it)
	sm.shader = load("res://shaders/sky.gdshader")
	sky.sky_material = sm
	sky.process_mode = Sky.PROCESS_MODE_INCREMENTAL # clouds drift; the lighting probe catches up over a few frames
	sky.radiance_size = Sky.RADIANCE_SIZE_128
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.9
	env.tonemap_mode = Environment.TONE_MAPPER_ACES
	env.tonemap_white = 6.0
	# screen-space reflections: glass towers, wet streets and car paint pick up the city around them
	env.ssr_enabled = true; env.ssr_max_steps = 48; env.ssr_fade_in = 0.15; env.ssr_fade_out = 2.0; env.ssr_depth_tolerance = 0.3
	env.fog_enabled = true
	env.fog_light_color = Color(0.72, 0.76, 0.82)
	env.fog_density = 0.00022
	env.fog_sky_affect = 0.15
	env.ssao_enabled = true
	env.ssao_radius = 1.4; env.ssao_intensity = 1.9; env.ssao_detail = 0.7; env.ssao_light_affect = 0.15
	# screen-space indirect light: sunlit walls and lawns bounce colour into shade (no more flat grey shadows)
	env.ssil_enabled = true; env.ssil_radius = 6.0; env.ssil_intensity = 1.1; env.ssil_sharpness = 0.98
	env.glow_enabled = true
	env.glow_intensity = 0.35
	env.glow_bloom = 0.05
	env.glow_hdr_threshold = 1.1
	# colour grade: a touch more contrast and saturation (the photo-based ground reads flat otherwise)
	env.adjustment_enabled = true
	env.adjustment_contrast = 1.04
	env.adjustment_saturation = 1.05
	env.adjustment_color_correction = _grade_lut()        # filmic warm-highlights / cool-shadows grade (GTA-style)
	if Look.bully():
		# Bully look (2026-11-21): bright, clean, saturated sunny afternoon with clear (not harsh) shadows and a gentle
		# bloom. Lighting and grade only; the painted surfaces are in textures_bully/.
		env.tonemap_mode = Environment.TONE_MAPPER_ACES; env.tonemap_white = 6.0; env.tonemap_exposure = 1.08
		env.adjustment_contrast = 1.06; env.adjustment_saturation = 1.06
		env.glow_intensity = 0.4; env.glow_bloom = 0.06; env.glow_hdr_threshold = 1.0
		env.ssao_intensity = 1.5; env.ssil_intensity = 1.2
		env.fog_density = 0.00012
	var we := WorldEnvironment.new(); we.environment = env; add_child(we)
	var sun := DirectionalLight3D.new()
	sun.name = "Sun"
	sun.rotation_degrees = Vector3(-42, -35, 0)
	sun.light_energy = 1.25
	sun.light_color = Color(1.0, 0.95, 0.86)
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 420.0
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
	sun.directional_shadow_split_1 = 0.06; sun.directional_shadow_split_2 = 0.16; sun.directional_shadow_split_3 = 0.4
	sun.directional_shadow_blend_splits = true
	sun.light_angular_distance = 0.6        # the sun's real size: shadows soften with distance from the caster
	if Look.bully(): sun.light_angular_distance = 0.9     # Bully: softer shadow edges (PCSS cost grows fast with size)
	sun.shadow_bias = 0.03; sun.shadow_normal_bias = 1.2
	add_child(sun)
