extends Node
## Game clock, calendar, sun/moon, sky and night lighting (Bible §6; decision log: 1 real hour per game day).
## All numbers come from source_data/climate.json. Weather (weather.gd) feeds cloud/fog/darkness multipliers in.

const CLIMATE_PATH := "res://source_data/climate.json"
const SAVE_PATH := "user://world_state.json"

var main: Node
var C: Dictionary                 # climate.json
var total_hours := 0.0            # game hours since day 0, 00:00
var time_scale := 1.0             # F6 toggles x60 for testing
var sec_per_day := 3600.0
var days_per_season := 12
var seasons: Array = []
var start_weekday := 0

var sun: DirectionalLight3D
var moon: DirectionalLight3D
var sky_mat: ShaderMaterial
var night := 0.0                  # 0 day .. 1 full night (drives window/lamp emission)
var sun_alt := 0.0                # degrees
var occupancy := 0.5
var fog_base := 0.00022           # demo/camera code sets this; weather multiplies it
var _night_mats: Array = []       # StandardMaterial3D with window emission masks
var _lamp_mat: StandardMaterial3D
var _acc := 0.0
var wetness := 0.0                # 0 dry .. 1 soaked (rain), drives the global shader parameter
var snow_cover := 0.0             # 0 none .. 1 full cover
var _surf_last := -1.0
var globals := {}                 # last values pushed to the global shader parameters (readable at runtime)
var _ground: Array = []           # [StandardMaterial3D, base albedo, base roughness, snow factor]
const GROUND := {"asphalt": 0.45, "sidewalk": 0.85, "concrete": 0.7, "concrete_dk": 0.7, "yellowline": 0.4, "whiteline": 0.4, "crosswalk": 0.5}   # roads get plowed

func _ready() -> void:
	C = JSON.parse_string(FileAccess.get_file_as_string(CLIMATE_PATH))
	var ck: Dictionary = C["clock"]
	sec_per_day = ck["real_seconds_per_game_day"]
	days_per_season = int(ck["days_per_season"])
	seasons = ck["seasons"]
	var st: Dictionary = ck["start"]
	start_weekday = int(st["weekday"])
	total_hours = (seasons.find(st["season"]) * days_per_season + int(st["day"]) - 1) * 24.0 + float(st["hour"])
	sun = main.get_node("Sun")
	moon = DirectionalLight3D.new(); moon.name = "Moon"
	moon.light_color = Color(0.6, 0.7, 0.95); moon.light_energy = 0.0; moon.shadow_enabled = false
	moon.sky_mode = DirectionalLight3D.SKY_MODE_LIGHT_ONLY   # no sky disc (a dark disc showed by day)
	main.add_child(moon)
	sky_mat = main.env.sky.sky_material
	# cloud noise for shaders/sky.gdshader: one tileable fbm texture the shader layers at several scales
	var nt := NoiseTexture2D.new()
	var fn := FastNoiseLite.new()
	fn.noise_type = FastNoiseLite.TYPE_PERLIN
	fn.frequency = 0.012
	fn.fractal_octaves = 3
	nt.noise = fn; nt.width = 512; nt.height = 512; nt.seamless = true; nt.generate_mipmaps = true
	sky_mat.set_shader_parameter("cloud_noise", nt)
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--time="):          # --time=21.5 or --time=summer,3,21.5
			var p := a.substr(7).split(",")
			if p.size() == 3: set_date(p[0], int(p[1]), float(p[2]))
			else: set_hour(float(p[0]))
		if a.begins_with("--wet="): wetness = float(a.substr(6))
		if a.begins_with("--snowcover="): snow_cover = float(a.substr(12))
	if not InputMap.has_action("time_fast"):
		for pair in [["time_fast", KEY_F6], ["weather_next", KEY_F7]]:
			InputMap.add_action(pair[0])
			var ev := InputEventKey.new(); ev.physical_keycode = pair[1]
			InputMap.action_add_event(pair[0], ev)
	apply_now()

