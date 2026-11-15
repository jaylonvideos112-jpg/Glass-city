extends CanvasLayer
## GTA-style HUD (Bible section 13: original GLASS CITY UI).
##   bottom-left: rounded minimap (real streets, GPS route, blips) with health / stamina / hunger bars under it
##   bottom-right: street + area name; speedometer and car condition when driving
##   top-right: clock and date; cash and GlassPay; wanted stars; job status
##   top-left: notification toasts (every notice also goes to the phone's Messages)
##   centre: big banners for BUSTED / WANTED changes; bottom-centre: the context prompt in a box with key caps
## Overlay panels (job board, catalogue, inventory, minigames) use overlay_label().

var main: Node
var street_label: Label
var district_label: Label
var speed_label: Label
var speed_unit: Label
var car_label: Label
var clock_label: Label
var date_label: Label
var prompt_label: Label
var prompt_box: PanelContainer
var flash_label: Label          # big centre banner (kept for compatibility)
var help_label: Label
var help_box: PanelContainer
var radar: Control
var bars: Control
var money_label: Label
var wallet_label: Label
var wanted_label: Label
var job_label: Label
var needs_label: Label          # unused text (bars replace it); kept for compatibility
var toasts: VBoxContainer
var flash_t := 0.0
var cur_street := ""
var _hint_t := 12.0
var _money_shown := -1
var _money_pop := 0.0
var _overlays: Array = []      # [panel, label]: the panel shows while its label is visible

const C_TEXT := Color(0.96, 0.96, 0.97)
const C_DIM := Color(0.78, 0.82, 0.88)
const C_MONEY := Color(0.45, 0.85, 0.45)
const C_PANEL := Color(0.04, 0.05, 0.07, 0.78)
const C_ACCENT := Color(0.95, 0.75, 0.25)

const DISTRICTS := [
	# name, center x (east m), center z (south m), radius - rough, relative to downtown origin
	["Downtown", 250.0, 150.0, 700.0],
	["Warehouse District", -50.0, 750.0, 450.0],
]

var font_bold: Font
var font_black: Font
var font_med: Font

