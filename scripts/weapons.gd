extends Node
## Weapons (Bible section 14: arcade aiming comparable to GTA V; fictional game stats only - source_data/weapons.json).
##   1 fists  2 melee (bat / knife)  3 pistol  4 shotgun  5 rifle  6 grenades      R reload      C crouch (cover)
##   Hold right mouse to aim (over-the-shoulder, crosshair, soft lock-on to people near the crosshair); left mouse fires
##   (hip fire without aiming is much less accurate). Grenades: aim and click to throw (arc), they go off after a fuse.
##   Melee weapons swing through combat.gd (more damage and reach). Gun stores (E at the sign) sell guns and ammo.
## Shots are hitscan from the camera through the crosshair (with spread) - people (capsule test), cars (damage), the
## city (impact). People shot go down injured (an ambulance comes); everyone nearby panics; police treat gunfire as
## serious (police.json shots_fired / shoot_ped / shoot_police / explosion) and armed officers get out of their cars.
## Cover: crouch behind a car or a wall - shooters need a clear line to your chest, which sits lower when crouched.

var main: Node
var W: Dictionary
var owned := {"fists": true}
var ammo := {}                 # ammo type -> rounds in reserve
var mag := {}                  # weapon id -> rounds loaded
var current := "fists"
var melee_pick := ""           # which melee weapon is in slot 2
var aiming := false
var crouch := false
var _fire_held := false
var _cool := 0.0
var _reload_t := 0.0
var shots_fired := 0
var hits := 0
var _store_signs := {}
var _sign_t := 0.0
var shop_open := false
var _shop_rows: Array = []
var _overlay: Label
var _gun_node: Node3D
var rng := RandomNumberGenerator.new()
var _shot_sound: AudioStreamWAV
var _players: Array = []
var _boom_sound: AudioStreamWAV
var grenades_live: Array = []
var hit_marker := 0.0
const Signs := preload("res://scripts/signs.gd")

func _ready() -> void:
	rng.randomize()
	W = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/weapons.json"))
	for k in W["weapons"]: if W["weapons"][k]["type"] == "gun": mag[k] = 0
	_overlay = main.hud.overlay_label() if main.hud and main.hud.has_method("overlay_label") else Label.new()
	_overlay.visible = false
	_shot_sound = _make_shot(0.32, 1.0); _boom_sound = _make_shot(1.4, 0.35)
	for i in 6:
		var p := AudioStreamPlayer3D.new(); p.max_distance = 400.0; p.unit_size = 12.0; p.bus = "Master"
		main.world.add_child(p); _players.append(p)

func def(id: String) -> Dictionary: return W["weapons"].get(id, {})
func kind() -> String: return def(current).get("type", "fists")
func armed_gun() -> bool: return kind() == "gun" or kind() == "throw"

# ------------------------------------------------------------------ owning things
func give(id: String, with_ammo := true) -> void:
	owned[id] = true
	var d := def(id)
	if d.get("type", "") == "melee": melee_pick = id
	if with_ammo and d.has("ammo"):
		var a: String = d["ammo"]
		ammo[a] = int(ammo.get(a, 0)) + int(W["start_ammo"].get(a, 2 if a == "grenade" else 0))
		if d["type"] == "gun": _load(id)
	if main.inventory: main.inventory.items["weapons"][d.get("name", id)] = 1

func select_slot(slot: int) -> void:
	for id in owned:
		if int(def(id).get("slot", 0)) == slot and (slot != 2 or id == melee_pick or melee_pick == ""):
			equip(id); return
	if slot == 1: equip("fists")

func equip(id: String) -> void:
	if not owned.has(id): return
	current = id; _reload_t = 0.0
	if kind() != "gun" and kind() != "throw": aiming = false
	_update_gun_mesh()
	if main.hud: main.hud.flash(def(id)["name"])

func _load(id: String) -> void:
	var d := def(id)
	var a: String = d["ammo"]
	var need: int = int(d["mag"]) - int(mag.get(id, 0))
	var got: int = mini(need, int(ammo.get(a, 0)))
	mag[id] = int(mag.get(id, 0)) + got; ammo[a] = int(ammo.get(a, 0)) - got