# ------------------------------------------------------------------ calendar
func day_index() -> int: return int(floor(total_hours / 24.0))
func hour() -> float: return fposmod(total_hours, 24.0)
func season_index() -> int: return int(day_index() / days_per_season) % seasons.size()
func season_name() -> String: return seasons[season_index()]
func day_in_season() -> int: return day_index() % days_per_season + 1
func year() -> int: return int(day_index() / (days_per_season * seasons.size())) + 1
func weekday_name() -> String:
	var w: Array = C["clock"]["weekdays"]
	return w[(start_weekday + day_index()) % 7]
func clock_string() -> String:
	var h := hour(); var hh := int(h); var mm := int((h - hh) * 60.0)
	return "%d:%02d %s" % [(hh + 11) % 12 + 1, mm, "AM" if hh < 12 else "PM"]
func date_string() -> String:
	return "%s, %s day %d, year %d" % [weekday_name(), season_name().capitalize(), day_in_season(), year()]

func set_hour(h: float) -> void:
	total_hours = day_index() * 24.0 + clamp(h, 0.0, 23.999)
	apply_now()

func set_date(season: String, day: int, h: float) -> void:
	total_hours = ((year() - 1) * days_per_season * seasons.size() + seasons.find(season) * days_per_season + day - 1) * 24.0 + h
	apply_now()

# ------------------------------------------------------------------ sun
## Day of the real year that this game day stands for (seasons start on the solstices/equinoxes).
func day_of_year() -> float:
	var sd: Dictionary = C["clock"]["season_day_of_year"]
	var s := season_name()
	var nxt: String = seasons[(season_index() + 1) % seasons.size()]
	var a: float = sd[s]; var b: float = sd[nxt]
	if b < a: b += 365.0
	var f := (day_in_season() - 1 + hour() / 24.0) / days_per_season
	return fposmod(a + (b - a) * f, 365.0)

## Sun altitude/azimuth (degrees) for the current clock. Azimuth from north, clockwise.
func sun_position() -> Vector2:
	var L: Dictionary = C["location"]
	var lat := deg_to_rad(float(L["lat"]))
	var decl := deg_to_rad(23.44 * sin(TAU * (day_of_year() - 81.0) / 365.0))
	var noon: float = L["solar_noon_standard"] + (1.0 if L["dst_seasons"].has(season_name()) else 0.0)
	var ha := deg_to_rad((hour() - noon) * 15.0)
	var sin_alt := sin(lat) * sin(decl) + cos(lat) * cos(decl) * cos(ha)
	var alt := asin(clamp(sin_alt, -1.0, 1.0))
	var az := atan2(-sin(ha), tan(decl) * cos(lat) - sin(lat) * cos(ha))
	return Vector2(rad_to_deg(alt), fposmod(rad_to_deg(az), 360.0))

static func dir_from(alt_deg: float, az_deg: float) -> Vector3:
	var a := deg_to_rad(alt_deg); var z := deg_to_rad(az_deg)
	return Vector3(sin(z) * cos(a), sin(a), -cos(z) * cos(a))   # north = -Z, east = +X

# ------------------------------------------------------------------ per frame
func _unhandled_input(e: InputEvent) -> void:
	if e.is_action_pressed("time_fast"):
		time_scale = 60.0 if time_scale == 1.0 else 1.0
		main.hud.flash("Time x%d" % int(time_scale))

func _process(dt: float) -> void:
	var dh := dt * 24.0 / sec_per_day * time_scale
	total_hours += dh
	step_surface(dh)
	_acc += dt
	if _acc > 0.1 or time_scale > 1.0:   # lighting changes slowly; 10 Hz is plenty at normal speed
		_acc = 0.0
		apply_now()

func register_night_material(m: StandardMaterial3D) -> void:
	_night_mats.append(m)

func register_lamp_material(m: StandardMaterial3D) -> void:
	_lamp_mat = m

func register_ground_materials(mats: Dictionary) -> void:
	for k in GROUND:
		var m = mats.get(k)
		if m is StandardMaterial3D:
			_ground.append([m, m.albedo_color, m.roughness, GROUND[k]])

