extends CanvasLayer
## GLASS CITY HUD, "B · Cinematic Minimal" (owner's pick, 2026-11-28; mock-ups: HUD options canvas, board B).
## Quiet, photoreal-friendly: warm off-white type with soft shadows, no heavy panels, things fade when idle.
##   bottom-left: small rounded-square minimap (real streets, GPS route in gold, blips), and under it three thin
##                rings (health / stamina / hunger) beside the street name
##   bottom-right: weapon + ammo; speed and car condition when driving
##   top-right: cash with a small caption (fades back when unchanged), clock, job
##   WANTED: no stars (owner, 2026-11-28: "whenever the cops are on you you get red and blue flashing at the top of
##   your screen no stars"). A police light bar glows along the top edge: red and blue wig-wag with strobe bursts,
##   brighter and faster with more heat. The closer you are to beating the cops (police.escape_progress()), the
##   smaller, dimmer and slower it gets: it shrinks toward the top corners and stops strobing.
##   top-left: notification toasts (every notice also goes to the phone's Messages)
##   centre: big banners for BUSTED / WANTED changes; bottom-centre: the context prompt with key caps
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
var weapon_label: Label
var needs_label: Label          # unused text (bars replace it); kept for compatibility
var toasts: VBoxContainer
var flash_t := 0.0
var cur_street := ""
var _hint_t := 12.0
var _money_shown := -1
var _money_pop := 0.0
var _overlays: Array = []
## minimap picture: an unshaded top-down render of the real scene (roofs, lawns, water, trees), refreshed a few
## times a second; the road lines and blips are drawn over it
var _mm_vp: SubViewport
var _mm_cam: Camera3D
var _mm_t := 0.0
var _tgt: Control              # combat lock-on marker + the target's health
var hit_flash := 0.0           # red edge flash when you get hurt
var _vignette: ColorRect
var fish := {}                 # {"state": "wait"|"bite", "frac": 0..1 of the bite window left} or {} = hidden
var fish_ctl: Control
var meter := -1.0               # 0..1 shows the minigame aim meter (bowling); < 0 hides it
var meter_ctl: Control      # [panel, label]: the panel shows while its label is visible