func reload() -> void:
	if kind() != "gun" or _reload_t > 0.0: return
	var d := def(current)
	if int(mag[current]) >= int(d["mag"]) or int(ammo.get(d["ammo"], 0)) <= 0: return
	_reload_t = float(d["reload_s"])

func ammo_line() -> String:
	var d := def(current)
	match kind():
		"gun": return "%s  %d / %d%s" % [d["name"].to_upper(), int(mag[current]), int(ammo.get(d["ammo"], 0)), "  RELOADING" if _reload_t > 0.0 else ""]
		"throw": return "%s  x%d" % [d["name"].to_upper(), int(ammo.get("grenade", 0))]
		"melee": return d["name"].to_upper()
	return ""

# ------------------------------------------------------------------ input
func _unhandled_input(e: InputEvent) -> void:
	if shop_open and e is InputEventKey and e.pressed and not e.echo:
		_shop_key(e.physical_keycode); get_viewport().set_input_as_handled(); return
	if not _can_use(): return
	if e is InputEventKey and e.pressed and not e.echo:
		var k: int = e.physical_keycode
		if k >= KEY_1 and k <= KEY_6 and not (main.get("phone") and main.phone.photo_mode):
			select_slot(k - KEY_0); get_viewport().set_input_as_handled()
		elif k == KEY_R and kind() == "gun": reload()
		elif k == KEY_C: set_crouch(not crouch)
		elif k == KEY_E and _store_near() >= 0: open_shop(_store_near()); get_viewport().set_input_as_handled()
	if e is InputEventMouseButton and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED and armed_gun():
		if e.button_index == MOUSE_BUTTON_RIGHT: aiming = e.pressed; get_viewport().set_input_as_handled()
		elif e.button_index == MOUSE_BUTTON_LEFT:
			_fire_held = e.pressed
			if e.pressed: trigger()
			get_viewport().set_input_as_handled()

func _can_use() -> bool:
	return main.current_car == null and not main.dying and main.input_enabled and not (main.bars and main.bars.inside) \
		and not (main.get("phone") and main.phone.open) and (main.combat == null or main.combat.pstate == "")

func set_crouch(on: bool) -> void:
	crouch = on
	main.player.model.scale = Vector3(1, 0.68 if on else 1.0, 1)
	main.player.crouch_mult = 0.45 if on else 1.0

# ------------------------------------------------------------------ firing
## pull the trigger once (guns) / throw (grenade). Returns true if something was fired.
func trigger() -> bool:
	if _cool > 0.0 or _reload_t > 0.0: return false
	var d := def(current)
	if kind() == "throw":
		if int(ammo.get("grenade", 0)) <= 0: return false
		ammo["grenade"] = int(ammo["grenade"]) - 1
		_throw_grenade(); _cool = 0.9
		return true
	if kind() != "gun": return false
	if int(mag[current]) <= 0:
		reload(); return false
	mag[current] = int(mag[current]) - 1
	_cool = 1.0 / float(d["rate"])
	shots_fired += 1
	var spread: float = float(d["spread"] if aiming else d["hip_spread"]) * (1.6 if main.player.velocity.length() > 3.0 else 1.0) * (0.7 if crouch else 1.0)
	var origin: Vector3 = main.camera.global_position
	var fwd: Vector3 = -main.camera.global_transform.basis.z
	var assist = _assist_target(origin, fwd, float(d["range"])) if aiming else null
	if assist != null: fwd = (assist - origin).normalized()
	for pellet in int(d.get("pellets", 1)):
		var dir := _spread_dir(fwd, spread)
		_shoot_ray(origin, dir, float(d["range"]), float(d["dmg"]))
	_muzzle()
	_sound(_shot_sound, _gun_tip(), 0.0)
	# gunfire: everyone nearby panics; police care
	var me: Vector3 = main.player.global_position + main.world_offset
	if main.peds:
		for p in main.peds.peds:
			if p["state"] in ["walk", "wait", "cross", "fight"] and not p.get("cop", false) and (p["pos"] - me).length() < float(d.get("loud", 60)):
				if p["state"] == "fight" and p.get("gun", "") != "": continue
				main.peds._flee(p, me)
	if main.police: main.police.report("shots_fired", me)
	if int(mag[current]) <= 0: reload()
	return true

