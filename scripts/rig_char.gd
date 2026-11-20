class_name RigChar
extends Node3D
## A skinned, motion-captured person (tools/blender/rigged_people.py -> assets/models/char_<variant>.glb).
## 53-bone UE-mannequin-named skeleton; clips are CMU mocap retargeted per bone.
## Animation graph (AnimationTree, built in code):
##   loco  = BlendSpace1D on ground speed (idle .. walk .. jog .. run .. sprint), synced, then TimeScale so the feet
##           keep pace above the fastest clip
##   act   = one clip scrubbed to a 0..1 time (punches, kicks, jump, sitting, getting up) mixed over loco
##   aim   = upper body only (spine, arms, head) holding the aim pose over whatever the legs do
## Clothes/skin are material slots tinted from a 'look' dictionary (same keys as humans.gd).

const SPEEDS := {"idle": 0.0, "walk": 1.47, "walk_fast": 2.12, "jog": 2.79, "run": 3.59, "sprint": 3.67}
const LOOPS := ["idle", "walk", "walk_fast", "jog", "run", "sprint", "crouch_walk", "limp", "carry_walk", "aim", "sit"]
const UPPER := ["spine_01", "spine_02", "spine_03", "neck_01", "head", "clavicle_l", "clavicle_r", "upperarm_l", "upperarm_r",
	"lowerarm_l", "lowerarm_r", "hand_l", "hand_r"]
const VARIANTS := ["m1", "m2", "m3", "m4", "f1", "f2", "f3", "f4"]

var skel: Skeleton3D
var player: AnimationPlayer
var tree: AnimationTree
var body: MeshInstance3D
var speed := 0.0
var _act_anim: AnimationNodeAnimation
var _act_len := 1.0
var _act_w := 0.0
var _act_target := 0.0
var _aim_w := 0.0
var _aim_target := 0.0
var _loco_kind := "normal"

static func available(variant: String) -> bool:
	return ResourceLoader.exists("res://assets/models/char_%s.glb" % variant)

static func create(variant: String, look := {}) -> RigChar:
	var r := RigChar.new()
	r.name = "Rig"
	var ps: PackedScene = load("res://assets/models/char_%s.glb" % variant)
	var inst := ps.instantiate()
	r.add_child(inst)
	r._setup(inst, look)
	return r

func _find(n: Node, cls: String) -> Node:
	if n.is_class(cls): return n
	for c in n.get_children():
		var f := _find(c, cls)
		if f: return f
	return null

func _setup(inst: Node, look: Dictionary) -> void:
	skel = _find(inst, "Skeleton3D") as Skeleton3D
	player = _find(inst, "AnimationPlayer") as AnimationPlayer
	body = _find(inst, "MeshInstance3D") as MeshInstance3D
	if player:
		for lib_name in player.get_animation_library_list():
			var lib := player.get_animation_library(lib_name)
			for a in lib.get_animation_list():
				lib.get_animation(a).loop_mode = Animation.LOOP_LINEAR if a in LOOPS else Animation.LOOP_NONE
	dress(look)
	_build_tree()

## tint the material slots: skin, hair, shirt, sleeve, pants, shin, shoes, eye_white, iris
func dress(look: Dictionary) -> void:
	if body == null or body.mesh == null: return
	var skin: Color = look.get("skin", Color(0.72, 0.53, 0.42))
	var top: Color = look.get("top", Color(0.3, 0.35, 0.5))
	var bottom: Color = look.get("bottom", Color(0.16, 0.18, 0.25))
	var cols := {"skin": skin, "hair": look.get("hair", Color(0.1, 0.07, 0.05)), "shirt": top,
		"sleeve": top if int(look.get("sleeves", 1)) > 0 else skin, "pants": bottom,
		"shin": bottom if int(look.get("legs", 0)) == 0 else skin, "shoes": look.get("shoe", Color(0.1, 0.1, 0.1)),
		"eye_white": Color(0.9, 0.9, 0.87), "iris": look.get("eyes", Color(0.25, 0.16, 0.08))}
	for i in body.mesh.get_surface_count():
		var src := body.mesh.surface_get_material(i)
		var key: String = src.resource_name if src else ""
		if not cols.has(key): continue
		var m := StandardMaterial3D.new()
		m.albedo_color = cols[key]
		m.roughness = 0.55 if key == "skin" else (0.15 if key in ["eye_white", "iris"] else 0.85)
		if key == "skin":
			m.subsurf_scatter_enabled = true; m.subsurf_scatter_strength = 0.25    # light through ears/fingers
		if key in ["shirt", "sleeve", "pants", "shin"]:
			m.albedo_texture = _cloth_tex()                                          # woven fabric grain
			m.uv1_triplanar = true; m.uv1_scale = Vector3(18, 18, 18)
		body.set_surface_override_material(i, m)

static var _ctex: Texture2D
static func _cloth_tex() -> Texture2D:
	if _ctex: return _ctex
	var n := FastNoiseLite.new(); n.frequency = 0.35; n.fractal_octaves = 2
	var t := NoiseTexture2D.new(); t.noise = n; t.seamless = true; t.width = 128; t.height = 128
	var g := Gradient.new(); g.set_color(0, Color(0.86, 0.86, 0.86)); g.set_color(1, Color(1, 1, 1))
	t.color_ramp = g
	_ctex = t
	return t

