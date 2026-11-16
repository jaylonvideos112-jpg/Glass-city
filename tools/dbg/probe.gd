extends SceneTree
# usage: godot --headless --script tools/dbg/probe.gd -- x z   (world coords) -> layers under that point
func _init():
	var a := OS.get_cmdline_user_args(); var x := float(a[0]); var z := float(a[1])
	var man = JSON.parse_string(FileAccess.get_file_as_string("res://data/manifest.json"))
	var cs: float = man["chunk_size"]
	var k := Vector2i(floori(x / cs), floori(-z / cs)); var o := Vector3(k.x * cs, 0, -k.y * cs)
	var bytes := FileAccess.get_file_as_bytes("res://data/chunks/%d_%d.bin" % [k.x, k.y])
	if bytes.slice(0, 4).get_string_from_ascii() == "TCZ1": bytes = bytes.slice(8).decompress(bytes.decode_u32(4), FileAccess.COMPRESSION_DEFLATE)
	var d: Dictionary = bytes_to_var(bytes)
	var p := Vector2(x - o.x, z - o.z)
	for L in d["layers"]:
		var v: PackedVector3Array = L["v"]
		for i in range(0, v.size(), 3):
			if Geometry2D.point_is_inside_triangle(p, Vector2(v[i].x, v[i].z), Vector2(v[i+1].x, v[i+1].z), Vector2(v[i+2].x, v[i+2].z)):
				print(L["mat"], " y=", snappedf((v[i].y + v[i+1].y + v[i+2].y) / 3.0, 0.01))
				break
	print("streets: ", d["streets"].size() if d.has("streets") else -1)
	quit()