func _spread_dir(fwd: Vector3, deg: float) -> Vector3:
	var r := deg_to_rad(deg) * sqrt(rng.randf())
	var a := rng.randf() * TAU
	var side := fwd.cross(Vector3.UP).normalized()
	if side == Vector3.ZERO: side = Vector3.RIGHT
	var up := side.cross(fwd).normalized()
	return (fwd + (side * cos(a) + up * sin(a)) * tan(r)).normalized()

## soft lock: the person (chest) closest to the crosshair within a few degrees
func _assist_target(origin: Vector3, fwd: Vector3, rng_m: float):
	if main.peds == null: return null
	var best = null; var ba := deg_to_rad(float(W["aim_assist_deg"]))
	for p in main.peds.peds:
		if p["state"] in ["fly", "down", "injured"]: continue
		var chest: Vector3 = Vector3(p["pos"].x, float(p["y"]) + 1.25, p["pos"].z) - main.world_offset
		var to := chest - origin
		if to.length() > rng_m: continue
		var a := fwd.angle_to(to)
		if a < ba: ba = a; best = chest
	return best

func _shoot_ray(origin: Vector3, dir: Vector3, range_m: float, dmg: float) -> void:
	var space: PhysicsDirectSpaceState3D = main.get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(origin, origin + dir * range_m, 1 | 2)
	q.exclude = [main.player.get_rid()]
	var hit: Dictionary = space.intersect_ray(q)
	var wall_d: float = (hit["position"] - origin).length() if not hit.is_empty() else range_m
	# people: ray vs a capsule from their feet to the top of the head
	var best = null; var bd := wall_d; var head := false
	if main.peds:
		for p in main.peds.peds:
			if p["state"] == "fly": continue
			var lying: bool = p["state"] in ["down", "injured"]
			var base: Vector3 = Vector3(p["pos"].x, float(p["y"]), p["pos"].z) - main.world_offset
			var top: Vector3 = base + (Vector3(0, 0.35, 0) if lying else Vector3(0, 1.8, 0))
			if (base - origin).length() > range_m + 2.0: continue
			var r: Array = _ray_seg(origin, dir, base, top)
			if r[1] < (0.45 if lying else 0.32) and r[0] > 0.3 and r[0] < bd:
				bd = r[0]; best = p; head = (r[2] > 0.86) and not lying
	var end: Vector3 = origin + dir * bd
	_tracer(_gun_tip(), end)
	if best != null:
		hits += 1; hit_marker = 0.25
		_hit_person(best, dmg * (float(W["headshot_mult"]) if head else 1.0), dir)
		_impact(end, Color(0.45, 0.05, 0.04))
		return
	if not hit.is_empty():
		var col = hit["collider"]
		if col is VehicleBody3D and col.has_method("damage"): col.damage(dmg * 3.0)
		_impact(hit["position"], Color(0.6, 0.58, 0.52))

## closest approach between a ray and a segment: [distance along ray, gap, fraction along segment]
func _ray_seg(o: Vector3, d: Vector3, a: Vector3, b: Vector3) -> Array:
	var u := b - a
	var w0 := o - a
	var aa := d.dot(d); var bb := d.dot(u); var cc := u.dot(u); var dd := d.dot(w0); var ee := u.dot(w0)
	var den := aa * cc - bb * bb
	var sc := 0.0; var tc := 0.0
	if den > 1e-6:
		sc = (bb * ee - cc * dd) / den; tc = (aa * ee - bb * dd) / den
	tc = clampf(tc, 0.0, 1.0)
	sc = maxf(0.0, d.dot((a + u * tc) - o) / aa)
	var gap := ((o + d * sc) - (a + u * tc)).length()
	return [sc, gap, tc]

