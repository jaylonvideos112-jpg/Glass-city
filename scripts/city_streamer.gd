extends Node3D
## Streams pre-generated city chunks (res://data/chunks/X_Z.bin) around a focus point.
## Chunk data is decoded on worker threads; meshes/colliders are built on the main
## thread with a per-frame budget so driving fast doesn't hitch.

signal chunk_loaded(key: Vector2i)

const DATA_DIR := "res://data/"
@export var load_radius_m := 650.0
@export var unload_radius_m := 900.0
@export var builds_per_frame := 2

var manifest: Dictionary
var chunk_size := 200.0
var available := {}          # Vector2i -> true
var loaded := {}             # Vector2i -> Node3D
var pending := {}            # Vector2i -> task id
var decoded := {}            # Vector2i -> Dictionary (ready to build)
var _mutex := Mutex.new()
var world_offset := Vector3.ZERO   # world-space position of this node's origin (origin rebasing)

var materials := {}
## Surfaces that take the real aerial photo (ground cover and every roof).
const AERIAL_LAYERS := {"lot": true, "grass": true, "parking": true, "industrial": true, "forest_floor": true,
	"roof": true, "shingle": true, "shingle_red": true, "copper_green": true}
var _aerial_shader: Shader = preload("res://shaders/aerial.gdshader")
var _detail_tex: Texture2D = preload("res://textures/parking.png")
var label_font_size := 96
var lamp_bulb_mat: StandardMaterial3D = null
var bars: Node = null   # bars.gd: builds bar exteriors and handles enter/exit

func _ready() -> void:
	var f := FileAccess.open(DATA_DIR + "manifest.json", FileAccess.READ)
	manifest = JSON.parse_string(f.get_as_text())
	chunk_size = manifest["chunk_size"]
	for c in manifest["chunks"]:
		available[Vector2i(int(c[0]), int(c[1]))] = true
	_make_materials()

# ------------------------------------------------------------------ materials
func _tex_mat(tex: String, tint := Color.WHITE, rough := 0.9) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_texture = load("res://textures/%s.png" % tex)
	m.albedo_color = tint
	m.roughness = rough
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	var ep := "res://textures/%s_emit.png" % tex
	if ResourceLoader.exists(ep):
		# lit windows at night: time_of_day.gd drives emission_energy_multiplier
		m.emission_enabled = true
		m.emission_texture = load(ep)
		m.emission = Color.WHITE
		m.emission_operator = BaseMaterial3D.EMISSION_OP_MULTIPLY   # ADD would light the whole wall
		m.emission_energy_multiplier = 0.0
	return m

