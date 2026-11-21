extends Node
## Themed bars: street exteriors (neon sign, awning, door) streamed in with the city chunks, and one
## enterable interior per brand. Interiors are built on demand 3 km under the street the player came
## from, so the city stays streamed in around them. All themes are data (THEMES) so they port cleanly.

const INTERIOR_Y := -3000.0

# brand -> look. size = [width x, depth z, height]; kind: big (club/sports/theme bar) or dive.
const THEMES := {
	"Shot Clock":     {"kind": "big", "size": [20, 15, 5.5], "floor": "wood_floor", "floor_tint": "#d89a5a", "wall": "#1c2a44", "accent": "#ff7a1a", "light": "#fff1dc", "deco": "sports", "sign": "#ff8a2a"},
	"The Salty Hull": {"kind": "big", "size": [18, 14, 4.8], "floor": "wood_dark", "floor_tint": "#ffffff", "wall": "#22403f", "accent": "#c9a45a", "light": "#ffc77a", "deco": "nautical", "sign": "#4fd2ff"},
	"Cardboard Club": {"kind": "big", "size": [18, 14, 5.0], "floor": "wood_floor", "floor_tint": "#c8b090", "wall": "#b08a5a", "accent": "#7a5a34", "light": "#ffe6c0", "deco": "cardboard", "sign": "#ffd27a"},
	"Easy Pour":      {"kind": "big", "size": [20, 14, 5.5], "floor": "wood_dark", "floor_tint": "#b0aaa4", "wall": "#3a3d40", "accent": "#d4a020", "light": "#fff6e8", "deco": "taproom", "sign": "#ffd040"},
	"Velvet Mile":    {"kind": "big", "size": [18, 14, 5.0], "floor": "wood_dark", "floor_tint": "#6a4a5a", "wall": "#2c1030", "accent": "#b0206a", "light": "#ff8ad8", "deco": "lounge", "sign": "#ff4fc0"},
	"Erie Tiki":      {"kind": "big", "size": [18, 14, 5.0], "floor": "sand", "floor_tint": "#ffffff", "wall": "#8a6a3a", "accent": "#2aa88a", "light": "#ffb060", "deco": "tiki", "sign": "#40ffb0"},
	"Neon Coyote":    {"kind": "big", "size": [18, 14, 5.0], "floor": "wood_floor", "floor_tint": "#b07a50", "wall": "#4a2a1c", "accent": "#20c0c0", "light": "#ffd0a0", "deco": "western", "sign": "#ff3a8a"},
	"Alligator Club": {"kind": "big", "size": [16, 12, 4.6], "floor": "swamp_floor", "floor_tint": "#ffffff", "wall": "#1e3a22", "accent": "#7ac040", "light": "#d8ffb0", "deco": "swamp", "sign": "#7aff4a"},
	"Two Buck Tavern":  {"kind": "dive", "size": [12, 9, 3.6], "floor": "wood_dark", "floor_tint": "#ffffff", "wall": "#5a3a2a", "accent": "#e0c040", "light": "#ffcf8a", "deco": "dive", "sign": "#ffe040"},
	"Dollar Draft":     {"kind": "dive", "size": [12, 9, 3.6], "floor": "wood_dark", "floor_tint": "#ffffff", "wall": "#2e4a2e", "accent": "#60c060", "light": "#e8ffd0", "deco": "dive", "sign": "#5aff5a"},
	"Corner Tap":       {"kind": "dive", "size": [11, 8, 3.4], "floor": "wood_floor", "floor_tint": "#8a6a50", "wall": "#4a2a26", "accent": "#d04030", "light": "#ffc890", "deco": "dive", "sign": "#ff5040"},
	"Happy Hour Hut":   {"kind": "dive", "size": [12, 9, 3.6], "floor": "wood_floor", "floor_tint": "#c09060", "wall": "#6a3a5a", "accent": "#ff9a20", "light": "#ffd0a0", "deco": "dive", "sign": "#ffa020"},
	"Tipsy Tom's":      {"kind": "dive", "size": [12, 9, 3.6], "floor": "wood_dark", "floor_tint": "#ffffff", "wall": "#2a3450", "accent": "#4a8aff", "light": "#d0e0ff", "deco": "dive", "sign": "#5a9aff"},
	"BAR":              {"kind": "dive", "size": [10, 8, 3.3], "floor": "rubber_floor", "floor_tint": "#9a9a98", "wall": "#303030", "accent": "#ff2a2a", "light": "#ffd8c0", "deco": "dive", "sign": "#ff2020"},
	"Last Call":        {"kind": "dive", "size": [12, 9, 3.6], "floor": "wood_dark", "floor_tint": "#ffffff", "wall": "#3a2a3a", "accent": "#c040ff", "light": "#ffc0e0", "deco": "dive", "sign": "#d060ff"},
}

var main: Node
var doors: Array = []          # [{node: Node3D (door anchor, outside), theme: String}]
var inside := false
var interior: Node3D = null
var exit_point := Vector3.ZERO  # local position of the interior exit
var return_xf: Transform3D      # where to put the player back outside (world coords, not rebased-local)
var current_theme := ""
var drinks := 0                # drinks bought (this session)
var _mats := {}
var _saved_env := {}