## Tyre grip for the current road surface (1 = dry). Cars and AI traffic read this.
func road_grip() -> float:
	var G: Dictionary = C["surface"]["grip"]
	return maxf(float(G["min"]), 1.0 - wetness * float(G["wet_loss"]) - snow_cover * float(G["snow_loss"]))

## Speed factor for AI drivers on wet/snowy roads (1 = dry).
func ai_speed_factor() -> float:
	var G: Dictionary = C["surface"]["grip"]
	return lerpf(1.0, float(G["ai_speed_wet"]), clampf(wetness, 0, 1)) * lerpf(1.0, float(G["ai_speed_snow"]), clampf(snow_cover, 0, 1))

## Advance wetness/snow by elapsed game hours (also called directly by tests).
func step_surface(dh: float) -> void:
	if dh <= 0.0: return
	var S: Dictionary = C["surface"]
	var precip: String = main.weather.W["states"][main.weather.state]["precip"] if main.weather else ""
	if precip == "rain":
		wetness = min(1.0, wetness + dh / float(S["wet_hours"]))
		snow_cover = max(0.0, snow_cover - dh * float(S["rain_melt_per_hour"]))
	elif precip == "snow":
		snow_cover = min(1.0, snow_cover + dh / float(S["snow_build_hours"]))
		wetness = max(0.0, wetness - dh / float(S["dry_hours"]))
	else:
		var dry: float = S["dry_hours_night"] if night > 0.5 else S["dry_hours"]
		var melt: float = float(S["melt_per_hour"][season_name()]) * dh
		if snow_cover > 0.0 and melt > 0.0 and float(S["melt_per_hour"][season_name()]) > 0.1:
			wetness = max(wetness, float(S["snow_wetness_on_melt"]) * minf(1.0, snow_cover * 2.0))   # slush
		snow_cover = max(0.0, snow_cover - melt)
		wetness = max(0.0, wetness - dh / dry)

func _col(h: String) -> Color: return Color(h)