func _ready() -> void:
	font_bold = load("res://fonts/Inter-Bold.otf")
	font_black = load("res://fonts/InterDisplay-Black.otf")
	font_med = load("res://fonts/Inter-Medium.otf")
	# ---- bottom right: where you are, speed
	street_label = _label(30, font_bold)
	_anchor(street_label, Control.PRESET_BOTTOM_RIGHT, -34, -66, true)
	district_label = _label(19, font_med, C_DIM)
	_anchor(district_label, Control.PRESET_BOTTOM_RIGHT, -34, -40, true)
	speed_label = _label(64, font_black)
	_anchor(speed_label, Control.PRESET_BOTTOM_RIGHT, -96, -104, true)
	speed_unit = _label(20, font_bold, C_DIM)
	_anchor(speed_unit, Control.PRESET_BOTTOM_RIGHT, -34, -116, true)
	car_label = _label(16, font_bold, C_DIM)
	_anchor(car_label, Control.PRESET_BOTTOM_RIGHT, -34, -186, true)
	# ---- top right: clock, money, stars, job
	clock_label = _label(30, font_black)
	_anchor(clock_label, Control.PRESET_TOP_RIGHT, -34, 16, true)
	date_label = _label(15, font_med, C_DIM)
	_anchor(date_label, Control.PRESET_TOP_RIGHT, -34, 54, true)
	money_label = _label(34, font_black, C_MONEY)
	_anchor(money_label, Control.PRESET_TOP_RIGHT, -34, 80, true)
	wallet_label = _label(16, font_bold, C_DIM)
	_anchor(wallet_label, Control.PRESET_TOP_RIGHT, -34, 122, true)
	wanted_label = _label(38, font_black, C_ACCENT)
	_anchor(wanted_label, Control.PRESET_TOP_RIGHT, -30, 144, true)
	job_label = _label(15, font_bold, Color(0.75, 0.88, 1.0))
	_anchor(job_label, Control.PRESET_TOP_RIGHT, -34, 194, true)
	needs_label = _label(1, font_med); needs_label.visible = false
	# ---- top left: notifications
	toasts = VBoxContainer.new(); toasts.position = Vector2(28, 24); toasts.custom_minimum_size = Vector2(420, 0)
	toasts.add_theme_constant_override("separation", 8)
	add_child(toasts)
	# ---- centre banner
	flash_label = _label(64, font_black, Color(0.95, 0.25, 0.2))
	flash_label.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	flash_label.grow_horizontal = Control.GROW_DIRECTION_BOTH; flash_label.grow_vertical = Control.GROW_DIRECTION_BOTH
	flash_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	flash_label.offset_top = -160
	flash_label.visible = false
	# ---- bottom centre prompt
	prompt_box = _panel()
	prompt_box.set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM)
	prompt_box.grow_horizontal = Control.GROW_DIRECTION_BOTH; prompt_box.grow_vertical = Control.GROW_DIRECTION_BEGIN
	prompt_box.offset_bottom = -42
	prompt_label = _label(19, font_bold); prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	remove_child(prompt_label); prompt_box.add_child(prompt_label)
	# ---- controls (H)
	help_box = _panel()
	help_box.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	help_box.grow_horizontal = Control.GROW_DIRECTION_BOTH; help_box.grow_vertical = Control.GROW_DIRECTION_BOTH
	help_label = _label(17, font_med)
	remove_child(help_label); help_box.add_child(help_label)
	help_label.text = "CONTROLS\n\n" + \
		"WASD  move / drive        Mouse  look        Shift  sprint        Space  jump / handbrake\n" + \
		"E  get in/out, use, talk, apply, clock in        T  activity here (eat, gym, bowl, fish...)\n" + \
		"Tab  phone        J  job board        I  inventory        K  dealership catalogue\n" + \
		"R  flip car / rent / deposit        B  buy / collect        G  garage        N  auto-deposit\n" + \
		"P / C / U  repair / respray / upgrade at an auto shop        V  camera view        H  this help\n" + \
		"Esc  pause\n\nMap data © OpenStreetMap contributors (ODbL)"
	help_box.visible = false
	# ---- minimap + bars
	radar = Control.new()
	radar.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	radar.offset_left = 28; radar.offset_top = -268; radar.offset_right = 288; radar.offset_bottom = -58
	radar.draw.connect(_draw_radar)
	radar.clip_contents = true
	add_child(radar)
	bars = Control.new()
	bars.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	bars.offset_left = 28; bars.offset_top = -52; bars.offset_right = 288; bars.offset_bottom = -26
	bars.draw.connect(_draw_bars)
	add_child(bars)

func _label(size: int, font: Font = null, col := C_TEXT) -> Label:
	var l := Label.new()
	if font: l.add_theme_font_override("font", font)
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", col)
	l.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.75))
	l.add_theme_constant_override("shadow_offset_x", 2); l.add_theme_constant_override("shadow_offset_y", 2)
	l.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	l.add_theme_constant_override("outline_size", 4 if size < 30 else 7)
	add_child(l)
	return l

func _anchor(l: Label, preset: int, x: float, y: float, right: bool) -> void:
	l.set_anchors_and_offsets_preset(preset)
	l.grow_horizontal = Control.GROW_DIRECTION_BEGIN if right else Control.GROW_DIRECTION_END
	if preset == Control.PRESET_BOTTOM_RIGHT: l.grow_vertical = Control.GROW_DIRECTION_BEGIN
	l.offset_right = x
	if preset == Control.PRESET_BOTTOM_RIGHT: l.offset_bottom = y
	else: l.offset_top = y
	l.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT if right else HORIZONTAL_ALIGNMENT_LEFT

func _panel(col := C_PANEL) -> PanelContainer:
	var p := PanelContainer.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = col
	sb.corner_radius_top_left = 10; sb.corner_radius_top_right = 10; sb.corner_radius_bottom_left = 10; sb.corner_radius_bottom_right = 10
	sb.content_margin_left = 18; sb.content_margin_right = 18; sb.content_margin_top = 10; sb.content_margin_bottom = 10
	sb.shadow_color = Color(0, 0, 0, 0.35); sb.shadow_size = 6
	p.add_theme_stylebox_override("panel", sb)
	add_child(p)
	return p