func _hit_person(p: Dictionary, dmg: float, dir: Vector3) -> void:
	var cb = main.combat
	if cb: cb.ped_hp(p)
	p["hp"] = float(p.get("hp", 100.0)) - dmg
	p["react_t"] = 0.35
	var me: Vector3 = main.player.global_position + main.world_offset
	if main.police: main.police.report("shoot_police" if p.get("cop", false) else "shoot_ped", p["pos"], true)
	if float(p["hp"]) <= 0.0 and not (p["state"] in ["down", "injured"]):
		main.peds.knock_down(p, dir * 2.5)
		p["hit_speed"] = 99.0                    # stays down: an ambulance comes
		if cb and cb.target == p: cb.target = null
	elif p["state"] in ["walk", "wait", "cross"]:
		main.peds._flee(p, me)

# ------------------------------------------------------------------ grenades
func _throw_grenade() -> void:
	var g := RigidBody3D.new(); g.mass = 0.4
	var cs := CollisionShape3D.new(); var sh := SphereShape3D.new(); sh.radius = 0.07; cs.shape = sh; g.add_child(cs)
	var mi := MeshInstance3D.new(); var sm := SphereMesh.new(); sm.radius = 0.07; sm.height = 0.14; mi.mesh = sm
	var m := StandardMaterial3D.new(); m.albedo_color = Color(0.2, 0.25, 0.15); mi.material_override = m; g.add_child(mi)
	main.world.add_child(g)
	g.global_position = main.player.global_position + Vector3(0, 1.7, 0) - main.camera.global_transform.basis.z * 0.6
	var f: Vector3 = -main.camera.global_transform.basis.z
	g.linear_velocity = f * 15.0 + Vector3(0, 4.5, 0)
	grenades_live.append({"node": g, "t": float(def("grenade")["fuse_s"])})

func _explode(at_local: Vector3) -> void:
	var d := def("grenade")
	var R: float = float(d["radius"]); var dmg: float = float(d["dmg"])
	var at_w: Vector3 = at_local + main.world_offset
	if main.peds:
		for p in main.peds.peds.duplicate():
			var to: Vector3 = p["pos"] - at_w; var dist := to.length()
			if dist > R: continue
			var k := 1.0 - dist / R
			_hit_person(p, dmg * k, to.normalized())
			if p["state"] != "fly": main.peds.knock_down(p, to.normalized() * 10.0 * k + Vector3(0, 4, 0))
	for c in main.cars:
		if is_instance_valid(c) and c.global_position.distance_to(at_local) < R * 1.4:
			c.damage(dmg * 6.0)
			c.apply_central_impulse((c.global_position - at_local).normalized() * 4000.0 + Vector3(0, 3000, 0))
	var pd: float = (main.player.global_position + Vector3(0, 1, 0)).distance_to(at_local)
	if pd < R: main.hurt(dmg * (1.0 - pd / R), "explosion")
	_boom(at_local)
	if main.police: main.police.report("explosion", at_w, true)
	if main.peds:
		for p in main.peds.peds:
			if p["state"] in ["walk", "wait", "cross"] and (p["pos"] - at_w).length() < 80.0: main.peds._flee(p, at_w)

# ------------------------------------------------------------------ per frame
func _physics_process(dt: float) -> void:
	_cool = maxf(0.0, _cool - dt)
	hit_marker = maxf(0.0, hit_marker - dt)
	if _reload_t > 0.0:
		_reload_t -= dt
		if _reload_t <= 0.0: _load(current)
	if _fire_held and kind() == "gun" and bool(def(current).get("auto", false)) and _can_use(): trigger()
	if not _can_use(): aiming = aiming and main.current_car == null
	if main.current_car != null and crouch: set_crouch(false)
	# while aiming you face where you aim and move slower
	if aiming and main.player:
		main.player.model.rotation.y = lerp_angle(main.player.model.rotation.y, main.cam_yaw, 1.0 - exp(-20.0 * dt))
		main.player.aim_mult = 0.55
	elif main.player:
		main.player.aim_mult = 1.0
	_pose()
	if _gun_node and is_instance_valid(_gun_node):
		# carried low in the right hand; up at the shoulder / out at arm's length when aiming or firing
		var up: bool = aiming or _cool > 0.0
		var want: Vector3 = Vector3(0.27, 0.86, -0.12)
		if up: want = Vector3(0.14, 1.36, -0.45) if current != "pistol" else Vector3(0.24, 1.38, -0.66)
		_gun_node.position = _gun_node.position.lerp(want, 1.0 - exp(-20.0 * dt))
	for g in grenades_live.duplicate():
		g["t"] = float(g["t"]) - dt
		if g["t"] <= 0.0:
			if is_instance_valid(g["node"]):
				_explode(g["node"].global_position); g["node"].queue_free()
			grenades_live.erase(g)
	_sign_t -= dt
	if _sign_t <= 0.0: _sign_t = 2.0; _update_store_signs()
	if shop_open and _store_near() < 0: close_shop()

