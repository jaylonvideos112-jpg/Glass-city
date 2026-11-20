extends SceneTree
func _init() -> void:
	var cs := preload("res://scripts/city_streamer.gd").new()
	for k in [Vector2i(1, 1), Vector2i(0, 0)]:
		var d: Dictionary = cs.read_chunk(k)
		for l in d.get("layers", []):
			if l["mat"] == "facade": print(k, " facade keys ", l.keys(), " nv ", l["v"].size())
	var m = JSON.parse_string(FileAccess.get_file_as_string("res://data/manifest.json"))
	print("spawn ", m["spawn"], " chunks ", m["chunks"].size())
	quit()