func _make_materials() -> void:
	materials["brick_red"] = _tex_mat("brick_red")
	materials["brick_brown"] = _tex_mat("brick_brown")
	materials["brick_tan"] = _tex_mat("brick_tan")
	materials["warehouse"] = _tex_mat("warehouse")
	materials["glass"] = _tex_mat("glass", Color.WHITE, 0.15)
	materials["glass"].metallic = 0.6
	materials["concrete"] = _tex_mat("concrete")
	var tints := [Color(0.95, 0.95, 0.92), Color(0.75, 0.82, 0.9), Color(0.92, 0.85, 0.65),
		Color(0.7, 0.8, 0.7), Color(0.85, 0.7, 0.68), Color(0.8, 0.78, 0.75)]
	for i in tints.size():
		materials["siding%d" % i] = _tex_mat("siding", tints[i])
	materials["roof"] = _tex_mat("roof")
	var fac := ShaderMaterial.new()
	fac.shader = load("res://shaders/facade.gdshader")
	var nt := NoiseTexture2D.new()
	var fnl := FastNoiseLite.new()
	fnl.frequency = 0.08
	nt.noise = fnl
	nt.seamless = true
	nt.width = 256
	nt.height = 256
	fac.set_shader_parameter("noise_tex", nt)
	materials["facade"] = fac
	# county-record house facades: era texture x paint tint (tints mirror ERA_TINTS in tools/build_city.py)
	var era_tints := {"old": ["#e9e3d2", "#c8b386", "#7f8d6f", "#9b5c4b", "#61748a", "#d8c27c", "#5e6b5a", "#efe8d8"],
		"mid": ["#eeeadc", "#bab29b", "#8f9c86", "#c6a679", "#7f90a2", "#e6dcc1", "#a8826a", "#f3efe4"],
		"post": ["#f2f0ea", "#cfd3cf", "#a3b3c1", "#e3d6b5", "#b9aa92", "#a7b59c", "#e9e4d4", "#c9c2b2"],
		"new": ["#f4f2ec", "#d9d5c9", "#c3c5c0", "#b7ab95", "#8f9ba4", "#e8e0cc", "#a6a294", "#d2c6ad"]}
	for era in era_tints:
		var etints: Array = era_tints[era]
		for i in etints.size():
			materials["h_clap_%s#%d" % [era, i]] = _tex_mat("h_clap_" + era, Color(etints[i]))
			materials["h_lap#%s%d" % [era, i]] = _tex_mat("h_lap_plain", Color(etints[i]))
		materials["h_brick_" + era] = _tex_mat("h_brick_" + era)
	for nm in ["h_stucco", "h_stone", "h_block"]:
		materials[nm] = _tex_mat(nm)
	for nm in ["bar_shooters", "bar_anchor", "bar_cardboard", "bar_easypour", "bar_velvet", "bar_lakefront", "bar_coyote", "bar_gator",
			"dive_twobuck", "dive_dollar", "dive_cornertap", "dive_happyhour", "dive_tipsytom", "dive_bar", "dive_lastcall"]:
		materials[nm] = _tex_mat(nm)
	materials["asphalt"] = _tex_mat("asphalt", Color.WHITE, 0.95)
	materials["sidewalk"] = _tex_mat("sidewalk", Color(0.78, 0.77, 0.75))
	materials["lot"] = _tex_mat("grass", Color(0.7, 0.72, 0.62))
	materials["grass"] = _tex_mat("grass", Color(0.85, 0.9, 0.8))
	materials["parking"] = _tex_mat("parking")
	materials["riverbed"] = _tex_mat("riverbed")
	materials["seawall"] = _tex_mat("seawall")
	materials["concrete_dk"] = _tex_mat("sidewalk", Color(0.75, 0.75, 0.75))
	materials["rail"] = _tex_mat("rail")
	materials["shingle"] = _tex_mat("shingle")
	materials["metal"] = _tex_mat("metal", Color.WHITE, 0.6)
	materials["forest_floor"] = _tex_mat("forest_floor")
	materials["industrial"] = _tex_mat("industrial")
	for n in ["copper_green", "shingle_red", "storefront", "limestone", "granite_black", "yamasaki", "terracotta", "sandstone", "marble", "seats", "porch"]:
		materials[n] = _tex_mat(n)
	for n in ["intl_dark", "glass_oneseagate", "glass_dark", "glass_blue"]:
		materials[n] = _tex_mat(n, Color.WHITE, 0.18)
		materials[n].metallic = 0.45
	materials["bridge_blue"] = _tex_mat("bridge_blue", Color.WHITE, 0.5)
	materials["bridge_blue"].metallic = 0.3
	materials["cable"] = _tex_mat("cable", Color.WHITE, 0.4)
	var gl := _tex_mat("glass_lit", Color.WHITE, 0.1)
	gl.emission_enabled = true
	gl.emission = Color(0.45, 0.9, 0.85)
	gl.emission_energy_multiplier = 0.9
	materials["glass_lit"] = gl
	var y := StandardMaterial3D.new()
	y.albedo_color = Color(0.95, 0.78, 0.15)
	materials["yellowline"] = y
	var w := StandardMaterial3D.new()
	w.albedo_color = Color(0.17, 0.32, 0.38, 0.82)
	w.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	w.roughness = 0.08
	w.metallic = 0.3
	w.cull_mode = BaseMaterial3D.CULL_DISABLED
	materials["water"] = w
	materials["pillar"] = materials["concrete_dk"]
	var hv := StandardMaterial3D.new()
	hv.albedo_color = Color(0.6, 0.62, 0.62)
	materials["hvac"] = hv

