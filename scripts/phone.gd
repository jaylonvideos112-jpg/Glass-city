extends CanvasLayer
## The smartphone (Bible section 12): Tab opens it. Arrow keys move, Enter opens, Backspace goes back, Tab closes.
## Apps: Maps (island map + GPS to any place), GlassPay (balance and history), Jobs (job board), Messages (every
## notification), Contacts (call a tow to bring your car), My Stuff (cars, businesses, home), News (Glass City
## Gazette), Profile (stats and needs), Camera (photo mode with zoom and filters), Settings (wallpaper).
## GPS: the waypoint shows on the radar with a route along the roads and a light beam in the world.
## Saved as world-state section "phone" (wallpaper, messages, photos taken).

var main: Node
var open := false
var app := ""                 # "" = home screen
var sel := 0
var messages: Array = []      # [time string, text]
var wallpaper := 0
const WALLS := [Color(0.08, 0.12, 0.22), Color(0.15, 0.06, 0.12), Color(0.05, 0.16, 0.12), Color(0.12, 0.12, 0.12)]
const APPS := ["Maps", "GlassPay", "Jobs", "Messages", "Contacts", "My Stuff", "News", "Profile", "Camera", "Settings"]
var waypoint := Vector3.INF   # world
var waypoint_name := ""
var route: Array = []         # world points along the roads
var _route_t := 0.0
var _beam: MeshInstance3D
var photos := 0
var photo_mode := false
var _filter := 0
const FILTERS := ["Normal", "Black & white", "Warm", "Vivid"]
var _fov := 70.0
var map_cat := 0
var map_zoom := 1.0
var _list: Array = []         # current selectable rows [label, data]
var M: Dictionary             # phone_map.json bounds

var _panel: Panel
var _title: Label
var _body: Label
var _map: TextureRect
var _map_clip: Control
var _marks: Control
var _photo_label: Label

const CATS := ["My places", "Food", "Groceries", "Bars", "ATMs", "Jobs hiring", "Car dealers", "Auto shops", "Gyms & bowling",
	"Ballparks & cinemas", "Fishing", "Homes for rent", "Police & hospitals"]

func _ready() -> void:
	layer = 5
	M = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/phone_map.json"))
	_panel = Panel.new()
	_panel.set_anchors_preset(Control.PRESET_CENTER_RIGHT)
	_panel.offset_left = -440; _panel.offset_right = -40; _panel.offset_top = -290; _panel.offset_bottom = 345
	add_child(_panel)
	_title = Label.new(); _title.position = Vector2(20, 14); _title.add_theme_font_size_override("font_size", 24); _panel.add_child(_title)
	_map_clip = Control.new(); _map_clip.position = Vector2(14, 56); _map_clip.size = Vector2(372, 300); _map_clip.clip_contents = true
	_panel.add_child(_map_clip)
	_map = TextureRect.new(); _map.texture = load("res://textures/phone_map.png"); _map.stretch_mode = TextureRect.STRETCH_SCALE
	_map_clip.add_child(_map)
	_marks = Control.new(); _marks.size = _map_clip.size; _marks.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_map_clip.add_child(_marks)          # drawn above the map image
	_marks.draw.connect(_draw_map_marks)
	_body = Label.new(); _body.position = Vector2(20, 56); _body.size = Vector2(360, 590); _body.add_theme_font_size_override("font_size", 17)
	_body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_panel.add_child(_body)
	_photo_label = Label.new(); _photo_label.position = Vector2(30, 30); _photo_label.add_theme_font_size_override("font_size", 20)
	_photo_label.add_theme_color_override("font_outline_color", Color.BLACK); _photo_label.add_theme_constant_override("outline_size", 6)
	_photo_label.visible = false; add_child(_photo_label)
	_beam = MeshInstance3D.new()
	var cm := CylinderMesh.new(); cm.top_radius = 1.2; cm.bottom_radius = 1.2; cm.height = 80.0; _beam.mesh = cm
	var m := StandardMaterial3D.new(); m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = Color(0.7, 0.3, 1.0, 0.3); m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_beam.material_override = m; _beam.visible = false; _beam.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	main.world.add_child(_beam)
	_refresh()