# ------------------------------------------------------------------ materials
func _col(h: String) -> Color:
	return Color(h)

func _mat(color: Color, rough := 0.85, emit := 0.0, metal := 0.0) -> StandardMaterial3D:
	var key := "%s|%.2f|%.2f|%.2f" % [color.to_html(), rough, emit, metal]
	if _mats.has(key): return _mats[key]
	var m := StandardMaterial3D.new()
	m.albedo_color = color
	m.roughness = rough
	m.metallic = metal
	if emit > 0.0:
		m.emission_enabled = true
		m.emission = color
		m.emission_energy_multiplier = emit
	_mats[key] = m
	return m

func _tex(name: String, tint: Color, scale: float) -> StandardMaterial3D:
	var key := "tex|%s|%s|%.2f" % [name, tint.to_html(), scale]
	if _mats.has(key): return _mats[key]
	var m := StandardMaterial3D.new()
	m.albedo_texture = load(Look.t("res://textures/%s.png" % name))
	m.albedo_color = tint
	m.uv1_triplanar = true
	m.uv1_scale = Vector3(scale, scale, scale)
	m.roughness = 0.8
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	_mats[key] = m
	return m

func _box(parent: Node3D, size: Vector3, pos: Vector3, mat: Material, collide := false, rot_y := 0.0) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var b := BoxMesh.new(); b.size = size
	mi.mesh = b
	mi.material_override = mat
	mi.position = pos
	mi.rotation.y = rot_y
	parent.add_child(mi)
	if collide:
		var body := StaticBody3D.new()
		var cs := CollisionShape3D.new()
		var sh := BoxShape3D.new(); sh.size = size
		cs.shape = sh
		body.add_child(cs)
		mi.add_child(body)
	return mi

func _cyl(parent: Node3D, r: float, h: float, pos: Vector3, mat: Material, collide := false, top_r := -1.0) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var c := CylinderMesh.new(); c.bottom_radius = r; c.top_radius = (r if top_r < 0 else top_r); c.height = h; c.radial_segments = 12
	mi.mesh = c
	mi.material_override = mat
	mi.position = pos
	parent.add_child(mi)
	if collide:
		var body := StaticBody3D.new()
		var cs := CollisionShape3D.new()
		var sh := CylinderShape3D.new(); sh.radius = max(r, c.top_radius); sh.height = h
		cs.shape = sh
		body.add_child(cs)
		mi.add_child(body)
	return mi

func _label(parent: Node3D, text: String, pos: Vector3, color: Color, size := 96, px := 0.012, rot_y := 0.0) -> Label3D:
	var l := Label3D.new()
	l.text = text
	l.font_size = size
	l.pixel_size = px
	l.outline_size = 10
	l.modulate = color
	l.outline_modulate = Color(color.r * 0.25, color.g * 0.25, color.b * 0.25, 1)
	l.shaded = false
	l.double_sided = false
	l.position = pos
	l.rotation.y = rot_y
	parent.add_child(l)
	return l