## a styled panel with a label inside, for overlay screens (job board, catalogue, inventory, minigames)
func overlay_label(pos := Vector2(28, 250)) -> Label:
	var p := _panel(Color(0.04, 0.05, 0.08, 0.86))
	p.position = pos
	var l := Label.new()
	l.add_theme_font_override("font", font_med)
	l.add_theme_font_size_override("font_size", 18)
	l.add_theme_color_override("font_color", C_TEXT)
	p.add_child(l)
	l.visible = false; p.visible = false
	_overlays.append([p, l])
	return l

func toggle_help() -> void:
	help_box.visible = not help_box.visible

## a notice: a toast top-left (big news gets the centre banner too)
func flash(t: String) -> void:
	if main and main.get("phone") and main.phone: main.phone.notify(t)     # every notice also lands in Messages
	var big := t.begins_with("BUSTED") or t.begins_with("You lost the police") or t.begins_with("You were fired")
	if big:
		flash_label.text = t.split(" - ")[0].to_upper()
		flash_label.add_theme_color_override("font_color", Color(0.95, 0.25, 0.2) if t.begins_with("BUSTED") or t.begins_with("You were") else Color(0.4, 0.85, 1.0))
		flash_t = 3.0
	_toast(t)

func _toast(t: String) -> void:
	var p := _panel(Color(0.04, 0.05, 0.08, 0.82))
	remove_child(p)
	var l := Label.new(); l.text = t
	l.add_theme_font_override("font", font_bold); l.add_theme_font_size_override("font_size", 17)
	l.add_theme_color_override("font_color", C_TEXT)
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART; l.custom_minimum_size = Vector2(380, 0)
	p.add_child(l)
	p.set_meta("t", 5.0)
	toasts.add_child(p)
	while toasts.get_child_count() > 4: toasts.get_child(0).free()

func _process(dt: float) -> void:
	if main == null or main.streamer == null:
		return
	var fw: Vector3 = main.focus_world()
	var st: Dictionary = main.streamer.street_at(fw, 28.0)
	if st["name"] != "":
		cur_street = st["name"]
	street_label.text = cur_street
	var dname := "Glass City"
	var bestd := 1e9
	for d in DISTRICTS:
		var dd: float = Vector2(fw.x - d[1], fw.z - d[2]).length() / d[3]
		if dd < 1.0 and dd < bestd:
			bestd = dd; dname = d[0]
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
		var m: int = main.money.cash
		if _money_shown >= 0 and m != _money_shown: _money_pop = 1.0
		_money_shown = m
		money_label.text = "$%s" % _commas(m)
		wallet_label.text = "%s  $%s" % [main.money.app_name, _commas(main.money.wallet)]
		_money_pop = maxf(0.0, _money_pop - dt * 2.0)
		money_label.scale = Vector2.ONE * (1.0 + 0.12 * _money_pop)
	if main.get("jobs") and main.jobs: job_label.text = main.jobs.status_line()
	if main.get("police") and main.police:
		var n: int = main.police.stars
		var blink: bool = main.police.searching and fmod(Time.get_ticks_msec() / 400.0, 2.0) < 1.0
		wanted_label.text = "" if n == 0 else ("★".repeat(n) + "☆".repeat(5 - n))
		wanted_label.modulate.a = 0.35 if blink else 1.0
	job_label.offset_top = 194 if (main.get("police") and main.police and main.police.stars > 0) else 150
	if main.current_car:
		var cc = main.current_car
		speed_label.text = "%d" % int(cc.speed_mps() * 2.237)
		speed_unit.text = "MPH"
		var parts: Array = []
		if cc.health < 999.0: parts.append("ENGINE %d%%" % int(cc.health / 10.0))
		if cc.stolen: parts.append("STOLEN")
		parts.append(cc.model_name.to_upper())
		car_label.text = "  ·  ".join(parts)
		_set_prompt(main.vehicles.prompt(cc.global_position) if main.get("vehicles") and main.vehicles else "")
	else:
		speed_label.text = ""; speed_unit.text = ""; car_label.text = ""
		var bp: String = main.jobs.prompt(main.player.global_position) if main.get("jobs") and main.jobs else ""
		if bp == "" and main.get("homes") and main.homes: bp = main.homes.prompt(main.player.global_position)
		if main.get("business") and main.business:
			var bz: String = main.business.prompt(main.player.global_position)
			if bz != "": bp = (bp + "\n" + bz) if bp != "" else bz
		if bp == "": bp = main.money.prompt(main.player.global_position) if main.get("money") and main.money else ""
		if bp == "": bp = main.bars.prompt(main.player.global_position) if main.bars else ""
		if bp == "" and main.get("vehicles") and main.vehicles: bp = main.vehicles.prompt(main.player.global_position)
		if main.get("activities") and main.activities:
			var ap: String = main.activities.prompt(main.player.global_position)
			if ap != "": bp = (bp + "\n" + ap) if bp != "" else ap
		if bp == "" and main.nearest_car() != null and not main.bars.inside: bp = "Press E to get in"
		_set_prompt(bp)
	# first seconds: a hint about the controls
	if _hint_t > 0.0:
		_hint_t -= dt
		if prompt_label.text == "": _set_prompt("Press H for controls  ·  Tab for your phone")
	flash_t -= dt
	flash_label.visible = flash_t > 0
	flash_label.modulate.a = clampf(flash_t, 0.0, 1.0)
	for tp in toasts.get_children():
		var tt: float = float(tp.get_meta("t", 0.0)) - dt
		tp.set_meta("t", tt)
		tp.modulate.a = clampf(tt * 2.0, 0.0, 1.0)
		if tt <= 0.0: tp.queue_free()
	for o in _overlays: o[0].visible = o[1].visible
	radar.queue_redraw()
	bars.queue_redraw()

