extends Node
## Homes (Bible section 9): rent or buy a house or apartment (source_data/homes.json, ~220 real buildings with
## made-up addresses), use it as your base, and keep cars in its garage.
##   * Listings have a For Rent / For Sale sign out front: R = rent (charged every 7 game days from your money),
##     B = buy. One home at a time; buying while renting ends the lease. Can't pay the rent = evicted.
##   * At your home's sign: E = sleep until 8 am (saves the game), G = put the car you're next to in the garage /
##     take it out (houses with a garage).
##   * Interiors and customising them come later. Saved as world-state section "home".

const Signs := preload("res://scripts/signs.gd")
var main: Node
var homes: Array = []
var home := {}               # {"id", "mode": "rent"|"own", "next_rent_day"}
var garage: Array = []       # stored cars [{model, color}]
var _signs := {}
var _sign_t := 0.0
const RENT_DAYS := 7

func _ready() -> void:
	homes = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/homes.json"))["homes"]

func listing(id: int) -> Dictionary:
	return homes[id] if id >= 0 and id < homes.size() else {}

func day() -> int:
	return int(floor(main.tod.total_hours / 24.0))

func rent(id: int) -> bool:
	var h := listing(id)
	if h.is_empty() or (not home.is_empty() and int(home["id"]) == id): return false
	var first: int = int(h["rent_week"])
	if not main.money.spend(first, "Rent: " + h["address"]):
		main.hud.flash("You need $%d for the first week's rent" % first); return false
	_move_out()
	home = {"id": id, "mode": "rent", "next_rent_day": day() + RENT_DAYS}
	main.hud.flash("You rent %s - $%d a week" % [h["address"], first])
	return true

func buy(id: int) -> bool:
	var h := listing(id)
	if h.is_empty() or int(h["price"]) <= 0: return false
	if not home.is_empty() and int(home["id"]) == id and home["mode"] == "own": return false
	if not main.money.spend(int(h["price"]), "Bought " + h["address"]):
		main.hud.flash("You need $%d to buy this home" % int(h["price"])); return false
	if home.is_empty() or int(home["id"]) != id: _move_out()
	home = {"id": id, "mode": "own", "next_rent_day": -1}
	main.hud.flash("You bought %s!" % h["address"])
	return true

func _move_out() -> void:
	if not garage.is_empty() and main.hud: main.hud.flash("Your stored cars moved with you")
	home = {}

## charge rent when it's due; evict if you can't pay
func _process(_dt: float) -> void:
	if main.tod == null: return
	_sign_t -= _dt
	if _sign_t <= 0.0:
		_sign_t = 2.0
		_update_signs()
	if home.is_empty() or home["mode"] != "rent": return
	if day() >= int(home["next_rent_day"]):
		var h := listing(int(home["id"]))
		if main.money.spend(int(h["rent_week"]), "Rent: " + h["address"]):
			home["next_rent_day"] = int(home["next_rent_day"]) + RENT_DAYS
			main.hud.flash("Rent paid: $%d" % int(h["rent_week"]))
		else:
			main.hud.flash("You couldn't pay the rent - evicted from %s" % h["address"])
			home = {}

## sleep: to 8 am the next morning, then save
func sleep() -> void:
	var tod = main.tod
	var h: float = fposmod(tod.total_hours, 24.0)
	tod.total_hours += (24.0 - h + 8.0) if h >= 8.0 else (8.0 - h)
	tod.apply_now()
	if main.world_state and main.world_state.enabled: main.world_state.save()
	main.hud.flash("You slept until 8 AM. Game saved.")

## garage = owned cars marked "garage" in vehicles.gd. A car you drive in becomes yours (even a stolen one).
func store_car() -> bool:
	var h := listing(int(home.get("id", -1)))
	if h.is_empty() or not h.get("garage", false): return false
	var c = main.nearest_car(6.0)
	if c == null or c == main.current_car or not c.visible: return false
	var idx: int = main.vehicles.add_owned(c) if main.vehicles else -1
	if idx < 0: return false
	if not garage.has(idx): garage.append(idx)
	c.visible = false; c.freeze = true; c.collision_layer = 0
	main.hud.flash("Stored the %s in your garage" % c.model_name)
	return true

func take_car(sign_pos: Vector3) -> bool:
	if garage.is_empty(): return false
	var idx: int = int(garage.pop_back())
	for c in main.cars:
		if is_instance_valid(c) and c.owned_index == idx:
			c.global_position = sign_pos + Vector3(3.0, 0.8, 0)
			c.visible = true; c.freeze = false; c.collision_layer = 1
			c.linear_velocity = Vector3.ZERO
			main.hud.flash("Took the %s out of the garage" % c.model_name)
			return true
	return false