func _pose() -> void:
	var body: MeshInstance3D = main.player.get("_body") if main.player else null
	if body == null or main.combat == null or main.combat.busy(): return
	if armed_gun() and (aiming or _cool > 0.0):
		body.set_instance_shader_parameter("act", 14.0 if current != "pistol" else 15.0)
		body.set_instance_shader_parameter("act_t", 0.5)
	elif not main.combat.guard:
		body.set_instance_shader_parameter("act", 0.0)

# ------------------------------------------------------------------ visuals and sound
func _update_gun_mesh() -> void:
	if _gun_node: _gun_node.queue_free(); _gun_node = null
	if current == "fists" or main.player == null: return
	_gun_node = Node3D.new(); _gun_node.name = "Weapon"
	var dark := StandardMaterial3D.new(); dark.albedo_color = Color(0.08, 0.08, 0.09); dark.metallic = 0.6; dark.roughness = 0.4
	var wood := StandardMaterial3D.new(); wood.albedo_color = Color(0.45, 0.28, 0.14)
	var steel := StandardMaterial3D.new(); steel.albedo_color = Color(0.7, 0.7, 0.72); steel.metallic = 0.9; steel.roughness = 0.25
	var parts: Array = []
	match current:
		"pistol": parts = [[Vector3(0.04, 0.05, 0.2), Vector3(0, 0.02, -0.08), dark], [Vector3(0.035, 0.11, 0.05), Vector3(0, -0.04, 0.0), dark]]
		"shotgun": parts = [[Vector3(0.05, 0.06, 0.75), Vector3(0, 0.02, -0.3), dark], [Vector3(0.05, 0.1, 0.28), Vector3(0, -0.02, 0.2), wood], [Vector3(0.045, 0.045, 0.2), Vector3(0, -0.03, -0.35), wood]]
		"rifle": parts = [[Vector3(0.05, 0.08, 0.7), Vector3(0, 0.02, -0.25), dark], [Vector3(0.04, 0.14, 0.05), Vector3(0, -0.07, -0.1), dark], [Vector3(0.05, 0.09, 0.22), Vector3(0, 0.0, 0.2), dark]]
		"bat": parts = [[Vector3(0.06, 0.06, 0.85), Vector3(0, 0.0, -0.4), wood]]
		"knife": parts = [[Vector3(0.02, 0.03, 0.12), Vector3(0, 0.0, 0.0), dark], [Vector3(0.01, 0.025, 0.12), Vector3(0, 0.0, -0.12), steel]]
		"grenade": parts = [[Vector3(0.07, 0.09, 0.07), Vector3(0, 0, 0), dark]]
	for pt in parts:
		var mi := MeshInstance3D.new(); var bm := BoxMesh.new(); bm.size = pt[0]; mi.mesh = bm; mi.position = pt[1]; mi.material_override = pt[2]
		_gun_node.add_child(mi)
	_gun_node.position = Vector3(0.27, 0.86, -0.12)      # right hand, held low
	main.player.model.add_child(_gun_node)

func _gun_tip() -> Vector3:
	var pl = main.player
	var fwd := Vector3(-sin(pl.model.rotation.y), 0, -cos(pl.model.rotation.y))
	return pl.global_position + Vector3(0, 1.38, 0) + fwd * 0.85 + fwd.cross(Vector3.UP) * 0.16

func _muzzle() -> void:
	_muzzle_at(_gun_tip())

func _muzzle_at(at: Vector3) -> void:
	var l := OmniLight3D.new(); l.light_color = Color(1.0, 0.8, 0.45); l.light_energy = 3.0; l.omni_range = 6.0
	main.world.add_child(l); l.global_position = at
	get_tree().create_timer(0.05).timeout.connect(l.queue_free)

