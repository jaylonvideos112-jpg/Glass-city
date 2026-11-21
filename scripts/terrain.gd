class_name Terrain
## Coarse ground height (16 m grid from the LiDAR bare earth, data/terrain.bin) for "where is the ground here"
## questions: spawn spots, AI targets, street-level checks. Rendering and collision use the exact chunk meshes.
static var _x0 := 0.0
static var _y0 := 0.0
static var _cell := 16.0
static var _w := 0
static var _h := 0
static var _g := PackedByteArray()
static var _loaded := false

static func _load() -> void:
	_loaded = true
	var f := FileAccess.open("res://data/terrain.bin", FileAccess.READ)
	if f == null: return
	var b := f.get_buffer(f.get_length())
	if b.size() < 28 or b.slice(0, 4).get_string_from_ascii() != "TRZ1": return
	_x0 = b.decode_float(4); _y0 = b.decode_float(8); _cell = b.decode_float(12)
	_w = b.decode_s32(16); _h = b.decode_s32(20)
	var raw := b.decode_u32(24)
	_g = b.slice(28).decompress(raw, FileAccess.COMPRESSION_DEFLATE)
	if _g.size() != _w * _h * 2: _w = 0

static func _at(i: int, j: int) -> float:
	i = clampi(i, 0, _w - 1); j = clampi(j, 0, _h - 1)
	return _g.decode_u16((j * _w + i) * 2) / 100.0 - 20.0

## Ground height (game y) at a world position (x east, z = -north). 0 if there is no terrain data.
static func height(p: Vector3) -> float:
	if not _loaded: _load()
	if _w == 0: return 0.0
	var gx := (p.x - _x0) / _cell - 0.5
	var gy := (-p.z - _y0) / _cell - 0.5
	var i := floori(gx); var j := floori(gy)
	var fx := gx - i; var fy := gy - j
	return lerpf(lerpf(_at(i, j), _at(i + 1, j), fx), lerpf(_at(i, j + 1), _at(i + 1, j + 1), fx), fy)