# ------------------------------------------------------------------ coordinates
## World (un-rebased) position -> chunk key. Plan north = -Z.
func key_for_world(p: Vector3) -> Vector2i:
	return Vector2i(floori(p.x / chunk_size), floori(-p.z / chunk_size))

func chunk_world_origin(k: Vector2i) -> Vector3:
	return Vector3(k.x * chunk_size, 0, -k.y * chunk_size)

# ------------------------------------------------------------------ streaming
func update_focus(world_pos: Vector3) -> void:
	var r := int(ceil(load_radius_m / chunk_size))
	var ck := key_for_world(world_pos)
	var want: Array[Vector2i] = []
	for dx in range(-r, r + 1):
		for dz in range(-r, r + 1):
			var k := ck + Vector2i(dx, dz)
			if not available.has(k) or loaded.has(k) or pending.has(k):
				continue
			var center := chunk_world_origin(k) + Vector3(chunk_size * 0.5, 0, -chunk_size * 0.5)
			if Vector2(center.x - world_pos.x, center.z - world_pos.z).length() < load_radius_m + chunk_size * 0.7:
				want.append(k)
	want.sort_custom(func(a, b): return (a - ck).length_squared() < (b - ck).length_squared())
	for k in want:
		_request(k)
	# unload far chunks
	for k in loaded.keys():
		var center := chunk_world_origin(k) + Vector3(chunk_size * 0.5, 0, -chunk_size * 0.5)
		if Vector2(center.x - world_pos.x, center.z - world_pos.z).length() > max(unload_radius_m, load_radius_m + 250.0) + chunk_size:
			loaded[k].queue_free()
			loaded.erase(k)

func _request(k: Vector2i) -> void:
	pending[k] = WorkerThreadPool.add_task(_decode.bind(k))

## Read and decode one chunk file (no aerial image). Returns {} if missing or corrupt. Thread-safe.
func read_chunk(k: Vector2i) -> Dictionary:
	var bytes := FileAccess.get_file_as_bytes(DATA_DIR + "chunks/%d_%d.bin" % [k.x, k.y])
	if bytes.size() > 8 and bytes.slice(0, 4).get_string_from_ascii() == "TCZ1":
		var size := bytes.decode_u32(4)
		bytes = bytes.slice(8).decompress(size, FileAccess.COMPRESSION_DEFLATE)
	var d = bytes_to_var(bytes) if bytes.size() > 0 else null
	return d if d is Dictionary else {}

func _decode(k: Vector2i) -> void:
	var d = read_chunk(k)
	if d.is_empty(): d = null
	var jp := DATA_DIR + "aerial/%d_%d.jpg" % [k.x, k.y]
	if d != null and FileAccess.file_exists(jp):
		var img := Image.new()
		if img.load_jpg_from_buffer(FileAccess.get_file_as_bytes(jp)) == OK:
			img.generate_mipmaps()
			d["aerial_img"] = img
	_mutex.lock()
	decoded[k] = d
	_mutex.unlock()

func _process(_dt: float) -> void:
	var built := 0
	while built < builds_per_frame:
		_mutex.lock()
		var keys := decoded.keys()
		if keys.is_empty():
			_mutex.unlock()
			break
		var k: Vector2i = keys[0]
		var d: Dictionary = decoded[k]
		decoded.erase(k)
		_mutex.unlock()
		WorkerThreadPool.wait_for_task_completion(pending[k])
		pending.erase(k)
		_build(k, d)
		built += 1

func is_idle() -> bool:
	return pending.is_empty()

