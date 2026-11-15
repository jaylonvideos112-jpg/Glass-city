extends Node
## Vehicles (Bible section 8): the roster (source_data/vehicles.json), owning cars, buying them, stealing them,
## damage repair and upgrades, and driving camera views.
##   * Owned cars are saved (model, paint, damage, upgrades, where you left them or "garage"). You start with one
##     beat-up used car. Owned cars are placed back in the world when you're near where you parked them.
##   * Dealerships (41, source_data/dealers.json): new-car dealers sell any civilian model at list price; used lots
##     offer a few cheaper cars in worse condition, changing every day. K at the sign opens the catalogue; 1-9 buys;
##     the car is waiting at the curb.
##   * Stealing: E next to an AI car that's stopped or crawling pulls the driver out and takes it (a crime if a cop
##     or a bystander sees it). Unowned parked cars can be taken too. Stolen cars can be kept: drive one into your
##     garage and it's yours.
##   * Auto shops (the auto_shop workplaces): P repair, C repaint, U upgrade (engine, brakes, suspension, 3 levels).
##   * V cycles the driving camera: chase, far chase, hood, bumper, cockpit.

const Car := preload("res://scripts/car.gd")
var main: Node
var V: Dictionary
var roster := {}              # id -> model entry
var owned: Array = []         # [{spec, color, health, upgrades, where: "street"|"garage", pos:[x,y,z], yaw}]
var dealers: Array = []
var catalogue: Array = []     # offers shown [{spec, color, price, health}]
var cat_open := false
var _cat_dealer := -1
var _cat_label: Label
var _signs := {}
var _sign_t := 0.0
var rng := RandomNumberGenerator.new()
var cam_view := 0
const VIEWS := ["chase", "far chase", "hood", "bumper", "cockpit"]

func _ready() -> void:
	V = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/vehicles.json"))
	for m in V["models"]: roster[m["id"]] = m
	dealers = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/dealers.json"))["dealers"]
	rng.seed = 808
	_cat_label = Label.new(); _cat_label.position = Vector2(30, 140); _cat_label.visible = false
	_cat_label.add_theme_font_size_override("font_size", 20)
	_cat_label.add_theme_color_override("font_outline_color", Color.BLACK); _cat_label.add_theme_constant_override("outline_size", 6)
	if main.hud: main.hud.add_child(_cat_label)

func spec(id: String) -> Dictionary:
	return roster.get(id, roster.values()[0])

## a drivable car of a roster model (not yet in the tree)
func make_car(id: String, color: Color, health := 1000.0, upgrades := {}) -> Node:
	var c := Car.new()
	c.spec = spec(id); c.spec_id = id; c.body_color = color; c.health = health
	if not upgrades.is_empty(): c.upgrades = upgrades.duplicate()
	if main.traffic: c.body_mesh = main.traffic.vehicle_mesh(main.traffic._type(id), color)
	return c

func spawn_car(id: String, color: Color, world_pos: Vector3, yaw: float, health := 1000.0, upgrades := {}) -> Node:
	var c := make_car(id, color, health, upgrades)
	main.world.add_child(c)
	c.global_transform = Transform3D(Basis(Vector3.UP, yaw), world_pos - main.world_offset + Vector3(0, 0.6, 0))
	main.cars.append(c)
	return c

# ------------------------------------------------------------------ ownership
func add_owned(c: Node) -> int:
	if c.owned_index >= 0: return c.owned_index
	owned.append({"spec": c.spec_id, "color": c.body_color.to_html(false), "health": c.health, "upgrades": c.upgrades.duplicate(),
		"where": "street", "pos": [0, 0, 0], "yaw": 0.0})
	c.owned_index = owned.size() - 1
	c.stolen = false
	return c.owned_index

func _sync_owned() -> void:
	for c in main.cars:
		if not is_instance_valid(c) or c.owned_index < 0 or c.owned_index >= owned.size(): continue
		var o: Dictionary = owned[c.owned_index]
		var p: Vector3 = c.global_position + main.world_offset
		o["health"] = c.health; o["upgrades"] = c.upgrades.duplicate(); o["color"] = c.body_color.to_html(false)
		o["where"] = "garage" if not c.visible else "street"
		o["pos"] = [p.x, p.y, p.z]; o["yaw"] = c.global_rotation.y