func _anim_node(name: String) -> AnimationNodeAnimation:
	var a := AnimationNodeAnimation.new(); a.animation = name; return a

func _build_tree() -> void:
	if player == null: return
	tree = AnimationTree.new()
	tree.name = "Tree"
	add_child(tree)
	tree.anim_player = tree.get_path_to(player)
	tree.root_node = tree.get_path_to(player.get_parent())
	var bt := AnimationNodeBlendTree.new()
	var bs := AnimationNodeBlendSpace1D.new()
	bs.min_space = 0.0; bs.max_space = 4.0; bs.sync = true
	for k in SPEEDS:
		bs.add_blend_point(_anim_node(k), SPEEDS[k])
	bt.add_node("loco", bs, Vector2(0, 0))
	bt.add_node("ts", AnimationNodeTimeScale.new(), Vector2(200, 0))
	bt.connect_node("ts", 0, "loco")
	_act_anim = _anim_node("punch")
	bt.add_node("act", _act_anim, Vector2(0, 200))
	bt.add_node("act_seek", AnimationNodeTimeSeek.new(), Vector2(200, 200))
	bt.connect_node("act_seek", 0, "act")
	var b_act := AnimationNodeBlend2.new()
	bt.add_node("mix_act", b_act, Vector2(400, 100))
	bt.connect_node("mix_act", 0, "ts"); bt.connect_node("mix_act", 1, "act_seek")
	bt.add_node("aim", _anim_node("aim"), Vector2(400, 300))
	var b_aim := AnimationNodeBlend2.new()
	b_aim.filter_enabled = true
	var skel_path := String(player.get_parent().get_path_to(skel))
	for bn in UPPER:
		b_aim.set_filter_path(NodePath("%s:%s" % [skel_path, bn]), true)
	bt.add_node("mix_aim", b_aim, Vector2(600, 150))
	bt.connect_node("mix_aim", 0, "mix_act"); bt.connect_node("mix_aim", 1, "aim")
	bt.connect_node("output", 0, "mix_aim")
	tree.tree_root = bt
	tree.active = true

## per frame: ground speed (m/s), grounded, vertical speed
func update(dt: float, ground_speed: float, on_floor := true, vy := 0.0) -> void:
	if tree == null: return
	speed = lerpf(speed, ground_speed, 1.0 - exp(-10.0 * dt))
	var top: float = SPEEDS["sprint"]
	tree.set("parameters/loco/blend_position", minf(speed, top))
	tree.set("parameters/ts/scale", maxf(1.0, speed / top) if speed > top else 1.0)
	if not on_floor and _act_target <= 0.0:        # airborne: hold the jump clip at the matching phase
		_set_act_clip("jump")
		var ph := clampf(0.5 - vy * 0.04, 0.38, 0.72)
		tree.set("parameters/act_seek/seek_request", ph * _act_len)
		_act_w = lerpf(_act_w, 1.0, 1.0 - exp(-14.0 * dt))
	else:
		_act_w = lerpf(_act_w, _act_target, 1.0 - exp(-(18.0 if _act_target > _act_w else 9.0) * dt))
	tree.set("parameters/mix_act/blend_amount", _act_w)
	_aim_w = lerpf(_aim_w, _aim_target, 1.0 - exp(-12.0 * dt))
	tree.set("parameters/mix_aim/blend_amount", _aim_w)

func _set_act_clip(clip: String) -> void:
	if _act_anim.animation == StringName(clip): return
	_act_anim.animation = clip
	var a := player.get_animation(clip) if player.has_animation(clip) else null
	_act_len = a.length if a else 1.0

## combat/weapons pose codes (same meaning as the old pedestrian shader 'act'): 0 none, 1 right punch, 2 left
## punch, 3 kick, 4 guard, 6 hook, 7 tackle, 11 hands up, 14/15 aim rifle/pistol, 20 sit, 21 get up
func set_act(a: float, t: float) -> void:
	var ia := int(a + 0.5)
	_aim_target = 1.0 if ia in [14, 15] else 0.0
	var clip := ""; var tt := t
	match ia:
		1, 6, 7: clip = "punch"
		2: clip = "punch_l"
		3: clip = "kick"
		4: clip = "punch"; tt = 0.18           # fists up, ready
		11: clip = "wave"; tt = 0.35
		20: clip = "sit"; tt = 0.5
		21: clip = "get_up"
	if clip == "":
		_act_target = 0.0
		return
	_set_act_clip(clip)
	_act_target = 1.0
	tree.set("parameters/act_seek/seek_request", clampf(tt, 0.0, 1.0) * _act_len)

func locomotion_set(kind: String) -> void:
	## "normal" / "crouch" / "limp" / "carry": swaps the walking clip in the blend space
	if kind == _loco_kind or tree == null: return
	_loco_kind = kind
	var bs := (tree.tree_root as AnimationNodeBlendTree).get_node("loco") as AnimationNodeBlendSpace1D
	var walk_clip: String = {"normal": "walk", "crouch": "crouch_walk", "limp": "limp", "carry": "carry_walk"}[kind]
	(bs.get_blend_point_node(1) as AnimationNodeAnimation).animation = walk_clip

## static pose for passengers/drivers: jump straight to the act clip fully weighted
func pose_hold(a: float, t := 0.5) -> void:
	set_act(a, t)
	_act_w = 1.0
	if tree: tree.set("parameters/mix_act/blend_amount", 1.0)