## Load everything around a point synchronously (used at spawn/teleport).
func load_now(world_pos: Vector3) -> void:
	update_focus(world_pos)
	while not pending.is_empty():
		for k in pending.keys():
			WorkerThreadPool.wait_for_task_completion(pending[k])
			pending.erase(k)
			_mutex.lock()
			var d = decoded.get(k)
			decoded.erase(k)
			_mutex.unlock()
			if d != null:
				_build(k, d)

func _build(k: Vector2i, d: Dictionary) -> void:
	var root := Node3D.new()
	root.name = "chunk_%d_%d" % [k.x, k.y]
	root.position = chunk_world_origin(k) - world_offset
	root.set_meta("streets", d["streets"])
	var mesh := ArrayMesh.new()
	var nsurf := 0
	var aerial_mat: ShaderMaterial = null
	if d.has("aerial_img"):
		aerial_mat = ShaderMaterial.new()
		aerial_mat.shader = _aerial_shader
		aerial_mat.set_shader_parameter("aerial", ImageTexture.create_from_image(d["aerial_img"]))
		aerial_mat.set_shader_parameter("detail", _detail_tex)
		aerial_mat.set_shader_parameter("chunk_size", chunk_size)
	for layer in d["layers"]:
		var arrays := []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = layer["v"]
		arrays[Mesh.ARRAY_NORMAL] = layer["n"]
		arrays[Mesh.ARRAY_TEX_UV] = layer["uv"]
		var fmt := 0
		if layer.has("color"):
			arrays[Mesh.ARRAY_TEX_UV2] = layer["uv2"]
			arrays[Mesh.ARRAY_COLOR] = layer["color"]
			arrays[Mesh.ARRAY_CUSTOM0] = layer["c0"]
			fmt = Mesh.ARRAY_CUSTOM_RGBA_FLOAT << Mesh.ARRAY_FORMAT_CUSTOM0_SHIFT
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays, [], {}, fmt)
		var m: Material = materials.get(layer["mat"], materials["concrete"])
		if aerial_mat != null and AERIAL_LAYERS.has(layer["mat"]):
			m = aerial_mat
		mesh.surface_set_material(nsurf, m)
		nsurf += 1
	if nsurf > 0:
		var mi := MeshInstance3D.new()
		mi.mesh = mesh
		root.add_child(mi)
	var col: PackedVector3Array = d["col"]
	if col.size() >= 3:
		var body := StaticBody3D.new()
		var cs := CollisionShape3D.new()
		var shape := ConcavePolygonShape3D.new()
		shape.backface_collision = true
		shape.set_faces(col)
		cs.shape = shape
		body.add_child(cs)
		root.add_child(body)
	var trees := []
	var lamps := []
	for p in d["props"]:
		if p[0] == "tree": trees.append(p)
		elif p[0] == "lamp": lamps.append(p)
		else: _add_prop(root, p)
	if not trees.is_empty():
		root.add_child(_multimesh(_tree_mesh(), trees, true))
	if not lamps.is_empty():
		root.add_child(_multimesh(_lamp_mesh(), lamps, false))
		# night light pools on the ground + head positions for street_lights.gd
		var heads: Array = []
		var pools: Array = []
		for p in lamps:
			var b := Basis(Vector3.UP, p[4])
			heads.append(Vector3(p[1], p[3], p[2]) + b * Vector3(0, 6.6, -2.1))
			var g: Vector3 = Vector3(p[1], p[3], p[2]) + b * Vector3(0, 0.07, -2.1)
			pools.append(["pool", g.x, g.z, g.y, 0.0])
		root.set_meta("lamp_heads", heads)
		var pm := _multimesh(_pool_mesh(), pools, false)
		pm.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		pm.visibility_range_end = 450.0
		pm.name = "lamp_pools"
		root.add_child(pm)
		for p in lamps:
			var body := StaticBody3D.new()
			var cs := CollisionShape3D.new()
			var cyl := CylinderShape3D.new(); cyl.radius = 0.15; cyl.height = 7.0
			cs.shape = cyl
			body.position = Vector3(p[1], 3.5, p[2])
			body.add_child(cs)
			root.add_child(body)
	for l in d["labels"]:
		var lab := Label3D.new()
		lab.text = l[0]
		lab.font_size = label_font_size
		lab.pixel_size = 0.03
		lab.outline_size = 18
		lab.modulate = Color(1, 0.96, 0.85)
		lab.billboard = BaseMaterial3D.BILLBOARD_FIXED_Y
		lab.position = Vector3(l[1], l[3], l[2])
		lab.visibility_range_end = 700.0
		root.add_child(lab)
	if bars != null and d.has("bars"):
		for b in d["bars"]:
			bars.add_exterior(root, b)
	add_child(root)
	loaded[k] = root
	chunk_loaded.emit(k)

