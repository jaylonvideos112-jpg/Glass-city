extends SceneTree
func _init() -> void:
	var cs := preload("res://scripts/city_streamer.gd").new()
	for k in [Vector2i(1, 1), Vector2i(1, -1), Vector2i(0, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(-1, -1)]:
		var d: Dictionary = cs.read_chunk(k)
		var mats := []
		for l in d.get("layers", []): mats.append(l["mat"])
		print(k, " ", mats)
	quit()
