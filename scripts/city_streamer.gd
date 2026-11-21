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
const AERIAL_LAYERS := {"lot": true, "grass": true, "lawn": true, "drive": true, "parking": true, "industrial": true, "forest_floor": true,
	"roof": true, "shingle": true, "shingle_red": true, "copper_green": true}
var _aerial_shader: Shader = preload("res://shaders/aerial.gdshader")
var _detail_tex: Texture2D = preload("res://textures/parking.png")
## ground layers drawn from the aerial photo, and how much photo to keep (the rest is a clean tiled texture)
## photo_mix -1 = classify mode (photo only picks lawn vs paved), 0 = clean texture only.
## [photo_mix, clean set, clean tile metres]; sets are CC0 Poly Haven scans in textures/pbr/
const PHOTO_MIX := {"lot": [-1.0, "brushed_concrete", 2.5], "parking": [0.0, "asphalt_04", 3.0], "industrial": [0.0, "brushed_concrete", 2.5],
	"grass": [0.0, "grass_ground", 2.5], "forest_floor": [0.0, "forest_leaves_02", 2.5],
	"lawn": [0.0, "grass_ground", 2.2], "drive": [0.0, "brushed_concrete", 2.0],
	"shingle": [2.0, "grey_roof_01", 1.0]}   # 2 = sloped roof: aerial colour, asphalt-shingle relief along the roof UVs   # residential yards (build_city yards())
const LAWN_TINT := Color(0.28, 0.5, 0.16)
var _pbr_cache := {}
func pbr(set_name: String) -> Dictionary:
	if not _pbr_cache.has(set_name):
		var b := "res://textures/pbr/%s_" % set_name
		_pbr_cache[set_name] = {"diff": load(Look.t(b + "diff.jpg")), "nor": load(b + "nor.jpg"), "rough": load(b + "rough.jpg")}
	return _pbr_cache[set_name]
func ground_mat(set_name: String, tile_m: float, tint := Color.WHITE, tint_mix := 0.0, bright := 1.0, break_tiling := 1.0) -> ShaderMaterial:
	var t := pbr(set_name)
	var m := ShaderMaterial.new(); m.shader = load("res://shaders/ground_pbr.gdshader")
	m.set_shader_parameter("albedo_tex", t["diff"]); m.set_shader_parameter("normal_tex", t["nor"]); m.set_shader_parameter("rough_tex", t["rough"])
	m.set_shader_parameter("tile_m", tile_m); m.set_shader_parameter("tint", tint); m.set_shader_parameter("tint_mix", tint_mix)
	m.set_shader_parameter("brightness", bright); m.set_shader_parameter("break_tiling", break_tiling)
	m.set_shader_parameter("normal_strength", Look.normal_k())
	return m
var label_font_size := 96
var lamp_bulb_mat: StandardMaterial3D = null
var bars: Node = null   # bars.gd: builds bar exteriors and handles enter/exit
const Hlod := preload("res://scripts/hlod.gd")
const ModelLib := preload("res://scripts/model_lib.gd")
const StreetFurniture := preload("res://scripts/street_furniture.gd")
const UtilityWires := preload("res://scripts/utility_wires.gd")
var grass: Node = null   # grass.gd: 3D grass blades on lawns near the camera (set by main.gd)
var hlod: Node3D = null   # far-distance low-detail city (hlod.gd); off with --no-hlod

func _ready() -> void:
	var f := FileAccess.open(DATA_DIR + "manifest.json", FileAccess.READ)
	manifest = JSON.parse_string(f.get_as_text())
	chunk_size = manifest["chunk_size"]
	for c in manifest["chunks"]:
		available[Vector2i(int(c[0]), int(c[1]))] = true
	_make_materials()
	if not OS.get_cmdline_user_args().has("--no-hlod"):
		hlod = Hlod.new(); hlod.name = "HLOD"
		add_child(hlod)
		hlod.position = -world_offset
		hlod.setup(self)