# ------------------------------------------------------------------ notifications
func notify(text: String) -> void:
	var t := "%s" % main.tod.clock_string() if main.tod and main.tod.has_method("clock_string") else ""
	messages.append([t, text])
	if messages.size() > 60: messages.pop_front()

# ------------------------------------------------------------------ open/close and input
func set_open(o: bool) -> void:
	open = o; app = ""; sel = 0
	main.input_enabled = not o
	if o: Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	_refresh()

func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventMouseButton and photo_mode and e.pressed:
		if e.button_index == MOUSE_BUTTON_WHEEL_UP: _fov = maxf(15.0, _fov - 4.0)
		if e.button_index == MOUSE_BUTTON_WHEEL_DOWN: _fov = minf(90.0, _fov + 4.0)
		return
	if not (e is InputEventKey and e.pressed and not e.echo): return
	var k: int = e.physical_keycode
	if photo_mode:
		match k:
			KEY_SPACE, KEY_ENTER: take_photo()
			KEY_Z: _fov = maxf(15.0, _fov - 5.0)
			KEY_X: _fov = minf(90.0, _fov + 5.0)
			KEY_1, KEY_2, KEY_3, KEY_4: set_filter(k - KEY_1)
			KEY_TAB, KEY_ESCAPE: exit_photo_mode()
		get_viewport().set_input_as_handled()
		return
	if k == KEY_TAB:
		set_open(not open); get_viewport().set_input_as_handled(); return
	if not open: return
	get_viewport().set_input_as_handled()
	match k:
		KEY_UP: sel = maxi(0, sel - (3 if app == "" else 1))
		KEY_DOWN: sel = mini(_count() - 1, sel + (3 if app == "" else 1))
		KEY_LEFT:
			if app == "": sel = maxi(0, sel - 1)
			elif app == "Maps": map_cat = (map_cat - 1 + CATS.size()) % CATS.size(); sel = 0
		KEY_RIGHT:
			if app == "": sel = mini(APPS.size() - 1, sel + 1)
			elif app == "Maps": map_cat = (map_cat + 1) % CATS.size(); sel = 0
		KEY_ENTER, KEY_KP_ENTER: _activate()
		KEY_BACKSPACE:
			if app == "": set_open(false); return
			app = ""; sel = 0
		KEY_Z: map_zoom = minf(6.0, map_zoom * 1.4)
		KEY_X: map_zoom = maxf(1.0, map_zoom / 1.4)
	_refresh()

func _count() -> int:
	return APPS.size() if app == "" else maxi(1, _list.size())

func _activate() -> void:
	if app == "":
		app = APPS[sel]; sel = 0
		if app == "Camera": set_open(false); enter_photo_mode()
		return
	if sel >= _list.size(): return
	var row: Array = _list[sel]
	match app:
		"Maps": set_waypoint(row[1], row[0])
		"Jobs":
			if row[1] is int and row[1] >= 0: main.jobs.hire(row[1])
			elif row[1] is int and row[1] == -2: main.jobs.quit_job()
		"Contacts": call_contact(row[1])
		"My Stuff":
			if row[1] is Vector3: set_waypoint(row[1], row[0])
		"Settings": wallpaper = int(row[1])

# ------------------------------------------------------------------ GPS
func set_waypoint(p: Vector3, label: String) -> void:
	waypoint = Vector3(p.x, p.y, p.z); waypoint_name = label
	_route_t = 0.0
	if main.hud: main.hud.flash("GPS: " + label)

func clear_waypoint() -> void:
	waypoint = Vector3.INF; waypoint_name = ""; route = []; _beam.visible = false

func _update_route() -> void:
	route = []
	if waypoint == Vector3.INF or main.traffic == null or main.traffic.edges.is_empty() or main.services == null: return
	var a: int = main.police._nearest_node(main.focus_world())
	var b: int = main.police._nearest_node(waypoint)
	if a < 0 or b < 0 or a == b: return
	var pth: Array = main.services.route_path(a, b, 8000)
	for n in pth: route.append(main.traffic.npos[n])