const C_TEXT := Color(0.945, 0.93, 0.894)        # warm off-white (#f1ede4)
const C_DIM := Color(0.945, 0.93, 0.894, 0.7)
const C_MONEY := Color(0.945, 0.93, 0.894)
const C_PANEL := Color(0.05, 0.05, 0.05, 0.45)
const C_ACCENT := Color(0.91, 0.75, 0.42)          # muted gold: GPS, waypoint, wanted
var _money_idle := 0.0
var _lights: ColorRect          # the police light bar across the top of the screen
var _lights_a := 0.0            # eased visibility, so the lights fade in and out instead of popping
var _tame := 0.0                # eased escape progress: the closer you are to beating the cops, the smaller and calmer

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
	street_label = _label(13, font_bold)            # drawn beside the rings now; labels kept for other scripts
	street_label.visible = false
	district_label = _label(13, font_med, C_DIM); district_label.visible = false
	speed_label = _label(40, font_bold)
	_anchor(speed_label, Control.PRESET_BOTTOM_RIGHT, -84, -70, true)
	speed_unit = _label(13, font_bold, C_DIM)
	_anchor(speed_unit, Control.PRESET_BOTTOM_RIGHT, -40, -80, true)
	car_label = _label(13, font_med, C_DIM)
	_anchor(car_label, Control.PRESET_BOTTOM_RIGHT, -40, -124, true)
	# ---- top right: clock, money, stars, job
	money_label = _label(26, font_bold, C_MONEY)
	_anchor(money_label, Control.PRESET_TOP_RIGHT, -40, 30, true)
	wallet_label = _label(12, font_med, C_DIM)
	_anchor(wallet_label, Control.PRESET_TOP_RIGHT, -40, 64, true)
	wanted_label = _label(22, font_bold, C_ACCENT)
	_anchor(wanted_label, Control.PRESET_TOP_RIGHT, -38, 86, true)
	clock_label = _label(15, font_med, C_DIM)
	_anchor(clock_label, Control.PRESET_TOP_RIGHT, -40, 118, true)
	date_label = _label(12, font_med, C_DIM)
	_anchor(date_label, Control.PRESET_TOP_RIGHT, -40, 138, true)
	job_label = _label(13, font_med, C_DIM)
	_anchor(job_label, Control.PRESET_TOP_RIGHT, -40, 160, true)
	weapon_label = _label(20, font_bold, C_TEXT)
	_anchor(weapon_label, Control.PRESET_BOTTOM_RIGHT, -40, -34, true)
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
	prompt_box.offset_bottom = -112
	prompt_label = _label(16, font_bold); prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	remove_child(prompt_label); prompt_box.add_child(prompt_label)
	# ---- controls (H)
	help_box = _panel()
	help_box.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	help_box.grow_horizontal = Control.GROW_DIRECTION_BOTH; help_box.grow_vertical = Control.GROW_DIRECTION_BOTH
	help_label = _label(17, font_med)
	remove_child(help_label); help_box.add_child(help_label)
	help_label.text = "CONTROLS\n\n" + \
		"WASD  move / drive        Mouse  look        Shift  sprint        Space  jump / handbrake\n" + \
		"F  get in / out of a car        E  use, talk, apply, clock in, doors        T  activity here (eat, gym, bowl...)\n" + \
		"1-6  fists / bat or knife / pistol / shotgun / rifle / grenades    Right mouse (hold)  aim    Left mouse  fire / throw    R  reload    C  crouch\n" + \
		"Left click  punch (tap: combo)   Right click  kick   Z / middle click  tackle   Q  guard (tap just before a hit = parry)   Ctrl  dodge   Space  struggle / get up\n" + \
		"Up arrow  phone        Tab (hold)  weapon wheel        J  job board        I  inventory        K  dealership catalogue\n" + \
		"R  flip car / rent / deposit        B  buy / collect        G  garage        N  auto-deposit\n" + \
		"P / C / U  repair / respray / upgrade at an auto shop        V  camera view        H  this help\n" + \
		"Esc  pause\n\nMap data © OpenStreetMap contributors (ODbL)"
	help_box.visible = false
	# ---- minimap + bars
	radar = Control.new()
	radar.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	radar.offset_left = 32; radar.offset_top = -254; radar.offset_right = 208; radar.offset_bottom = -78
	radar.draw.connect(_draw_radar)
	radar.clip_contents = true
	add_child(radar)
	bars = Control.new()
	bars.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	bars.offset_left = 32; bars.offset_top = -68; bars.offset_right = 560; bars.offset_bottom = -28
	bars.draw.connect(_draw_bars)
	add_child(bars)
	meter_ctl = Control.new()
	meter_ctl.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	meter_ctl.offset_left = -220; meter_ctl.offset_right = 220; meter_ctl.offset_top = -150; meter_ctl.offset_bottom = -110
	meter_ctl.draw.connect(_draw_meter)
	add_child(meter_ctl)
	_vignette = ColorRect.new(); _vignette.set_anchors_preset(Control.PRESET_FULL_RECT); _vignette.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var vm := ShaderMaterial.new(); vm.shader = Shader.new()
	vm.shader.code = "shader_type canvas_item; uniform float a = 0.0; uniform float low = 0.0; void fragment() { vec2 q = UV - 0.5; float e = smoothstep(0.25, 0.75, length(q) * 1.4); float k = max(a, low * (0.55 + 0.25 * sin(TIME * 4.0))); COLOR = vec4(0.6, 0.0, 0.0, e * k * 0.8); }"
	_vignette.material = vm
	add_child(_vignette); move_child(_vignette, 0)
	_lights = ColorRect.new(); _lights.set_anchors_preset(Control.PRESET_TOP_WIDE); _lights.offset_bottom = 170
	_lights.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var lm := ShaderMaterial.new(); lm.shader = Shader.new()
	lm.shader.code = """shader_type canvas_item;
uniform float vis = 0.0;      // 0 hidden .. 1 full
uniform float heat = 0.2;     // 0.2 (1 star) .. 1.0 (5 stars)
uniform float search = 0.0;   // 1 = cops lost sight: no strobe
uniform float tame = 0.0;     // 0 full chase .. 1 about to lose them: smaller, dimmer, slower
void fragment() {
	float rate = mix(2.6, 4.2, heat) * mix(1.0, 0.35, tame);
	float ph = fract(TIME * rate);
	float side = step(0.5, ph);                                  // which side is lit (wig-wag)
	float strobe = mix(step(0.5, fract(ph * 6.0)) * 0.55 + 0.45, 1.0, max(search, tame));   // quick bursts inside each half
	vec2 uv = UV;
	float fall = exp(-uv.y * mix(mix(5.5, 3.6, heat), 14.0, tame));   // glow hangs down from the top edge
	float spread = mix(1.25, 4.0, tame);                              // and pulls back into the corners when tame
	float red_pool = smoothstep(1.0, 0.0, uv.x * spread);             // red pools from the left
	float blue_pool = smoothstep(1.0, 0.0, (1.0 - uv.x) * spread);    // blue from the right
	vec3 red = vec3(1.0, 0.08, 0.06), blue = vec3(0.1, 0.25, 1.0);
	float r = red_pool * (1.0 - side) * strobe, b = blue_pool * side * strobe;
	float edge = smoothstep(0.03, 0.0, uv.y) * 0.6;              // a hot line right at the top
	vec3 col = red * r + blue * b;
	float a = (max(r, b) * 0.85 + edge * max(r, b)) * fall * vis * mix(0.55, 1.0, heat) * mix(1.0, 0.22, tame);
	COLOR = vec4(col, clamp(a, 0.0, 0.9));
}"""
	_lights.material = lm
	add_child(_lights); move_child(_lights, 1)
	_tgt = Control.new(); _tgt.set_anchors_preset(Control.PRESET_FULL_RECT); _tgt.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_tgt.draw.connect(_draw_target); add_child(_tgt)
	fish_ctl = Control.new()
	fish_ctl.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	fish_ctl.offset_left = -130; fish_ctl.offset_right = 130; fish_ctl.offset_top = -150; fish_ctl.offset_bottom = -12
	fish_ctl.draw.connect(_draw_fish)
	add_child(fish_ctl)