## put owned cars back into the world near the player (after loading)
func _restore_owned_cars() -> void:
	for i in owned.size():
		var o: Dictionary = owned[i]
		var exists := false
		for c in main.cars:
			if is_instance_valid(c) and c.owned_index == i: exists = true
		if exists: continue
		var p := Vector3(o["pos"][0], o["pos"][1], o["pos"][2])
		var c2 = spawn_car(o["spec"], Color(o["color"]), p, float(o["yaw"]), float(o["health"]), o.get("upgrades", {}))
		c2.owned_index = i
		if o["where"] == "garage":
			c2.visible = false; c2.freeze = true; c2.collision_layer = 0

# ------------------------------------------------------------------ stealing
## E near an AI car that's stopped or crawling: take it. Returns the new car or null.
func try_carjack(local_pos: Vector3) -> Node:
	var tr = main.traffic
	if tr == null: return null
	var pw: Vector3 = local_pos + main.world_offset
	var best = null; var bd := 3.6
	for c in tr.cars:
		if c.get("siren", false) or c["type"] in ["bus", "ambulance", "firetruck"] or float(c["v"]) > 4.0: continue
		var d: float = Vector2(c["pos"].x - pw.x, c["pos"].z - pw.z).length()
		var half_w: float = float(tr._type(c["type"])["size"][1]) * 0.5
		if d < bd + half_w: bd = d - half_w; best = c
	if best == null: return null
	var t: Dictionary = tr._type(best["type"])
	var id: String = best["type"] if roster.has(best["type"]) else "halden_fairway"
	var paint: Color = best.get("paint", Color(0.5, 0.5, 0.5))
	var pos: Vector3 = best["pos"]; var yaw: float = best["yaw"]
	var was_police: bool = best["type"] == "police"
	tr._despawn(best)
	var car = spawn_car(id, paint, pos + Vector3(0, 0.2, 0), yaw)
	car.stolen = true
	if main.police: main.police.report("steal_police_car" if was_police else "car_theft", pw)
	if main.hud: main.hud.flash("You took the %s" % car.model_name)
	return car

## taking a parked car that isn't yours (E on a car with owned_index -1 and not already stolen)
func on_enter_car(c: Node) -> void:
	if c.owned_index < 0 and not c.stolen and c.get_meta("parked_free", false) == false:
		c.stolen = true
		if main.police: main.police.report("car_theft", c.global_position + main.world_offset)

# ------------------------------------------------------------------ dealers
func _offers(d: Dictionary) -> Array:
	var r := RandomNumberGenerator.new()
	r.seed = int(d["id"]) * 7919 + (main.jobs.day() if d["used"] else 0) * 31
	var civ: Array = []
	for m in V["models"]:
		if m["category"] != "commercial": civ.append(m)
	var out: Array = []
	if d["used"]:
		for i in 6:
			var m: Dictionary = civ[r.randi() % civ.size()]
			if m["category"] == "exotic" and r.randf() < 0.8: m = civ[0]
			var cond := r.randf_range(float(V["used_condition"][0]), float(V["used_condition"][1]))
			var pf := r.randf_range(float(V["used_price_factor"][0]), float(V["used_price_factor"][1]))
			out.append({"spec": m["id"], "color": V["colors"][r.randi() % V["colors"].size()], "price": int(round(float(m["price"]) * pf * cond / 100.0)) * 100, "health": cond * 1000.0})
	else:
		var picks := civ.duplicate()
		for i in mini(9, picks.size()):
			var m2: Dictionary = picks[(int(d["id"]) * 3 + i) % picks.size()]
			out.append({"spec": m2["id"], "color": V["colors"][(i + int(d["id"])) % V["colors"].size()], "price": int(m2["price"]), "health": 1000.0})
	return out

func buy_offer(dealer_id: int, n: int) -> Node:
	var d: Dictionary = dealers[dealer_id]
	var offs := _offers(d)
	if n < 0 or n >= offs.size(): return null
	var o: Dictionary = offs[n]
	var m := spec(o["spec"])
	if not main.money.spend(int(o["price"]), "Bought %s %s" % [m["make"], m["model"]]):
		main.hud.flash("You need $%d" % int(o["price"])); return null
	var s: Dictionary = main.jobs._curb(Vector3(float(d["x"]), 0, float(d["z"])))
	var p: Vector3 = (s["pos"] as Vector3) if not s.is_empty() else Vector3(float(d["x"]), 0, float(d["z"]))
	p.y = main.services._ground_y(p) if main.services else 0.0
	var yaw: float = atan2(-(s["face"] as Vector3).z, (s["face"] as Vector3).x) if not s.is_empty() else 0.0
	var c = spawn_car(o["spec"], Color(o["color"]), p + Vector3(0, 0.3, 0), yaw, float(o["health"]))
	add_owned(c)
	main.hud.flash("You bought a %s for $%d - it's at the curb" % [c.model_name, int(o["price"])])
	return c

