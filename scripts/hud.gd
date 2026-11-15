extends CanvasLayer
## GTA-style HUD: radar (real streets), street/district name, speedometer, prompts.

var main: Node
var street_label: Label
var district_label: Label
var speed_label: Label
var clock_label: Label
var date_label: Label
var prompt_label: Label
var flash_label: Label
var help_label: Label
var radar: Control
var money_label: Label
var wanted_label: Label
var job_label: Label
var flash_t := 0.0
var cur_street := ""

const DISTRICTS := [
	# name, center x (east m), center z (south m), radius — rough, relative to downtown origin
	["Downtown", 250.0, 150.0, 700.0],
	["Warehouse District", -50.0, 750.0, 450.0],
]

func _ready() -> void:
	var font_big := 30
	street_label = _label(font_big, Vector2(0, 0))
	street_label.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_RIGHT)
	street_label.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	street_label.grow_vertical = Control.GROW_DIRECTION_BEGIN
	street_label.offset_right = -30; street_label.offset_bottom = -64
	street_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	district_label = _label(20, Vector2.ZERO)
	district_label.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_RIGHT)
	district_label.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	district_label.grow_vertical = Control.GROW_DIRECTION_BEGIN
	district_label.offset_right = -30; district_label.offset_bottom = -36
	district_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	district_label.modulate = Color(0.85, 0.9, 1.0)
	speed_label = _label(26, Vector2.ZERO)
	speed_label.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	speed_label.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	speed_label.offset_right = -30; speed_label.offset_top = 92
	clock_label = _label(30, Vector2.ZERO)
	clock_label.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	clock_label.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	clock_label.offset_right = -30; clock_label.offset_top = 18
	clock_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	date_label = _label(17, Vector2.ZERO)
	date_label.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	date_label.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	date_label.offset_right = -30; date_label.offset_top = 58
	date_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	date_label.modulate = Color(0.85, 0.9, 1.0)
	speed_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	money_label = _label(26, Vector2(30, 18))
	money_label.modulate = Color(0.55, 0.95, 0.55)
	wanted_label = _label(34, Vector2(30, 56))
	wanted_label.modulate = Color(1.0, 0.85, 0.3)
	job_label = _label(18, Vector2(30, 102))
	job_label.modulate = Color(0.85, 0.92, 1.0)
	prompt_label = _label(22, Vector2.ZERO)
	prompt_label.set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM)
	prompt_label.grow_horizontal = Control.GROW_DIRECTION_BOTH
	prompt_label.grow_vertical = Control.GROW_DIRECTION_BEGIN
	prompt_label.offset_bottom = -140
	prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	flash_label = _label(44, Vector2.ZERO)
	flash_label.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	flash_label.grow_horizontal = Control.GROW_DIRECTION_BOTH
	flash_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	flash_label.modulate = Color(0.9, 0.2, 0.15)
	help_label = _label(18, Vector2(24, 24))
	help_label.text = "WASD move / drive    Mouse look    Shift sprint    Space jump / handbrake\nE enter/exit car    R flip car    Wheel zoom    H hide help    Esc free mouse\nMap data © OpenStreetMap contributors (ODbL)"
	help_label.modulate = Color(1, 1, 1, 0.85)
	radar = Control.new()
	radar.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
	radar.position = Vector2(30, -250)
	radar.size = Vector2(220, 220)
	radar.draw.connect(_draw_radar)
	add_child(radar)
	radar.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	radar.offset_left = 30; radar.offset_top = -250; radar.offset_right = 250; radar.offset_bottom = -30

func _label(size: int, pos: Vector2) -> Label:
	var l := Label.new()
	l.position = pos
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_outline_color", Color.BLACK)
	l.add_theme_constant_override("outline_size", 8)
	add_child(l)
	return l

func toggle_help() -> void:
	help_label.visible = not help_label.visible

func flash(t: String) -> void:
	flash_label.text = t
	flash_t = 2.5

