extends SceneTree
# ascii map of top ground layer around (x,z): usage -- x z radius step
func _init():
	var a := OS.get_cmdline_user_args(); var cx := float(a[0]); var cz := float(a[1]); var r := float(a[2]); var st := float(a[3])
	var man = JSON.parse_string(FileAccess.get_file_as_string("res://data/manifest.json")); var cs: float = man["chunk_size"]
	var cache := {}
	var sym := {"asphalt": "#", "sidewalk": ".", "lot": "c", "grass": "g", "parking": "p", "forest_floor": "f", "water": "~", "industrial": "i"}
	var z := cz - r
	while z <= cz + r:
		var line := ""
		var x := cx - r
		while x <= cx + r:
			var k := Vector2i(floori(x / cs), floori(-z / cs)); var o := Vector3(k.x * cs, 0, -k.y * cs)
			if not cache.has(k):
				var b := FileAccess.get_file_as_bytes("res://data/chunks/%d_%d.bin" % [k.x, k.y])
				if b.slice(0, 4).get_string_from_ascii() == "TCZ1": b = b.slice(8).decompress(b.decode_u32(4), FileAccess.COMPRESSION_DEFLATE)
				cache[k] = bytes_to_var(b)
			var p := Vector2(x - o.x, z - o.z); var best := " "; var by := -99.0
			for L in cache[k]["layers"]:
				if not sym.has(L["mat"]): continue
				var v: PackedVector3Array = L["v"]
				for i in range(0, v.size(), 3):
					if v[i].y > 1.0: continue
					if Geometry2D.point_is_inside_triangle(p, Vector2(v[i].x, v[i].z), Vector2(v[i+1].x, v[i+1].z), Vector2(v[i+2].x, v[i+2].z)):
						if v[i].y > by: by = v[i].y; best = sym[L["mat"]]
						break
			line += "@" if absf(x - cx) < st * 0.5 and absf(z - cz) < st * 0.5 else best
			x += st
		print(line); z += st
	quit()