func _update_signs() -> void:
	if main.jobs == null or main.traffic == null or main.traffic.edges.is_empty(): return
	var f: Vector3 = main.focus_world()
	var want := {}
	for d in dealers:
		if Vector2(float(d["x"]) - f.x, float(d["z"]) - f.z).length() < 260.0: want[int(d["id"])] = true
	for id in _signs.keys():
		if not want.has(id):
			if is_instance_valid(_signs[id]): _signs[id].queue_free()
			_signs.erase(id)
	for id in want:
		if _signs.has(id): continue
		var d: Dictionary = dealers[id]
		var s: Dictionary = main.jobs._curb(Vector3(float(d["x"]), 0, float(d["z"])))
		if s.is_empty(): continue
		var root := Node3D.new(); main.world.add_child(root)
		var sp: Vector3 = s["pos"]; sp.y = main.services._ground_y(sp) if main.services else 0.0
		root.global_position = sp - main.world_offset
		root.look_at(root.global_position + (s["face"] as Vector3), Vector3.UP)
		var post := MeshInstance3D.new(); var pm := BoxMesh.new(); pm.size = Vector3(0.12, 3.0, 0.12); post.mesh = pm; post.position.y = 1.5
		root.add_child(post)
		var bd := MeshInstance3D.new(); var bm := BoxMesh.new(); bm.size = Vector3(2.6, 0.9, 0.08); bd.mesh = bm; bd.position.y = 3.0
		var mat := StandardMaterial3D.new(); mat.albedo_color = Color(0.1, 0.3, 0.6) if not d["used"] else Color(0.85, 0.6, 0.1); bd.material_override = mat
		root.add_child(bd)
		var lab := Label3D.new(); lab.text = d["name"] + "\n" + ("NEW CARS" if not d["used"] else "USED CARS - DAILY DEALS"); lab.font_size = 34; lab.pixel_size = 0.0045
		lab.position = Vector3(0, 3.0, -0.05); lab.rotation.y = PI; root.add_child(lab)
		_signs[id] = root

func dealer_near(local_pos: Vector3) -> int:
	for id in _signs:
		var n: Node3D = _signs[id]
		if is_instance_valid(n) and Vector2(n.global_position.x - local_pos.x, n.global_position.z - local_pos.z).length() < 3.0: return id
	return -1

func _show_catalogue(dealer_id: int) -> void:
	_cat_dealer = dealer_id
	cat_open = dealer_id >= 0
	_cat_label.visible = cat_open
	if not cat_open: return
	var d: Dictionary = dealers[dealer_id]
	catalogue = _offers(d)
	var lines := ["%s  ·  number = buy  ·  K = close   (you have $%d)" % [d["name"], main.money.total()]]
	for i in catalogue.size():
		var o: Dictionary = catalogue[i]; var m := spec(o["spec"])
		lines.append("%d. %s %s (%s)  $%d%s" % [i + 1, m["make"], m["model"], m["category"], int(o["price"]), "  · condition %d%%" % int(float(o["health"]) / 10.0) if d["used"] else ""])
	_cat_label.text = "\n".join(lines)

# ------------------------------------------------------------------ auto shops
func shop_near(local_pos: Vector3) -> int:
	var id: int = main.jobs.sign_near(local_pos, 9.0) if main.jobs else -1
	if id >= 0 and main.jobs.place(id)["kind"] == "auto_shop": return id
	return -1

func my_car_near(local_pos: Vector3) -> Node:
	if main.current_car: return main.current_car
	for c in main.cars:
		if is_instance_valid(c) and c.visible and (c.owned_index >= 0 or c.stolen) and c.global_position.distance_to(local_pos) < 9.0: return c
	return null

func repair_cost(c: Node) -> int:
	return int(ceil((1000.0 - c.health) * float(spec(c.spec_id)["price"]) / 1000.0 * 0.04 / 10.0)) * 10

func upgrade_cost(c: Node, part: String) -> int:
	var lvl: int = int(c.upgrades.get(part, 0))
	return int(float(spec(c.spec_id)["price"]) * 0.06 * (lvl + 1) / 50.0) * 50 + 400

func repair(c: Node) -> bool:
	var cost := repair_cost(c)
	if cost <= 0: main.hud.flash("Nothing to fix"); return true
	if not main.money.spend(cost, "Repair"): main.hud.flash("Repair costs $%d" % cost); return false
	c.health = 1000.0
	main.hud.flash("Repaired - $%d" % cost)
	return true