func _label(size: int, font: Font = null, col := C_TEXT) -> Label:
	var l := Label.new()
	if font: l.add_theme_font_override("font", font)
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", col)
	l.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.7))          # soft shadow, thin outline
	l.add_theme_constant_override("shadow_offset_x", 0); l.add_theme_constant_override("shadow_offset_y", 1)
	l.add_theme_constant_override("shadow_outline_size", 4)
	l.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.35))
	l.add_theme_constant_override("outline_size", 2)
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
	sb.corner_radius_top_left = 8; sb.corner_radius_top_right = 8; sb.corner_radius_bottom_left = 8; sb.corner_radius_bottom_right = 8
	sb.content_margin_left = 14; sb.content_margin_right = 14; sb.content_margin_top = 8; sb.content_margin_bottom = 8
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
	var big := t.begins_with("BUSTED") or t.begins_with("WASTED") or t.begins_with("You lost the police") or t.begins_with("You were fired")
	if big:
		flash_label.text = t.split(" - ")[0].to_upper()
		flash_label.add_theme_color_override("font_color", Color(0.95, 0.25, 0.2) if t.begins_with("BUSTED") or t.begins_with("WASTED") or t.begins_with("You were") else Color(0.4, 0.85, 1.0))
		flash_t = 3.0
	_toast(t)

