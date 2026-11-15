extends CanvasLayer
## Title screen, pause menu, settings (Bible section 13: original GLASS CITY UI).
##   * Title: the city behind a slow camera flight, the GLASS CITY logo, Continue / New Game / Controls / Settings / Quit.
##   * Esc in game: pause (the world stops) - Resume / Save / Controls / Settings / Quit to title.
##   * Settings (user://settings.cfg): volume, mouse sensitivity, field of view, fullscreen, shadows, view distance.
## Skipped for tests, benchmarks and demos (they pass --test/--benchmark/--demo), or with --no-menu.

var main: Node
var screen := ""              # "title", "pause", "settings", "controls", ""
var _prev := ""
var sel := 0
var _root: Control
var _logo: Label
var _sub: Label
var _items: VBoxContainer
var _info: Label
var _orbit := 0.0
var settings := {"volume": 0.8, "mouse": 1.0, "fov": 70, "fullscreen": false, "shadows": true, "view": 1}
const VIEW_DIST := [["Near", 2200.0], ["Normal", 3200.0], ["Far", 4500.0]]
const CFG := "user://settings.cfg"

func _ready() -> void:
	layer = 20
	process_mode = Node.PROCESS_MODE_ALWAYS
	_load_settings()
	_root = Control.new(); _root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT); add_child(_root)
	var shade := ColorRect.new(); shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	shade.color = Color(0.02, 0.03, 0.05, 0.55); shade.name = "Shade"; _root.add_child(shade)
	var fb: Font = load("res://fonts/InterDisplay-Black.otf")
	var fm: Font = load("res://fonts/Inter-SemiBold.otf")
	_logo = Label.new(); _logo.text = "GLASS CITY"; _logo.add_theme_font_override("font", fb); _logo.add_theme_font_size_override("font_size", 110)
	_logo.add_theme_color_override("font_color", Color(0.95, 0.97, 1.0)); _logo.add_theme_color_override("font_shadow_color", Color(0.1, 0.4, 0.8, 0.7))
	_logo.add_theme_constant_override("shadow_offset_x", 0); _logo.add_theme_constant_override("shadow_offset_y", 6)
	_logo.position = Vector2(90, 90); _root.add_child(_logo)
	_sub = Label.new(); _sub.add_theme_font_override("font", fm); _sub.add_theme_font_size_override("font_size", 22)
	_sub.add_theme_color_override("font_color", Color(0.75, 0.85, 1.0)); _sub.position = Vector2(96, 222); _root.add_child(_sub)
	_items = VBoxContainer.new(); _items.position = Vector2(96, 300); _items.add_theme_constant_override("separation", 10); _root.add_child(_items)
	_info = Label.new(); _info.add_theme_font_override("font", fm); _info.add_theme_font_size_override("font_size", 18)
	_info.add_theme_color_override("font_color", Color(0.85, 0.88, 0.92)); _info.position = Vector2(96, 300); _root.add_child(_info)
	_apply_settings()
	var skip := false
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--test") or a.begins_with("--benchmark") or a.begins_with("--demo") or a == "--no-menu": skip = true
	if skip: show_screen("")
	else: show_screen("title")

func _rows() -> Array:
	match screen:
		"title":
			var r := []
			if FileAccess.file_exists("user://world_state.json"): r.append(["Continue", "continue"])
			r.append_array([["New Game", "new"], ["Controls", "controls"], ["Settings", "settings"], ["Quit", "quit"]])
			return r
		"pause": return [["Resume", "resume"], ["Save Game", "save"], ["Controls", "controls"], ["Settings", "settings"], ["Quit to Title", "title"], ["Quit Game", "quit"]]
		"settings":
			return [["Volume  %d%%" % int(settings["volume"] * 100), "volume"], ["Mouse sensitivity  %.1fx" % settings["mouse"], "mouse"],
				["Field of view  %d" % int(settings["fov"]), "fov"], ["Fullscreen  %s" % ("On" if settings["fullscreen"] else "Off"), "fullscreen"],
				["Shadows  %s" % ("On" if settings["shadows"] else "Off"), "shadows"], ["View distance  %s" % VIEW_DIST[int(settings["view"])][0], "view"], ["Back", "back"]]
		"controls": return [["Back", "back"]]
	return []

func show_screen(s: String) -> void:
	if s in ["settings", "controls"] and screen in ["title", "pause"]: _prev = screen
	screen = s; sel = 0
	_root.visible = s != ""
	var in_game := s == ""
	main.input_enabled = in_game and not (main.get("phone") and main.phone and main.phone.open)
	get_tree().paused = s in ["pause"] or (s in ["settings", "controls"] and _prev == "pause")
	if main.hud: main.hud.visible = s == "" or s == "pause" or ((s == "settings" or s == "controls") and _prev == "pause")
	if s == "title" or s == "": main.cam_override = s == "title"
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if in_game else Input.MOUSE_MODE_VISIBLE
	if in_game: Input.mouse_mode = Input.MOUSE_MODE_VISIBLE   # captured again on the first click (as before)
	_logo.visible = s == "title"
	_sub.text = "An open city on Lake Glassmere" if s == "title" else ""
	(_root.get_node("Shade") as ColorRect).color = Color(0.02, 0.03, 0.05, 0.25 if s == "title" else 0.6)
	_info.visible = s == "controls"
	if s == "controls":
		_info.text = main.hud.help_label.text if main.hud else ""
		_info.position = Vector2(96, 120)
	_items.position = Vector2(96, 300 if s == "title" else (140 if s != "controls" else 560))
	if s == "pause":
		_sub.text = "PAUSED"; _sub.add_theme_font_size_override("font_size", 54); _sub.position = Vector2(96, 50)
	elif s == "title":
		_sub.add_theme_font_size_override("font_size", 22); _sub.position = Vector2(96, 222)
	_build()