# ------------------------------------------------------------------ exteriors (called per streamed chunk)
## b = [theme, x, z, yaw, wall_h, wall_len] in chunk-local coordinates; local -Z of the anchor points out of the building.
func add_exterior(chunk_root: Node3D, b: Array) -> void:
	var theme: String = b[0]
	var th: Dictionary = THEMES.get(theme, THEMES["BAR"])
	var anchor := Node3D.new()
	anchor.name = "bar_" + theme.replace(" ", "_").replace("'", "")
	anchor.position = Vector3(b[1], float(b[6]) if b.size() > 6 else 0.0, b[2])
	anchor.rotation.y = b[3]
	chunk_root.add_child(anchor)
	var sign_col := _col(th["sign"])
	var acc := _col(th["accent"])
	var wall_h: float = b[4]
	var big: bool = th["kind"] == "big"
	# door: dark recessed panel with a lit frame, sitting just outside the wall plane
	_box(anchor, Vector3(1.6, 2.5, 0.12), Vector3(0, 1.25, -0.08), _mat(Color(0.08, 0.06, 0.05), 0.6))
	_box(anchor, Vector3(1.85, 0.12, 0.16), Vector3(0, 2.56, -0.1), _mat(sign_col, 0.4, 2.5))
	_box(anchor, Vector3(0.6, 0.06, 0.02), Vector3(0.45, 1.15, -0.15), _mat(Color(0.75, 0.7, 0.6), 0.3, 0.0, 0.8))  # push bar
	# awning
	var aw := _box(anchor, Vector3(4.2 if big else 3.0, 0.12, 1.4), Vector3(0, 3.0, -0.75), _mat(acc.darkened(0.25), 0.7))
	aw.rotation.x = -0.18
	# neon sign: backing board + emissive brand name; big brands get a taller blade sign too
	var sy: float = clamp(wall_h - 1.2, 3.6, 7.5) if big else 3.75
	var w: float = clamp(theme.length() * (0.42 if big else 0.32), 2.2, 9.0)
	_box(anchor, Vector3(w + 0.6, 1.1 if big else 0.8, 0.12), Vector3(0, sy + 0.2, -0.12), _mat(Color(0.05, 0.05, 0.06), 0.5))
	var lab := _label(anchor, theme.to_upper(), Vector3(0, sy + 0.2, -0.2), sign_col, 112 if big else 84, 0.011, PI)
	lab.render_priority = 1
	if big:
		var blade := Node3D.new(); blade.position = Vector3(max(2.8, w * 0.5 + 0.9), sy - 1.0, -0.9); anchor.add_child(blade)
		_box(blade, Vector3(0.14, 3.2, 0.9), Vector3.ZERO, _mat(Color(0.06, 0.06, 0.07), 0.5))
		_box(blade, Vector3(0.18, 3.25, 0.06), Vector3(0, 0, -0.47), _mat(sign_col, 0.4, 2.0))
		_box(blade, Vector3(0.18, 3.25, 0.06), Vector3(0, 0, 0.47), _mat(sign_col, 0.4, 2.0))
		var vl := _label(blade, theme.to_upper(), Vector3(0.09, 0, 0), sign_col, 64, 0.008)
		vl.rotation = Vector3(0, PI * 0.5, PI * 0.5)
		var vl2 := _label(blade, theme.to_upper(), Vector3(-0.09, 0, 0), sign_col, 64, 0.008)
		vl2.rotation = Vector3(0, -PI * 0.5, -PI * 0.5)
	else:
		# dive bars: a couple of beer-sign squares in the window band
		for sx in [-2.2, 2.2]:
			_box(anchor, Vector3(0.7, 0.45, 0.04), Vector3(sx, 1.7, -0.06), _mat(Color(0.05, 0.05, 0.05), 0.5))
			_box(anchor, Vector3(0.55, 0.3, 0.05), Vector3(sx, 1.7, -0.08), _mat(acc.lightened(0.2), 0.4, 1.6))
	var glow := OmniLight3D.new()
	glow.light_color = sign_col
	glow.light_energy = 1.4
	glow.omni_range = 7.0
	glow.position = Vector3(0, sy - 0.6, -1.4)
	glow.distance_fade_enabled = true
	glow.distance_fade_begin = 160.0
	glow.distance_fade_length = 40.0
	anchor.add_child(glow)
	doors.append({"node": anchor, "theme": theme})

## Nearest bar door to a world position (within max_d metres), or {}.
func nearest_door(local_pos: Vector3, max_d := 2.6) -> Dictionary:
	var best := {}
	var bd := max_d
	var keep: Array = []
	for d in doors:
		var nv = d["node"]
		if not is_instance_valid(nv):
			continue
		keep.append(d)
		var n: Node3D = nv
		if not n.is_inside_tree():
			continue
		var front: Vector3 = n.global_transform * Vector3(0, 0, -1.0)
		var dist := Vector2(front.x - local_pos.x, front.z - local_pos.z).length()
		if dist < bd and abs(front.y - local_pos.y) < 3.0:
			bd = dist; best = d
	doors = keep
	return best

func near_exit(local_pos: Vector3) -> bool:
	return inside and interior != null and local_pos.distance_to(interior.global_transform * exit_point) < 2.4

func near_counter(local_pos: Vector3) -> bool:
	if not inside or interior == null or not interior.has_meta("counter"): return false
	var c: Vector3 = interior.global_transform * (interior.get_meta("counter") as Vector3)
	return Vector2(local_pos.x - c.x, local_pos.z - c.z).length() < 2.2 or (absf(local_pos.z - c.z) < 1.2 and absf(local_pos.x - c.x) < 4.0)

func prompt(local_pos: Vector3) -> String:
	if inside:
		if near_exit(local_pos): return "Press E to leave %s" % current_theme
		if near_counter(local_pos) and main.get("money"):
			return "Press E to buy a drink ($%d)" % int(main.money.E["prices"]["drink"])
		return ""
	var d := nearest_door(local_pos)
	return ("Press E to enter %s" % d["theme"]) if not d.is_empty() else ""

# ------------------------------------------------------------------ enter / exit
func try_interact(player: Node3D) -> bool:
	if inside:
		if near_exit(player.global_position):
			exit_bar(player)
			return true
		if near_counter(player.global_position) and main.get("money"):
			var price: int = int(main.money.E["prices"]["drink"])
			if main.money.spend(price, "Drink at " + current_theme):
				drinks += 1
				main.hud.flash("Bought a drink at %s  -$%d" % [current_theme, price])
			else: main.hud.flash("You can't afford a drink")
			return true
		return false
	var d := nearest_door(player.global_position)
	if d.is_empty():
		return false
	enter_bar(player, d)
	return true

