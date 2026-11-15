extends Node
## Real lights for the street lamps nearest the camera (the rest only have fake ground pools).
## A fixed pool of OmniLight3Ds is moved to the closest lamp heads every quarter second, and only at night.

var main: Node
var lights: Array[OmniLight3D] = []
var _t := 0.0
var count := 24
var light_range := 15.0
var energy := 1.6

func _ready() -> void:
	var L: Dictionary = main.tod.C.get("lights", {})
	count = int(L.get("real_lamp_lights", 24)); light_range = L.get("real_lamp_range", 15.0); energy = L.get("real_lamp_energy", 1.6)
	for i in count:
		var o := OmniLight3D.new()
		o.light_color = Color(1.0, 0.78, 0.5)
		o.omni_range = light_range
		o.omni_attenuation = 1.4
		o.shadow_enabled = false
		o.visible = false
		lights.append(o)
		main.world.add_child(o)

## Lamp head positions (local coords) from loaded chunks within radius of p.
func heads_near(p: Vector3, radius: float) -> Array:
	var out: Array = []
	for k in main.streamer.loaded:
		var root: Node3D = main.streamer.loaded[k]
		if not root.has_meta("lamp_heads"): continue
		if Vector2(root.position.x + 100.0 - p.x, root.position.z - 100.0 - p.z).length() > radius + 150.0: continue
		for h in root.get_meta("lamp_heads"):
			var q: Vector3 = root.position + h
			if (q - p).length() < radius: out.append(q)
	return out

func _process(dt: float) -> void:
	_t -= dt
	if _t > 0.0: return
	_t = 0.25
	var n: float = main.tod.night
	var indoors: bool = main.bars != null and main.bars.inside
	if n < 0.05 or indoors or main.camera == null:
		for o in lights: o.visible = false
		return
	var cp: Vector3 = main.camera.global_position
	var hs := heads_near(cp, 140.0)
	hs.sort_custom(func(a, b): return a.distance_squared_to(cp) < b.distance_squared_to(cp))
	for i in lights.size():
		var o := lights[i]
		if i < hs.size():
			o.global_position = hs[i] + Vector3(0, -0.4, 0)
			o.light_energy = energy * n
			o.visible = true
		else:
			o.visible = false