# ------------------------------------------------------------------ materials
## Paint palette measured from county reference photos (data/house_palette.json, written by the city build).
var _house_pal := {}
const ERA_PAINT := {"old": ["#e9e3d2", "#c8b386", "#7f8d6f", "#9b5c4b", "#61748a", "#d8c27c", "#5e6b5a", "#efe8d8"],
	"mid": ["#eeeadc", "#bab29b", "#8f9c86", "#c6a679", "#7f90a2", "#e6dcc1", "#a8826a", "#f3efe4"],
	"post": ["#f2f0ea", "#cfd3cf", "#a3b3c1", "#e3d6b5", "#b9aa92", "#a7b59c", "#e9e4d4", "#c9c2b2"],
	"new": ["#f4f2ec", "#d9d5c9", "#c3c5c0", "#b7ab95", "#8f9ba4", "#e8e0cc", "#a6a294", "#d2c6ad"]}
const BRICK_TONE := {"old": Color(1.0, 0.93, 0.88), "mid": Color(1, 1, 1), "post": Color(0.93, 0.86, 0.8), "new": Color(1.08, 1.0, 0.94)}
var _tex_mean := {}
func _mat(name: String) -> Material:
	if materials.has(name): return materials[name]
	var tl := name.find("~")
	if tl > 0:                                  # photo-measured wall colour on a textured wall: "<mat>~rrggbb"
		var base_m = materials.get(name.substr(0, tl))
		var want := Color("#" + name.substr(tl + 1))
		var m2: Material = base_m.duplicate() if base_m != null else StandardMaterial3D.new()
		if m2 is StandardMaterial3D:
			var sm := m2 as StandardMaterial3D
			var mean := Color(0.6, 0.6, 0.6)
			if sm.albedo_texture != null:
				var key := sm.albedo_texture.resource_path
				if not _tex_mean.has(key):
					var img := sm.albedo_texture.get_image()
					if img != null:
						img = img.duplicate(); img.decompress(); img.resize(8, 8, Image.INTERPOLATE_BILINEAR)
						var acc := Color(0, 0, 0)
						for yy in 8:
							for xx in 8: acc += img.get_pixel(xx, yy)
						_tex_mean[key] = acc / 64.0
					else: _tex_mean[key] = mean
				mean = _tex_mean[key] * sm.albedo_color
			var k := Color(clampf(want.r / maxf(mean.r, 0.05), 0.35, 1.9), clampf(want.g / maxf(mean.g, 0.05), 0.35, 1.9), clampf(want.b / maxf(mean.b, 0.05), 0.35, 1.9))
			sm.albedo_color = sm.albedo_color * k
		_mutex.lock(); materials[name] = m2; _mutex.unlock()
		return m2
	if name.begins_with("hsid#"):              # house siding (real lap boards) in an era paint: hsid#<era><i>
		var era := name.substr(5, name.length() - 6); var i := int(name.substr(name.length() - 1))
		materials[name] = _tex_mat("hsid", Color(ERA_PAINT.get(era, ERA_PAINT["mid"])[i]), 0.75)
		return materials[name]
	if name in ["hstu", "hstn", "hblk"]:        # stucco / stone / block houses (3D windows go on top)
		materials[name] = _tex_mat(name, Color(1, 1, 1), 0.9)
		return materials[name]
	if name.begins_with("hbrk_"):
		materials[name] = _tex_mat("hbrk", BRICK_TONE.get(name.substr(5), Color.WHITE), 0.9)
		return materials[name]
	var at := name.find("@")
	if at < 0: return materials["concrete"]
	if _house_pal.is_empty():
		var f := FileAccess.open("res://data/house_palette.json", FileAccess.READ)
		_house_pal = JSON.parse_string(f.get_as_text()) if f else {"wall": [], "trim": []}
	var base := name.substr(0, at); var i := int(name.substr(at + 1))
	var pal: Array = _house_pal.get("trim" if base == "trim" else "wall", [])
	var col := Color(pal[i]) if i < pal.size() else Color(0.85, 0.84, 0.8)
	var m: Material
	_mutex.lock()
	if base == "trim":
		var t := StandardMaterial3D.new(); t.albedo_color = col; t.roughness = 0.7; m = t
	elif base == "hsid":
		m = _tex_mat("hsid", col, 0.75)
	elif base == "h_lap":
		m = _tex_mat("h_lap_plain", col)
	else:
		m = _tex_mat(base, col)        # h_clap_<era>
	materials[name] = m
	_mutex.unlock()
	return m