func enter_bar(player: Node3D, d: Dictionary) -> void:
	var n: Node3D = d["node"]
	current_theme = d["theme"]
	if main.get("stats") and main.stats: main.stats.on_bar_entered(d["theme"])
	var out_pos: Vector3 = n.global_transform * Vector3(0, 0.15, -1.8)
	return_xf = Transform3D(Basis(Vector3.UP, n.global_rotation.y), out_pos + main.world_offset)   # world coords: survives origin rebasing
	interior = build_interior(current_theme)
	main.world.add_child(interior)
	interior.global_position = Vector3(out_pos.x, INTERIOR_Y, out_pos.z)
	var th: Dictionary = THEMES.get(current_theme, THEMES["BAR"])
	var sz: Array = th["size"]
	player.global_position = interior.global_transform * Vector3(0, 0.2, sz[1] * 0.5 - 1.8)
	player.velocity = Vector3.ZERO
	main.cam_yaw = 0.0
	inside = true
	_set_indoor_env(true, th)
	main.hud.flash(current_theme)

func exit_bar(player: Node3D) -> void:
	player.global_position = return_xf.origin - main.world_offset
	player.velocity = Vector3.ZERO
	main.cam_yaw = return_xf.basis.get_euler().y + PI
	if interior:
		interior.queue_free()
	interior = null
	inside = false
	_set_indoor_env(false, {})

func _set_indoor_env(on: bool, th: Dictionary) -> void:
	var env: Environment = main.env
	if on:
		_saved_env = {"fog": env.fog_enabled, "amb": env.ambient_light_energy, "amb_col": env.ambient_light_color, "src": env.ambient_light_source,
			"cam_dist": main.cam_dist}
		env.fog_enabled = false
		env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
		env.ambient_light_color = _col(th["light"]).darkened(0.35)
		env.ambient_light_energy = 0.55
		main.cam_dist = min(main.cam_dist, 3.2)
		if main.has_node("Sun"): main.get_node("Sun").visible = false
		if main.has_node("Moon"): main.get_node("Moon").visible = false
	else:
		if _saved_env.is_empty(): return
		env.fog_enabled = _saved_env["fog"]
		env.ambient_light_source = _saved_env["src"]
		env.ambient_light_color = _saved_env["amb_col"]
		env.ambient_light_energy = _saved_env["amb"]
		main.cam_dist = _saved_env["cam_dist"]
		if main.has_node("Sun"): main.get_node("Sun").visible = true
		if main.has_node("Moon"): main.get_node("Moon").visible = true

