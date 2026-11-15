extends Node
## Player money (Bible section 9): physical cash plus a digital wallet in a made-up phone payment app.
##   * Pay: cash first, then the wallet (most businesses take both). spend() returns false if you can't afford it.
##   * ATMs (source_data/atms.json, one outside every bank): E = withdraw, R = deposit all cash.
##   * Saved as world-state section "money". Settings: source_data/economy.json.
## No bank accounts, credit or loans (Bible).

var main: Node
var E: Dictionary
var cash := 0
var wallet := 0
var app_name := "GlassPay"
var atms: Array = []          # {x, z, bank}
var _nodes := {}              # atm index -> Node3D (placed near the player)
var _place_t := 0.0
var history: Array = []       # last transactions [label, amount]

func _ready() -> void:
	E = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/economy.json"))
	cash = int(E["start_cash"]); wallet = int(E["start_wallet"]); app_name = E["app_name"]
	if FileAccess.file_exists("res://source_data/atms.json"):
		atms = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/atms.json"))["atms"]

func total() -> int:
	return cash + wallet

func _note(label: String, amount: int) -> void:
	history.append([label, amount])
	if history.size() > 20: history.pop_front()

## pay for something: cash first, the rest from the wallet. false (and nothing taken) if you can't afford it.
func spend(amount: int, label := "") -> bool:
	if amount > total(): return false
	var from_cash := mini(cash, amount)
	cash -= from_cash
	wallet -= amount - from_cash
	_note(label, -amount)
	return true

func earn(amount: int, label := "", digital := true) -> void:
	if digital: wallet += amount
	else: cash += amount
	_note(label, amount)

func withdraw(amount: int) -> bool:
	amount = mini(amount, wallet)
	if amount <= 0: return false
	wallet -= amount; cash += amount
	return true

func deposit_all() -> int:
	var a := cash
	wallet += cash; cash = 0
	return a

## lose cash (e.g. a fine); the rest of a fine comes from the wallet
func fine(amount: int, label := "Fine") -> int:
	var paid := mini(amount, total())
	var from_cash := mini(cash, paid)
	cash -= from_cash; wallet -= paid - from_cash
	_note(label, -paid)
	return paid

# ------------------------------------------------------------------ ATMs in the world
func _process(dt: float) -> void:
	_place_t -= dt
	if _place_t > 0.0 or main.traffic == null or main.traffic.edges.is_empty(): return
	_place_t = 2.0
	var f: Vector3 = main.focus_world()
	for i in atms.size():
		var a: Dictionary = atms[i]
		var near := Vector2(float(a["x"]) - f.x, float(a["z"]) - f.z).length() < 300.0
		if near and not _nodes.has(i): _place(i)
		elif not near and _nodes.has(i):
			if is_instance_valid(_nodes[i]): _nodes[i].queue_free()
			_nodes.erase(i)

## an ATM kiosk on the sidewalk nearest the bank, facing the street
func _place(i: int) -> void:
	var tr = main.traffic
	var a: Dictionary = atms[i]
	var p := Vector3(float(a["x"]), 0, float(a["z"]))
	var best := -1; var bd := 1e9; var bq := Vector3.ZERO
	for k in tr.edges.size():
		var e: Dictionary = tr.edges[k]
		if e["cls"] > 6: continue
		var q := Geometry3D.get_closest_point_to_segment(p, tr.npos[e["a"]], tr.npos[e["b"]])
		var d := Vector2(q.x - p.x, q.z - p.z).length()
		if d < bd: bd = d; best = k; bq = q
	if best < 0 or bd > 120.0: return
	var e2: Dictionary = tr.edges[best]
	var to_bank := Vector3(p.x - bq.x, 0, p.z - bq.z).normalized()
	if to_bank == Vector3.ZERO: to_bank = Vector3(-e2["dir"].z, 0, e2["dir"].x)
	var spot: Vector3 = bq + to_bank * (float(e2.get("w", 8.0)) * 0.5 + 3.2)
	var root := Node3D.new(); root.name = "ATM_%d" % i
	root.set_meta("atm", i)
	main.world.add_child(root)
	var sp: PhysicsDirectSpaceState3D = main.get_world_3d().direct_space_state
	var q2 := PhysicsRayQueryParameters3D.create(spot - main.world_offset + Vector3(0, 40, 0), spot - main.world_offset + Vector3(0, -40, 0), 1)
	var hit := sp.intersect_ray(q2)
	var y: float = (hit["position"].y + main.world_offset.y) if not hit.is_empty() else 0.0
	root.global_position = Vector3(spot.x, y, spot.z) - main.world_offset
	root.look_at(root.global_position - to_bank, Vector3.UP)   # screen faces the street
	var body := MeshInstance3D.new(); var bm := BoxMesh.new(); bm.size = Vector3(0.9, 1.75, 0.6); body.mesh = bm
	var m := StandardMaterial3D.new(); m.albedo_color = Color(0.2, 0.42, 0.62); m.roughness = 0.4; m.metallic = 0.3
	body.material_override = m; body.position = Vector3(0, 0.875, 0); root.add_child(body)
	var scr := MeshInstance3D.new(); var sm := BoxMesh.new(); sm.size = Vector3(0.55, 0.38, 0.03); scr.mesh = sm
	var m2 := StandardMaterial3D.new(); m2.albedo_color = Color(0.1, 0.25, 0.3); m2.emission_enabled = true; m2.emission = Color(0.3, 0.8, 0.9); m2.emission_energy_multiplier = 0.8
	scr.material_override = m2; scr.position = Vector3(0, 1.3, -0.31); root.add_child(scr)
	var lab := Label3D.new(); lab.text = "ATM\n" + String(a["bank"]); lab.font_size = 42; lab.pixel_size = 0.006
	lab.position = Vector3(0, 1.95, -0.31); lab.rotation.y = PI; lab.modulate = Color(1, 1, 1); lab.outline_size = 8
	root.add_child(lab)
	var col := StaticBody3D.new(); var cs := CollisionShape3D.new(); var bx := BoxShape3D.new(); bx.size = bm.size
	cs.shape = bx; cs.position = body.position; col.add_child(cs); root.add_child(col)
	_nodes[i] = root

func nearest_atm(local_pos: Vector3, max_d := 2.2) -> Node3D:
	for i in _nodes:
		var n: Node3D = _nodes[i]
		if is_instance_valid(n) and n.global_position.distance_to(local_pos) < max_d: return n
	return null

func prompt(local_pos: Vector3) -> String:
	if nearest_atm(local_pos) == null: return ""
	return "ATM: E withdraw $%d  ·  R deposit cash   (%s $%d)" % [int(E["atm_withdraw"]), app_name, wallet]

## E at an ATM. true if handled.
func try_withdraw(local_pos: Vector3) -> bool:
	if nearest_atm(local_pos) == null: return false
	var ok := withdraw(int(E["atm_withdraw"]))
	if main.hud: main.hud.flash("Withdrew $%d" % int(E["atm_withdraw"]) if ok else "Not enough in %s" % app_name)
	return true

## R at an ATM. true if handled.
func try_deposit(local_pos: Vector3) -> bool:
	if nearest_atm(local_pos) == null: return false
	var a := deposit_all()
	if main.hud: main.hud.flash("Deposited $%d to %s" % [a, app_name] if a > 0 else "No cash to deposit")
	return true

func get_save_data() -> Dictionary:
	return {"cash": cash, "wallet": wallet}

func apply_save_data(d: Dictionary) -> void:
	cash = int(d.get("cash", cash)); wallet = int(d.get("wallet", wallet))