func _add_prop(root: Node3D, p: Array) -> void:
	var kind: String = p[0]
	var mi := MeshInstance3D.new()
	var bm := BoxMesh.new()
	if kind == "pillar":
		var h: float = p[3]
		bm.size = Vector3(1.4, h, 1.4)
		mi.position = Vector3(p[1], h * 0.5, p[2])
		mi.material_override = materials["pillar"]
		var body := StaticBody3D.new()
		var cs := CollisionShape3D.new()
		var bs := BoxShape3D.new()
		bs.size = bm.size
		cs.shape = bs
		body.add_child(cs)
		mi.add_child(body)
	elif kind == "hvac":
		var s: float = 2.0 + p[4] * 3.0
		bm.size = Vector3(s, 1.6, s * 0.7)
		mi.position = Vector3(p[1], p[3] + 0.8, p[2])
		mi.material_override = materials["hvac"]
	mi.mesh = bm
	root.add_child(mi)

var _tree_cache: ArrayMesh
var _lamp_cache: ArrayMesh

func _multimesh(mesh: Mesh, items: Array, scale_from_data: bool) -> MultiMeshInstance3D:
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = mesh
	mm.instance_count = items.size()
	for i in items.size():
		var p: Array = items[i]
		var b := Basis()
		if scale_from_data:
			b = Basis(Vector3.UP, float(i) * 1.7).scaled(Vector3.ONE * p[4])
		else:
			b = Basis(Vector3.UP, p[4])
		mm.set_instance_transform(i, Transform3D(b, Vector3(p[1], p[3], p[2])))
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	mmi.visibility_range_end = 600.0
	return mmi

func _merge_into(st: SurfaceTool, m: PrimitiveMesh, xf: Transform3D) -> void:
	st.append_from(m, 0, xf)

func _tree_mesh() -> ArrayMesh:
	if _tree_cache: return _tree_cache
	var am := ArrayMesh.new()
	var trunk := CylinderMesh.new(); trunk.top_radius = 0.18; trunk.bottom_radius = 0.28; trunk.height = 3.0; trunk.radial_segments = 6; trunk.rings = 1
	var crown := SphereMesh.new(); crown.radius = 2.6; crown.height = 4.6; crown.radial_segments = 7; crown.rings = 4
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES); st.append_from(trunk, 0, Transform3D(Basis(), Vector3(0, 1.5, 0)))
	st.commit(am)
	var st2 := SurfaceTool.new(); st2.begin(Mesh.PRIMITIVE_TRIANGLES); st2.append_from(crown, 0, Transform3D(Basis(), Vector3(0, 4.6, 0)))
	st2.commit(am)
	var tm := StandardMaterial3D.new(); tm.albedo_color = Color(0.33, 0.24, 0.16)
	var cm := StandardMaterial3D.new(); cm.albedo_color = Color(0.22, 0.42, 0.18); cm.roughness = 1.0
	am.surface_set_material(0, tm); am.surface_set_material(1, cm)
	_tree_cache = am
	return am