func _toast(t: String) -> void:
	for q in toasts.get_children():          # the same notice again just refreshes the one on screen
		if q.get_child_count() > 0 and q.get_child(0) is Label and q.get_child(0).text == t:
			q.set_meta("t", 5.0); return
	var p := _panel(Color(0.03, 0.03, 0.03, 0.5))
	remove_child(p)
	var l := Label.new(); l.text = t
	l.add_theme_font_override("font", font_med); l.add_theme_font_size_override("font_size", 15)
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
		wallet_label.text = "CASH  ·  %s $%s" % [main.money.app_name.to_upper(), _commas(main.money.wallet)]
		if _money_pop > 0.0: _money_idle = 0.0
		_money_idle += dt
		_money_pop = maxf(0.0, _money_pop - dt * 2.0)
		money_label.scale = Vector2.ONE * (1.0 + 0.08 * _money_pop)
		var fade: float = clampf(1.0 - (_money_idle - 6.0) / 1.5, 0.45, 1.0)    # cinematic: settles back when idle
		money_label.modulate.a = fade; wallet_label.modulate.a = fade * 0.9
	if main.get("jobs") and main.jobs: job_label.text = main.jobs.status_line()
	if main.get("weapons") and main.weapons: weapon_label.text = main.weapons.ammo_line() if main.current_car == null else ""
	var stars: int = main.police.stars if (main.get("police") and main.police) else 0
	var searching: bool = stars > 0 and main.police.searching
	wanted_label.text = ""                                       # no stars: the light bar says it all
	_lights_a = move_toward(_lights_a, 1.0 if stars > 0 else 0.0, dt * (2.5 if stars > 0 else 0.8))
	_lights.visible = _lights_a > 0.001
	var lsm := _lights.material as ShaderMaterial
	lsm.set_shader_parameter("vis", _lights_a)
	lsm.set_shader_parameter("heat", clampf(float(stars) / 5.0, 0.2, 1.0))
	lsm.set_shader_parameter("search", 1.0 if searching else 0.0)
	var tame: float = main.police.escape_progress() if stars > 0 else 0.0
	_tame = lerpf(_tame, tame, clampf(dt * 3.0, 0.0, 1.0))
	lsm.set_shader_parameter("tame", _tame)
	_lights.offset_bottom = lerpf(170.0, 45.0, _tame)            # the whole bar shrinks as you get away
	clock_label.offset_top = 86; date_label.offset_top = 106; job_label.offset_top = 128
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
		if bp == "" and main.get("weapons") and main.weapons: bp = main.weapons.prompt(main.player.global_position)
		if bp == "" and main.get("vehicles") and main.vehicles: bp = main.vehicles.prompt(main.player.global_position)
		if main.get("activities") and main.activities:
			var ap: String = main.activities.prompt(main.player.global_position)
			if ap != "": bp = (bp + "\n" + ap) if bp != "" else ap
		if bp == "" and main.nearest_car() != null and not main.bars.inside: bp = "Press F to get in"
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
	_update_minimap_cam(dt)
	if main and main.get("player") and main.player: radar.visible = main.player.global_position.y > -500.0 or main.current_car != null   # no map indoors
	radar.queue_redraw()
	bars.queue_redraw()
	hit_flash = maxf(0.0, hit_flash - dt * 1.5)
	_tgt.queue_redraw()
	var lowh: float = 0.0
	if main and main.get("needs") and main.needs: lowh = clampf((30.0 - main.needs.health) / 30.0, 0.0, 1.0)
	(_vignette.material as ShaderMaterial).set_shader_parameter("a", hit_flash)
	(_vignette.material as ShaderMaterial).set_shader_parameter("low", lowh)
	meter_ctl.visible = meter >= 0.0
	fish_ctl.visible = not fish.is_empty()
	if fish_ctl.visible: fish_ctl.queue_redraw()
	if meter >= 0.0: meter_ctl.queue_redraw()

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

