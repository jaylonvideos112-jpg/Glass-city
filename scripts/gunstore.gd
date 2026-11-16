extends Node
## Walk-in gun stores (GTA V style). E at the store sign takes you inside: a shop floor with a glass counter, wall
## racks of guns and a clerk. E at the counter opens the store menu: categories down the left, the selected weapon
## on a turntable on the counter with its stats (damage, fire rate, accuracy, range, magazine), price, and for guns
## you own: ammo, attachments (scope, extended magazine, suppressor, grip, flashlight) and finishes - all with real
## gameplay effects (weapons.json "attachments" / "finishes"). E at the door to leave.
## Interiors are built on demand 2.6 km under the street (like bars), so the city stays streamed in above.

const INTERIOR_Y := -2600.0
const STATS := {"pistol": [0.45, 0.5, 0.75, 0.5, 0.4], "shotgun": [0.95, 0.15, 0.3, 0.22, 0.2], "rifle": [0.6, 0.85, 0.82, 0.95, 0.85],
	"bat": [0.55, 0.3, 0.0, 0.05, 0.0], "knife": [0.45, 0.6, 0.0, 0.03, 0.0], "grenade": [1.0, 0.1, 0.2, 0.35, 0.0]}
const STAT_NAMES := ["Damage", "Fire rate", "Accuracy", "Range", "Magazine"]

var main: Node
var wp: Node                     # weapons.gd
var inside := false
var store := {}
var interior: Node3D
var return_xf: Transform3D
var menu_open := false
var level := "cat"               # cat -> items -> gun (owned gun options) -> mods / finishes
var cat := 0
var sel := 0
var gun := ""
var _ui: Control
var _turntable: Node3D
var _counter_p := Vector3.ZERO   # interior-local counter / door / display points
var _door_p := Vector3.ZERO
var _display_p := Vector3.ZERO

func _ready() -> void:
	var cl := CanvasLayer.new(); cl.layer = 7; add_child(cl)
	_ui = Control.new(); _ui.set_anchors_preset(Control.PRESET_FULL_RECT); _ui.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_ui.draw.connect(_draw); _ui.visible = false; cl.add_child(_ui)

# ------------------------------------------------------------------ enter / leave
func enter(store_id: int) -> void:
	for s in wp.W["stores"]:
		if int(s["id"]) == store_id: store = s
	var pl = main.player
	return_xf = Transform3D(Basis(Vector3.UP, pl.model.rotation.y + PI), pl.global_position + main.world_offset)
	interior = _build()
	main.world.add_child(interior)
	interior.global_position = Vector3(pl.global_position.x, INTERIOR_Y, pl.global_position.z)
	pl.global_position = interior.global_transform * (_door_p + Vector3(0, 0.2, -1.2))
	pl.velocity = Vector3.ZERO
	main.cam_yaw = 0.0
	inside = true
	if main.bars: main.bars._set_indoor_env(true, {"light": "#fff4e2"})
	if main.hud: main.hud.flash(store.get("name", "Gun store"))

func leave() -> void:
	close_menu()
	main.player.global_position = return_xf.origin - main.world_offset + Vector3(0, 0.3, 0)
	main.player.velocity = Vector3.ZERO
	if interior: interior.queue_free(); interior = null
	inside = false
	if main.bars: main.bars._set_indoor_env(false, {})

func near_counter() -> bool:
	return inside and interior != null and main.player.global_position.distance_to(interior.global_transform * _counter_p) < 2.2

func near_door() -> bool:
	return inside and interior != null and main.player.global_position.distance_to(interior.global_transform * _door_p) < 2.0

func prompt() -> String:
	if not inside or menu_open: return ""
	if near_counter(): return "Press E to browse the store"
	if near_door(): return "Press E to leave"
	return ""

func try_interact() -> bool:
	if not inside: return false
	if menu_open: return true
	if near_counter(): open_menu(); return true
	if near_door(): leave(); return true
	return false