func _tracer(a: Vector3, b: Vector3) -> void:
	var mi := MeshInstance3D.new(); var im := ImmediateMesh.new(); mi.mesh = im
	var m := StandardMaterial3D.new(); m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED; m.albedo_color = Color(1.0, 0.9, 0.6, 0.7)
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	im.surface_begin(Mesh.PRIMITIVE_LINES, m); im.surface_add_vertex(a); im.surface_add_vertex(b); im.surface_end()
	main.world.add_child(mi)
	get_tree().create_timer(0.06).timeout.connect(mi.queue_free)

func _impact(at: Vector3, col: Color) -> void:
	var pp := CPUParticles3D.new(); pp.one_shot = true; pp.amount = 10; pp.lifetime = 0.45; pp.explosiveness = 1.0
	pp.direction = Vector3(0, 1, 0); pp.spread = 70.0; pp.initial_velocity_min = 1.0; pp.initial_velocity_max = 3.5; pp.gravity = Vector3(0, -6, 0)
	var sm := SphereMesh.new(); sm.radius = 0.03; sm.height = 0.06; pp.mesh = sm
	var m := StandardMaterial3D.new(); m.albedo_color = col; sm.material = m
	main.world.add_child(pp); pp.global_position = at; pp.emitting = true
	get_tree().create_timer(1.0).timeout.connect(pp.queue_free)

func _boom(at: Vector3) -> void:
	var l := OmniLight3D.new(); l.light_color = Color(1.0, 0.6, 0.25); l.light_energy = 12.0; l.omni_range = 22.0
	main.world.add_child(l); l.global_position = at + Vector3(0, 1, 0)
	get_tree().create_timer(0.25).timeout.connect(l.queue_free)
	var pp := CPUParticles3D.new(); pp.one_shot = true; pp.amount = 40; pp.lifetime = 1.4; pp.explosiveness = 1.0
	pp.direction = Vector3(0, 1, 0); pp.spread = 180.0; pp.initial_velocity_min = 3.0; pp.initial_velocity_max = 9.0; pp.gravity = Vector3(0, -3, 0)
	pp.scale_amount_min = 0.6; pp.scale_amount_max = 1.6
	var sm := SphereMesh.new(); sm.radius = 0.35; sm.height = 0.7; pp.mesh = sm
	var m := StandardMaterial3D.new(); m.albedo_color = Color(0.25, 0.23, 0.22); m.emission_enabled = true; m.emission = Color(1.0, 0.45, 0.1); m.emission_energy_multiplier = 1.5
	sm.material = m
	main.world.add_child(pp); pp.global_position = at; pp.emitting = true
	get_tree().create_timer(2.0).timeout.connect(pp.queue_free)
	_sound(_boom_sound, at, 6.0)

func _sound(s: AudioStream, at: Vector3, db: float) -> void:
	if main.audio and main.audio.get("muted"): return
	for p in _players:
		if not p.playing:
			p.stream = s; p.volume_db = db; p.global_position = at; p.play(); return

## a gunshot / blast: noise burst with a sharp attack and a low thump, built once in code
func _make_shot(length_s: float, brightness: float) -> AudioStreamWAV:
	var rate := 22050; var n := int(rate * length_s)
	var data := PackedByteArray(); data.resize(n * 2)
	var lp := 0.0; var r := RandomNumberGenerator.new(); r.seed = 7
	for i in n:
		var t := float(i) / rate
		var env := exp(-t * (14.0 if brightness > 0.5 else 3.0))
		lp += (r.randf_range(-1.0, 1.0) - lp) * (0.6 * brightness + 0.05)
		var thump := sin(TAU * 55.0 * t) * exp(-t * 9.0) * 0.6
		var v := clampf((lp * 1.4 + thump) * env, -1.0, 1.0)
		data.encode_s16(i * 2, int(v * 30000))
	var w := AudioStreamWAV.new(); w.format = AudioStreamWAV.FORMAT_16_BITS; w.mix_rate = rate; w.data = data
	return w