func _process(dt: float) -> void:
	if main == null or main.streamer == null:
		return
	var fw: Vector3 = main.focus_world()
	var st: Dictionary = main.streamer.street_at(fw, 28.0)
	if st["name"] != "":
		cur_street = st["name"]
	street_label.text = cur_street
	var dname := "Toledo"
	var bestd := 1e9
	for d in DISTRICTS:
		var dd: float = Vector2(fw.x - d[1], fw.z - d[2]).length() / d[3]
		if dd < 1.0 and dd < bestd:
			bestd = dd; dname = d[0]
	# real neighbourhood names from OpenStreetMap place nodes (closest one within ~1.3 km wins)
	for pl in main.streamer.manifest.get("places", []):
		var r: float = 1300.0 if pl[3] in ["neighbourhood", "quarter"] else 2200.0
		var dd2: float = Vector2(fw.x - pl[1], fw.z - pl[2]).length() / r
		if dd2 < 1.0 and dd2 < bestd:
			bestd = dd2; dname = pl[0]
	district_label.text = dname
	if main.tod:
		clock_label.text = main.tod.clock_string()
		date_label.text = "%s  ·  %s" % [main.tod.date_string(), main.weather.label() if main.weather else ""]
	if main.get("money") and main.money:
		money_label.text = "$%d   %s $%d" % [main.money.cash, main.money.app_name, main.money.wallet]
	if main.get("jobs") and main.jobs: job_label.text = main.jobs.status_line()
	if main.get("police") and main.police:
		var n: int = main.police.stars
		var blink: bool = main.police.searching and fmod(Time.get_ticks_msec() / 400.0, 2.0) < 1.0
		wanted_label.text = "" if n == 0 else ("★".repeat(n) + "☆".repeat(5 - n))
		wanted_label.visible = n > 0 and not blink
	if main.current_car:
		speed_label.text = "%d MPH" % int(main.current_car.speed_mps() * 2.237)
		prompt_label.text = ""
	else:
		speed_label.text = ""
		var bp: String = main.jobs.prompt(main.player.global_position) if main.get("jobs") and main.jobs else ""
		if bp == "" and main.get("homes") and main.homes: bp = main.homes.prompt(main.player.global_position)
		if main.get("business") and main.business:
			var bz: String = main.business.prompt(main.player.global_position)
			if bz != "": bp = (bp + "\n" + bz) if bp != "" else bz
		if bp == "": bp = main.money.prompt(main.player.global_position) if main.get("money") and main.money else ""
		if bp == "": bp = main.bars.prompt(main.player.global_position) if main.bars else ""
		if bp != "": prompt_label.text = bp
		else: prompt_label.text = "Press E to get in" if (main.nearest_car() != null and not main.bars.inside) else ""
	flash_t -= dt
	flash_label.visible = flash_t > 0
	radar.queue_redraw()

func _draw_radar() -> void:
	var c := Vector2(110, 110)
	var R := 105.0
	var scale := R / 220.0   # 220 m radius shown
	radar.draw_circle(c, R + 4, Color(0, 0, 0, 0.75))
	radar.draw_circle(c, R, Color(0.16, 0.2, 0.17, 0.85))
	if main == null:
		return
	var fw: Vector3 = main.focus_world()
	var yaw: float = main.cam_yaw
	var f2 := Vector2(fw.x, fw.z)
	for s in main.streamer.segments_near(fw, 260.0):
		var a: Vector2 = (s[0] - f2).rotated(yaw) * scale
		var b: Vector2 = (s[1] - f2).rotated(yaw) * scale
		if a.length() > R and b.length() > R:
			continue
		a = a.limit_length(R); b = b.limit_length(R)
		radar.draw_line(c + a, c + b, Color(0.85, 0.85, 0.8, 0.9), 3.0)
	# player arrow (heading relative to camera)
	var heading: float
	if main.current_car:
		heading = main.current_car.global_rotation.y - yaw
	else:
		heading = main.player.model.rotation.y - yaw
	var pts := PackedVector2Array([Vector2(0, -9), Vector2(6, 7), Vector2(-6, 7)])
	for i in pts.size():
		pts[i] = c + pts[i].rotated(-heading)
	radar.draw_colored_polygon(pts, Color(1, 0.85, 0.2))
	# north marker
	var n := Vector2(0, -R).rotated(yaw)
	radar.draw_string(ThemeDB.fallback_font, c + n * 0.9 + Vector2(-6, 6), "N", HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color.WHITE)