func _process(dt: float) -> void:
	if waypoint != Vector3.INF:
		var f: Vector3 = main.focus_world()
		if Vector2(waypoint.x - f.x, waypoint.z - f.z).length() < 25.0:
			if main.hud: main.hud.flash("You've arrived: " + waypoint_name)
			clear_waypoint()
		else:
			_route_t -= dt
			if _route_t <= 0.0: _route_t = 2.0; _update_route()
			_beam.visible = true
			_beam.global_position = Vector3(waypoint.x, waypoint.y + 40.0, waypoint.z) - main.world_offset
	if photo_mode:
		main.camera.fov = _fov
	if open and app == "Maps": _marks.queue_redraw()

# ------------------------------------------------------------------ contacts
const CONTACTS := [["Mike's Towing - bring my car here ($150)", "tow"], ["Boss (work schedule)", "boss"], ["Landlord / home", "home"],
	["Glass City Transit (bus info)", "bus"], ["Mom", "mom"]]

func call_contact(id: String) -> void:
	match id:
		"tow":
			var mine = null
			for c in main.cars:
				if is_instance_valid(c) and c.owned_index >= 0 and c.visible and c != main.current_car: mine = c
			if mine == null: notify("Mike: You don't have a car out I can bring you."); return
			if not main.money.spend(150, "Tow"): notify("Mike: It's $150, pal."); return
			var p: Vector3 = main.player.global_position + main.player.global_transform.basis.x * 4.0 + Vector3(0, 1.0, 0)
			mine.global_transform = Transform3D(Basis(Vector3.UP, main.player.global_rotation.y), p)
			mine.linear_velocity = Vector3.ZERO
			notify("Mike: Dropped your %s off right next to you." % mine.model_name)
		"boss": notify("Boss: " + (main.jobs.status_line() if not main.jobs.job.is_empty() else "We don't have you on the schedule. Apply somewhere first."))
		"home":
			var hm = main.homes
			if hm.home.is_empty(): notify("You don't have a place yet - look for For Rent signs (Maps > Homes for rent).")
			else:
				var h: Dictionary = hm.listing(int(hm.home["id"]))
				notify("%s: %s" % [h["address"], "you own it" if hm.home["mode"] == "own" else "rent $%d due on day %d" % [int(h["rent_week"]), int(hm.home["next_rent_day"]) + 1]])
		"bus": notify("Glass City Transit: %d routes run from downtown to every town. Look for the blue stop signs." % main.services.routes.size())
		"mom": notify(["Mom: Are you eating enough?", "Mom: Call me back when you get a chance.", "Mom: Don't drive like a maniac."][randi() % 3])
	_refresh()

# ------------------------------------------------------------------ photo mode
func enter_photo_mode() -> void:
	photo_mode = true; _fov = main.camera.fov
	main.hud.visible = false
	_photo_label.visible = true
	_photo_label.text = "PHOTO  ·  Space = take  ·  Z/X or wheel = zoom  ·  1-4 = filter (%s)  ·  Tab = exit" % FILTERS[_filter]

func exit_photo_mode() -> void:
	photo_mode = false; set_filter(0)
	main.hud.visible = true; _photo_label.visible = false
	main.camera.fov = 70.0

func set_filter(i: int) -> void:
	_filter = i
	var env: Environment = main.env
	env.adjustment_enabled = true
	env.adjustment_saturation = [1.08, 0.0, 0.85, 1.6][i]
	env.adjustment_contrast = [1.06, 1.15, 1.05, 1.1][i]
	env.adjustment_brightness = [1.0, 1.0, 1.05, 1.0][i]
	if photo_mode: _photo_label.text = "PHOTO  ·  Space = take  ·  Z/X or wheel = zoom  ·  1-4 = filter (%s)  ·  Tab = exit" % FILTERS[_filter]