# ------------------------------------------------------------------ gun stores
func _update_store_signs() -> void:
	if main.jobs == null or main.traffic == null or main.traffic.edges.is_empty(): return
	var f: Vector3 = main.focus_world()
	for s in W["stores"]:
		var id: int = int(s["id"])
		var near: bool = Vector2(float(s["x"]) - f.x, float(s["z"]) - f.z).length() < 260.0
		if near and not _store_signs.has(id):
			var c: Dictionary = main.jobs._curb(Vector3(float(s["x"]), 0, float(s["z"])))
			if c.is_empty(): continue
			var sg: Node3D = Signs.make("GUN STORE", s["name"], "Guns · ammo · E to shop", Color(0.75, 0.15, 0.12), 2.6)
			main.world.add_child(sg)
			var y: float = main.services._ground_y(c["pos"]) if main.services else 0.0
			sg.global_position = Vector3(c["pos"].x, y, c["pos"].z) - main.world_offset
			sg.look_at(sg.global_position - c["face"], Vector3.UP)
			_store_signs[id] = sg
		elif not near and _store_signs.has(id):
			_store_signs[id].queue_free(); _store_signs.erase(id)

func _store_near() -> int:
	if main.player == null: return -1
	for id in _store_signs:
		var n: Node3D = _store_signs[id]
		if is_instance_valid(n) and n.global_position.distance_to(main.player.global_position) < 3.0: return id
	return -1

func prompt(local_pos: Vector3) -> String:
	if _store_near() >= 0 and not shop_open: return "Press E to shop at the gun store"
	return ""

func open_shop(id: int) -> void:
	shop_open = true; _shop_rows = []
	for wid in W["weapons"]:
		var d: Dictionary = W["weapons"][wid]
		if int(d["price"]) > 0: _shop_rows.append(["weapon", wid, d["name"], int(d["price"])])
	for a in W["ammo"]:
		if a == "grenade": continue
		_shop_rows.append(["ammo", a, W["ammo"][a]["name"], int(W["ammo"][a]["price"])])
	_refresh_shop()

func close_shop() -> void:
	shop_open = false; _overlay.visible = false

func _refresh_shop() -> void:
	var lines := ["GUN STORE  ·  number key to buy  ·  Esc / E to leave"]
	for i in _shop_rows.size():
		var r: Array = _shop_rows[i]
		var have: String = ""
		if r[0] == "weapon" and owned.has(r[1]) and r[1] != "grenade": have = "  (owned)"
		lines.append("%d  %s  $%d%s" % [(i + 1) % 10, r[2], r[3], have])
	_overlay.text = "\n".join(lines); _overlay.visible = true

func _shop_key(k: int) -> void:
	if k == KEY_ESCAPE or k == KEY_E: close_shop(); return
	var i := -1
	if k >= KEY_1 and k <= KEY_9: i = k - KEY_1
	elif k == KEY_0: i = 9
	if i < 0 or i >= _shop_rows.size(): return
	buy(i)

func buy(i: int) -> bool:
	var r: Array = _shop_rows[i]
	if r[0] == "weapon" and owned.has(r[1]) and r[1] != "grenade":
		if main.hud: main.hud.flash("You already have a %s" % r[2])
		return false
	if not main.money.spend(int(r[3]), "Gun store: " + r[2]):
		if main.hud: main.hud.flash("Not enough money")
		return false
	if r[0] == "weapon":
		if r[1] == "grenade": owned["grenade"] = true; ammo["grenade"] = int(ammo.get("grenade", 0)) + 1
		else: give(r[1])
	else:
		ammo[r[1]] = int(ammo.get(r[1], 0)) + int(W["ammo"][r[1]]["box"])
	if main.hud: main.hud.flash("Bought %s" % r[2])
	_refresh_shop()
	return true

func get_save_data() -> Dictionary:
	return {"owned": owned.keys(), "ammo": ammo, "mag": mag, "current": current, "melee": melee_pick}

func apply_save_data(d: Dictionary) -> void:
	owned = {"fists": true}
	for k in d.get("owned", []): owned[k] = true
	ammo = d.get("ammo", {}); melee_pick = d.get("melee", "")
	for k in d.get("mag", {}): mag[k] = int(d["mag"][k])
	var cur: String = d.get("current", "fists")
	equip(cur if owned.has(cur) else "fists")