# ------------------------------------------------------------------ interiors
## Room centred on the origin: floor at y=0, entrance/exit door in the +Z wall, bar counter along -Z.
func build_interior(theme: String) -> Node3D:
	var th: Dictionary = THEMES.get(theme, THEMES["BAR"])
	var root := Node3D.new(); root.name = "Interior_" + theme.replace(" ", "_")
	var sz: Array = th["size"]
	var W: float = sz[0]; var D: float = sz[1]; var H: float = sz[2]
	var wall := _col(th["wall"]); var acc := _col(th["accent"]); var lc := _col(th["light"])
	var big: bool = th["kind"] == "big"
	var rng := RandomNumberGenerator.new(); rng.seed = hash(theme)
	# shell
	_box(root, Vector3(W, 0.2, D), Vector3(0, -0.1, 0), _tex(th["floor"], _col(th["floor_tint"]), 0.5), true)
	_box(root, Vector3(W, 0.2, D), Vector3(0, H + 0.1, 0), _mat(wall.darkened(0.55), 0.9), true)
	var wm := _mat(wall, 0.9)
	if th["deco"] == "nautical" or th["deco"] == "western" or th["deco"] == "dive" or th["deco"] == "tiki":
		wm = _tex("wood_dark" if th["deco"] != "tiki" else "wood_floor", wall.lightened(0.5), 0.6)
	if th["deco"] == "cardboard":
		wm = _tex("bar_cardboard", Color(1, 1, 1), 0.25)
	for s in [-1, 1]:
		_box(root, Vector3(0.3, H, D), Vector3(s * (W * 0.5 + 0.15), H * 0.5, 0), wm, true)
	_box(root, Vector3(W, H, 0.3), Vector3(0, H * 0.5, -D * 0.5 - 0.15), wm, true)
	_box(root, Vector3(W, H, 0.3), Vector3(0, H * 0.5, D * 0.5 + 0.15), wm, true)
	# trim band around the walls
	for s in [-1, 1]:
		_box(root, Vector3(0.06, 0.12, D), Vector3(s * (W * 0.5 - 0.03), 1.0, 0), _mat(acc.darkened(0.3), 0.6))
		_box(root, Vector3(W, 0.12, 0.06), Vector3(0, 1.0, s * (D * 0.5 - 0.03)), _mat(acc.darkened(0.3), 0.6))
	# exit door (inside face of the +Z wall)
	_box(root, Vector3(1.6, 2.5, 0.08), Vector3(0, 1.25, D * 0.5 - 0.02), _mat(Color(0.1, 0.07, 0.05), 0.6))
	_label(root, "EXIT", Vector3(0, 2.85, D * 0.5 - 0.06), Color(1.0, 0.2, 0.15), 64, 0.006, PI)
	exit_point = Vector3(0, 1.0, D * 0.5 - 1.0)
	# bar counter along the back wall, back-bar shelves with bottles, taps
	var cz: float = -D * 0.5 + 2.6
	root.set_meta("counter", Vector3(0, 0, cz + 0.9))   # where you stand to order
	var cw: float = W * (0.62 if big else 0.7)
	_box(root, Vector3(cw, 1.08, 0.7), Vector3(0, 0.54, cz), _tex("wood_dark", Color(0.85, 0.75, 0.65), 0.6), true)
	_box(root, Vector3(cw + 0.2, 0.06, 0.85), Vector3(0, 1.11, cz), _mat(acc.darkened(0.45), 0.25, 0.0, 0.3))
	_box(root, Vector3(cw, 0.05, 0.05), Vector3(0, 0.25, cz + 0.4), _mat(Color(0.7, 0.65, 0.55), 0.3, 0.0, 0.9))  # foot rail
	var shelf_z: float = -D * 0.5 + 0.35
	_box(root, Vector3(cw, 2.2, 0.4), Vector3(0, 1.6, shelf_z), _tex("wood_dark", Color(0.6, 0.5, 0.45), 0.6), true)
	_box(root, Vector3(cw - 0.4, 1.5, 0.05), Vector3(0, 1.75, shelf_z + 0.21), _mat(lc.darkened(0.2), 0.1, 0.35, 0.6))  # mirror glow
	var bottle_cols := [Color(0.25, 0.5, 0.2), Color(0.55, 0.3, 0.1), Color(0.8, 0.8, 0.85), Color(0.35, 0.15, 0.1), Color(0.2, 0.3, 0.6), Color(0.75, 0.6, 0.2)]
	for row in 2:
		_box(root, Vector3(cw - 0.3, 0.04, 0.3), Vector3(0, 1.25 + row * 0.6, shelf_z + 0.3), _mat(Color(0.3, 0.25, 0.2), 0.5))
		var x := -cw * 0.5 + 0.35
		while x < cw * 0.5 - 0.3:
			var c: Color = bottle_cols[rng.randi() % bottle_cols.size()]
			_cyl(root, 0.045, 0.32, Vector3(x, 1.43 + row * 0.6, shelf_z + 0.3), _mat(c, 0.15, 0.25, 0.1), false, 0.03)
			x += 0.13 + rng.randf() * 0.05
	for i in (6 if big else 3):
		var tx := -0.9 + i * 0.35
		_cyl(root, 0.025, 0.35, Vector3(tx, 1.32, cz - 0.15), _mat(Color(0.8, 0.75, 0.6), 0.25, 0.0, 0.9))
		_box(root, Vector3(0.05, 0.12, 0.05), Vector3(tx, 1.55, cz - 0.15), _mat(acc, 0.4))
	# stools
	var n_stools := int(cw / 0.85)
	for i in n_stools:
		var sx: float = -cw * 0.5 + 0.45 + i * (cw - 0.9) / max(1, n_stools - 1)
		_cyl(root, 0.03, 0.72, Vector3(sx, 0.36, cz + 0.85), _mat(Color(0.2, 0.2, 0.2), 0.3, 0.0, 0.8))
		_cyl(root, 0.2, 0.08, Vector3(sx, 0.75, cz + 0.85), _mat(acc.darkened(0.2), 0.6), true)
	# bartender
	_npc(root, Vector3(0.6, 0, cz - 0.75), PI, Color(0.1, 0.1, 0.1), Color(0.9, 0.9, 0.88))
	# tables with chairs in the room
	var cols := 3 if big else 2
	var rows := 2 if big else 1
	for r in rows:
		for c2 in cols:
			var tx2: float = -W * 0.32 + c2 * (W * 0.64 / max(1, cols - 1))
			var tz := cz + 3.2 + r * 3.0
			if abs(tx2) < 1.4 and r == rows - 1: tx2 += 2.2   # keep the walkway to the door clear
			_table(root, Vector3(tx2, 0, tz), acc, th["deco"])
	# lights: pendant row over the counter + a couple of room fills
	for i in 3:
		var lx := -cw * 0.33 + i * cw * 0.33
		var ph: float = H - 1.25
		_cyl(root, 0.18, 0.22, Vector3(lx, ph, cz + 0.6), _mat(lc, 0.3, 3.0), false, 0.06)
		_cyl(root, 0.008, H - ph, Vector3(lx, (H + ph) * 0.5, cz + 0.6), _mat(Color(0.1, 0.1, 0.1), 0.5))
		var pl := OmniLight3D.new(); pl.light_color = lc; pl.light_energy = 1.6; pl.omni_range = 5.5
		pl.position = Vector3(lx, H - 1.0, cz + 0.4); pl.shadow_enabled = false
		root.add_child(pl)
	for fx in [-W * 0.25, W * 0.25]:
		var fl := OmniLight3D.new(); fl.light_color = lc; fl.light_energy = 1.5; fl.omni_range = max(W, D) * 0.6
		fl.position = Vector3(fx, H - 0.5, D * 0.12)
		root.add_child(fl)
	# brand name over the back bar
	_label(root, theme.to_upper(), Vector3(0, 2.95, shelf_z + 0.25), _col(th["sign"]), 120 if big else 90, 0.009)
	_decorate(root, th, W, D, H, rng)
	return root