var _pool_cache: PlaneMesh
func _pool_mesh() -> PlaneMesh:
	if _pool_cache: return _pool_cache
	_pool_cache = PlaneMesh.new()
	_pool_cache.size = Vector2(15, 15)
	var m := ShaderMaterial.new()
	m.shader = load("res://shaders/lamp_pool.gdshader")
	_pool_cache.material = m
	return _pool_cache

func _lamp_mesh() -> ArrayMesh:
	if _lamp_cache: return _lamp_cache
	var am := ArrayMesh.new()
	var pole := CylinderMesh.new(); pole.top_radius = 0.08; pole.bottom_radius = 0.12; pole.height = 7.0; pole.radial_segments = 6; pole.rings = 1
	var arm := BoxMesh.new(); arm.size = Vector3(0.12, 0.12, 2.2)
	var head := BoxMesh.new(); head.size = Vector3(0.4, 0.18, 0.8)
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	st.append_from(pole, 0, Transform3D(Basis(), Vector3(0, 3.5, 0)))
	st.append_from(arm, 0, Transform3D(Basis(), Vector3(0, 6.9, -1.1)))
	st.append_from(head, 0, Transform3D(Basis(), Vector3(0, 6.8, -2.1)))
	st.commit(am)
	var m := StandardMaterial3D.new(); m.albedo_color = Color(0.22, 0.24, 0.25); m.metallic = 0.5; m.roughness = 0.5
	am.surface_set_material(0, m)
	var bulb := BoxMesh.new(); bulb.size = Vector3(0.3, 0.04, 0.6)
	var st2 := SurfaceTool.new(); st2.begin(Mesh.PRIMITIVE_TRIANGLES)
	st2.append_from(bulb, 0, Transform3D(Basis(), Vector3(0, 6.7, -2.1)))
	st2.commit(am)
	lamp_bulb_mat = StandardMaterial3D.new()
	lamp_bulb_mat.albedo_color = Color(0.9, 0.85, 0.7)
	lamp_bulb_mat.emission_enabled = true
	lamp_bulb_mat.emission = Color(1.0, 0.78, 0.45)   # sodium-ish warm white
	lamp_bulb_mat.emission_energy_multiplier = 0.0
	am.surface_set_material(1, lamp_bulb_mat)
	_lamp_cache = am
	return am

# ------------------------------------------------------------------ queries
## Nearest named street to a world position (searches loaded chunks around it).
func street_at(world_pos: Vector3, max_dist := 25.0) -> Dictionary:
	var best := {"name": "", "dist": max_dist, "dir": Vector3.ZERO, "point": Vector3.ZERO}
	var ck := key_for_world(world_pos)
	for dx in range(-1, 2):
		for dz in range(-1, 2):
			var k := ck + Vector2i(dx, dz)
			if not loaded.has(k):
				continue
			var o := chunk_world_origin(k)
			for s in loaded[k].get_meta("streets"):
				var a := Vector3(o.x + s[1], 0, o.z + s[2])
				var b := Vector3(o.x + s[3], 0, o.z + s[4])
				var q := Geometry3D.get_closest_point_to_segment(Vector3(world_pos.x, 0, world_pos.z), a, b)
				var dd := q.distance_to(Vector3(world_pos.x, 0, world_pos.z))
				if dd < best["dist"]:
					best = {"name": s[0], "dist": dd, "dir": (b - a).normalized(), "point": q}
	return best

## Street segments (world coords) near a point, for the radar.
func segments_near(world_pos: Vector3, radius: float) -> Array:
	var out := []
	var r := int(ceil(radius / chunk_size))
	var ck := key_for_world(world_pos)
	for dx in range(-r, r + 1):
		for dz in range(-r, r + 1):
			var k := ck + Vector2i(dx, dz)
			if not loaded.has(k):
				continue
			var o := chunk_world_origin(k)
			for s in loaded[k].get_meta("streets"):
				out.append([Vector2(o.x + s[1], o.z + s[2]), Vector2(o.x + s[3], o.z + s[4]), s[0]])
	return out
