extends Node3D
## Far-distance city (HLOD). Beyond the detailed chunks, the city is drawn as merged low-detail meshes: one mesh
## per 2x2-chunk region, one material (vertex colours), no small details (porches, curbs, lines, cables...), no
## shadows and no collision. Built at runtime from the same chunk files on worker threads, so it costs no disk.
## A region's low-detail mesh is shown until every chunk of that region is loaded in detail (the streamer loads
## whole regions), so there are no holes and no double geometry.
## Sits under the streamer at position -world_offset, so region meshes use world coordinates (rebasing shifts us).

const REGION := 2                      # chunks per side
var radius_m := 3200.0                 # how far the low-detail city reaches
var builds_per_frame := 2
## materials left out of the far mesh (small or hidden details)
const SKIP := {"porch": true, "yellowline": true, "cable": true, "hvac": true, "seats": true, "rail": true,
	"riverbed": true, "metal": true, "concrete_dk": true, "pillar": true, "seawall": true}

var streamer: Node3D
var regions := {}         # Vector2i -> MeshInstance3D (null while building)
var pending := {}         # Vector2i -> task id
var decoded := {}         # Vector2i -> Dictionary of arrays, or {} for empty
var colors := {}          # material name -> Color
var _mutex := Mutex.new()
var _std: StandardMaterial3D = null   # debug: --hlod-std
var _mat: ShaderMaterial    # shaders/hlod.gdshader; time_of_day.gd sets night/occupancy
var _t := 0.0
var _focus := Vector3.INF
var queue: Array[Vector2i] = []    # regions waiting to be built, nearest first
const MAX_INFLIGHT := 2

func setup(s: Node3D) -> void:
	streamer = s
	_cs = s.chunk_size
	_mat = ShaderMaterial.new()
	_mat.shader = load("res://shaders/hlod.gdshader")
	if OS.get_cmdline_user_args().has("--hlod-std"):
		_std = StandardMaterial3D.new(); _std.vertex_color_use_as_albedo = true; _std.vertex_color_is_srgb = true; _std.roughness = 0.92
	for k in streamer.materials:
		colors[k] = _avg_color(streamer.materials[k])

## alpha 1 = building wall (lit windows at night in the far city)
func _avg_color(m: Material) -> Color:
	if m is StandardMaterial3D:
		var wall := 1.0 if m.emission_texture != null else 0.0
		var c: Color = m.albedo_color
		var t: Texture2D = m.albedo_texture
		if t != null:
			var img := t.get_image()
			if img != null:
				if img.is_compressed(): img.decompress()
				img.resize(1, 1, Image.INTERPOLATE_BILINEAR)
				c *= img.get_pixel(0, 0)
		c.a = wall
		return _clamp01(c)
	return Color(0.62, 0.62, 0.64, 1.0)    # facade shader buildings

const AER_RES := 16

## same exposure/saturation as shaders/aerial.gdshader (without the detail texture)
static func _aerial_look(c: Color) -> Color:
	var a := c.srgb_to_linear()
	var r := Vector3(pow(a.r, 1.18), pow(a.g, 1.18), pow(a.b, 1.18)) * 0.82
	var l := r.dot(Vector3(0.299, 0.587, 0.114))
	r = Vector3(l, l, l).lerp(r, 1.18) * 0.92
	var o := Color(maxf(r.x, 0), maxf(r.y, 0), maxf(r.z, 0)).linear_to_srgb()
	o.a = 0.0
	return _clamp01(o)

## vertex colours are stored as 8-bit: anything outside 0..1 wraps around into bright speckles
static func _clamp01(c: Color) -> Color:
	return Color(clampf(c.r, 0, 1), clampf(c.g, 0, 1), clampf(c.b, 0, 1), clampf(c.a, 0, 1))

static func region_of(k: Vector2i) -> Vector2i:
	return Vector2i(floori(float(k.x) / REGION), floori(float(k.y) / REGION))

func region_chunks(r: Vector2i) -> Array[Vector2i]:
	var out: Array[Vector2i] = []
	for dx in REGION:
		for dy in REGION:
			var k := Vector2i(r.x * REGION + dx, r.y * REGION + dy)
			if streamer.available.has(k): out.append(k)
	return out

func region_center(r: Vector2i) -> Vector3:
	var cs: float = streamer.chunk_size
	return Vector3((r.x + 0.5) * REGION * cs, 0, -(r.y + 0.5) * REGION * cs)

## true when every chunk of the region is built in detail
func region_detailed(r: Vector2i) -> bool:
	var ks := region_chunks(r)
	for k in ks:
		if not streamer.loaded.has(k): return false
	return not ks.is_empty()