func take_photo() -> String:
	_photo_label.visible = false
	await get_tree().process_frame
	await get_tree().process_frame
	var img := get_viewport().get_texture().get_image()
	if img == null: img = Image.create(320, 180, false, Image.FORMAT_RGB8)   # no renderer (headless tests)
	DirAccess.make_dir_recursive_absolute("user://photos")
	photos += 1
	var path := "user://photos/glasscity_%04d.png" % photos
	img.save_png(path)
	_photo_label.visible = true
	notify("Photo saved (%s)" % path.get_file())
	if main.hud: main.hud.flash("Photo saved")
	return path

# ------------------------------------------------------------------ places for the map
func _places(cat: String) -> Array:
	var f: Vector3 = main.focus_world()
	var out: Array = []
	var add := func(label: String, x: float, z: float): out.append([label, Vector3(x, 0, z), Vector2(x - f.x, z - f.z).length()])
	match cat:
		"My places":
			if not main.homes.home.is_empty():
				var h: Dictionary = main.homes.listing(int(main.homes.home["id"])); add.call("Home - " + h["address"], h["x"], h["z"])
			if not main.jobs.job.is_empty():
				var p: Dictionary = main.jobs.place(int(main.jobs.job["place"])); add.call("Work - " + p["name"], p["x"], p["z"])
			for c in main.cars:
				if is_instance_valid(c) and c.owned_index >= 0 and c.visible and c != main.current_car:
					var cp: Vector3 = c.global_position + main.world_offset; add.call("My " + c.model_name, cp.x, cp.z)
			for id in main.business.owned:
				var b: Dictionary = main.jobs.place(int(id)); add.call("My business - " + b["name"], b["x"], b["z"])
		"Food", "Groceries", "Jobs hiring", "Auto shops":
			var kinds: Array = {"Food": ["fast_food", "restaurant"], "Groceries": ["grocery", "convenience"], "Auto shops": ["auto_shop"]}.get(cat, [])
			for p in main.jobs.places:
				if cat == "Jobs hiring" or kinds.has(p["kind"]):
					add.call(p["name"] + ("" if cat != "Jobs hiring" else " - " + main.jobs.def_for(p["kind"]).get("title", "")), p["x"], p["z"])
		"Bars":
			for b in _bars(): add.call(b[0], b[1], b[2])
		"ATMs":
			for a in main.money.atms: add.call("ATM - " + a["bank"], a["x"], a["z"])
		"Car dealers":
			for d in main.vehicles.dealers: add.call(d["name"], d["x"], d["z"])
		"Gyms & bowling", "Ballparks & cinemas", "Fishing":
			var ks: Array = {"Gyms & bowling": ["gym", "bowling"], "Ballparks & cinemas": ["stadium", "cinema"], "Fishing": ["fishing"]}[cat]
			for p in main.activities.places:
				if ks.has(p["kind"]): add.call(p["name"], p["x"], p["z"])
		"Homes for rent":
			for h in main.homes.homes: add.call("%s - $%d/wk" % [h["address"], int(h["rent_week"])], h["x"], h["z"])
		"Police & hospitals":
			var S = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/stations.json"))["stations"]
			for p in S["police"]: add.call("Police station", p["x"], p["z"])
			for p in S["hospital"]: add.call("Hospital", p["x"], p["z"])
	out.sort_custom(func(a, b): return a[2] < b[2])
	return out.slice(0, 8)

var _bars_cache: Array = []
func _bars() -> Array:
	if _bars_cache.is_empty():
		for b in JSON.parse_string(FileAccess.get_file_as_string("res://source_data/bars.json")):
			_bars_cache.append([b["theme"], float(b["x"]), -float(b["y"])])
	return _bars_cache

# ------------------------------------------------------------------ drawing
func _to_map(p: Vector3) -> Vector2:
	var u: float = (p.x - float(M["x0"])) / (float(M["x1"]) - float(M["x0"]))
	var v: float = (p.z - float(M["z0"])) / (float(M["z1"]) - float(M["z0"]))
	return Vector2(u, v) * _map.size + _map.position