## prompt text with key caps: "Press E to ..." -> "[E]  ..."
func _set_prompt(t: String) -> void:
	if t == "":
		prompt_label.text = ""; prompt_box.visible = false; return
	var re := RegEx.new(); re.compile("Press ([A-Z])(?: to|:)? ")
	t = re.sub(t, "[$1]  ", true)
	var re2 := RegEx.new(); re2.compile("(^|  ·  |\\n)([A-Z0-9/]{1,5}): ")
	t = re2.sub(t, "$1[$2] ", true)
	prompt_label.text = t
	prompt_box.visible = true

static func _commas(n: int) -> String:
	var s := str(absi(n))
	var out := ""
	while s.length() > 3:
		out = "," + s.substr(s.length() - 3) + out
		s = s.substr(0, s.length() - 3)
	return ("-" if n < 0 else "") + s + out

func _draw_bars() -> void:
	if main == null or not (main.get("needs") and main.needs): return
	var nd = main.needs
	var w: float = bars.size.x
	var gap := 6.0
	var bw: float = (w - gap * 2.0) / 3.0
	var specs := [[nd.health / 100.0, Color(0.35, 0.8, 0.35), "HEALTH"], [nd.stamina / maxf(nd.max_stamina(), 1.0), Color(0.3, 0.65, 0.95), "STAMINA"],
		[nd.hunger / 100.0, Color(0.95, 0.65, 0.2) if nd.hunger > 20.0 else Color(0.95, 0.3, 0.2), "HUNGER"]]
	for i in 3:
		var x: float = i * (bw + gap)
		bars.draw_rect(Rect2(x, 0, bw, 10), Color(0, 0, 0, 0.6))
		bars.draw_rect(Rect2(x + 1, 1, (bw - 2) * clampf(specs[i][0], 0.0, 1.0), 8), specs[i][1])
		bars.draw_string(font_bold, Vector2(x, 24), specs[i][2], HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color(1, 1, 1, 0.75))