## fishing: a patch of water with the bobber; on a bite it dips, ripples ring out and a timer ring runs down
func _draw_fish() -> void:
	var w: float = fish_ctl.size.x; var h: float = fish_ctl.size.y
	var t := Time.get_ticks_msec() / 1000.0
	var sb := StyleBoxFlat.new(); sb.bg_color = Color(0.05, 0.16, 0.24, 0.88)
	for k in ["corner_radius_top_left", "corner_radius_top_right", "corner_radius_bottom_left", "corner_radius_bottom_right"]: sb.set(k, 14)
	sb.border_width_bottom = 2; sb.border_width_top = 2; sb.border_width_left = 2; sb.border_width_right = 2; sb.border_color = Color(0, 0, 0, 0.6)
	fish_ctl.draw_style_box(sb, Rect2(0, 0, w, h))
	var c := Vector2(w * 0.5, h * 0.52)
	for i in 3:     # gentle ripples
		var r := fmod(t * 14.0 + i * 16.0, 48.0) + 8.0
		fish_ctl.draw_arc(c + Vector2(0, 8), r, 0, TAU, 32, Color(0.6, 0.85, 1.0, 0.35 * (1.0 - r / 56.0)), 1.5)
	var bite: bool = fish.get("state", "") == "bite"
	var dip := 0.0
	if bite:
		dip = 10.0 + sin(t * 30.0) * 4.0
		fish_ctl.draw_arc(c + Vector2(0, 8), 54, -PI * 0.5, -PI * 0.5 + TAU * float(fish.get("frac", 1.0)), 40, Color(1.0, 0.85, 0.2), 5.0)
	else:
		dip = sin(t * 2.2) * 2.0
	fish_ctl.draw_line(Vector2(w * 0.5 + 70, 6), c + Vector2(0, dip - 12), Color(0.9, 0.9, 0.9, 0.6), 1.0)
	fish_ctl.draw_circle(c + Vector2(0, dip - 4), 9.0, Color(0.92, 0.12, 0.1))
	fish_ctl.draw_rect(Rect2(c.x - 9, c.y + dip - 4, 18, 9), Color(0.96, 0.96, 0.94))
	fish_ctl.draw_rect(Rect2(c.x - 1.5, c.y + dip - 20, 3, 8), Color(0.15, 0.15, 0.15))
	var label := "BITE!  SPACE" if bite else "Waiting for a bite..."
	fish_ctl.draw_string(font_bold, Vector2(0, h - 12), label, HORIZONTAL_ALIGNMENT_CENTER, w, 20 if bite else 15, Color(1, 0.88, 0.25) if bite else Color(0.85, 0.92, 1.0))