func _tex_mat(tex: String, tint := Color.WHITE, rough := 0.9) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_texture = load(Look.t("res://textures/%s.png" % tex))
	m.albedo_color = tint
	m.roughness = rough
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	var np_ := "res://textures/%s_nor.png" % tex
	if ResourceLoader.exists(np_):
		m.normal_enabled = true; m.normal_texture = load(np_); m.normal_scale = Look.normal_k()
	var rp := "res://textures/%s_rough.png" % tex
	if ResourceLoader.exists(rp):
		# windows are glossy and a little metallic, so they pick up the sky; walls stay matte
		var rt: Texture2D = load(rp)
		m.roughness_texture = rt; m.roughness_texture_channel = BaseMaterial3D.TEXTURE_CHANNEL_RED
		m.roughness = 1.0
		m.metallic_texture = rt; m.metallic_texture_channel = BaseMaterial3D.TEXTURE_CHANNEL_GREEN
		m.metallic = 1.0; m.metallic_specular = 0.6
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
	# dirt, splash-back and drips along the base of house walls (a transparent band just in front of the wall)
	var gm := StandardMaterial3D.new()
	gm.albedo_texture = load("res://textures/grime_base.png")
	gm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA; gm.depth_draw_mode = BaseMaterial3D.DEPTH_DRAW_DISABLED
	gm.roughness = 1.0; gm.cull_mode = BaseMaterial3D.CULL_BACK; gm.render_priority = 1
	materials["grime_base"] = gm
	# back-yard fences (build_city.py emit_fence): galvanized chain-link (alpha-tested) and weathered privacy boards
	var cl := StandardMaterial3D.new()
	cl.albedo_texture = load("res://textures/chainlink.png"); cl.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
	cl.alpha_scissor_threshold = 0.5; cl.cull_mode = BaseMaterial3D.CULL_DISABLED; cl.metallic = 0.5; cl.roughness = 0.5
	cl.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	materials["chainlink"] = cl
	var fw := StandardMaterial3D.new()
	fw.albedo_texture = load(Look.t("res://textures/fence_wood.png")); fw.cull_mode = BaseMaterial3D.CULL_DISABLED; fw.roughness = 0.95
	materials["fence_wood"] = fw
	var fmt := StandardMaterial3D.new(); fmt.albedo_color = Color(0.62, 0.64, 0.63); fmt.metallic = 0.6; fmt.roughness = 0.45
	materials["fence_metal"] = fmt
	var fpo := StandardMaterial3D.new(); fpo.albedo_color = Color(0.42, 0.33, 0.24); fpo.roughness = 0.95
	materials["fence_post"] = fpo
	materials["sand"] = ground_mat("coast_sand_01", 2.5)   # island beaches
	var trim := StandardMaterial3D.new(); trim.albedo_color = Color(0.88, 0.87, 0.83); trim.roughness = 0.7
	materials["trim_white"] = trim                                  # fascia, soffits, rake boards
	materials["foundation"] = _tex_mat("concrete", Color(0.72, 0.71, 0.68))
	# sports courts / ball fields / playgrounds (OSM leisure=pitch, playground)
	for cm in [["court_green", Color(0.24, 0.42, 0.32), 0.75], ["court_blue", Color(0.20, 0.33, 0.52), 0.75], ["court_red", Color(0.55, 0.24, 0.20), 0.8],
			["infield", Color(0.56, 0.40, 0.28), 0.95], ["mulch", Color(0.36, 0.25, 0.16), 1.0], ["paint_line", Color(0.93, 0.93, 0.9), 0.7]]:
		var sm := StandardMaterial3D.new(); sm.albedo_color = cm[1]; sm.roughness = cm[2]
		materials[cm[0]] = sm
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
	# photo wall materials for the parametric facades
	for pair in [["brick", "red_brick_03"], ["stone", "large_sandstone_blocks"], ["conc", "concrete_wall_008"], ["metal", "box_profile_metal_sheet"]]:
		var ps := pbr(pair[1])
		fac.set_shader_parameter(pair[0] + "_tex", ps["diff"]); fac.set_shader_parameter(pair[0] + "_nor", ps["nor"])
		var im: Image = (ps["diff"] as Texture2D).get_image()
		if im != null:
			if im.is_compressed(): im.decompress()
			im.resize(1, 1, Image.INTERPOLATE_BILINEAR)
			var mc: Color = im.get_pixel(0, 0).srgb_to_linear()
			fac.set_shader_parameter(pair[0] + "_mean", Vector3(mc.r, mc.g, mc.b))
	fac.set_shader_parameter("use_photo", 1.0)
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
		_mat("hbrk_" + era)
		for i in 8: _mat("hsid#%s%d" % [era, i])
	# photo-measured paint (eager so the far-city HLOD sees their colours too)
	if FileAccess.file_exists("res://data/house_palette.json"):
		var pal = JSON.parse_string(FileAccess.get_file_as_string("res://data/house_palette.json"))
		for i in pal["wall"].size():
			_mat("hsid@%d" % i)
		for i in pal["trim"].size(): _mat("trim@%d" % i)
	for nm in ["h_stucco", "h_stone", "h_block"]:
		materials[nm] = _tex_mat(nm)
	for nm in ["bar_shooters", "bar_anchor", "bar_cardboard", "bar_easypour", "bar_velvet", "bar_lakefront", "bar_coyote", "bar_gator",
			"dive_twobuck", "dive_dollar", "dive_cornertap", "dive_happyhour", "dive_tipsytom", "dive_bar", "dive_lastcall"]:
		materials[nm] = _tex_mat(nm)
	materials["asphalt"] = ground_mat("asphalt_02", 3.0, Color.WHITE, 0.0, 0.95)
	if Look.bully(): materials["asphalt"].set_shader_parameter("wear", 1.0)    # patches, cracks, tar snakes
	materials["sidewalk"] = ground_mat("concrete_pavement", 1.8, Color.WHITE, 0.0, 1.05, 0.0)
	if Look.bully():      # cracks, gum, dirt drifts, weeds in the cracks
		materials["sidewalk"].set_shader_parameter("wear", 1.0); materials["sidewalk"].set_shader_parameter("wear_mode", 1)
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
	# made-up countryside crop fields: wheat, corn, soy, hay, plowed (crop rows texture, tinted)
	var crop_tints := [Color(0.93, 0.82, 0.5), Color(0.55, 0.74, 0.34), Color(0.4, 0.6, 0.3), Color(0.8, 0.8, 0.5), Color(0.56, 0.43, 0.31)]
	for i in crop_tints.size():
		materials["field%d" % i] = _tex_mat("field", crop_tints[i])
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
				# load whole HLOD regions, so a region is either all-detail or all-far (no holes, no overlap)
				for k2 in hlod.region_chunks(Hlod.region_of(k)) if hlod != null else [k]:
					if not loaded.has(k2) and not pending.has(k2) and not want.has(k2): want.append(k2)
	want.sort_custom(func(a, b): return (a - ck).length_squared() < (b - ck).length_squared())
	for k in want:
		_request(k)
	# unload far chunks
	if hlod != null: hlod.update(world_pos)
	for k in loaded.keys():
		var center := chunk_world_origin(k) + Vector3(chunk_size * 0.5, 0, -chunk_size * 0.5)
		if hlod != null: center = hlod.region_center(Hlod.region_of(k))
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
	_update_tree_lod(_dt)
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
	return pending.is_empty() and (hlod == null or hlod.is_idle())

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
	var _ground_mats := {}
	if d.has("aerial_img"):
		aerial_mat = ShaderMaterial.new()
		aerial_mat.shader = _aerial_shader
		aerial_mat.set_shader_parameter("aerial", ImageTexture.create_from_image(d["aerial_img"]))
		aerial_mat.set_shader_parameter("detail", _detail_tex)
		aerial_mat.set_shader_parameter("chunk_size", chunk_size)
	var grass_tris := PackedVector3Array(); var grass_block := PackedVector3Array()
	for layer in d["layers"]:
		if grass != null:
			if layer["mat"] == "lawn" or layer["mat"] == "grass": grass_tris.append_array(layer["v"])
			elif layer["mat"] in ["drive", "lot", "parking", "plaza", "pavement", "concrete_dk", "sidewalk"]: grass_block.append_array(layer["v"])   # walks/drives laid over the lawn
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
		var m: Material = _mat(String(layer["mat"]))
		if aerial_mat != null and AERIAL_LAYERS.has(layer["mat"]):
			m = aerial_mat
			if PHOTO_MIX.has(layer["mat"]):
				var pm: Array = PHOTO_MIX[layer["mat"]]
				var key2: String = layer["mat"]
				if not _ground_mats.has(key2):
					var gm := aerial_mat.duplicate() as ShaderMaterial
					var cs := pbr(pm[1])
					gm.set_shader_parameter("photo_mix", clampf(pm[0], 0.0, 1.0))
					if pm[0] >= 2.0: gm.set_shader_parameter("roof_uv", 1.0)
					gm.set_shader_parameter("use_pbr", 1.0)
					gm.set_shader_parameter("clean", cs["diff"]); gm.set_shader_parameter("clean_nor", cs["nor"]); gm.set_shader_parameter("clean_rough", cs["rough"])
					gm.set_shader_parameter("clean_scale", 1.0 / float(pm[2]))
					if layer["mat"] == "grass" or layer["mat"] == "lawn":
						gm.set_shader_parameter("alt_tint", LAWN_TINT); gm.set_shader_parameter("alt_tint_mix", 0.7)
					if pm[0] < 0.0:
						var gs := pbr("grass_ground")
						gm.set_shader_parameter("classify", 1.0)
						gm.set_shader_parameter("alt", gs["diff"]); gm.set_shader_parameter("alt_nor", gs["nor"]); gm.set_shader_parameter("alt_rough", gs["rough"])
						gm.set_shader_parameter("alt_scale", 1.0 / 2.5)
						gm.set_shader_parameter("alt_tint", LAWN_TINT); gm.set_shader_parameter("alt_tint_mix", 0.7)
					_ground_mats[key2] = gm
				m = _ground_mats[key2]
		mesh.surface_set_material(nsurf, m)
		nsurf += 1
	if nsurf > 0:
		var mi := MeshInstance3D.new()
		mi.mesh = mesh
		root.add_child(mi)
	if grass != null and grass_tris.size() > 0: grass.add_chunk(root, grass_tris, grass_block)
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
	var models := {}
	var wires := []
	for p in d["props"]:
		if p[0] == "tree": trees.append(p)
		elif String(p[0]).begins_with("wire"): wires.append(p)
		elif p[0] == "lamp": lamps.append(p)
		elif String(p[0]).begins_with("m:"):      # Blender model prop (park equipment ...): batch per model
			if not models.has(p[0]): models[p[0]] = []
			models[p[0]].append(p)
		else: _add_prop(root, p)
	var npoles := 0
	for mk in models:
		var mname := String(mk).substr(2)
		if mname.begins_with("util_pole"): npoles += models[mk].size()
		var swap := {}
		if mname.begins_with("hp_"): swap = {"hp_glass": _window_mat()}    # lived-in panes (curtains, blinds, rooms)
		var mm_mesh := ModelLib.mesh(mname, swap)
		if mm_mesh: 
			var mmi := _multimesh(mm_mesh, models[mk], false)
			mmi.visibility_range_end = 350.0
			root.add_child(mmi)
	root.set_meta("poles", npoles)
	var wmi := UtilityWires.build(wires, chunk_world_origin(k))
	if wmi: root.add_child(wmi)
	if not trees.is_empty():
		# two species of photo-real billboard trees (baked from CC0 Poly Haven models)
		var tA: Array = []; var tB: Array = []
		for tp in trees: (tA if (int(absf(tp[1]) * 7.0 + absf(tp[2]) * 3.0) % 3) != 0 else tB).append(tp)
		for tv in 2:
			var items: Array = tA if tv == 0 else tB
			if items.is_empty(): continue
			var bb := _multimesh(_tree_mesh(tv), items, true)
			var t3 := _tree3d(tv)
			if t3 != null:        # Bully look: real 3D trees in chunks near the camera, billboards further out
				var near := _multimesh(t3, items, true)
				near.visible = false
				root.add_child(near)
				_tree_lod.append([root, near, bb])
			root.add_child(bb)
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
		StreetFurniture.add_to(root, lamps)
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
	root.set_meta("roads", d.get("roads", []))
	root.set_meta("ix", d.get("ix", []))
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
		mi.position = Vector3(p[1], h * 0.5 + (float(p[4]) if p.size() > 4 and kind == "pillar" and p[4] < 200.0 and h > 0.0 else 0.0), p[2])
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

