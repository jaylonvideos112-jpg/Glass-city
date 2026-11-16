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

func _pbr_mat(set_name: String, tile: Vector2, tint := Color.WHITE, rough := 1.0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_texture = load("res://textures/pbr/%s_diff.jpg" % set_name); m.albedo_color = tint
	m.normal_enabled = true; m.normal_texture = load("res://textures/pbr/%s_nor.jpg" % set_name)
	m.roughness_texture = load("res://textures/pbr/%s_rough.jpg" % set_name); m.roughness = rough
	m.uv1_scale = Vector3(tile.x, tile.y, 1)
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	return m

func _cyl(root: Node3D, r: float, h: float, pos: Vector3, rot: Vector3, m: Material, seg := 16) -> void:
	var mi := MeshInstance3D.new(); var cm := CylinderMesh.new(); cm.top_radius = r; cm.bottom_radius = r; cm.height = h; cm.radial_segments = seg
	mi.mesh = cm; mi.position = pos; mi.rotation = rot; mi.material_override = m; root.add_child(mi)

func _gun(root: Node3D, id: String, pos: Vector3, rot: Vector3, scale := 1.0) -> void:
	var g: Node3D = wp.build_gun_mesh(id); g.position = pos; g.rotation = rot; g.scale = Vector3.ONE * scale; root.add_child(g)

## An armory in an old Glass City brick warehouse: brick walls and steel columns, a dark slatwall of long guns
## lit by cool LED strips, a backlit pistol cabinet, a walnut-and-glass counter, pendant lamps under exposed ducts,
## the store name in neon, and a window behind the counter onto the shooting lanes.
func _build() -> Node3D:
	var root := Node3D.new(); root.name = "GunStore"
	var W := 16.0; var D := 12.0; var H := 4.4
	var brick := _pbr_mat("red_brick_03", Vector2(W / 1.0, H / 1.0) * 0.5)
	var brick_side := _pbr_mat("red_brick_03", Vector2(D / 1.0, H / 1.0) * 0.5)
	var conc := _pbr_mat("brushed_concrete", Vector2(W / 2.5, D / 2.5), Color(0.75, 0.75, 0.78), 0.55)
	var steel := _mat(Color(0.16, 0.17, 0.19), 0.45, 0.7)
	var slat := _mat(Color(0.09, 0.1, 0.11), 0.6, 0.2)
	var walnut := _mat(Color(0.2, 0.12, 0.07), 0.4)
	var felt := _mat(Color(0.05, 0.06, 0.08), 0.95)
	var glass := StandardMaterial3D.new(); glass.albedo_color = Color(0.7, 0.85, 0.95, 0.18); glass.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	glass.roughness = 0.03; glass.metallic_specular = 1.0
	var led_cool := _mat(Color(0.75, 0.88, 1.0), 0.5, 0.0, 4.0)
	var led_warm := _mat(Color(1.0, 0.78, 0.5), 0.5, 0.0, 5.0)
	var accent := _mat(Color(0.2, 0.62, 0.95), 0.4, 0.0, 2.5)
	# shell
	_box(root, Vector3(W, 0.2, D), Vector3(0, -0.1, 0), conc, true)
	_box(root, Vector3(W, 0.2, D), Vector3(0, H + 0.1, 0), _mat(Color(0.12, 0.12, 0.13), 0.9))
	_box(root, Vector3(W, H, 0.3), Vector3(0, H * 0.5, -D * 0.5), brick, true)
	_box(root, Vector3(0.3, H, D), Vector3(-W * 0.5, H * 0.5, 0), brick_side, true)
	_box(root, Vector3(0.3, H, D), Vector3(W * 0.5, H * 0.5, 0), brick_side, true)
	_box(root, Vector3(W * 0.5 - 1.1, H, 0.3), Vector3(-W * 0.25 - 0.55, H * 0.5, D * 0.5), brick, true)
	_box(root, Vector3(W * 0.5 - 1.1, H, 0.3), Vector3(W * 0.25 + 0.55, H * 0.5, D * 0.5), brick, true)
	_door_p = Vector3(0, 0, D * 0.5 - 0.8)
	_box(root, Vector3(2.2, 2.6, 0.06), Vector3(0, 1.3, D * 0.5 + 0.02), glass)
	_box(root, Vector3(2.4, 0.12, 0.3), Vector3(0, 2.66, D * 0.5), steel)
	_box(root, Vector3(2.6, 0.02, 1.6), Vector3(0, 0.01, D * 0.5 - 1.0), _mat(Color(0.05, 0.05, 0.05), 0.95))     # entry mat
	# steel columns and a beam, ducts and pendant lamps
	for x in [-W * 0.5 + 0.6, W * 0.5 - 0.6]:
		for z in [-D * 0.5 + 0.6, 0.0]:
			_box(root, Vector3(0.25, H, 0.25), Vector3(x, H * 0.5, z), steel, true)
	_box(root, Vector3(W, 0.35, 0.25), Vector3(0, H - 0.18, 0.0), steel)
	_cyl(root, 0.32, W - 1.0, Vector3(-3.0, H - 0.55, -2.5), Vector3(0, 0, PI * 0.5), _mat(Color(0.55, 0.57, 0.6), 0.35, 0.85))
	_cyl(root, 0.22, D - 1.0, Vector3(5.0, H - 0.45, 0.0), Vector3(PI * 0.5, 0, 0), _mat(Color(0.55, 0.57, 0.6), 0.35, 0.85))
	for x in [-4.5, -1.5, 1.5, 4.5]:
		for z in [-0.6, 3.2]:
			_cyl(root, 0.006, 1.1, Vector3(x, H - 0.55, z), Vector3.ZERO, steel, 6)
			var shade := MeshInstance3D.new(); var cm := CylinderMesh.new(); cm.top_radius = 0.06; cm.bottom_radius = 0.26; cm.height = 0.24; cm.radial_segments = 16
			shade.mesh = cm; shade.position = Vector3(x, H - 1.2, z); shade.material_override = _mat(Color(0.1, 0.11, 0.12), 0.4, 0.6); root.add_child(shade)
			_cyl(root, 0.07, 0.04, Vector3(x, H - 1.33, z), Vector3.ZERO, led_warm, 12)
			var l := OmniLight3D.new(); l.position = Vector3(x, H - 1.45, z); l.omni_range = 6.5; l.light_energy = 1.4; l.light_color = Color(1.0, 0.8, 0.58)
			l.shadow_enabled = x == -1.5 or x == 1.5
			root.add_child(l)
	# back wall: slatwall of long guns with cool LED strips above and below
	var bz := -D * 0.5 + 0.17
	_box(root, Vector3(11.0, 2.2, 0.05), Vector3(0, 2.0, bz), slat)
	for i in 11: _box(root, Vector3(11.0, 0.012, 0.06), Vector3(0, 0.95 + i * 0.2, bz + 0.01), _mat(Color(0.2, 0.21, 0.23), 0.5, 0.5))
	_box(root, Vector3(11.0, 0.03, 0.03), Vector3(0, 3.12, bz + 0.05), led_cool)
	_box(root, Vector3(11.0, 0.03, 0.03), Vector3(0, 0.88, bz + 0.05), led_cool)
	for k in 3:
		var sl := SpotLight3D.new(); sl.position = Vector3(-3.5 + k * 3.5, 3.4, bz + 1.0); sl.rotation = Vector3(-1.1, 0, 0)
		sl.spot_range = 4.0; sl.spot_angle = 50.0; sl.light_energy = 2.0; sl.light_color = Color(0.85, 0.92, 1.0); root.add_child(sl)
	var longs := ["rifle", "shotgun", "rifle", "rifle", "shotgun", "rifle", "shotgun", "rifle"]
	for row in 3:
		for i in 4:
			var id: String = longs[(row * 4 + i) % longs.size()]
			_gun(root, id, Vector3(-4.2 + i * 2.8, 1.35 + row * 0.62, bz + 0.09), Vector3(0, PI * 0.5, 0), 1.25)
			for hx in [-0.18, 0.18]: _box(root, Vector3(0.015, 0.05, 0.06), Vector3(-4.2 + i * 2.8 + hx, 1.3 + row * 0.62, bz + 0.05), steel)
	# left wall: backlit pistol cabinet
	var lx := -W * 0.5 + 0.2
	_box(root, Vector3(0.35, 1.6, 5.2), Vector3(lx + 0.15, 1.75, -1.2), _mat(Color(0.07, 0.07, 0.08), 0.5, 0.3), true)
	_box(root, Vector3(0.02, 1.4, 5.0), Vector3(lx + 0.33, 1.75, -1.2), _mat(Color(0.9, 0.95, 1.0), 0.6, 0.0, 1.6))
	_box(root, Vector3(0.02, 1.5, 5.1), Vector3(lx + 0.36, 1.75, -1.2), glass)
	for r in 3:
		for i in 5:
			_gun(root, "pistol", Vector3(lx + 0.29, 1.25 + r * 0.45, -3.2 + i * 1.0), Vector3(0, -PI * 0.5, 0), 1.6)
	# counter: walnut top, lit glass front with pistols on dark felt
	var cz := -1.4; var cw := 7.6
	_box(root, Vector3(cw, 0.85, 0.85), Vector3(0, 0.42, cz), _mat(Color(0.08, 0.08, 0.09), 0.5, 0.4), true)
	_box(root, Vector3(cw + 0.12, 0.06, 1.0), Vector3(0, 0.88, cz), walnut)
	_box(root, Vector3(cw - 0.3, 0.02, 0.7), Vector3(0, 0.6, cz), felt)
	_box(root, Vector3(cw - 0.2, 0.3, 0.02), Vector3(0, 0.72, cz + 0.42), glass)
	_box(root, Vector3(cw - 0.2, 0.02, 0.02), Vector3(0, 0.84, cz + 0.4), led_warm)
	_box(root, Vector3(cw, 0.03, 0.03), Vector3(0, 0.05, cz + 0.44), accent)                    # kick plate glow
	for i in 7: _gun(root, "pistol" if i % 2 == 0 else "knife", Vector3(-3.0 + i * 1.0, 0.63, cz), Vector3(PI * 0.5, PI * 0.5, 0), 1.3)
	var reg := MeshInstance3D.new(); var rb := BoxMesh.new(); rb.size = Vector3(0.35, 0.22, 0.3); reg.mesh = rb; reg.position = Vector3(3.0, 1.02, cz - 0.1)
	reg.material_override = _mat(Color(0.1, 0.1, 0.12), 0.4, 0.3); root.add_child(reg)
	_box(root, Vector3(0.3, 0.16, 0.01), Vector3(3.0, 1.18, cz + 0.06), _mat(Color(0.2, 0.6, 0.9), 0.3, 0.0, 1.5))
	_counter_p = Vector3(0, 0, cz + 1.3)
	_display_p = Vector3(-0.9, 1.08, cz)
	var mat_disc := MeshInstance3D.new(); var dm := CylinderMesh.new(); dm.top_radius = 0.32; dm.bottom_radius = 0.34; dm.height = 0.03; mat_disc.mesh = dm
	mat_disc.position = _display_p - Vector3(0, 0.15, 0); mat_disc.material_override = _mat(Color(0.03, 0.03, 0.035), 0.75, 0.1); root.add_child(mat_disc)
	var ring := MeshInstance3D.new(); var tm := TorusMesh.new(); tm.inner_radius = 0.33; tm.outer_radius = 0.345; tm.rings = 48
	ring.mesh = tm; ring.position = _display_p - Vector3(0, 0.135, 0); ring.material_override = accent; root.add_child(ring)
	_turntable = Node3D.new(); _turntable.position = _display_p; root.add_child(_turntable)
	var spot := SpotLight3D.new(); spot.position = _display_p + Vector3(0.4, 1.4, 0.6); spot.look_at_from_position(spot.position, _display_p, Vector3.UP)
	spot.spot_range = 3.0; spot.spot_angle = 28.0; spot.light_energy = 1.6; spot.light_color = Color(1, 0.95, 0.88); spot.shadow_enabled = true
	root.add_child(spot)
	# behind the counter: a window onto the shooting lanes
	_box(root, Vector3(4.0, 1.4, 0.06), Vector3(4.0, 1.9, -D * 0.5 + 0.2), glass)
	var lane := _mat(Color(0.03, 0.035, 0.04), 0.9)
	_box(root, Vector3(4.0, 1.4, 0.05), Vector3(4.0, 1.9, -D * 0.5 - 0.15), lane)
	for t in 3:
		_box(root, Vector3(0.35, 0.5, 0.01), Vector3(2.9 + t * 1.1, 1.95, -D * 0.5 - 0.1), _mat(Color(0.92, 0.9, 0.82), 0.8, 0.0, 0.4))
		_box(root, Vector3(0.12, 0.12, 0.012), Vector3(2.9 + t * 1.1, 2.0, -D * 0.5 - 0.09), _mat(Color(0.75, 0.1, 0.08), 0.8, 0.0, 0.4))
	# the clerk, and someone browsing
	var Hm := preload("res://scripts/humans.gd")
	var look := {"h": 1.0, "w": 1.15, "skin": Color(0.78, 0.6, 0.48), "hair": Color(0.3, 0.25, 0.2), "top": Color(0.2, 0.22, 0.18),
		"top2": Color(0.32, 0.3, 0.22), "bottom": Color(0.2, 0.2, 0.25), "shoe": Color(0.15, 0.12, 0.1), "sleeves": 2, "legs": 0, "hair_style": 4, "beard": true}
	var clerk := MeshInstance3D.new(); clerk.mesh = Hm.build(look); clerk.mesh.surface_set_material(0, main.peds._mat if main.peds else null)
	clerk.position = Vector3(1.2, 0, cz - 1.0); clerk.rotation.y = PI * 0.92; root.add_child(clerk)
	var look2 := {"h": 0.97, "w": 1.0, "skin": Color(0.36, 0.25, 0.18), "hair": Color(0.05, 0.04, 0.04), "top": Color(0.55, 0.15, 0.12),
		"top2": Color(0.55, 0.15, 0.12), "bottom": Color(0.18, 0.22, 0.3), "shoe": Color(0.9, 0.9, 0.88), "sleeves": 1, "legs": 0, "hair_style": 0, "beard": false}
	var cust := MeshInstance3D.new(); cust.mesh = Hm.build(look2); cust.mesh.surface_set_material(0, main.peds._mat if main.peds else null)
	cust.position = Vector3(-W * 0.5 + 1.4, 0, -2.0); cust.rotation.y = PI * 0.5; root.add_child(cust)
	# the name in neon on the brick
	var neon := Label3D.new(); neon.text = String(store.get("name", "GUN STORE")).to_upper()
	neon.font = load("res://fonts/Inter-Bold.otf"); neon.font_size = 120; neon.pixel_size = 0.0028
	neon.modulate = Color(0.55, 0.85, 1.0); neon.outline_size = 18; neon.outline_modulate = Color(0.2, 0.55, 1.0, 0.55)
	neon.position = Vector3(0, 3.62, bz + 0.05); neon.shaded = false; root.add_child(neon)
	var tag := Label3D.new(); tag.text = "EST. GLASS CITY  ·  FIREARMS  ·  AMMUNITION  ·  RANGE"; tag.font = load("res://fonts/Inter-Medium.otf")
	tag.font_size = 48; tag.pixel_size = 0.0022; tag.modulate = Color(0.85, 0.85, 0.85); tag.position = Vector3(0, 3.32, bz + 0.05); root.add_child(tag)
	var fill := OmniLight3D.new(); fill.position = Vector3(0, 2.6, 2.5); fill.omni_range = 12.0; fill.light_energy = 0.5; fill.light_color = Color(0.8, 0.86, 1.0)
	root.add_child(fill)
	return root

# ------------------------------------------------------------------ the menu
func open_menu() -> void:
	menu_open = true; level = "cat"; cat = 0; sel = 0; gun = ""
	main.input_enabled = false
	main.cam_override = true
	var cam: Camera3D = main.camera
	# over the counter, the turntable sitting right of the menu
	cam.global_position = interior.global_transform * (_display_p + Vector3(-0.42, 0.28, 1.05))
	cam.look_at(interior.global_transform * (_display_p + Vector3(-0.3, 0.02, 0)), Vector3.UP)
	cam.fov = 48.0
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
	g.scale = Vector3.ONE * (1.0 if id in ["rifle", "shotgun", "bat"] else 1.6)
	g.rotation = Vector3(0, PI * 0.5, 0)
	_turntable.add_child(g)

func _process(dt: float) -> void:
	if menu_open and _turntable: _turntable.rotate_y(dt * 0.8)

# ---- the menu look: smoked-glass panels with an ice-blue accent (Glass City), not a copy of anyone's store UI
const ICE := Color(0.56, 0.83, 1.0)
const PANEL := Color(0.035, 0.05, 0.075, 0.82)

func _panel(r: Rect2, col := PANEL, rad := 14) -> void:
	var sb := StyleBoxFlat.new(); sb.bg_color = col
	sb.set_corner_radius_all(rad); sb.border_color = Color(1, 1, 1, 0.1); sb.set_border_width_all(1)
	sb.shadow_color = Color(0, 0, 0, 0.35); sb.shadow_size = 18
	_ui.draw_style_box(sb, r)

func _keycap(at: Vector2, key: String, label: String, fb: Font, fm: Font) -> float:
	var kw: float = maxf(26.0, fb.get_string_size(key, HORIZONTAL_ALIGNMENT_LEFT, -1, 13).x + 14.0)
	var sb := StyleBoxFlat.new(); sb.bg_color = Color(1, 1, 1, 0.9); sb.set_corner_radius_all(5)
	_ui.draw_style_box(sb, Rect2(at.x, at.y - 18, kw, 24))
	_ui.draw_string(fb, Vector2(at.x, at.y), key, HORIZONTAL_ALIGNMENT_CENTER, kw, 13, Color(0.05, 0.06, 0.08))
	_ui.draw_string(fm, Vector2(at.x + kw + 8, at.y), label, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color(1, 1, 1, 0.85))
	return kw + 16.0 + fm.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, 14).x + 22.0