func _draw_target() -> void:
	if main == null or main.get("combat") == null or main.camera == null: return
	var wpx = main.get("weapons")
	if wpx and wpx.armed_gun() and main.current_car == null:
		var c0: Vector2 = _tgt.size * 0.5
		var gap: float = 5.0 + (2.0 if wpx.aiming else 12.0) * (2.0 if wpx.current == "shotgun" else 1.0)
		var cc := Color(1, 1, 1, 0.9 if wpx.aiming else 0.45)
		for v in [Vector2(1, 0), Vector2(-1, 0), Vector2(0, 1), Vector2(0, -1)]:
			_tgt.draw_line(c0 + v * gap, c0 + v * (gap + 7.0), Color(0, 0, 0, 0.6), 4.0)
			_tgt.draw_line(c0 + v * gap, c0 + v * (gap + 7.0), cc, 2.0)
		_tgt.draw_circle(c0, 1.6, cc)
		if wpx.hit_marker > 0.0:        # hit confirm
			for v in [Vector2(1, 1), Vector2(-1, 1), Vector2(1, -1), Vector2(-1, -1)]:
				_tgt.draw_line(c0 + v * 6.0, c0 + v * 13.0, Color(1, 0.3, 0.25, wpx.hit_marker * 4.0), 2.5)
	if wpx and wpx.lock != null and wpx.aiming:        # hard lock: a red diamond on them
		var lp: Vector3 = wpx._lock_point()
		if not main.camera.is_position_behind(lp):
			var q: Vector2 = main.camera.unproject_position(lp)
			_tgt.draw_polyline(PackedVector2Array([q + Vector2(0, -9), q + Vector2(9, 0), q + Vector2(0, 9), q + Vector2(-9, 0), q + Vector2(0, -9)]), Color(1, 0.25, 0.2), 2.5)
	var cbt = main.combat
	if cbt.pstate in ["pinned", "down"]:
		var vs: Vector2 = _tgt.size
		var bw := 360.0; var x0 := (vs.x - bw) * 0.5; var y0 := vs.y - 210.0
		var label := "PINNED  -  MASH  SPACE" if cbt.pstate == "pinned" else "KNOCKED DOWN  -  SPACE to get up"
		_tgt.draw_string(font_bold, Vector2(0, y0 - 12), label, HORIZONTAL_ALIGNMENT_CENTER, vs.x, 22, Color(1, 0.85, 0.3))
		if cbt.pstate == "pinned":
			_tgt.draw_rect(Rect2(x0, y0, bw, 16), Color(0, 0, 0, 0.7))
			_tgt.draw_rect(Rect2(x0 + 2, y0 + 2, (bw - 4) * clampf(cbt.escape, 0.0, 1.0), 12), Color(0.95, 0.75, 0.2))
	if cbt.target == null: return
	var t: Dictionary = main.combat.target
	var head: Vector3 = Vector3(t["pos"].x, float(t["y"]) + 2.0, t["pos"].z) - main.world_offset
	if main.camera.is_position_behind(head): return
	var sp: Vector2 = main.camera.unproject_position(head)
	var col := Color(1.0, 0.3, 0.25) if t["state"] == "fight" else Color(1, 1, 1, 0.9)
	_tgt.draw_colored_polygon(PackedVector2Array([sp + Vector2(-9, -12), sp + Vector2(9, -12), sp + Vector2(0, 0)]), col)
	if t.has("hp"):
		var f: float = clampf(float(t["hp"]) / maxf(float(t.get("hp_max", 100.0)), 1.0), 0.0, 1.0)
		_tgt.draw_rect(Rect2(sp + Vector2(-26, -26), Vector2(52, 6)), Color(0, 0, 0, 0.6))
		_tgt.draw_rect(Rect2(sp + Vector2(-25, -25), Vector2(50 * f, 4)), Color(0.9, 0.25, 0.2))

## aim meter: a track, a green sweet spot in the middle, a white marker
func _draw_meter() -> void:
	var w: float = meter_ctl.size.x; var h := 22.0
	var sb := StyleBoxFlat.new(); sb.bg_color = Color(0.03, 0.04, 0.06, 0.85)
	sb.corner_radius_top_left = 8; sb.corner_radius_top_right = 8; sb.corner_radius_bottom_left = 8; sb.corner_radius_bottom_right = 8
	meter_ctl.draw_style_box(sb, Rect2(0, 0, w, h + 12))
	meter_ctl.draw_rect(Rect2(8, 6, w - 16, h), Color(0.75, 0.25, 0.2, 0.7))
	meter_ctl.draw_rect(Rect2(8 + (w - 16) * 0.3, 6, (w - 16) * 0.4, h), Color(0.9, 0.75, 0.25, 0.85))
	meter_ctl.draw_rect(Rect2(8 + (w - 16) * 0.45, 6, (w - 16) * 0.1, h), Color(0.35, 0.85, 0.35))
	var x: float = 8 + (w - 16) * clampf(meter, 0.0, 1.0)
	meter_ctl.draw_rect(Rect2(x - 3, 2, 6, h + 8), Color.WHITE)