func _draw_radar() -> void:
	var sz: Vector2 = radar.size
	var c := sz * 0.5
	var R: float = minf(sz.x, sz.y) * 0.5
	var scale := 110.0 / 220.0 * (sz.x / 220.0)   # ~240 m across the short side
	# rounded dark map background
	var sb := StyleBoxFlat.new(); sb.bg_color = Color(0.11, 0.14, 0.13, 0.88)
	sb.corner_radius_top_left = 14; sb.corner_radius_top_right = 14; sb.corner_radius_bottom_left = 14; sb.corner_radius_bottom_right = 14
	sb.border_width_left = 3; sb.border_width_right = 3; sb.border_width_top = 3; sb.border_width_bottom = 3; sb.border_color = Color(0, 0, 0, 0.8)
	radar.draw_style_box(sb, Rect2(Vector2.ZERO, sz))
	if main == null:
		return
	var fw: Vector3 = main.focus_world()
	var yaw: float = main.cam_yaw
	var f2 := Vector2(fw.x, fw.z)
	var lim := func(v: Vector2) -> Vector2: return Vector2(clampf(v.x, -c.x + 6, c.x - 6), clampf(v.y, -c.y + 6, c.y - 6))
	# roads: wide ones thicker
	for s in main.streamer.segments_near(fw, 330.0):
		var a: Vector2 = (s[0] - f2).rotated(yaw) * scale
		var b: Vector2 = (s[1] - f2).rotated(yaw) * scale
		if absf(a.x) > c.x + 20 and absf(b.x) > c.x + 20: continue
		if absf(a.y) > c.y + 20 and absf(b.y) > c.y + 20: continue
		radar.draw_line(c + a, c + b, Color(0.55, 0.58, 0.6, 0.95), 4.0)
	for s in main.streamer.segments_near(fw, 330.0):
		var a2: Vector2 = (s[0] - f2).rotated(yaw) * scale
		var b2: Vector2 = (s[1] - f2).rotated(yaw) * scale
		radar.draw_line(c + a2, c + b2, Color(0.82, 0.84, 0.86, 1.0), 2.0)
	# police and service blips
	if main.traffic:
		for tc in main.traffic.cars:
			if not (tc.get("siren", false) or tc.get("chase", false)): continue
			var q: Vector2 = (Vector2(tc["pos"].x, tc["pos"].z) - f2).rotated(yaw) * scale
			var blink := fmod(Time.get_ticks_msec() / 250.0, 2.0) < 1.0
			var col := Color(0.95, 0.2, 0.2) if blink else Color(0.25, 0.45, 1.0)
			radar.draw_circle(c + lim.call(q), 5.0, col)
	# GPS: route along the roads and the waypoint
	var ph = main.get("phone")
	if ph and ph.waypoint != Vector3.INF:
		var prev = null
		for q2 in ph.route:
			var r2: Vector2 = (Vector2(q2.x, q2.z) - f2).rotated(yaw) * scale
			if prev != null:
				radar.draw_line(c + lim.call(prev), c + lim.call(r2), Color(0.75, 0.35, 1.0), 5.0)
			prev = r2
		var wpt: Vector2 = (Vector2(ph.waypoint.x, ph.waypoint.z) - f2).rotated(yaw) * scale
		radar.draw_circle(c + lim.call(wpt), 7.0, Color(0.75, 0.35, 1.0))
		radar.draw_circle(c + lim.call(wpt), 3.0, Color.WHITE)
		var dist_m: float = Vector2(ph.waypoint.x - fw.x, ph.waypoint.z - fw.z).length()
		radar.draw_string(font_bold, Vector2(10, sz.y - 10), "%.1f mi" % (dist_m / 1609.0), HORIZONTAL_ALIGNMENT_LEFT, -1, 15, Color(0.88, 0.75, 1.0))
	# player arrow
	var heading: float
	if main.current_car:
		heading = main.current_car.global_rotation.y - yaw
	else:
		heading = main.player.model.rotation.y - yaw
	var pts := PackedVector2Array([Vector2(0, -11), Vector2(8, 9), Vector2(0, 4), Vector2(-8, 9)])
	for i in pts.size():
		pts[i] = c + pts[i].rotated(-heading)
	radar.draw_colored_polygon(pts, Color(1, 1, 1))
	radar.draw_polyline(pts + PackedVector2Array([pts[0]]), Color(0, 0, 0, 0.8), 1.5)
	# north marker on the rim
	var n: Vector2 = lim.call(Vector2(0, -R * 2.0).rotated(yaw))
	radar.draw_circle(c + n, 10.0, Color(0, 0, 0, 0.7))
	radar.draw_string(font_bold, c + n + Vector2(-5, 6), "N", HORIZONTAL_ALIGNMENT_LEFT, -1, 15, Color.WHITE)
