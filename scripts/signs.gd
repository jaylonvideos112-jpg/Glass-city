extends RefCounted
## Street signs for places you can use (jobs, homes, dealers, activities): one consistent, readable style.
## A two-post sign on a small concrete base, a coloured header band with the kind of place, a white panel with the
## name and details, and a soft glow at night so you can spot them. Front faces -Z of the returned node.

static func make(header: String, title: String, detail: String, accent: Color, width := 2.2) -> Node3D:
	var root := Node3D.new()
	var dark := StandardMaterial3D.new(); dark.albedo_color = Color(0.16, 0.17, 0.19); dark.metallic = 0.4; dark.roughness = 0.5
	var concrete := StandardMaterial3D.new(); concrete.albedo_color = Color(0.62, 0.62, 0.6)
	var panel := StandardMaterial3D.new(); panel.albedo_color = Color(0.96, 0.96, 0.94); panel.roughness = 0.6
	panel.emission_enabled = true; panel.emission = Color(0.9, 0.9, 0.85); panel.emission_energy_multiplier = 0.08
	var band := StandardMaterial3D.new(); band.albedo_color = accent
	band.emission_enabled = true; band.emission = accent; band.emission_energy_multiplier = 0.35
	var h := 1.0                       # panel bottom
	var ph := 0.95                     # panel height
	_box(root, Vector3(width + 0.5, 0.12, 0.45), Vector3(0, 0.06, 0), concrete)
	for sx in [-1, 1]:
		_box(root, Vector3(0.08, h + ph + 0.35, 0.08), Vector3(sx * (width * 0.5 - 0.05), (h + ph + 0.35) * 0.5, 0.0), dark)
	_box(root, Vector3(width, ph, 0.06), Vector3(0, h + ph * 0.5, 0), panel)
	_box(root, Vector3(width, 0.3, 0.07), Vector3(0, h + ph + 0.15, 0), band)
	_box(root, Vector3(width + 0.06, 0.04, 0.09), Vector3(0, h + ph + 0.32, 0), dark)
	_box(root, Vector3(width + 0.06, 0.04, 0.09), Vector3(0, h - 0.02, 0), dark)
	var font: Font = load("res://fonts/Inter-Bold.otf")
	_text(root, header.to_upper(), Vector3(0, h + ph + 0.15, -0.04), 40, Color.WHITE, font, width)
	_text(root, title, Vector3(0, h + ph * 0.68, -0.035), 44, Color(0.08, 0.08, 0.1), font, width)
	_text(root, detail, Vector3(0, h + ph * 0.28, -0.035), 30, Color(0.25, 0.27, 0.3), load("res://fonts/Inter-Medium.otf"), width)
	return root

static func _box(root: Node3D, size: Vector3, pos: Vector3, m: Material) -> void:
	var mi := MeshInstance3D.new(); var bm := BoxMesh.new(); bm.size = size; mi.mesh = bm
	mi.material_override = m; mi.position = pos
	root.add_child(mi)

static func _text(root: Node3D, t: String, pos: Vector3, size: int, col: Color, font: Font, width: float) -> void:
	var l := Label3D.new(); l.text = t; l.font = font; l.font_size = size; l.modulate = col
	l.outline_size = 0; l.pixel_size = 0.0035
	l.width = width / l.pixel_size * 0.95; l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	l.position = pos; l.rotation.y = PI   # readable from the front (-Z)
	l.double_sided = false
	root.add_child(l)