func _update_minimap_cam(dt: float) -> void:
	if main == null or main.get("camera") == null or not radar.visible: return
	if _mm_vp == null:
		if main.has_meta("no_minimap_render"): return
		_mm_vp = SubViewport.new(); _mm_vp.size = Vector2i(256, 256)
		_mm_vp.world_3d = get_viewport().world_3d
		_mm_vp.debug_draw = Viewport.DEBUG_DRAW_UNSHADED
		_mm_vp.render_target_update_mode = SubViewport.UPDATE_ONCE
		_mm_vp.positional_shadow_atlas_size = 0
		_mm_cam = Camera3D.new(); _mm_cam.projection = Camera3D.PROJECTION_ORTHOGONAL
		_mm_cam.far = 900.0; _mm_cam.near = 1.0
		var env := Environment.new(); env.background_mode = Environment.BG_COLOR; env.background_color = Color(0.2, 0.3, 0.38)
		_mm_cam.environment = env
		_mm_vp.add_child(_mm_cam); add_child(_mm_vp)
	_mm_t -= dt
	if _mm_t > 0.0: return
	_mm_t = 0.5
	var scale := 110.0 / 220.0 * (radar.size.x / 220.0)
	var span: float = maxf(radar.size.x, radar.size.y) / scale
	_mm_cam.size = span
	var fw: Vector3 = main.focus_world() - main.world_offset
	var yaw: float = main.cam_yaw
	var fwd := Vector3(-sin(yaw), 0, -cos(yaw))
	_mm_cam.global_transform = Transform3D(Basis.looking_at(Vector3.DOWN, fwd), fw + Vector3(0, 500, 0))
	_mm_vp.render_target_update_mode = SubViewport.UPDATE_ONCE

## three thin rings (health, stamina, hunger) with a small glyph each, then the street and area name
func _draw_bars() -> void:
	if main == null or not (main.get("needs") and main.needs): return
	var nd = main.needs
	var specs := [[nd.health / 100.0, "h"], [nd.stamina / maxf(nd.max_stamina(), 1.0), "s"], [nd.hunger / 100.0, "f"]]
	var r := 17.0
	for i in 3:
		var c := Vector2(r + 2.0 + i * 48.0, 20.0)
		var f: float = clampf(specs[i][0], 0.0, 1.0)
		var col := C_TEXT if f > 0.25 else Color(0.92, 0.42, 0.34)
		bars.draw_circle(c, r, Color(0, 0, 0, 0.45))
		bars.draw_arc(c, r - 1.0, 0, TAU, 40, Color(1, 1, 1, 0.22), 2.0, true)
		if f > 0.001: bars.draw_arc(c, r - 1.0, -PI * 0.5, -PI * 0.5 + TAU * f, 40, col, 2.6, true)
		match specs[i][1]:
			"h":     # heart
				var hp := PackedVector2Array()
				for k in 24:
					var t := TAU * k / 24.0
					hp.append(c + Vector2(16 * pow(sin(t), 3), -(13 * cos(t) - 5 * cos(2 * t) - 2 * cos(3 * t) - cos(4 * t))) * 0.36 + Vector2(0, 1))
				bars.draw_colored_polygon(hp, col)
			"s":     # bolt
				bars.draw_colored_polygon(PackedVector2Array([c + Vector2(-4, 8), c + Vector2(0, 0), c + Vector2(-4, 0), c + Vector2(3, -8), c + Vector2(1, -1), c + Vector2(5, -1)]), col)
			"f":     # fork
				bars.draw_line(c + Vector2(0, -7), c + Vector2(0, 8), col, 2.0)
				for dx in [-3.0, 0.0, 3.0]: bars.draw_line(c + Vector2(dx, -8), c + Vector2(dx, -3), col, 1.5)
				bars.draw_line(c + Vector2(-3, -3), c + Vector2(3, -3), col, 1.5)
	var x0 := 3 * 48.0 + 8.0
	bars.draw_string(font_bold, Vector2(x0 + 1, 22), cur_street.to_upper(), HORIZONTAL_ALIGNMENT_LEFT, -1, 13, Color(0, 0, 0, 0.6))
	bars.draw_string(font_bold, Vector2(x0, 21), cur_street.to_upper(), HORIZONTAL_ALIGNMENT_LEFT, -1, 13, C_TEXT)
	bars.draw_string(font_med, Vector2(x0, 37), district_label.text.to_upper(), HORIZONTAL_ALIGNMENT_LEFT, -1, 11, C_DIM)