## house window glass: shaders/window_interior.gdshader paints a different curtain / blind / room on every pane
func _window_mat() -> ShaderMaterial:
	if not materials.has("window"):
		var m := ShaderMaterial.new()
		m.shader = load("res://shaders/window_interior.gdshader")
		materials["window"] = m
	return materials["window"]

func _multimesh(mesh: Mesh, items: Array, scale_from_data: bool) -> MultiMeshInstance3D:
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = mesh
	mm.instance_count = items.size()
	for i in items.size():
		var p: Array = items[i]
		var b := Basis()
		if scale_from_data and p.size() > 5:      # LiDAR tree: [.., height scale, crown scale]
			b = Basis(Vector3.UP, float(i) * 1.7).scaled(Vector3(p[5], p[4], p[5]))
		elif scale_from_data:
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

const TREE_3D_M := 240.0     # chunk centre within this: 3D trees (the chunk is 200 m, so trees up to ~380 m)
var _tree_lod: Array = []     # [chunk root, 3D trees, billboards]
var _tree_lod_t := 0.0
## Swap 3D trees and billboards per chunk by the camera's distance to the chunk centre (twice a second).
func _update_tree_lod(dt: float) -> void:
	_tree_lod_t -= dt
	if _tree_lod_t > 0.0 or _tree_lod.is_empty(): return
	_tree_lod_t = 0.5
	var cam := get_viewport().get_camera_3d()
	if cam == null: return
	var keep: Array = []
	for t in _tree_lod:
		if not is_instance_valid(t[0]): continue
		keep.append(t)
		var vi: VisualInstance3D = t[2]
		var c := vi.global_transform * vi.get_aabb().get_center()
		var d := Vector2(c.x - cam.global_position.x, c.z - cam.global_position.z).length()
		var near := d < TREE_3D_M
		(t[1] as Node3D).visible = near; (t[2] as Node3D).visible = not near
	_tree_lod = keep