func repaint(c: Node) -> bool:
	var cost := 250
	if not main.money.spend(cost, "Paint"): main.hud.flash("A respray costs $%d" % cost); return false
	var cols: Array = V["colors"]
	var col := Color(cols[rng.randi() % cols.size()])
	c.body_color = col
	var body: MeshInstance3D = c.get_node_or_null("Body")
	if body and main.traffic: body.mesh = main.traffic.vehicle_mesh(main.traffic._type(c.spec_id), col)
	c.stolen = false if c.owned_index >= 0 else c.stolen
	main.hud.flash("Resprayed - $%d" % cost)
	return true

func upgrade(c: Node) -> bool:
	for part in ["engine", "brakes", "suspension"]:
		if int(c.upgrades.get(part, 0)) < 3:
			var cost := upgrade_cost(c, part)
			if not main.money.spend(cost, "Upgrade " + part): main.hud.flash("%s upgrade costs $%d" % [part.capitalize(), cost]); return false
			c.upgrades[part] = int(c.upgrades.get(part, 0)) + 1
			c.apply_spec()
			main.hud.flash("%s upgraded to level %d - $%d" % [part.capitalize(), c.upgrades[part], cost])
			return true
	main.hud.flash("Fully upgraded")
	return true

# ------------------------------------------------------------------ per frame / input / HUD
func _process(dt: float) -> void:
	_sign_t -= dt
	if _sign_t <= 0.0:
		_sign_t = 2.0
		_update_signs()
		_sync_owned()
	if cat_open and dealer_near(main.player.global_position) != _cat_dealer: _show_catalogue(-1)

func prompt(local_pos: Vector3) -> String:
	var d := dealer_near(local_pos)
	if d >= 0: return "%s  ·  K: see the cars" % dealers[d]["name"]
	if shop_near(local_pos) >= 0:
		var c := my_car_near(local_pos)
		if c: return "Auto shop  ·  P: repair $%d  ·  C: respray $250  ·  U: upgrade" % repair_cost(c)
	return ""

func _unhandled_input(e: InputEvent) -> void:
	if not (e is InputEventKey and e.pressed and not e.echo): return
	var k: int = e.physical_keycode
	var lp: Vector3 = main.current_car.global_position if main.current_car else main.player.global_position
	if k == KEY_V:
		cam_view = (cam_view + 1) % VIEWS.size()
		main.hud.flash("Camera: " + VIEWS[cam_view]); get_viewport().set_input_as_handled(); return
	if k == KEY_K:
		var d := dealer_near(main.player.global_position)
		_show_catalogue(-1 if cat_open else d); get_viewport().set_input_as_handled(); return
	if cat_open and k >= KEY_1 and k <= KEY_9:
		buy_offer(_cat_dealer, k - KEY_1); _show_catalogue(-1); get_viewport().set_input_as_handled(); return
	if k in [KEY_P, KEY_C, KEY_U] and shop_near(lp) >= 0:
		var c := my_car_near(lp)
		if c == null: main.hud.flash("Bring your car to the shop"); return
		match k:
			KEY_P: repair(c)
			KEY_C: repaint(c)
			KEY_U: upgrade(c)
		get_viewport().set_input_as_handled()

## camera offset for the current view (car-local), used by main.gd's car camera; null = default chase
func view_offset(c: Node):
	var L: float = float(c.spec["size"][0]) if not c.spec.is_empty() else 4.5
	var H: float = float(c.spec["size"][2]) if not c.spec.is_empty() else 1.45
	match VIEWS[cam_view]:
		"hood": return [Vector3(0, H + 0.15, -L * 0.15), Vector3(0, H, -L * 0.15 - 20.0)]
		"bumper": return [Vector3(0, 0.6, -L * 0.5 - 0.3), Vector3(0, 0.6, -L * 0.5 - 20.0)]
		"cockpit": return [Vector3(-0.38, H * 0.82, 0.05), Vector3(-0.38, H * 0.78, -20.0)]
	return null

func chase_distance_mult() -> float:
	return 1.7 if VIEWS[cam_view] == "far chase" else 1.0

func get_save_data() -> Dictionary:
	_sync_owned()
	return {"owned": owned, "cam_view": cam_view}

func apply_save_data(d: Dictionary) -> void:
	for c in main.cars.duplicate():
		if is_instance_valid(c) and c.owned_index >= 0 and c != main.current_car:
			main.cars.erase(c); c.queue_free()
	owned = d.get("owned", []); cam_view = int(d.get("cam_view", 0))
	_restore_owned_cars()