func _draw_radar() -> void:
	var sz: Vector2 = radar.size
	var c := sz * 0.5
	var R: float = minf(sz.x, sz.y) * 0.5
	var scale := 110.0 / 220.0 * (sz.x / 220.0)   # ~240 m across the short side
	# rounded dark map background
	var sb := StyleBoxFlat.new(); sb.bg_color = Color(0.08, 0.086, 0.08, 0.55)
	sb.corner_radius_top_left = 14; sb.corner_radius_top_right = 14; sb.corner_radius_bottom_left = 14; sb.corner_radius_bottom_right = 14
	sb.border_width_left = 1; sb.border_width_right = 1; sb.border_width_top = 1; sb.border_width_bottom = 1; sb.border_color = Color(1, 1, 1, 0.18)
	radar.draw_style_box(sb, Rect2(Vector2.ZERO, sz))
	if main == null:
		return
	var fw: Vector3 = main.focus_world()
	var yaw: float = main.cam_yaw
	var f2 := Vector2(fw.x, fw.z)
	var lim := func(v: Vector2) -> Vector2: return Vector2(clampf(v.x, -c.x + 6, c.x - 6), clampf(v.y, -c.y + 6, c.y - 6))
	if _mm_vp != null:
		var span2: float = maxf(sz.x, sz.y)
		radar.draw_texture_rect(_mm_vp.get_texture(), Rect2(c - Vector2(span2, span2) * 0.5, Vector2(span2, span2)), false, Color(0.55, 0.56, 0.54, 0.8))
		radar.draw_rect(Rect2(Vector2.ZERO, sz), Color(0.06, 0.065, 0.06, 0.35))
	# roads: wide ones thicker
	for s in main.streamer.segments_near(fw, 330.0):
		var a: Vector2 = (s[0] - f2).rotated(yaw) * scale
		var b: Vector2 = (s[1] - f2).rotated(yaw) * scale
		if absf(a.x) > c.x + 20 and absf(b.x) > c.x + 20: continue
		if absf(a.y) > c.y + 20 and absf(b.y) > c.y + 20: continue
		radar.draw_line(c + a, c + b, Color(0.0, 0.0, 0.0, 0.25), 5.0)
	for s in main.streamer.segments_near(fw, 330.0):
		var a2: Vector2 = (s[0] - f2).rotated(yaw) * scale
		var b2: Vector2 = (s[1] - f2).rotated(yaw) * scale
		radar.draw_line(c + a2, c + b2, Color(0.92, 0.9, 0.86, 0.6), 3.0)
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
				radar.draw_line(c + lim.call(prev), c + lim.call(r2), C_ACCENT, 3.5)
			prev = r2
		var wpt: Vector2 = (Vector2(ph.waypoint.x, ph.waypoint.z) - f2).rotated(yaw) * scale
		radar.draw_circle(c + lim.call(wpt), 5.5, C_ACCENT)
		var dist_m: float = Vector2(ph.waypoint.x - fw.x, ph.waypoint.z - fw.z).length()
		radar.draw_string(font_med, Vector2(10, sz.y - 9), "%.1f mi" % (dist_m / 1609.0), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, C_TEXT)
	# player arrow
	var heading: float
	if main.current_car:
		heading = main.current_car.global_rotation.y - yaw
	else:
		heading = main.player.model.rotation.y - yaw
	var pts := PackedVector2Array([Vector2(0, -9), Vector2(7, 8), Vector2(0, 4), Vector2(-7, 8)])
	for i in pts.size():
		pts[i] = c + pts[i].rotated(-heading)
	radar.draw_colored_polygon(pts, Color(1, 1, 1))
	radar.draw_polyline(pts + PackedVector2Array([pts[0]]), Color(0, 0, 0, 0.8), 1.5)
	# north marker on the rim
	var n: Vector2 = lim.call(Vector2(0, -R * 2.0).rotated(yaw))
	radar.draw_string(font_bold, c + n + Vector2(-4, 5), "N", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, C_DIM)