func update(world_pos: Vector3) -> void:
	_focus = world_pos
	var cs: float = streamer.chunk_size
	var rs := cs * REGION
	var rr := int(ceil(radius_m / rs))
	var c := region_of(streamer.key_for_world(world_pos))
	var want: Array[Vector2i] = []
	for dx in range(-rr, rr + 1):
		for dy in range(-rr, rr + 1):
			var r := c + Vector2i(dx, dy)
			if regions.has(r) or pending.has(r): continue
			var rc := region_center(r)
			if Vector2(rc.x - world_pos.x, rc.z - world_pos.z).length() > radius_m: continue
			if region_chunks(r).is_empty(): continue
			want.append(r)
	want.sort_custom(func(a, b): return (a - c).length_squared() < (b - c).length_squared())
	queue = want     # started a few at a time in _process, only while the detail streamer is idle (detail first)
	for r in regions.keys():
		var rc := region_center(r)
		if Vector2(rc.x - world_pos.x, rc.z - world_pos.z).length() > radius_m + rs * 1.5 and not pending.has(r):
			if regions[r] != null: regions[r].queue_free()
			regions.erase(r)

const Streamer := preload("res://scripts/city_streamer.gd")
var _cs := 200.0     # chunk size, copied in setup() so worker threads never touch the streamer node

static func _read_chunk(k: Vector2i) -> Dictionary:
	var bytes := FileAccess.get_file_as_bytes(Streamer.DATA_DIR + "chunks/%d_%d.bin" % [k.x, k.y])
	if bytes.size() > 8 and bytes.slice(0, 4).get_string_from_ascii() == "TCZ1":
		var size := bytes.decode_u32(4)
		bytes = bytes.slice(8).decompress(size, FileAccess.COMPRESSION_DEFLATE)
	var d = bytes_to_var(bytes) if bytes.size() > 0 else null
	return d if d is Dictionary else {}

func _decode(r: Vector2i, ks: Array[Vector2i]) -> void:
	var cs: float = _cs
	var v := PackedVector3Array()
	var n := PackedVector3Array()
	var col := PackedColorArray()
	for k in ks:
		var d: Dictionary = _read_chunk(k)
		if d.is_empty(): continue
		var o := Vector3(k.x * cs, 0, -k.y * cs)
		var aer: Image = null           # real aerial photo, shrunk: ground colour per vertex like aerial.gdshader
		var jp: String = Streamer.DATA_DIR + "aerial/%d_%d.jpg" % [k.x, k.y]
		if FileAccess.file_exists(jp):
			aer = Image.new()
			if aer.load_jpg_from_buffer(FileAccess.get_file_as_bytes(jp)) == OK: aer.resize(AER_RES, AER_RES, Image.INTERPOLATE_BILINEAR)
			else: aer = null
		for layer in d["layers"]:
			var mat: String = layer["mat"]
			if SKIP.has(mat): continue
			var lv: PackedVector3Array = layer["v"]
			var cnt := lv.size()
			if cnt == 0: continue
			var base := v.size()
			v.resize(base + cnt)
			for i in cnt:
				v[base + i] = lv[i] + o
			n.append_array(layer["n"])
			var cc := PackedColorArray()
			cc.resize(cnt)
			if aer != null and Streamer.AERIAL_LAYERS.has(mat):
				for i in cnt:
					var px := clampi(int(lv[i].x / cs * AER_RES), 0, AER_RES - 1)
					var py := clampi(int((lv[i].z + cs) / cs * AER_RES), 0, AER_RES - 1)
					cc[i] = _aerial_look(aer.get_pixel(px, py))
			else:
				cc.fill(colors.get(mat, Color(0.6, 0.6, 0.6)))
			col.append_array(cc)
	_mutex.lock()
	decoded[r] = {"v": v, "n": n, "c": col} if v.size() > 0 else {}
	_mutex.unlock()

func _process(dt: float) -> void:
	if streamer == null: return
	while not queue.is_empty() and pending.size() < MAX_INFLIGHT and streamer.pending.is_empty():
		var q: Vector2i = queue.pop_front()
		if regions.has(q): continue
		regions[q] = null
		pending[q] = WorkerThreadPool.add_task(_decode.bind(q, region_chunks(q)))
	var built := 0
	while built < builds_per_frame:
		_mutex.lock()
		var keys := decoded.keys()
		if keys.is_empty():
			_mutex.unlock()
			break
		var r: Vector2i = keys[0]
		var d: Dictionary = decoded[r]
		decoded.erase(r)
		_mutex.unlock()
		WorkerThreadPool.wait_for_task_completion(pending[r])
		pending.erase(r)
		if not regions.has(r): continue        # dropped while building
		if d.is_empty():
			regions[r] = Node3D.new()           # nothing to draw; placeholder so it isn't rebuilt
			add_child(regions[r])
		else:
			var arrays := []
			arrays.resize(Mesh.ARRAY_MAX)
			arrays[Mesh.ARRAY_VERTEX] = d["v"]
			arrays[Mesh.ARRAY_NORMAL] = d["n"]
			arrays[Mesh.ARRAY_COLOR] = d["c"]
			var mesh := ArrayMesh.new()
			mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
			mesh.surface_set_material(0, _std if _std else _mat)
			var mi := MeshInstance3D.new()
			mi.mesh = mesh
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
			mi.name = "hlod_%d_%d" % [r.x, r.y]
			add_child(mi)
			regions[r] = mi
		built += 1
	_t += dt
	if _t > 0.25:
		_t = 0.0
		for r in regions:
			var mi = regions[r]
			if mi is Node3D:
				mi.visible = not region_detailed(r)

func is_idle() -> bool:
	return pending.is_empty() and queue.is_empty()
