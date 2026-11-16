extends RefCounted
## Low-poly people, built in code (placeholder art until the Unreal pass, but readable as people):
## tapered torso and hips, rounded (8-sided) head with hair styles, eyes and brows, tapered limbs with hands and
## shoes, clothing variants (tee with bare forearms, long sleeves, jacket over a shirt, shorts, dress, cap).
## One mesh per person; parts are tagged in UV2 (x = part: 0 body, 1/2 legs, 3/4 arms, 5 umbrella; y = joint height)
## so shaders/pedestrian.gdshader can swing the limbs. Used by pedestrians.gd and the player.

const SIDES := 10

## st: SurfaceTool (triangles). A frustum along Y from y0 (radii r0) to y1 (radii r1), n sides, flat shaded.
static func frustum(st: SurfaceTool, n: int, c: Vector3, y0: float, y1: float, r0: Vector2, r1: Vector2, col: Color, part: int, pivot: float, caps := true, rot := 0.0) -> void:
	var b: Array[Vector3] = []; var t: Array[Vector3] = []
	for i in n:
		var a := TAU * (float(i) + 0.5) / n + rot
		b.append(c + Vector3(cos(a) * r0.x, y0, sin(a) * r0.y))
		t.append(c + Vector3(cos(a) * r1.x, y1, sin(a) * r1.y))
	for i in n:
		var j := (i + 1) % n
		_quad(st, b[i], b[j], t[j], t[i], col, part, pivot)
	if caps:
		var cb := c + Vector3(0, y0, 0); var ct := c + Vector3(0, y1, 0)
		for i in n:
			var j := (i + 1) % n
			_tri(st, cb, b[j], b[i], col, part, pivot)
			_tri(st, ct, t[i], t[j], col, part, pivot)

static func _tri(st: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, col: Color, part: int, pivot: float) -> void:
	var nrm := (b - a).cross(c - a).normalized()
	if nrm == Vector3.ZERO: return
	for v in [a, b, c]:
		st.set_color(col); st.set_normal(-nrm); st.set_uv2(Vector2(part, pivot)); st.add_vertex(v)

static func _quad(st: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, d: Vector3, col: Color, part: int, pivot: float) -> void:
	_tri(st, a, b, c, col, part, pivot); _tri(st, a, c, d, col, part, pivot)

static func box(st: SurfaceTool, size: Vector3, pos: Vector3, col: Color, part: int, pivot: float) -> void:
	frustum(st, 4, pos, -size.y * 0.5, size.y * 0.5, Vector2(size.x, size.z) * 0.7071, Vector2(size.x, size.z) * 0.7071, col, part, pivot, true, PI * 0.25)