func _table(root: Node3D, p: Vector3, acc: Color, deco: String) -> void:
	var top_mat := _tex("wood_dark", Color(0.9, 0.8, 0.7), 0.8)
	if deco == "cardboard": top_mat = _tex("bar_cardboard", Color(1, 1, 1), 0.5)
	if deco == "taproom": top_mat = _tex("wood_floor", Color(0.9, 0.8, 0.65), 0.6)
	_box(root, Vector3(1.1, 0.06, 1.1), p + Vector3(0, 0.76, 0), top_mat, true)
	_cyl(root, 0.05, 0.74, p + Vector3(0, 0.37, 0), _mat(Color(0.15, 0.15, 0.15), 0.4, 0.0, 0.7))
	for a in 4:
		var ang := a * PI * 0.5
		var cp := p + Vector3(cos(ang) * 0.85, 0, sin(ang) * 0.85)
		_box(root, Vector3(0.45, 0.06, 0.45), cp + Vector3(0, 0.46, 0), _mat(acc.darkened(0.35), 0.7), true)
		_box(root, Vector3(0.45, 0.42, 0.05), cp + Vector3(cos(ang) * 0.22, 0.7, sin(ang) * 0.22), _mat(acc.darkened(0.45), 0.7), false, -ang + PI * 0.5)
	# a drink
	_cyl(root, 0.04, 0.14, p + Vector3(0.2, 0.86, 0.1), _mat(Color(0.95, 0.75, 0.25, 1), 0.1, 0.3))

func _npc(root: Node3D, p: Vector3, yaw: float, shirt: Color, apron: Color) -> void:
	var n := Node3D.new(); n.position = p; n.rotation.y = yaw; root.add_child(n)
	_box(n, Vector3(0.48, 0.62, 0.26), Vector3(0, 1.22, 0), _mat(shirt, 0.8))
	_box(n, Vector3(0.4, 0.5, 0.02), Vector3(0, 1.05, -0.14), _mat(apron, 0.8))
	var head := SphereMesh.new(); head.radius = 0.15; head.height = 0.32
	var hm := MeshInstance3D.new(); hm.mesh = head; hm.material_override = _mat(Color(0.62, 0.45, 0.34), 0.7); hm.position = Vector3(0, 1.7, 0); n.add_child(hm)
	for s in [-1, 1]:
		_box(n, Vector3(0.17, 0.85, 0.2), Vector3(0.12 * s, 0.45, 0), _mat(Color(0.12, 0.12, 0.14), 0.8))
		_box(n, Vector3(0.13, 0.6, 0.15), Vector3(0.32 * s, 1.2, 0), _mat(shirt, 0.8))