func _build() -> void:
	for c in _items.get_children(): c.queue_free()
	var rows := _rows()
	var fb: Font = load("res://fonts/Inter-Bold.otf")
	for i in rows.size():
		var l := Label.new(); l.text = rows[i][0]
		l.add_theme_font_override("font", fb); l.add_theme_font_size_override("font_size", 30 if screen == "title" else 26)
		var on := i == sel
		l.add_theme_color_override("font_color", Color(1, 0.82, 0.3) if on else Color(0.92, 0.94, 0.97))
		l.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.8)); l.add_theme_constant_override("outline_size", 6)
		if on: l.text = "›  " + l.text
		l.mouse_filter = Control.MOUSE_FILTER_STOP
		l.gui_input.connect(func(ev):
			if ev is InputEventMouseButton and ev.pressed and ev.button_index == MOUSE_BUTTON_LEFT: sel = i; _choose()
			elif ev is InputEventMouseMotion and sel != i: sel = i; _build())
		_items.add_child(l)

func _input(e: InputEvent) -> void:
	if not (e is InputEventKey and e.pressed and not e.echo): return
	if screen == "":
		if e.physical_keycode == KEY_ESCAPE and not (main.get("phone") and main.phone and (main.phone.open or main.phone.photo_mode)):
			show_screen("pause"); get_viewport().set_input_as_handled()
		return
	var n := _rows().size()
	match e.physical_keycode:
		KEY_UP, KEY_W: sel = (sel - 1 + n) % n; _build()
		KEY_DOWN, KEY_S: sel = (sel + 1) % n; _build()
		KEY_LEFT, KEY_A: _adjust(-1)
		KEY_RIGHT, KEY_D: _adjust(1)
		KEY_ENTER, KEY_KP_ENTER, KEY_SPACE: _choose()
		KEY_ESCAPE, KEY_BACKSPACE:
			if screen == "pause": show_screen("")
			elif screen in ["settings", "controls"]: show_screen(_prev)
	get_viewport().set_input_as_handled()

func _adjust(d: int) -> void:
	if screen != "settings": return
	match _rows()[sel][1]:
		"volume": settings["volume"] = clampf(settings["volume"] + 0.1 * d, 0.0, 1.0)
		"mouse": settings["mouse"] = clampf(settings["mouse"] + 0.1 * d, 0.3, 3.0)
		"fov": settings["fov"] = clampi(int(settings["fov"]) + 5 * d, 55, 95)
		"view": settings["view"] = clampi(int(settings["view"]) + d, 0, VIEW_DIST.size() - 1)
		"fullscreen", "shadows": _choose(); return
	_apply_settings(); _save_settings(); _build()

func _choose() -> void:
	var rows := _rows()
	if sel >= rows.size(): return
	match rows[sel][1]:
		"continue":
			if main.world_state: main.world_state.load_file()
			show_screen("")
		"new":
			show_screen("")
			if main.hud: main.hud.flash("Welcome to Glass City. Press H for controls, Tab for your phone.")
		"resume": show_screen("")
		"save":
			if main.world_state: main.world_state.save()
			if main.hud: main.hud.flash("Game saved")
			show_screen("")
		"controls": show_screen("controls")
		"settings": show_screen("settings")
		"back": show_screen(_prev)
		"title": show_screen("title")
		"quit":
			if main.world_state and main.world_state.enabled: main.world_state.save()
			get_tree().quit()
		"fullscreen":
			settings["fullscreen"] = not settings["fullscreen"]; _apply_settings(); _save_settings(); _build()
		"shadows":
			settings["shadows"] = not settings["shadows"]; _apply_settings(); _save_settings(); _build()
		_: _adjust(1)

func _apply_settings() -> void:
	AudioServer.set_bus_volume_db(0, linear_to_db(maxf(float(settings["volume"]), 0.0001)))
	main.set("mouse_sens", 0.0035 * float(settings["mouse"]))
	main.set("base_fov", float(settings["fov"]))
	if not Array(OS.get_cmdline_user_args()).any(func(a): return a.begins_with("--demo") or a.begins_with("--test") or a.begins_with("--benchmark")):
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN if settings["fullscreen"] else DisplayServer.WINDOW_MODE_WINDOWED)
	var sun = main.get_node_or_null("Sun")
	if sun: sun.shadow_enabled = bool(settings["shadows"])
	if main.streamer and main.streamer.hlod: main.streamer.hlod.radius_m = float(VIEW_DIST[int(settings["view"])][1])

func _load_settings() -> void:
	var cf := ConfigFile.new()
	if cf.load(CFG) != OK: return
	for k in settings: settings[k] = cf.get_value("settings", k, settings[k])

func _save_settings() -> void:
	var cf := ConfigFile.new()
	for k in settings: cf.set_value("settings", k, settings[k])
	cf.save(CFG)

## title screen: a slow flight over downtown and the river
func _process(dt: float) -> void:
	if screen != "title": return
	_orbit += dt * 0.025
	var c := Vector3(250, 0, 150)
	var p := c + Vector3(cos(_orbit) * 650.0, 190.0, sin(_orbit) * 650.0)
	main.focus_override = c
	main.camera.global_position = p - main.world_offset
	main.camera.look_at(c + Vector3(0, 40, 0) - main.world_offset, Vector3.UP)
