extends Node3D
## Parked cars along residential and minor streets (2026-11-21: streets must feel lived-in, never empty).
## Placed from the traffic road graph: on residential (class 5) and tertiary (class 4) streets with sidewalks,
## at the curb on each side, at deterministic spots (hashed from the street's node ids, so the same cars are
## there every visit), skipping the ends of each block (corners and crossings). Only streets within RADIUS of the
## camera get cars; each car is a static body with a box collider so you can bump into it. Models and paint
## come from the traffic roster (traffic.gd). Off with --no-parked.

const WheelMesh := preload("res://scripts/wheel_mesh.gd")
const RADIUS := 170.0
const GAP := 7.5             # one car slot every GAP metres of curb
const FILL := 0.42           # share of slots taken (Toledo side streets: plenty of cars, plenty of gaps)
const END_CLEAR := 11.0      # no parking this close to a corner

var main: Node = null
var enabled := true
var _edges := {}             # "a_b" -> Node3D holding that block's cars
var _t := 0.0
var _ver := -1

func _ready() -> void:
	enabled = not OS.get_cmdline_user_args().has("--no-parked")

func _process(dt: float) -> void:
	if not enabled or main == null or main.traffic == null: return
	_t -= dt
	if _t > 0.0: return
	_t = 0.5
	var tr = main.traffic
	var cam := get_viewport().get_camera_3d()
	if cam == null: return
	var cp: Vector3 = cam.global_position + main.world_offset
	var keep := {}
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		if e["cls"] < 4 or e["cls"] > 5 or e["len"] < END_CLEAR * 2.0 + GAP or not e.get("walk", false): continue
		var a: int = e["a"]; var b: int = e["b"]
		if a > b and not e["oneway"]: continue           # two-way street: handle it once (both curbs) from a < b
		var pa: Vector3 = tr.npos[a]; var pb: Vector3 = tr.npos[b]
		var mid := (pa + pb) * 0.5
		if Vector2(mid.x - cp.x, mid.z - cp.z).length() > RADIUS + float(e["len"]) * 0.5: continue
		var key := "%d_%d" % [a, b]
		keep[key] = true
		if not _edges.has(key): _edges[key] = _build(tr, e, key)
	for key in _edges.keys():
		if not keep.has(key):
			var n = _edges[key]
			if is_instance_valid(n): n.queue_free()
			_edges.erase(key)

func _build(tr, e: Dictionary, key: String) -> Node3D:
	var holder := Node3D.new()
	main.world.add_child(holder)
	holder.global_position = -main.world_offset
	holder.set_meta("world_origin", Vector3.ZERO)
	var rng := RandomNumberGenerator.new(); rng.seed = hash(key)
	var pa: Vector3 = tr.npos[e["a"]]; var pb: Vector3 = tr.npos[e["b"]]
	var d: Vector3 = (pb - pa); d.y = 0.0
	var L := d.length(); d = d / L
	var right := Vector3(-d.z, 0.0, d.x)
	var half_w: float = float(e.get("w", 8.0)) * 0.5
	var sides := [1.0] if e["oneway"] else [1.0, -1.0]
	for sd in sides:
		var s := END_CLEAR
		while s < L - END_CLEAR:
			if rng.randf() < FILL:
				var v: Dictionary = tr._pick_type()
				if float(v["size"][0]) < 6.0 and not String(v.get("category", "")).contains("bus"):
					var along: float = s + rng.randf_range(-0.6, 0.6)
					var p: Vector3 = pa + d * along + right * sd * (half_w - float(v["size"][1]) * 0.5 - 0.25)
					p.y = _ground(p)
					var yaw := atan2(-d.x, -d.z) + (0.0 if sd > 0.0 else PI) + rng.randf_range(-0.03, 0.03)
					_car(holder, tr, v, p, yaw, rng)
			s += GAP
	return holder

## the road surface under p (raycast against the chunk ground, layer 1); the coarse terrain grid alone left cars
## sunk into raised road beds
func _ground(p: Vector3) -> float:
	var T := Terrain.height(p)
	var sp: PhysicsDirectSpaceState3D = main.get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(Vector3(p.x, T + 4.0, p.z) - main.world_offset, Vector3(p.x, T - 4.0, p.z) - main.world_offset, 1)
	var hit: Dictionary = sp.intersect_ray(q)
	return (hit["position"] + main.world_offset).y if hit else T

func _car(holder: Node3D, tr, v: Dictionary, p: Vector3, yaw: float, rng: RandomNumberGenerator) -> void:
	var cols: Array = tr.T.get("paint", [])
	var paint: Color = Color(rng.randf_range(0.05, 0.85), rng.randf_range(0.05, 0.8), rng.randf_range(0.05, 0.8))
	if cols.size() > 0: paint = Color(cols[rng.randi() % cols.size()])
	var body := StaticBody3D.new()
	body.collision_layer = 2; body.collision_mask = 0          # like traffic cars: ground rays (mask 1) ignore them
	var mi := MeshInstance3D.new(); mi.mesh = tr.vehicle_mesh(v, paint)
	body.add_child(mi)
	if v.get("body", "") in ["sedan", "coupe", "sports", "hatch", "suv", "wagon"] or tr.has_model(v):     # wheels, as traffic.gd
		var wr2: float = tr.wheel_r(v)
		for az in [-1.0, 1.0]:
			for sx in [-1.0, 1.0]:
				var wm := MeshInstance3D.new(); wm.mesh = WheelMesh.make(wr2, 0.24)
				wm.position = Vector3(sx * (float(v["size"][1]) * 0.5 - 0.12), wr2, az * float(v["size"][0]) * tr.axle_f(v))
				body.add_child(wm)
	var cs := CollisionShape3D.new(); var bx := BoxShape3D.new()
	bx.size = Vector3(float(v["size"][1]), float(v["size"][2]) * 0.8, float(v["size"][0]))
	cs.shape = bx; cs.position.y = float(v["size"][2]) * 0.45
	body.add_child(cs)
	holder.add_child(body)
	body.global_transform = Transform3D(Basis(Vector3.UP, yaw), p - main.world_offset)

func count() -> int:
	var c := 0
	for k in _edges:
		var n = _edges[k]
		if is_instance_valid(n): c += n.get_child_count()
	return c