# ------------------------------------------------------------------ the shop floor
func _mat(c: Color, rough := 0.7, metal := 0.0, emit := 0.0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new(); m.albedo_color = c; m.roughness = rough; m.metallic = metal
	if emit > 0.0: m.emission_enabled = true; m.emission = c; m.emission_energy_multiplier = emit
	return m

func _box(root: Node3D, size: Vector3, pos: Vector3, m: Material, collide := false) -> void:
	var mi := MeshInstance3D.new(); var bm := BoxMesh.new(); bm.size = size; mi.mesh = bm; mi.position = pos; mi.material_override = m
	root.add_child(mi)
	if collide:
		var sb := StaticBody3D.new(); var cs := CollisionShape3D.new(); var sh := BoxShape3D.new(); sh.size = size; cs.shape = sh
		sb.position = pos; sb.add_child(cs); root.add_child(sb)

func _build() -> Node3D:
	var root := Node3D.new(); root.name = "GunStore"
	var W := 14.0; var D := 11.0; var H := 3.4
	var floor_m := StandardMaterial3D.new(); floor_m.albedo_texture = load("res://textures/pbr/concrete_pavement_diff.jpg"); floor_m.uv1_scale = Vector3(5, 4, 1)
	floor_m.normal_enabled = true; floor_m.normal_texture = load("res://textures/pbr/concrete_pavement_nor.jpg")
	_box(root, Vector3(W, 0.2, D), Vector3(0, -0.1, 0), floor_m, true)
	_box(root, Vector3(W, 0.2, D), Vector3(0, H + 0.1, 0), _mat(Color(0.82, 0.82, 0.8)))
	var wall := _mat(Color(0.24, 0.26, 0.28))
	var accent := _mat(Color(0.62, 0.12, 0.1))
	_box(root, Vector3(W, H, 0.2), Vector3(0, H * 0.5, -D * 0.5), wall, true)
	_box(root, Vector3(0.2, H, D), Vector3(-W * 0.5, H * 0.5, 0), wall, true)
	_box(root, Vector3(0.2, H, D), Vector3(W * 0.5, H * 0.5, 0), wall, true)
	_box(root, Vector3(W * 0.5 - 1.0, H, 0.2), Vector3(-W * 0.25 - 0.5, H * 0.5, D * 0.5), wall, true)
	_box(root, Vector3(W * 0.5 - 1.0, H, 0.2), Vector3(W * 0.25 + 0.5, H * 0.5, D * 0.5), wall, true)
	_box(root, Vector3(W, 0.35, 0.05), Vector3(0, H - 0.6, -D * 0.5 + 0.12), accent)          # red band
	_door_p = Vector3(0, 0, D * 0.5 - 0.6)
	_box(root, Vector3(2.0, 2.4, 0.08), Vector3(0, 1.2, D * 0.5 + 0.05), _mat(Color(0.15, 0.2, 0.24, 1.0), 0.1, 0.5))
	# pegboard racks with long guns on the back wall, pistols along the side wall
	var peg := _mat(Color(0.55, 0.47, 0.36), 0.9)
	_box(root, Vector3(W - 2.0, 1.8, 0.06), Vector3(0, 1.75, -D * 0.5 + 0.14), peg)
	var ids := ["rifle", "shotgun", "rifle", "shotgun", "rifle", "shotgun", "rifle"]
	for i in ids.size():
		var g: Node3D = wp.build_gun_mesh(ids[i])
		g.scale = Vector3.ONE * 1.5
		g.rotation = Vector3(0, PI * 0.5, PI * 0.5 * 0.0)
		g.position = Vector3(-5.0 + i * 1.65, 2.1 if i % 2 == 0 else 1.4, -D * 0.5 + 0.3)
		g.rotation = Vector3(0, 0, PI * 0.5)
		g.rotate_object_local(Vector3.UP, PI * 0.5)
		root.add_child(g)
	_box(root, Vector3(0.06, 1.4, 6.0), Vector3(-W * 0.5 + 0.14, 1.7, -0.5), peg)
	for i in 8:
		var pg: Node3D = wp.build_gun_mesh("pistol")
		pg.scale = Vector3.ONE * 1.8
		pg.position = Vector3(-W * 0.5 + 0.3, 1.3 + (i % 2) * 0.6, -3.0 + (i / 2) * 1.2)
		pg.rotation = Vector3(0, -PI * 0.5, 0)
		root.add_child(pg)
	# glass counter with pistols inside, the clerk behind it
	var cz := -1.4
	_box(root, Vector3(7.0, 0.9, 0.9), Vector3(0, 0.45, cz), _mat(Color(0.12, 0.12, 0.13), 0.4, 0.3), true)
	_box(root, Vector3(7.0, 0.05, 0.9), Vector3(0, 0.93, cz), _mat(Color(0.6, 0.75, 0.8, 1.0), 0.05, 0.6))
	for i in 6:
		var cg: Node3D = wp.build_gun_mesh("pistol"); cg.scale = Vector3.ONE * 1.4
		cg.position = Vector3(-2.6 + i * 1.05, 0.82, cz); cg.rotation = Vector3(0, PI * 0.5, 0)
		root.add_child(cg)
	_counter_p = Vector3(0, 0, cz + 1.3)
	_display_p = Vector3(0, 1.05, cz)
	_turntable = Node3D.new(); _turntable.position = _display_p; root.add_child(_turntable)
	var look := {"h": 1.0, "w": 1.15, "skin": Color(0.78, 0.6, 0.48), "hair": Color(0.3, 0.25, 0.2), "top": Color(0.2, 0.22, 0.18),
		"top2": Color(0.32, 0.3, 0.22), "bottom": Color(0.2, 0.2, 0.25), "shoe": Color(0.15, 0.12, 0.1), "sleeves": 2, "legs": 0, "hair_style": 4, "beard": true}
	var clerk := MeshInstance3D.new(); clerk.mesh = preload("res://scripts/humans.gd").build(look)
	clerk.mesh.surface_set_material(0, main.peds._mat if main.peds else null)
	clerk.position = Vector3(0.8, 0, cz - 1.0); clerk.rotation.y = PI
	root.add_child(clerk)
	# lights, signage
	for x in [-4.5, 0.0, 4.5]:
		for z in [-3.0, 2.0]:
			_box(root, Vector3(1.6, 0.04, 0.4), Vector3(x, H - 0.03, z), _mat(Color(1, 0.98, 0.92), 0.5, 0.0, 3.0))
			var l := OmniLight3D.new(); l.position = Vector3(x, H - 0.4, z); l.omni_range = 7.0; l.light_energy = 1.2; l.light_color = Color(1, 0.96, 0.9)
			root.add_child(l)
	var title := Label3D.new(); title.text = store.get("name", "GUN STORE").to_upper(); title.font_size = 96; title.pixel_size = 0.0032
	title.font = load("res://fonts/Inter-Black.otf") if ResourceLoader.exists("res://fonts/Inter-Black.otf") else null
	title.modulate = Color(1, 0.95, 0.9); title.position = Vector3(0, H - 0.6, -D * 0.5 + 0.2); root.add_child(title)
	return root

# ------------------------------------------------------------------ the menu
func open_menu() -> void:
	menu_open = true; level = "cat"; cat = 0; sel = 0; gun = ""
	main.input_enabled = false
	main.cam_override = true
	var cam: Camera3D = main.camera
	# over the counter, the turntable sitting right of the menu
	cam.global_position = interior.global_transform * (_display_p + Vector3(-0.75, 0.35, 1.9))
	cam.look_at(interior.global_transform * (_display_p + Vector3(-0.55, 0.05, 0)), Vector3.UP)
	cam.fov = 50.0
	_ui.visible = true
	if main.hud: main.hud.visible = false
	main.player.visible = false
	_show_preview()

func close_menu() -> void:
	if not menu_open: return
	menu_open = false
	main.input_enabled = true
	main.cam_override = false
	_ui.visible = false
	if main.hud: main.hud.visible = true
	main.player.visible = true
	for c in _turntable.get_children(): c.queue_free()

func _rows() -> Array:
	var C: Array = wp.W["categories"]
	match level:
		"cat":
			return C.map(func(c): return {"label": c[0], "kind": "cat"})
		"items":
			var out: Array = []
			for id in C[cat][1]:
				if String(id).begins_with("@"):
					var a: String = String(id).substr(1); var A: Dictionary = wp.W["ammo"][a]
					out.append({"label": A["name"], "price": int(A["price"]), "kind": "ammo", "id": a})
				else:
					var d: Dictionary = wp.def(id)
					var own: bool = wp.owned.has(id) and id != "grenade"
					out.append({"label": d["name"], "price": int(d["price"]), "kind": "weapon", "id": id, "owned": own})
			return out
		"gun":
			var g: Dictionary = wp.def(gun)
			var out2: Array = []
			if g.get("type", "") == "gun":
				var A2: Dictionary = wp.W["ammo"][g["ammo"]]
				out2.append({"label": A2["name"], "price": int(A2["price"]), "kind": "ammo", "id": g["ammo"]})
				out2.append({"label": "Attachments  >", "kind": "go", "to": "mods"})
			out2.append({"label": "Finishes  >", "kind": "go", "to": "finishes"})
			out2.append({"label": "Equip", "kind": "equip"})
			return out2
		"mods":
			var out3: Array = []
			for m in wp.W["attachments"]:
				var A3: Dictionary = wp.W["attachments"][m]
				if gun in A3["fits"]:
					out3.append({"label": A3["name"], "price": int(A3["price"]), "kind": "mod", "id": m, "owned": m in wp.attachments.get(gun, []), "desc": A3["desc"]})
			return out3
		"finishes":
			var out4: Array = []
			for f in wp.W["finishes"]:
				var F: Dictionary = wp.W["finishes"][f]
				out4.append({"label": F["name"], "price": int(F["price"]), "kind": "finish", "id": f, "owned": wp.tints.get(gun, "black") == f})
			return out4
	return []

func _unhandled_input(e: InputEvent) -> void:
	if inside and not menu_open and e is InputEventKey and e.pressed and not e.echo and e.physical_keycode == KEY_E:
		if try_interact(): get_viewport().set_input_as_handled()
		return
	if not menu_open or not (e is InputEventKey and e.pressed): return
	get_viewport().set_input_as_handled()
	var rows := _rows()
	match e.physical_keycode:
		KEY_UP, KEY_W: sel = (sel - 1 + rows.size()) % maxi(rows.size(), 1); _show_preview()
		KEY_DOWN, KEY_S: sel = (sel + 1) % maxi(rows.size(), 1); _show_preview()
		KEY_ENTER, KEY_KP_ENTER, KEY_SPACE: choose(sel)
		KEY_BACKSPACE:
			match level:
				"cat": close_menu()
				"items": level = "cat"; sel = cat
				"gun": level = "items"; sel = 0
				_: level = "gun"; sel = 0
			_show_preview()
		KEY_ESCAPE: close_menu()
	_ui.queue_redraw()

## act on a row: open a category / buy / equip / fit an attachment / apply a finish
func choose(i: int) -> bool:
	var rows := _rows()
	if i < 0 or i >= rows.size(): return false
	var r: Dictionary = rows[i]
	var ok := true
	match r["kind"]:
		"cat": cat = i; level = "items"; sel = 0
		"weapon":
			if r.get("owned", false): gun = r["id"]; level = "gun"; sel = 0
			elif _pay(r["price"], r["label"]):
				if r["id"] == "grenade": wp.owned["grenade"] = true; wp.ammo["grenade"] = int(wp.ammo.get("grenade", 0)) + 1
				else: wp.give(r["id"]); gun = r["id"]; level = "gun"; sel = 0
			else: ok = false
		"ammo":
			if _pay(r["price"], r["label"]): wp.ammo[r["id"]] = int(wp.ammo.get(r["id"], 0)) + int(wp.W["ammo"][r["id"]]["box"])
			else: ok = false
		"go": level = r["to"]; sel = 0
		"equip": wp.equip(gun); if main.hud: main.hud.flash("Equipped %s" % wp.def(gun)["name"])
		"mod":
			var have: Array = wp.attachments.get(gun, [])
			if r["owned"]: have.erase(r["id"]); wp.attachments[gun] = have         # take it off (keep it simple: no refund)
			elif _pay(r["price"], r["label"]): have.append(r["id"]); wp.attachments[gun] = have
			else: ok = false
			if wp.current == gun: wp._update_gun_mesh()
		"finish":
			if not r["owned"] and _pay(r["price"], r["label"] + " finish"): wp.tints[gun] = r["id"]
			elif not r["owned"]: ok = false
			if wp.current == gun: wp._update_gun_mesh()
	_show_preview(); _ui.queue_redraw()
	return ok

func _pay(price: int, what: String) -> bool:
	if price <= 0: return true
	if main.money.spend(price, "Gun store: " + what):
		if main.hud: main.hud.flash("Bought %s  -$%d" % [what, price])
		return true
	if main.hud: main.hud.flash("You can't afford that")
	return false

func _focus_id() -> String:
	var rows := _rows()
	if level in ["gun", "mods", "finishes"]: return gun
	if sel < rows.size() and rows[sel].get("kind", "") == "weapon": return rows[sel]["id"]
	if level == "cat":
		var C: Array = wp.W["categories"]
		for id in C[clampi(sel, 0, C.size() - 1)][1]:
			if not String(id).begins_with("@"): return id
	return ""

func _show_preview() -> void:
	if _turntable == null: return
	for c in _turntable.get_children(): c.queue_free()
	var id := _focus_id()
	if id == "": return
	var g: Node3D = wp.build_gun_mesh(id)
	g.scale = Vector3.ONE * 1.25
	_turntable.add_child(g)

func _process(dt: float) -> void:
	if menu_open and _turntable: _turntable.rotate_y(dt * 0.8)

func _draw() -> void:
	if not menu_open: return
	var fb: Font = load("res://fonts/Inter-Bold.otf"); var fm: Font = load("res://fonts/Inter-Medium.otf")
	var x0 := 60.0; var y0 := 70.0; var w := 400.0
	_ui.draw_rect(Rect2(x0, y0, w, 74), Color(0.6, 0.1, 0.08, 0.95))
	_ui.draw_string(fb, Vector2(x0 + 18, y0 + 46), String(store.get("name", "GUN STORE")).to_upper(), HORIZONTAL_ALIGNMENT_LEFT, w - 30, 26, Color.WHITE)
	var crumbs: String = {"cat": "WEAPONS", "items": String(wp.W["categories"][cat][0]).to_upper(), "gun": String(wp.def(gun).get("name", "")).to_upper(),
		"mods": "ATTACHMENTS", "finishes": "FINISHES"}[level]
	_ui.draw_rect(Rect2(x0, y0 + 74, w, 32), Color(0, 0, 0, 0.85))
	_ui.draw_string(fm, Vector2(x0 + 18, y0 + 96), crumbs, HORIZONTAL_ALIGNMENT_LEFT, w - 100, 15, Color(1, 1, 1, 0.8))
	_ui.draw_string(fm, Vector2(x0 + w - 110, y0 + 96), "$%d" % (main.money.cash + main.money.wallet), HORIZONTAL_ALIGNMENT_RIGHT, 92, 15, Color(0.5, 0.9, 0.5))
	var rows := _rows()
	var y := y0 + 106.0
	for i in rows.size():
		var r: Dictionary = rows[i]
		var on := i == sel
		_ui.draw_rect(Rect2(x0, y, w, 40), Color(0.95, 0.95, 0.95, 0.96) if on else Color(0, 0, 0, 0.72))
		var tc := Color(0.05, 0.05, 0.07) if on else Color.WHITE
		_ui.draw_string(fm, Vector2(x0 + 18, y + 26), r["label"], HORIZONTAL_ALIGNMENT_LEFT, w - 150, 17, tc)
		var right := ""
		if r.get("owned", false): right = "OWNED" if r["kind"] == "weapon" else "FITTED" if r["kind"] == "mod" else "CURRENT"
		elif r.has("price"): right = "FREE" if int(r["price"]) == 0 else "$%d" % int(r["price"])
		_ui.draw_string(fb, Vector2(x0 + w - 140, y + 26), right, HORIZONTAL_ALIGNMENT_RIGHT, 122, 16, tc if right != "OWNED" else Color(0.3, 0.75, 0.35))
		y += 41.0
	# description / stats panel
	y += 10.0
	var id := _focus_id()
	if sel < rows.size() and rows[sel].has("desc"):
		_ui.draw_rect(Rect2(x0, y, w, 46), Color(0, 0, 0, 0.72))
		_ui.draw_string(fm, Vector2(x0 + 18, y + 28), rows[sel]["desc"], HORIZONTAL_ALIGNMENT_LEFT, w - 30, 14, Color(1, 1, 1, 0.85))
		y += 52.0
	if id != "" and STATS.has(id):
		var st: Array = STATS[id].duplicate()
		var mods: Dictionary = wp.mods_for(id)
		if mods.has("spread"): st[2] = minf(1.0, st[2] / float(mods["spread"]) * 0.9)
		if mods.has("mag"): st[4] = minf(1.0, st[4] * float(mods["mag"]))
		_ui.draw_rect(Rect2(x0, y, w, 26 + 30 * 5), Color(0, 0, 0, 0.72))
		for k in 5:
			var yy := y + 30 + k * 30.0
			_ui.draw_string(fm, Vector2(x0 + 18, yy), STAT_NAMES[k], HORIZONTAL_ALIGNMENT_LEFT, 120, 14, Color(1, 1, 1, 0.85))
			_ui.draw_rect(Rect2(x0 + 140, yy - 10, 240, 8), Color(1, 1, 1, 0.15))
			_ui.draw_rect(Rect2(x0 + 140, yy - 10, 240 * float(st[k]), 8), Color(1, 1, 1, 0.9))
	_ui.draw_string(fm, Vector2(x0, _ui.size.y - 40), "W/S select   ·   Enter buy / open   ·   Backspace back   ·   Esc leave the counter", HORIZONTAL_ALIGNMENT_LEFT, 700, 14, Color(1, 1, 1, 0.85))