# ------------------------------------------------------------------ signs
func _update_signs() -> void:
	if main.jobs == null or main.traffic == null or main.traffic.edges.is_empty(): return
	var f: Vector3 = main.focus_world()
	var want := {}
	for h in homes:
		if Vector2(float(h["x"]) - f.x, float(h["z"]) - f.z).length() < 240.0: want[int(h["id"])] = true
	for id in _signs.keys():
		if not want.has(id):
			if is_instance_valid(_signs[id]): _signs[id].queue_free()
			_signs.erase(id)
	for id in want:
		if _signs.has(id): continue
		var h := listing(id)
		var s: Dictionary = main.jobs._curb(Vector3(float(h["x"]), 0, float(h["z"])))
		if s.is_empty(): continue
		var root := Node3D.new(); root.name = "Home_%d" % id
		main.world.add_child(root)
		var sp: Vector3 = s["pos"]; sp.y = main.services._ground_y(sp) if main.services else 0.0
		root.global_position = sp - main.world_offset
		root.look_at(root.global_position + (s["face"] as Vector3), Vector3.UP)
		_signs[id] = root
		_label(id)

func _label(id: int) -> void:
	if not _signs.has(id): return
	var h := listing(id)
	var root: Node3D = _signs[id]
	for c in root.get_children(): c.queue_free()
	var sg: Node3D
	if not home.is_empty() and int(home["id"]) == id:
		sg = Signs.make("Home", h["address"], "E sleep  ·  T cook  ·  G garage", Color(0.2, 0.45, 0.75), 1.6)
	else:
		var det := "Rent $%d/wk (R)" % int(h["rent_week"]) + ("  ·  Buy $%dk (B)" % int(int(h["price"]) / 1000) if int(h["price"]) > 0 else "")
		sg = Signs.make("For sale or rent" if int(h["price"]) > 0 else "For rent", h["address"], det, Color(0.75, 0.12, 0.12), 1.6)
	sg.scale = Vector3.ONE * 0.8
	root.add_child(sg)

func sign_near(local_pos: Vector3, max_d := 2.6) -> int:
	for id in _signs:
		var n: Node3D = _signs[id]
		if is_instance_valid(n) and Vector2(n.global_position.x - local_pos.x, n.global_position.z - local_pos.z).length() < max_d: return id
	return -1

func prompt(local_pos: Vector3) -> String:
	var id := sign_near(local_pos)
	if id < 0: return ""
	var h := listing(id)
	if not home.is_empty() and int(home["id"]) == id:
		var g := "  ·  G: garage (%d stored)" % garage.size() if h.get("garage", false) else ""
		return "%s (yours)  ·  E: sleep until 8 AM%s" % [h["address"], g]
	var s := "%s  ·  R: rent $%d/week" % [h["address"], int(h["rent_week"])]
	if int(h["price"]) > 0: s += "  ·  B: buy $%d" % int(h["price"])
	return s

func try_key(local_pos: Vector3, key: int) -> bool:
	var id := sign_near(local_pos)
	if id < 0: return false
	var mine: bool = not home.is_empty() and int(home["id"]) == id
	match key:
		KEY_E:
			if mine: sleep(); return true
		KEY_R:
			if not mine: rent(id); _refresh_labels(); return true
		KEY_B:
			buy(id); _refresh_labels(); return true
		KEY_G:
			if mine:
				if not store_car(): take_car(_signs[id].global_position)
				return true
	return false

func _refresh_labels() -> void:
	for id in _signs: _label(id)

func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventKey and e.pressed and not e.echo and e.physical_keycode in [KEY_E, KEY_R, KEY_B, KEY_G]:
		if main.current_car == null and try_key(main.player.global_position, e.physical_keycode):
			get_viewport().set_input_as_handled()

func get_save_data() -> Dictionary:
	return {"home": home, "garage": garage}

func apply_save_data(d: Dictionary) -> void:
	home = d.get("home", {}); garage = d.get("garage", [])
	if home.has("id"): home["id"] = int(home["id"]); home["next_rent_day"] = int(home.get("next_rent_day", -1))
	garage = garage.filter(func(x): return typeof(x) == TYPE_INT or typeof(x) == TYPE_FLOAT).map(func(x): return int(x))   # cars themselves come back via vehicles.gd