## look: Dictionary with skin, hair, top, top2 (jacket/sleeves), bottom, shoe colours and choices:
##   h (height scale), w (build), hair_style (0 short, 1 long, 2 bald, 3 bun, 4 cap), sleeves (0 tee, 1 long, 2 jacket),
##   legs (0 pants, 1 shorts, 2 dress), beard (bool), umbrella colour (or null)
static func build(look: Dictionary) -> ArrayMesh:
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var h: float = look.get("h", 1.0); var w: float = look.get("w", 1.0)
	var skin: Color = look["skin"]; var hair: Color = look["hair"]; var top: Color = look["top"]
	var top2: Color = look.get("top2", top); var bot: Color = look["bottom"]; var shoe: Color = look["shoe"]
	var sleeves: int = look.get("sleeves", 0); var legs: int = look.get("legs", 0); var hs: int = look.get("hair_style", 0)
	var hip := 0.93 * h; var waist := 1.08 * h; var sh := 1.45 * h
	# --- torso: hips (pants), waist->chest tapered, shoulders
	# rounded (8-sided) hips, waist, chest and shoulders instead of boxes
	frustum(st, 8, Vector3.ZERO, hip - 0.04, waist, Vector2(0.17, 0.12) * w, Vector2(0.155, 0.11) * w, bot if legs != 2 else top, 0, 0, true)
	var torso_col: Color = top2 if sleeves == 2 else top
	var chest := waist + (sh - waist) * 0.62
	frustum(st, 8, Vector3.ZERO, waist, chest, Vector2(0.155, 0.11) * w, Vector2(0.2, 0.125) * w, torso_col, 0, 0, false)
	frustum(st, 8, Vector3.ZERO, chest, sh - 0.05 * h, Vector2(0.2, 0.125) * w, Vector2(0.215, 0.12) * w, torso_col, 0, 0, false)
	frustum(st, 8, Vector3.ZERO, sh - 0.05 * h, sh + 0.02, Vector2(0.215, 0.12) * w, Vector2(0.12, 0.09) * w, torso_col, 0, 0, true)
	if sleeves == 2:   # open jacket: shirt showing down the front
		box(st, Vector3(0.11 * w, (sh - waist) * 0.92, 0.02), Vector3(0, (waist + sh) * 0.5 - 0.02, -0.15 * w), top, 0, 0)
	if legs == 2:      # dress / skirt
		frustum(st, 6, Vector3.ZERO, hip - 0.38 * h, waist, Vector2(0.27, 0.22) * w, Vector2(0.2, 0.15) * w, top, 0, 0)
	# --- neck and head (8-sided, jaw narrower than the cranium)
	frustum(st, 6, Vector3(0, 0, 0), sh, sh + 0.08 * h, Vector2(0.055, 0.055), Vector2(0.05, 0.05), skin, 0, 0, false)
	var hy := sh + 0.06 * h
	frustum(st, SIDES, Vector3(0, 0, -0.005), hy, hy + 0.1, Vector2(0.075, 0.085), Vector2(0.105, 0.115), skin, 0, 0, true)
	frustum(st, SIDES, Vector3(0, 0, 0), hy + 0.1, hy + 0.22, Vector2(0.105, 0.115), Vector2(0.075, 0.085), skin, 0, 0, true)
	# face: eyes, brows, nose (front is -Z)
	var fz := -0.112
	var iris: Color = look.get("eyes", Color(0.25, 0.17, 0.1))
	for s in [-1, 1]:
		box(st, Vector3(0.036, 0.02, 0.008), Vector3(0.042 * s, hy + 0.125, fz + 0.001), Color(0.93, 0.92, 0.88), 0, 0)   # eye white
		box(st, Vector3(0.017, 0.019, 0.01), Vector3(0.042 * s + 0.002 * s, hy + 0.125, fz - 0.002), iris, 0, 0)
		box(st, Vector3(0.008, 0.009, 0.011), Vector3(0.042 * s + 0.002 * s, hy + 0.125, fz - 0.003), Color(0.02, 0.02, 0.02), 0, 0)
		box(st, Vector3(0.04, 0.006, 0.012), Vector3(0.042 * s, hy + 0.137, fz + 0.002), skin.darkened(0.18), 0, 0)      # upper lid
		box(st, Vector3(0.045, 0.012, 0.012), Vector3(0.042 * s, hy + 0.155, fz + 0.003), hair.darkened(0.2), 0, 0)
		box(st, Vector3(0.02, 0.05, 0.035), Vector3(0.108 * s, hy + 0.11, 0.0), skin.darkened(0.05), 0, 0)               # ear
	box(st, Vector3(0.025, 0.045, 0.03), Vector3(0, hy + 0.095, fz - 0.005), skin.darkened(0.08), 0, 0)
	box(st, Vector3(0.05, 0.011, 0.01), Vector3(0, hy + 0.06, fz + 0.012), skin.darkened(0.32).lerp(Color(0.55, 0.2, 0.2), 0.2), 0, 0)
	box(st, Vector3(0.038, 0.008, 0.01), Vector3(0, hy + 0.05, fz + 0.014), skin.darkened(0.15).lerp(Color(0.6, 0.25, 0.25), 0.15), 0, 0)
	if look.get("beard", false):
		frustum(st, SIDES, Vector3(0, 0, -0.012), hy + 0.005, hy + 0.08, Vector2(0.08, 0.09), Vector2(0.1, 0.11), hair, 0, 0, true)
	match hs:
		0: frustum(st, SIDES, Vector3(0, 0, 0.005), hy + 0.17, hy + 0.255, Vector2(0.113, 0.123), Vector2(0.07, 0.08), hair, 0, 0, true)
		1:
			frustum(st, SIDES, Vector3(0, 0, 0.005), hy + 0.17, hy + 0.26, Vector2(0.115, 0.125), Vector2(0.07, 0.08), hair, 0, 0, true)
			box(st, Vector3(0.22, 0.26, 0.07), Vector3(0, hy + 0.06, 0.09), hair, 0, 0)
		3:
			frustum(st, SIDES, Vector3(0, 0, 0.005), hy + 0.17, hy + 0.25, Vector2(0.113, 0.123), Vector2(0.07, 0.08), hair, 0, 0, true)
			frustum(st, 6, Vector3(0, 0, 0.09), hy + 0.2, hy + 0.3, Vector2(0.06, 0.06), Vector2(0.045, 0.045), hair, 0, 0, true)
		4:
			frustum(st, SIDES, Vector3(0, 0, 0.0), hy + 0.17, hy + 0.27, Vector2(0.12, 0.13), Vector2(0.09, 0.1), top2, 0, 0, true)
			box(st, Vector3(0.17, 0.02, 0.12), Vector3(0, hy + 0.18, -0.14), top2, 0, 0)
	# --- legs (tapered thigh -> ankle) and shoes (none for a seated driver)
	for sgn in ([] if look.get("seated", false) else [-1, 1]):
		var leg := 1 if sgn < 0 else 2
		var lx: float = 0.1 * sgn * w
		var leg_col: Color = bot if legs == 0 else skin
		if legs == 1:   # shorts to the knee
			frustum(st, 6, Vector3(lx, 0, 0), hip * 0.55, hip, Vector2(0.085, 0.09) * w, Vector2(0.095, 0.1) * w, bot, leg, hip, true)
			frustum(st, 6, Vector3(lx, 0, 0), 0.08, hip * 0.55, Vector2(0.05, 0.055), Vector2(0.065, 0.07) * w, skin, leg, hip, false)
		elif legs == 2:
			frustum(st, 6, Vector3(lx, 0, 0), 0.08, hip - 0.3 * h, Vector2(0.048, 0.052), Vector2(0.065, 0.07) * w, skin, leg, hip, false)
		else:
			frustum(st, 6, Vector3(lx, 0, 0), 0.08, hip, Vector2(0.06, 0.065), Vector2(0.095, 0.1) * w, leg_col, leg, hip, true)
		# shoe: a sole and a rounded toe
		box(st, Vector3(0.11, 0.07, 0.26), Vector3(lx, 0.04, -0.04), shoe, leg, hip)
		box(st, Vector3(0.115, 0.02, 0.27), Vector3(lx, 0.008, -0.04), Color(0.92, 0.92, 0.9) if shoe.v < 0.5 else Color(0.2, 0.2, 0.2), leg, hip)
	# --- arms: upper (sleeve), forearm (sleeve or skin), hand
	for sgn in [-1, 1]:
		var arm := 3 if sgn < 0 else 4
		var ax: float = 0.255 * sgn * w
		var top_sleeve: Color = top2 if sleeves == 2 else top
		var elbow := sh - 0.3 * h
		frustum(st, 6, Vector3(ax, 0, 0), elbow, sh - 0.06 * h, Vector2(0.055, 0.06) * w, Vector2(0.07, 0.075) * w, top_sleeve, arm, sh - 0.06 * h, true)
		frustum(st, 6, Vector3(ax * 0.93, 0, 0), sh - 0.08 * h, sh + 0.01, Vector2(0.075, 0.08) * w, Vector2(0.045, 0.05) * w, top_sleeve, arm, sh - 0.06 * h, true)
		var fore: Color = skin if sleeves == 0 else top_sleeve
		frustum(st, 6, Vector3(ax, 0, 0), sh - 0.58 * h, elbow, Vector2(0.04, 0.045), Vector2(0.052, 0.056) * w, fore, arm, sh - 0.06 * h, false)
		box(st, Vector3(0.055, 0.09, 0.045), Vector3(ax, sh - 0.625 * h, 0), skin, arm, sh - 0.06 * h)
		box(st, Vector3(0.05, 0.05, 0.04), Vector3(ax, sh - 0.68 * h, -0.004), skin.darkened(0.04), arm, sh - 0.06 * h)
		box(st, Vector3(0.02, 0.05, 0.022), Vector3(ax - 0.028 * sgn, sh - 0.62 * h, -0.02), skin, arm, sh - 0.06 * h)
	# --- umbrella (hidden by the shader unless raining)
	var uc = look.get("umbrella", null)
	if uc != null:
		box(st, Vector3(0.025, 0.75, 0.025), Vector3(0.28 * w, sh + 0.2, -0.32), Color(0.2, 0.2, 0.2), 5, 0)
		frustum(st, 8, Vector3(0.2 * w, 0, -0.2), sh + 0.55, sh + 0.72, Vector2(0.62, 0.62), Vector2(0.05, 0.05), uc, 5, 0, true)
	return st.commit()