func _decorate(root: Node3D, th: Dictionary, W: float, D: float, H: float, rng: RandomNumberGenerator) -> void:
	var acc := _col(th["accent"]); var sign := _col(th["sign"])
	var side_x := W * 0.5 - 0.2
	match th["deco"]:
		"sports":
			# wall of TVs, a hoop, scoreboard, court stripe on the floor
			for i in 4:
				var tz := -D * 0.5 + 3.0 + i * 2.6
				_box(root, Vector3(0.08, 1.0, 1.7), Vector3(-side_x, 2.8, tz), _mat(Color(0.02, 0.02, 0.02), 0.3))
				_box(root, Vector3(0.02, 0.9, 1.6), Vector3(-side_x + 0.05, 2.8, tz), _mat(Color(0.2, 0.55, 0.3).lerp(Color(0.3, 0.4, 0.8), i * 0.3), 0.2, 1.5))
			_box(root, Vector3(0.05, 1.05, 1.8), Vector3(side_x, 3.4, 0), _mat(Color(0.95, 0.95, 0.95), 0.4))
			_cyl(root, 0.23, 0.03, Vector3(side_x - 0.35, 3.05, 0), _mat(acc, 0.4, 0.3))
			_box(root, Vector3(3.0, 1.0, 0.1), Vector3(0, H - 0.9, D * 0.5 - 0.2), _mat(Color(0.03, 0.03, 0.03), 0.5))
			_label(root, "HOME 88  AWAY 84", Vector3(0, H - 0.9, D * 0.5 - 0.27), Color(1, 0.55, 0.1), 64, 0.006, PI)
			_box(root, Vector3(W * 0.8, 0.005, 0.08), Vector3(0, 0.005, 0.5), _mat(Color(0.95, 0.95, 0.95), 0.6))
		"nautical":
			_box(root, Vector3(0.03, 2.0, D * 0.7), Vector3(-side_x, 2.6, 0), _tex("net", Color(0.85, 0.8, 0.65), 0.8))
			var wheel := MeshInstance3D.new(); var tor := TorusMesh.new(); tor.inner_radius = 0.55; tor.outer_radius = 0.66
			wheel.mesh = tor; wheel.material_override = _tex("wood_dark", Color(0.9, 0.75, 0.6), 1.0)
			wheel.rotation.z = PI * 0.5; wheel.position = Vector3(side_x - 0.08, 2.6, 0); root.add_child(wheel)
			for i in 4:
				_cyl(root, 0.42, 1.0, Vector3(side_x - 0.6, 0.5, -D * 0.5 + 3.5 + i * 1.0), _tex("wood_floor", Color(0.75, 0.55, 0.4), 1.0), true)
			for i in 3:
				_cyl(root, 0.12, 0.3, Vector3(-W * 0.3 + i * W * 0.3, H - 1.2, 1.0), _mat(Color(1.0, 0.7, 0.3), 0.3, 2.5))
		"cardboard":
			for i in 14:
				var s := Vector3(0.5 + rng.randf() * 0.7, 0.4 + rng.randf() * 0.6, 0.5 + rng.randf() * 0.6)
				var x := (side_x - 0.6) * (1 if i % 2 == 0 else -1)
				var z := -D * 0.5 + 3.0 + (i / 2) * 1.4
				_box(root, s, Vector3(x, s.y * 0.5 + (0.0 if i < 8 else 0.9), z), _tex("bar_cardboard", Color(1, 1, 1), 1.0), true, rng.randf() * 0.4)
			_label(root, "THIS SIDE UP", Vector3(-side_x + 0.05, 2.9, 0), Color(0.25, 0.15, 0.05), 80, 0.008, PI * 0.5)
		"taproom":
			# long tap wall: a row of taps with coloured handles on the left wall + communal table
			_box(root, Vector3(0.12, 0.25, D * 0.6), Vector3(-side_x + 0.1, 1.6, 0), _mat(Color(0.75, 0.72, 0.68), 0.25, 0.0, 0.9))
			for i in 20:
				_box(root, Vector3(0.05, 0.22, 0.05), Vector3(-side_x + 0.22, 1.85, -D * 0.3 + i * D * 0.6 / 19.0), _mat(Color.from_hsv(rng.randf(), 0.7, 0.9), 0.4, 0.4))
			_box(root, Vector3(1.4, 0.05, 6.0), Vector3(W * 0.18, 1.05, 1.5), _tex("wood_floor", Color(0.9, 0.8, 0.65), 0.5), true)
			_box(root, Vector3(0.3, 1.0, 5.5), Vector3(W * 0.18, 0.5, 1.5), _mat(Color(0.15, 0.15, 0.15), 0.5, 0.0, 0.6))
			_label(root, "ON TAP", Vector3(-side_x + 0.05, 3.0, 0), sign, 100, 0.01, PI * 0.5)
		"lounge":
			# velvet booths along both walls + chandelier
			for s in [-1, 1]:
				for i in 3:
					var bz := -D * 0.5 + 4.0 + i * 3.0
					_box(root, Vector3(0.9, 0.45, 2.2), Vector3(s * (side_x - 0.45), 0.23, bz), _tex("velvet_cloth", acc, 1.0), true)
					_box(root, Vector3(0.25, 1.2, 2.2), Vector3(s * (side_x - 0.1), 0.6, bz), _tex("velvet_cloth", acc.darkened(0.2), 1.0))
			var ch := Node3D.new(); ch.position = Vector3(0, H - 1.0, 1.5); root.add_child(ch)
			_cyl(ch, 0.6, 0.08, Vector3.ZERO, _mat(Color(0.85, 0.7, 0.35), 0.2, 0.0, 1.0))
			for i in 10:
				var a := i * TAU / 10.0
				_cyl(ch, 0.05, 0.3, Vector3(cos(a) * 0.55, -0.2, sin(a) * 0.55), _mat(Color(1, 0.9, 0.95), 0.1, 2.0))
			var cl := OmniLight3D.new(); cl.light_color = Color(1, 0.85, 0.95); cl.light_energy = 1.5; cl.omni_range = 7.0; ch.add_child(cl)
		"tiki":
			for i in 4:
				var p := Vector3((side_x - 0.8) * (1 if i % 2 == 0 else -1), 0, -D * 0.5 + 4.0 + (i / 2) * 5.0)
				_cyl(root, 0.12, 3.2, p + Vector3(0, 1.6, 0), _tex("wood_floor", Color(0.7, 0.5, 0.3), 1.0), true, 0.08)
				for k in 6:
					var leaf := _box(root, Vector3(1.6, 0.05, 0.4), p + Vector3(0, 3.2, 0), _mat(Color(0.2, 0.55, 0.25), 0.8), false, k * PI / 3.0)
					leaf.rotation.z = -0.35
			for s in [-1, 1]:
				_cyl(root, 0.04, 1.6, Vector3(s * 2.5, 0.8, D * 0.5 - 1.2), _tex("wood_dark", Color(1, 1, 1), 1.0))
				_cyl(root, 0.1, 0.25, Vector3(s * 2.5, 1.75, D * 0.5 - 1.2), _mat(Color(1.0, 0.55, 0.15), 0.3, 3.0))
			_box(root, Vector3(W * 0.62, 0.5, 0.9), Vector3(0, H - 0.25, -D * 0.5 + 2.6), _mat(Color(0.75, 0.6, 0.3), 0.95))   # thatch over the bar
		"western":
			for i in 3:
				var p := Vector3(side_x - 0.6, 0, -D * 0.5 + 4.0 + i * 3.5)
				_cyl(root, 0.18, 1.6, p + Vector3(0, 0.8, 0), _mat(Color(0.25, 0.55, 0.3), 0.8), true)
				_cyl(root, 0.1, 0.6, p + Vector3(0.25, 1.1, 0), _mat(Color(0.25, 0.55, 0.3), 0.8))
			_label(root, "HOWL", Vector3(-side_x + 0.05, 2.9, -1.0), Color(0.3, 1.0, 1.0), 140, 0.012, PI * 0.5)
			_label(root, "COLD BEER", Vector3(-side_x + 0.05, 2.0, 3.0), Color(1.0, 0.3, 0.6), 90, 0.009, PI * 0.5)
			var mech := Node3D.new(); mech.position = Vector3(-W * 0.25, 0, D * 0.15); root.add_child(mech)   # mechanical bull
			_cyl(mech, 1.4, 0.3, Vector3(0, 0.15, 0), _mat(Color(0.6, 0.1, 0.1), 0.8), true)
			_box(mech, Vector3(0.5, 0.5, 1.2), Vector3(0, 1.0, 0), _mat(Color(0.25, 0.15, 0.1), 0.7), true)
			_cyl(mech, 0.08, 0.6, Vector3(0, 0.45, 0), _mat(Color(0.3, 0.3, 0.3), 0.3, 0.0, 0.8))
		"swamp":
			var g := Node3D.new(); g.position = Vector3(side_x - 1.2, 0, 0); g.rotation.y = 0.4; root.add_child(g)   # the gator
			_box(g, Vector3(0.7, 0.45, 2.4), Vector3(0, 0.25, 0), _mat(Color(0.2, 0.32, 0.15), 0.7), true)
			_box(g, Vector3(0.45, 0.25, 0.9), Vector3(0, 0.22, -1.6), _mat(Color(0.22, 0.34, 0.16), 0.7))
			_box(g, Vector3(0.3, 0.22, 1.4), Vector3(0, 0.15, 1.8), _mat(Color(0.2, 0.3, 0.15), 0.7))
			for s in [-1, 1]:
				_cyl(g, 0.05, 0.05, Vector3(0.12 * s, 0.4, -1.8), _mat(Color(1, 0.85, 0.1), 0.3, 1.5))
			for i in 8:
				_box(root, Vector3(0.05, 1.2 + rng.randf(), 0.6), Vector3((side_x - 0.03) * (1 if i % 2 else -1), H - 0.7, -D * 0.4 + i * D * 0.1), _mat(Color(0.35, 0.45, 0.25), 0.9))
			_label(root, "NO FEEDING", Vector3(side_x - 0.05, 2.4, 0), Color(0.9, 1.0, 0.4), 70, 0.007, -PI * 0.5)
		_:
			# dive: pool table, dartboard, jukebox, neon beer signs
			var pt := Node3D.new(); pt.position = Vector3(-W * 0.22, 0, D * 0.12); root.add_child(pt)
			_box(pt, Vector3(1.4, 0.8, 2.6), Vector3(0, 0.4, 0), _tex("wood_dark", Color(0.8, 0.65, 0.5), 1.0), true)
			_box(pt, Vector3(1.2, 0.02, 2.4), Vector3(0, 0.81, 0), _tex("felt", Color(1, 1, 1), 1.0))
			for i in 6:
				var bc := Color.from_hsv(rng.randf(), 0.8, 0.9)
				var bm := MeshInstance3D.new(); var sp := SphereMesh.new(); sp.radius = 0.03; sp.height = 0.06; bm.mesh = sp
				bm.material_override = _mat(bc, 0.2); bm.position = Vector3(-0.4 + rng.randf() * 0.8, 0.85, -1.0 + rng.randf() * 2.0); pt.add_child(bm)
			_cyl(root, 0.23, 0.04, Vector3(side_x - 0.03, 1.73, -1.0), _mat(Color(0.1, 0.1, 0.1), 0.6)).rotation.z = PI * 0.5
			_cyl(root, 0.18, 0.05, Vector3(side_x - 0.04, 1.73, -1.0), _mat(Color(0.8, 0.2, 0.15), 0.6)).rotation.z = PI * 0.5
			_box(root, Vector3(0.9, 1.6, 0.6), Vector3(side_x - 0.45, 0.8, D * 0.3), _mat(acc.darkened(0.2), 0.4, 0.6), true)   # jukebox
			for i in 3:
				var nz := -D * 0.32 + i * D * 0.32
				_label(root, ["COLD BEER", "OPEN", "LITE"][i], Vector3(-side_x + 0.05, 2.25, nz), Color.from_hsv(rng.randf(), 0.8, 1.0), 64, 0.006, PI * 0.5)