func _layout_map() -> void:
	var base := Vector2(_map_clip.size.x, _map_clip.size.x * float(M["h"]) / float(M["w"]))
	_map.size = base * map_zoom * 1.0
	if map_zoom <= 1.0:
		_map.position = Vector2(0, (_map_clip.size.y - _map.size.y) * 0.5)
	else:
		_map.position = Vector2.ZERO
		var pp := _to_map(main.focus_world())
		_map.position = _map_clip.size * 0.5 - pp

func _draw_map_marks() -> void:
	if not (open and app == "Maps"): return
	var pp := _to_map(main.focus_world())
	_marks.draw_circle(pp, 6.0, Color(1, 0.85, 0.2))
	_marks.draw_arc(pp, 9.0, 0, TAU, 24, Color(0, 0, 0), 2.0)
	if waypoint != Vector3.INF:
		var wp := _to_map(waypoint)
		_marks.draw_circle(wp, 6.0, Color(0.75, 0.35, 1.0))
	if sel < _list.size() and _list[sel][1] is Vector3:
		var sp := _to_map(_list[sel][1]); _marks.draw_arc(sp, 8.0, 0, TAU, 20, Color(1, 1, 1), 2.0)

func _refresh() -> void:
	_panel.visible = open
	if not open: return
	var sb := StyleBoxFlat.new(); sb.bg_color = WALLS[wallpaper]; sb.corner_radius_top_left = 28; sb.corner_radius_top_right = 28
	sb.corner_radius_bottom_left = 28; sb.corner_radius_bottom_right = 28; sb.border_width_left = 6; sb.border_width_right = 6
	sb.border_width_top = 6; sb.border_width_bottom = 6; sb.border_color = Color(0.02, 0.02, 0.02)
	_panel.add_theme_stylebox_override("panel", sb)
	_map_clip.visible = app == "Maps"
	_body.position.y = 366 if app == "Maps" else 56
	var lines: Array = []
	_list = []
	match app:
		"":
			_title.text = "%s   %s" % [main.tod.clock_string() if main.tod.has_method("clock_string") else "", "GlassPay $%d" % main.money.wallet]
			for i in APPS.size():
				lines.append(("> " if i == sel else "   ") + APPS[i])
			lines.append("\nEnter open · Backspace/Tab close")
		"Maps":
			_title.text = "Maps  ·  < %s >" % CATS[map_cat]
			_layout_map()
			for p in _places(CATS[map_cat]): _list.append([p[0], p[1]]); lines.append("%s%s  (%.1f km)" % ["> " if _list.size() - 1 == sel else "   ", p[0], p[2] / 1000.0])
			if _list.is_empty(): lines.append("   (nothing here)")
			lines.append("Enter GPS · ←/→ category · Z/X zoom" + ("\nGPS: " + waypoint_name if waypoint_name != "" else ""))
		"GlassPay":
			_title.text = "GlassPay"
			lines.append("Balance: $%d\nCash on you: $%d\n\nRecent:" % [main.money.wallet, main.money.cash])
			var h: Array = main.money.history.duplicate(); h.reverse()
			for t in h.slice(0, 14): lines.append("  %s  %s$%d" % [t[0], "+" if t[1] > 0 else "-", absi(int(t[1]))])
		"Jobs":
			_title.text = "Jobs"
			lines.append(main.jobs.status_line() if not main.jobs.job.is_empty() else "No job right now.")
			for o in main.jobs.openings_near(main.focus_world(), 8):
				var pl: Dictionary = main.jobs.place(o[1]); var d: Dictionary = main.jobs.def_for(pl["kind"])
				_list.append(["apply", int(o[1])])
				lines.append("%s%s - %s  $%d/h  %d-%d  (%.1f km)" % ["> " if _list.size() - 1 == sel else "   ", d["title"], pl["name"], d["pay"], d["shift"][0], d["shift"][1], o[0] / 1000.0])
			if not main.jobs.job.is_empty():
				_list.append(["quit", -2]); lines.append(("> " if _list.size() - 1 == sel else "   ") + "Quit my job")
			lines.append("Enter = apply")
		"Messages":
			_title.text = "Messages"
			var ms := messages.duplicate(); ms.reverse()
			for m in ms.slice(0, 18): lines.append("%s  %s" % [m[0], m[1]])
			if ms.is_empty(): lines.append("No messages.")
		"Contacts":
			_title.text = "Contacts"
			for c in CONTACTS:
				_list.append([c[0], c[1]]); lines.append(("> " if _list.size() - 1 == sel else "   ") + c[0])
			lines.append("Enter = call · replies arrive in Messages")
			var ms2 := messages.slice(-3)
			for m in ms2: lines.append("  " + m[1])
		"My Stuff":
			_title.text = "My Stuff"
			lines.append("Cars:")
			for c in main.cars:
				if is_instance_valid(c) and c.owned_index >= 0:
					var cp: Vector3 = c.global_position + main.world_offset
					_list.append([c.model_name, cp])
					lines.append("%s%s  %d%%  %s" % ["> " if _list.size() - 1 == sel else "   ", c.model_name, int(c.health / 10.0), "garage" if not c.visible else "Enter = GPS"])
			lines.append("Businesses:")
			for id in main.business.owned:
				lines.append("   %s  ($%d waiting)" % [main.jobs.place(int(id))["name"], int(main.business.owned[id]["stored"])])
			if main.business.owned.is_empty(): lines.append("   none")
			lines.append("Home:  " + ("none" if main.homes.home.is_empty() else main.homes.listing(int(main.homes.home["id"]))["address"]))
		"News":
			_title.text = "Glass City Gazette"
			lines.append_array(_headlines())
		"Profile":
			_title.text = "Profile"
			lines.append(main.needs.status())
			lines.append(main.stats.summary())
			lines.append("Swamp Hens games: %d · movies: %d · best bowling: %d" % [main.activities.games_seen, main.activities.movies_seen, main.activities.bowling_best])
			lines.append("Times busted: %d · tickets: %d · photos: %d" % [main.stats.times_busted, main.police.tickets, photos])
			if not main.inventory.fish_log.is_empty():
				lines.append("Fish: " + ", ".join(main.inventory.fish_log.keys().map(func(k): return "%s %.1f kg" % [k, main.inventory.fish_log[k]])))
		"Settings":
			_title.text = "Settings · wallpaper"
			for i in WALLS.size():
				_list.append(["Wallpaper %d" % (i + 1), i]); lines.append("%sWallpaper %d%s" % ["> " if i == sel else "   ", i + 1, "  (current)" if i == wallpaper else ""])
	_body.text = "\n".join(lines)