func _draw() -> void:
	if not menu_open: return
	var fb: Font = load("res://fonts/Inter-Bold.otf"); var fm: Font = load("res://fonts/Inter-Medium.otf")
	var fk: Font = load("res://fonts/Inter-Black.otf") if ResourceLoader.exists("res://fonts/Inter-Black.otf") else fb
	var V: Vector2 = _ui.size
	# soft dark edge so the panels read over the shop
	_ui.draw_rect(Rect2(0, 0, 520, V.y), Color(0, 0, 0, 0.25))
	var x0 := 48.0; var y0 := 48.0; var w := 420.0
	var rows := _rows()
	var list_h := 120.0 + rows.size() * 46.0
	_panel(Rect2(x0, y0, w, list_h))
	# header: store name in ice blue, money on the right
	_ui.draw_string(fk, Vector2(x0 + 24, y0 + 44), String(store.get("name", "GUN STORE")).to_upper(), HORIZONTAL_ALIGNMENT_LEFT, w - 150, 22, ICE)
	_ui.draw_string(fm, Vector2(x0 + 24, y0 + 66), "Glass City  ·  firearms & ammunition", HORIZONTAL_ALIGNMENT_LEFT, w - 150, 12, Color(1, 1, 1, 0.5))
	_ui.draw_string(fb, Vector2(x0 + w - 150, y0 + 44), "$%s" % _commas(main.money.cash + main.money.wallet), HORIZONTAL_ALIGNMENT_RIGHT, 126, 18, Color(0.45, 0.92, 0.55))
	_ui.draw_line(Vector2(x0 + 24, y0 + 82), Vector2(x0 + w - 24, y0 + 82), Color(1, 1, 1, 0.1), 1.0)
	# breadcrumb pills
	var crumbs: Array = ["SHOP"]
	if level != "cat": crumbs.append(String(wp.W["categories"][cat][0]).to_upper())
	if level in ["gun", "mods", "finishes"]: crumbs.append(String(wp.def(gun).get("name", "")).to_upper())
	if level in ["mods", "finishes"]: crumbs.append("ATTACHMENTS" if level == "mods" else "FINISHES")
	var cx := x0 + 24.0
	for i in crumbs.size():
		var t: String = crumbs[i]
		var tw: float = fb.get_string_size(t, HORIZONTAL_ALIGNMENT_LEFT, -1, 11).x + 18.0
		var last: bool = i == crumbs.size() - 1
		var sb := StyleBoxFlat.new(); sb.bg_color = ICE if last else Color(1, 1, 1, 0.08); sb.set_corner_radius_all(10)
		_ui.draw_style_box(sb, Rect2(cx, y0 + 92, tw, 20))
		_ui.draw_string(fb, Vector2(cx, y0 + 106), t, HORIZONTAL_ALIGNMENT_CENTER, tw, 11, Color(0.03, 0.05, 0.08) if last else Color(1, 1, 1, 0.7))
		cx += tw + 6.0
	# rows
	var y := y0 + 122.0
	for i in rows.size():
		var r: Dictionary = rows[i]
		var on := i == sel
		if on:
			var sb2 := StyleBoxFlat.new(); sb2.bg_color = Color(0.56, 0.83, 1.0, 0.14); sb2.set_corner_radius_all(8)
			_ui.draw_style_box(sb2, Rect2(x0 + 12, y, w - 24, 40))
			_ui.draw_rect(Rect2(x0 + 12, y + 8, 3, 24), ICE)
		_ui.draw_string(fm if not on else fb, Vector2(x0 + 28, y + 26), r["label"], HORIZONTAL_ALIGNMENT_LEFT, w - 170, 16, Color.WHITE if on else Color(1, 1, 1, 0.78))
		var tag := ""; var tag_col := Color(1, 1, 1, 0.85)
		if r.get("owned", false):
			tag = "OWNED" if r["kind"] == "weapon" else ("FITTED" if r["kind"] == "mod" else "APPLIED"); tag_col = Color(0.45, 0.92, 0.55)
		elif r.has("price"): tag = "FREE" if int(r["price"]) == 0 else "$%s" % _commas(int(r["price"]))
		elif r["kind"] in ["cat", "go"]: tag = "›"
		_ui.draw_string(fb, Vector2(x0 + w - 150, y + 26), tag, HORIZONTAL_ALIGNMENT_RIGHT, 126, 15, tag_col)
		y += 46.0
	# the weapon card: name, description, stats (with your current gun as a white tick for comparison)
	var id := _focus_id()
	if id != "":
		var d: Dictionary = wp.def(id)
		var cy := y0 + list_h + 16.0
		var desc := ""
		if sel < rows.size() and rows[sel].has("desc"): desc = rows[sel]["desc"]
		var card_h := 70.0 + (36.0 if desc != "" else 0.0) + (5 * 30.0 + 10.0 if STATS.has(id) else 0.0)
		_panel(Rect2(x0, cy, w, card_h))
		_ui.draw_string(fk, Vector2(x0 + 24, cy + 40), String(d.get("name", id)).to_upper(), HORIZONTAL_ALIGNMENT_LEFT, w - 48, 20, Color.WHITE)
		_ui.draw_string(fm, Vector2(x0 + 24, cy + 60), {"gun": "Firearm", "melee": "Melee", "throw": "Throwable"}.get(d.get("type", ""), "") + ("  ·  %d-round magazine" % wp.mag_size(id) if d.get("type", "") == "gun" else ""), HORIZONTAL_ALIGNMENT_LEFT, w - 48, 12, Color(1, 1, 1, 0.5))
		var sy := cy + 76.0
		if desc != "":
			_ui.draw_string(fm, Vector2(x0 + 24, sy + 14), desc, HORIZONTAL_ALIGNMENT_LEFT, w - 48, 13, ICE)
			sy += 36.0
		if STATS.has(id):
			var st: Array = STATS[id].duplicate()
			var mods: Dictionary = wp.mods_for(id)
			if mods.has("spread"): st[2] = minf(1.0, st[2] / float(mods["spread"]) * 0.9)
			if mods.has("mag"): st[4] = minf(1.0, st[4] * float(mods["mag"]))
			var cur: Array = STATS.get(wp.current, [])
			for k in 5:
				var yy := sy + k * 30.0 + 14.0
				_ui.draw_string(fm, Vector2(x0 + 24, yy + 4), STAT_NAMES[k], HORIZONTAL_ALIGNMENT_LEFT, 110, 13, Color(1, 1, 1, 0.75))
				for seg in 10:          # segmented bar
					var filled: bool = float(seg) < float(st[k]) * 10.0 - 0.01
					_ui.draw_rect(Rect2(x0 + 140 + seg * 25.0, yy - 6, 21, 8), ICE if filled else Color(1, 1, 1, 0.1))
				if not cur.is_empty() and wp.current != id:
					var tx: float = x0 + 140 + float(cur[k]) * 250.0
					_ui.draw_line(Vector2(tx, yy - 10), Vector2(tx, yy + 6), Color(1, 1, 1, 0.9), 2.0)
	# key hints as keycaps
	var hx := x0; var hy := V.y - 36.0
	for kh in [["W / S", "select"], ["ENTER", "buy / open"], ["BACKSPACE", "back"], ["ESC", "leave counter"]]:
		hx += _keycap(Vector2(hx, hy), kh[0], kh[1], fb, fm)

func _commas(n: int) -> String:
	var s := str(absi(n)); var out := ""
	while s.length() > 3:
		out = "," + s.substr(s.length() - 3) + out; s = s.substr(0, s.length() - 3)
	return ("-" if n < 0 else "") + s + out