func apply_now() -> void:
	var sp := sun_position()
	sun_alt = sp.x
	var w: Dictionary = main.weather.look() if main.get("weather") else {"cloud": 0.05, "sun": 1.0, "fog": 1.0, "dark": 0.0}
	var s := sin(deg_to_rad(sun_alt))
	var day_f := smoothstep(-0.10, 0.22, s)                  # 0 night .. 1 day
	var dusk_f := clampf(1.0 - absf(s - 0.02) / 0.16, 0.0, 1.0) # peaks at sunrise/sunset
	night = 1.0 - smoothstep(-0.12, 0.06, s)
	occupancy = C["occupancy_by_hour"][int(hour()) % 24]
	# sun
	var dir := dir_from(max(sun_alt, -2.0), sp.y)
	sun.basis = Basis.looking_at(-dir, Vector3.UP if abs(dir.y) < 0.99 else Vector3.FORWARD)
	sun.light_energy = 1.3 * smoothstep(-0.02, 0.2, s) * float(w["sun"])
	sun.light_color = Color(1.0, 0.62, 0.38).lerp(Color(1.0, 0.95, 0.86), smoothstep(0.02, 0.3, s))
	sun.shadow_enabled = sun.light_energy > 0.05
	# moon: high in the opposite sky, soft and blue
	var md := dir_from(lerp(25.0, 55.0, night), fposmod(sp.y + 180.0, 360.0))
	moon.basis = Basis.looking_at(-md, Vector3.UP)
	moon.light_energy = 0.3 * night * (1.0 - 0.8 * float(w["cloud"]))
	# sky palette: night -> dusk -> day, then greyed by cloud
	var P: Dictionary = C["sky"]
	var keys := ["top", "horizon", "ground", "fog"]
	var col := {}
	for k in keys:
		var c := _col(P["night"][k]).lerp(_col(P["day"][k]), day_f)
		c = c.lerp(_col(P["dusk"][k]), dusk_f * 0.7 * (1.0 - float(w["cloud"]) * 0.6))
		var grey := Color(c.get_luminance(), c.get_luminance(), c.get_luminance()) * 0.95
		col[k] = c.lerp(grey, float(w["cloud"]) * 0.75).darkened(float(w["dark"]) * 0.5 * day_f)
	var cloud := float(w["cloud"])
	sky_mat.set_shader_parameter("zenith_color", col["top"])
	sky_mat.set_shader_parameter("horizon_color", col["horizon"])
	sky_mat.set_shader_parameter("ground_color", col["ground"])
	sky_mat.set_shader_parameter("dusk_color", _col(P["dusk"]["horizon"]))
	sky_mat.set_shader_parameter("dusk", dusk_f)
	sky_mat.set_shader_parameter("night", night)
	sky_mat.set_shader_parameter("cover", clampf(0.3 + cloud * 0.7, 0.0, 1.0))     # fair-weather cumulus even when "clear"
	sky_mat.set_shader_parameter("overcast", smoothstep(0.55, 0.95, cloud))
	sky_mat.set_shader_parameter("storm", float(w["dark"]))
	sky_mat.set_shader_parameter("cirrus", 0.7 * (1.0 - cloud))
	if main.bars == null or not main.bars.inside:
		main.env.fog_light_color = col["fog"]
		main.env.fog_density = fog_base * float(w["fog"])
		main.env.ambient_light_energy = lerp(float(P["night"]["ambient"]), float(P["day"]["ambient"]), day_f) * (1.0 - float(w["dark"]) * 0.4)
	# night lights: windows (facade shader + masked textures), street lamps
	var fac: ShaderMaterial = main.streamer.materials.get("facade")
	if fac:
		fac.set_shader_parameter("night", night)
		fac.set_shader_parameter("occupancy", occupancy)
	var hl = main.streamer.hlod if main.streamer else null
	if hl != null and hl._mat != null:
		hl._mat.set_shader_parameter("night", night)
		hl._mat.set_shader_parameter("occupancy", occupancy)
	var e := night * (0.25 + 0.5 * occupancy)
	for m in _night_mats:
		m.emission_energy_multiplier = e * 0.9
	if _lamp_mat:
		_lamp_mat.emission_energy_multiplier = 2.5 * night
	if main.get("replicas") and main.replicas: main.replicas.set_night(night, occupancy)
	globals = {"night_level": night, "wetness": wetness, "snow_cover": snow_cover}
	for k in globals: RenderingServer.global_shader_parameter_set(k, globals[k])
	for g in _ground:
		var m: StandardMaterial3D = g[0]
		var s2: float = clampf(snow_cover * g[3], 0.0, 1.0)
		var w2: float = wetness * (1.0 - s2)
		m.albedo_color = (g[1] as Color).lerp(Color(0.92, 0.93, 0.96), s2) * (1.0 - 0.3 * w2)
		m.roughness = lerp(float(g[2]), 0.22, w2)
	# car lights
	var on: bool = night > float(C.get("lights", {}).get("headlight_on_night", 0.25)) or float(w["dark"]) > 0.45
	for car in main.cars:
		if is_instance_valid(car): car.lights_on = on

func is_night() -> bool: return night > 0.5

# ------------------------------------------------------------------ persistence
## world_state.gd section "clock": time, weather spell, wet/snowy ground
func get_save_data() -> Dictionary:
	return {"total_hours": total_hours, "wetness": wetness, "snow_cover": snow_cover, "weather": main.weather.state if main.weather else "clear",
		"weather_left": main.weather.hours_left if main.weather else 6.0}

func apply_save_data(d: Dictionary) -> void:
	total_hours = float(d.get("total_hours", total_hours))
	wetness = float(d.get("wetness", 0.0)); snow_cover = float(d.get("snow_cover", 0.0))
	if main.weather and d.has("weather"):
		main.weather.set_state(d["weather"], float(d.get("weather_left", 6.0)))
	apply_now()

## kept for callers/tests: the whole world is saved/loaded through world_state.gd
func save_state() -> void:
	if main.get("world_state"): main.world_state.save()

func load_state() -> bool:
	return main.world_state.load_file(main.world_state.SAVE_PATH, ["clock"]) if main.get("world_state") else false   # just time & weather

func _notification(_what: int) -> void:
	pass   # saving on quit is done by world_state.gd