func _headlines() -> Array:
	var out: Array = []
	var w = main.weather
	out.append("WEATHER: %s now. %s" % [w.state.capitalize() if w else "Clear", "Roads are slick - drive carefully." if main.tod.wetness > 0.3 or main.tod.snow_cover > 0.2 else "Good driving conditions."])
	if main.activities.games_seen > 0: out.append("SPORTS: The Swamp Hens keep fans coming to the ballpark.")
	else: out.append("SPORTS: Swamp Hens play most evenings - tickets $15.")
	if main.police.stars > 0: out.append("CRIME: Police are searching for a suspect downtown.")
	elif main.stats.times_busted > 0: out.append("CRIME: Local resident spends a night in jail after a police pursuit.")
	else: out.append("CRIME: A quiet week for Glass City police.")
	out.append("BUSINESS: %d local businesses are hiring this week." % main.jobs.places.size())
	out.append("TRANSIT: Glass City Transit runs %d routes from downtown." % main.services.routes.size())
	return out

func get_save_data() -> Dictionary:
	return {"wallpaper": wallpaper, "messages": messages.slice(-30), "photos": photos}

func apply_save_data(d: Dictionary) -> void:
	wallpaper = int(d.get("wallpaper", 0)); messages = d.get("messages", []); photos = int(d.get("photos", 0))