var _tree3d_cache := {}
## Bully look: the Blender tree model (tools/blender/bully_trees.py) as one mesh, scaled to the billboard height
## of the same variant, leaves alpha-tested and lit through. null in the classic look or if the model is missing.
func _tree3d(variant: int) -> ArrayMesh:
	if not Look.bully(): return null
	if _tree3d_cache.has(variant): return _tree3d_cache[variant]
	var src := ModelLib.mesh(["bully_tree_a", "bully_tree_c"][variant])
	var out: ArrayMesh = null
	if src != null:
		var k: float = [9.0 / 9.0, 7.0 / 11.0][variant]
		out = ArrayMesh.new()
		for si in src.get_surface_count():
			var st := SurfaceTool.new(); st.create_from(src, si)
			var arr := st.commit_to_arrays()
			var vs: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
			for i in vs.size(): vs[i] = vs[i] * k
			arr[Mesh.ARRAY_VERTEX] = vs
			out.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arr)
			var m0 := src.surface_get_material(si) as BaseMaterial3D
			var m := (m0.duplicate() if m0 else StandardMaterial3D.new()) as BaseMaterial3D
			if m.albedo_texture != null:          # leaf cards
				m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR; m.alpha_scissor_threshold = 0.4
				m.cull_mode = BaseMaterial3D.CULL_DISABLED
				m.backlight_enabled = true; m.backlight = Color(0.42, 0.5, 0.2)     # sun through the leaves: no black crowns against the light
				m.albedo_color = Color(1.12, 1.15, 1.08)
			else:                                 # trunk and branches: painted bark, mapped from world space
				m.albedo_color = Color(1.7, 1.6, 1.5); m.albedo_texture = load("res://textures/bark_painted.png")
				m.uv1_triplanar = true; m.uv1_scale = Vector3(1.2, 0.6, 1.2)
			m.roughness = 0.9; m.metallic_specular = 0.15
			out.surface_set_material(si, m)
	_tree3d_cache[variant] = out
	return out

var _tree_meshes := {}
## A billboard tree: three crossed quads textured with renders of a real tree model (textures/trees, baked by
## tools/dbg/bake_impostor.gd). Normals bend outward from the crown so the canopy shades like a volume.
func _tree_mesh(variant := 0) -> ArrayMesh:
	if _tree_meshes.has(variant): return _tree_meshes[variant]
	var meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(Look.t("res://textures/trees/meta.json")))
	var views: Array = [["tree_small_02_a", "tree_small_02_b"], ["island_tree_02_c", "island_tree_02_d"]][variant]
	var height: float = [9.0, 7.0][variant]
	var am := ArrayMesh.new()
	var angles := [0.0, PI / 3.0, 2.0 * PI / 3.0]
	for vi in 2:
		var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
		var view: String = views[vi]
		var S: float = height / float(meta[view]["h_frac"])
		var cy: float = height * 0.62
		for ai in angles.size():
			if (ai == 1) != (vi == 1): continue          # view b on the middle quad, view a on the others
			var b := Basis(Vector3.UP, angles[ai])
			var corners := [Vector3(-S * 0.5, 0, 0), Vector3(S * 0.5, 0, 0), Vector3(S * 0.5, S, 0), Vector3(-S * 0.5, S, 0)]
			var uvs := [Vector2(0, 1), Vector2(1, 1), Vector2(1, 0), Vector2(0, 0)]
			for k in [0, 1, 2, 0, 2, 3]:
				var v: Vector3 = b * corners[k]
				var n := (v - Vector3(0, cy, 0)).normalized().lerp(Vector3.UP, 0.35).normalized()
				st.set_normal(n); st.set_uv(uvs[k]); st.add_vertex(v)
		st.commit(am)
		var m := StandardMaterial3D.new()
		m.albedo_texture = load(Look.t("res://textures/trees/%s.png" % view))
		m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR; m.alpha_scissor_threshold = 0.45
		m.alpha_antialiasing_mode = BaseMaterial3D.ALPHA_ANTIALIASING_ALPHA_TO_COVERAGE
		m.cull_mode = BaseMaterial3D.CULL_DISABLED; m.roughness = 0.9
		m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
		m.backlight_enabled = true; m.backlight = Color(0.12, 0.16, 0.06)      # light through the leaves
		m.metallic_specular = 0.15
		am.surface_set_material(am.get_surface_count() - 1, m)
	_tree_meshes[variant] = am
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
	if lamp_bulb_mat == null:
		lamp_bulb_mat = StandardMaterial3D.new()
		lamp_bulb_mat.albedo_color = Color(0.9, 0.85, 0.7)
		lamp_bulb_mat.emission_enabled = true
		lamp_bulb_mat.emission = Color(1.0, 0.78, 0.45)
		lamp_bulb_mat.emission_energy_multiplier = 0.0
	var glb := ModelLib.mesh("street_light", {"bulb": lamp_bulb_mat})     # tools/blender/street_props.py
	if glb:
		_lamp_cache = glb
		return glb
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
