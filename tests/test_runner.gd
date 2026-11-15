extends Node
## Automated game tests. Run: godot --headless --path . -- --test[=tests/out/results.json]
## (tools/run_tests.sh does this plus the Python data tests). Exit code = number of failed tests.
##
## Each test is a coroutine returning [ok: bool, detail: String]. Tests run in order against the live game
## (real streamed city data), so they catch integration breakage, not just unit logic.

var main: Node
var out_path := "res://tests/out/results.json"
var results: Array = []

func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--test="): out_path = a.substr(7)
	main.input_enabled = false
	_run.call_deferred()

func _frames(n: int) -> void:
	for i in n: await get_tree().physics_frame

func _record(name: String, r: Array, ms: int) -> void:
	results.append({"test": name, "pass": r[0], "detail": r[1], "ms": ms})
	print("[test] %s %s  (%s, %d ms)" % ["PASS" if r[0] else "FAIL", name, r[1], ms])

func _run() -> void:
	await _frames(10)
	var tests := [
		["manifest_and_world_bounds", t_manifest],
		["chunk_data_schema", t_chunk_schema],
		["streaming_loads_around_player", t_streaming],
		["player_spawns_on_ground", t_spawn],
		["player_can_walk", t_walk],
		["car_enter_drive_exit", t_car],
		["bar_enter_exit", t_bar_roundtrip],
		["bar_exit_after_origin_rebase", t_bar_rebase],
		["respawn_from_river", t_respawn],
		["clock_one_real_hour_per_day", t_clock],
		["sun_path_by_season", t_sun],
		["night_lights_switch_on", t_night],
		["weather_respects_seasons", t_weather_seasons],
		["weather_changes_the_look", t_weather_look],
		["world_state_save_load", t_persist],
		["street_lamps_light_at_night", t_lamps],
		["car_headlights_at_night", t_headlights],
		["rain_wets_and_dries_the_ground", t_wet],
		["snow_builds_and_melts", t_snow],
		["traffic_road_graph", t_tr_graph],
		["traffic_density_follows_hour", t_tr_density],
		["traffic_spawns_and_moves_in_lanes", t_tr_move],
		["traffic_no_overlapping_cars", t_tr_overlap],
		["traffic_stops_at_red_light", t_tr_red],
		["traffic_stops_for_player", t_tr_player],
		["peds_density_follows_hour", t_pd_density],
		["peds_spawn_and_walk_on_sidewalks", t_pd_walk],
		["peds_cross_only_at_intersections", t_pd_cross],
		["traffic_stops_for_crossing_ped", t_pd_car_stops],
		["peds_umbrellas_in_rain", t_pd_umbrella],
		["wet_and_snowy_roads_lose_grip", t_grip],
		["audio_follows_car_and_weather", t_audio],
		["far_city_hlod_covers_horizon", t_hlod],
		["world_state_sections_round_trip", t_world_state],
		["buses_follow_routes_and_stop", t_bus],
		["npc_schedules_shape_who_is_out", t_schedules],
		["money_cash_wallet_atm", t_money],
		["wanted_level_chase_escape_bust", t_wanted],
		["traffic_stop_ticket_or_flee", t_traffic_stop],
		["jobs_hire_shift_tasks_paycheck_strikes", t_jobs],
		["business_buy_income_collect", t_business],
		["homes_rent_buy_sleep_garage", t_homes],
		["vehicle_roster_in_traffic", t_roster],
		["steal_car_from_traffic", t_carjack],
		["buy_car_new_and_used", t_dealer],
		["car_damage_repair_upgrade_views", t_damage],
		["needs_hunger_stamina_fitness_weight", t_needs],
		["activities_food_gym_games_fishing_bowling", t_activities],
		["police_close_in_offroad_and_helicopter", t_police_heli],
		["emergency_responds_with_siren", t_dispatch],
	]
	for a in OS.get_cmdline_user_args():    # --only=substring runs a subset (debugging)
		if a.begins_with("--only="): tests = tests.filter(func(t): return a.substr(7) in t[0])
	for t in tests:
		var t0 := Time.get_ticks_msec()
		var r = await t[1].call()
		if not (r is Array) or r.size() < 2:
			r = [false, "test crashed (script error, see log above)"]
		_record(t[0], r, Time.get_ticks_msec() - t0)
	if results.size() != tests.size():
		_record("all_tests_ran", [false, "%d of %d tests reported" % [results.size(), tests.size()]], 0)
	var failed := results.filter(func(x): return not x["pass"]).size()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(out_path).get_base_dir())
	var f := FileAccess.open(out_path, FileAccess.WRITE)
	f.store_string(JSON.stringify({"when": Time.get_datetime_string_from_system(), "passed": results.size() - failed,
		"failed": failed, "results": results}, "  "))
	f.close()
	print("[test] %d passed, %d failed" % [results.size() - failed, failed])
	get_tree().quit(failed)

# ------------------------------------------------------------------ tests
func t_money() -> Array:
	var m = main.money
	var c0: int = m.cash; var w0: int = m.wallet
	m.cash = 10; m.wallet = 50
	if not m.spend(30, "test"): return [false, "couldn't pay 30 with 60"]
	if m.cash != 0 or m.wallet != 30: return [false, "cash first then wallet: got cash %d wallet %d" % [m.cash, m.wallet]]
	if m.spend(100, "test"): return [false, "paid more than you have"]
	m.withdraw(20)
	if m.cash != 20 or m.wallet != 10: return [false, "withdraw wrong"]
	m.deposit_all()
	if m.cash != 0 or m.wallet != 30: return [false, "deposit wrong"]
	var snap: Dictionary = main.world_state.snapshot()
	m.wallet = 999
	main.world_state.restore(snap, ["money"])
	var ok_save: bool = m.wallet == 30
	m.cash = c0; m.wallet = w0
	if not ok_save: return [false, "money not restored from save"]
	return [true, "cash first then %s; ATM withdraw/deposit; saved; %d ATMs in data, %d placed near you" % [m.app_name, m.atms.size(), m._nodes.size()]]

func t_wanted() -> Array:
	var po = main.police
	var keep_h: float = main.tod.total_hours; var c0: int = main.money.cash; var w0: int = main.money.wallet
	var pp: Vector3 = main.player.global_position
	po.report("hit_car", main.focus_world(), true)
	if po.stars < 1: return [false, "no stars after a crime seen by police"]
	var got_units := 0
	for i in 600:
		await _frames(1)
		got_units = po.units().size()
		if got_units >= 1: break
	if got_units == 0: return [false, "no police units came"]
	var unit: Dictionary = po.units()[0]
	var has_route: bool = unit.has("path") or unit.has("target")
	po._unseen_t = 999.0
	await _frames(2)
	if po.stars != 0: return [false, "stars stayed after losing them"]
	if po.units().size() > 0: return [false, "units still chasing after losing them"]
	po.stars = 2
	main.money.cash = 100; main.money.wallet = 1000
	po.bust()
	var h: float = fposmod(main.tod.total_hours, 24.0)
	var fined: int = 1100 - main.money.total()
	var at_station := false
	var pw: Vector3 = main.player.global_position + main.world_offset
	for st in po.stations:
		if Vector2(float(st["x"]) - pw.x, float(st["z"]) - pw.z).length() < 60.0: at_station = true
	main.tod.total_hours = keep_h; main.tod.apply_now()
	main.money.cash = c0; main.money.wallet = w0
	main.streamer.load_now(pp + main.world_offset); main.player.global_position = pp
	if po.stars != 0 or absf(h - 8.0) > 0.05: return [false, "after bust: stars %d, hour %.2f" % [po.stars, h]]
	if fined != 300: return [false, "fine %d, expected 300" % fined]
	if not at_station: return [false, "not released at a police station"]
	return [true, "1 star -> %d unit(s) (routed: %s); lost them; busted = 8 am at the station, fined $%d" % [got_units, has_route, fined]]

func t_needs() -> Array:
	var nd = main.needs; var tod = main.tod
	var keep := [nd.hunger, nd.stamina, nd.fitness, nd.weight_kg, nd.kcal_today, nd.burn_today]
	nd.hunger = 80.0
	var sec_per_game_h: float = float(tod.sec_per_day) / 24.0 / tod.time_scale
	nd._process(sec_per_game_h * 6.0)          # 6 game hours
	var drained: float = 80.0 - nd.hunger
	nd.eat("restaurant")
	var fed: bool = nd.hunger > 80.0 - drained
	var p = main.player
	nd.stamina = nd.max_stamina()
	p.sprint = true; p.velocity = Vector3(8, 0, 0)
	nd._process(2.0)
	p.sprint = false; p.velocity = Vector3.ZERO
	var used: float = nd.max_stamina() - nd.stamina
	var w0: float = nd.weight_kg
	nd.kcal_today = 5000.0; nd.burn_today = 0.0; nd.close_day()
	var gained: float = nd.weight_kg - w0
	var w1: float = nd.weight_kg
	nd.kcal_today = 800.0; nd.burn_today = 600.0; nd.close_day()
	var lost: float = w1 - nd.weight_kg
	nd.hunger = keep[0]; nd.stamina = keep[1]; nd.fitness = keep[2]; nd.weight_kg = keep[3]; nd.kcal_today = keep[4]; nd.burn_today = keep[5]
	if drained < 15.0 or drained > 25.0: return [false, "hunger drained %.1f in 6 game hours" % drained]
	if not fed: return [false, "eating didn't fill you up"]
	if used < 10.0: return [false, "sprinting used only %.1f stamina" % used]
	if gained <= 0.0 or lost <= 0.0: return [false, "weight: +%.2f on a big day, -%.2f on a light one" % [gained, lost]]
	return [true, "hunger -%.0f in 6 h; sprint -%.0f stamina in 2 s; a 5000 kcal day +%.2f kg, a light active day -%.2f kg" % [drained, used, gained, lost]]

func t_activities() -> Array:
	var ac = main.activities; var nd = main.needs; var inv = main.inventory; var tod = main.tod
	var keep_h: float = tod.total_hours; var c0: int = main.money.cash; var w0: int = main.money.wallet
	var hk: float = nd.hunger; var fk: float = nd.fitness
	main.money.cash = 0; main.money.wallet = 1000
	nd.hunger = 20.0
	ac.eat_out("fast_food")
	var ate: bool = nd.hunger > 60.0 and main.money.wallet == 1000 - int(ac.L["food"]["fast_food"]["price"])
	ac.buy_groceries()
	var g: int = inv.count("food", "Groceries (1 meal)")
	var f0: float = nd.fitness
	ac.workout()
	var fitter: bool = nd.fitness > f0
	# a Swamp Hens game: find a game day evening
	var day := int(floor(tod.total_hours / 24.0)) + 1
	for i in 7:
		if ac.L["sports"]["game_days"].has(day % 7): break
		day += 1
	tod.total_hours = day * 24.0 + 19.0; tod.apply_now()
	var game_ok: bool = ac.game_on() and ac.watch_game()
	tod.total_hours = day * 24.0 + 10.0; tod.apply_now()
	var no_game_morning: bool = not ac.game_on()
	var movie_ok: bool = ac.watch_movie()
	# fishing: cast, a bite, reel in
	ac.start_fishing(0)
	ac.fishing["state"] = "bite"
	var fish: Dictionary = ac.reel()
	ac.stop_fishing()
	var fish_ok: bool = not fish.is_empty() and inv.count("food", "Fish fillet") >= 1 and inv.fish_log.has(fish["name"])
	# bowling: 300 for a perfect game; a played game finishes after 10 frames
	var perfect: int = ac.score_frames([[10], [10], [10], [10], [10], [10], [10], [10], [10], [10, 10, 10]])
	ac.start_bowling()
	var rolls := 0
	while not ac.bowling.is_empty() and ac.bowling["frames"].size() < 10 and rolls < 30:
		ac.roll(0.5); rolls += 1
	var sc: int = ac.score_frames(ac.bowling["frames"]) if not ac.bowling.is_empty() else 0
	ac.bowling = {}; ac._overlay.visible = false
	inv.items = {"weapons": {}, "food": {}, "misc": {}}; inv.fish_log = {}
	tod.total_hours = keep_h; tod.apply_now(); main.money.cash = c0; main.money.wallet = w0
	nd.hunger = hk; nd.fitness = fk
	if not ate: return [false, "eating out didn't charge/feed"]
	if g != 3: return [false, "groceries gave %d meals" % g]
	if not fitter: return [false, "gym didn't raise fitness"]
	if not (game_ok and no_game_morning): return [false, "ballgame schedule wrong (evening %s, morning off %s)" % [game_ok, no_game_morning]]
	if not movie_ok: return [false, "movie failed"]
	if not fish_ok: return [false, "fishing didn't land a fish"]
	if perfect != 300: return [false, "perfect game scored %d" % perfect]
	if sc < 150: return [false, "dead-centre bowling only scored %d" % sc]
	return [true, "ate out, groceries, gym, Swamp Hens game, movie, caught a %s (%.1f kg), bowled %d (perfect = 300)" % [fish["name"], fish["kg"], sc]]

func t_roster() -> Array:
	var tr = main.traffic; var vh = main.vehicles
	var counts := {}
	for i in 4000:
		var v: Dictionary = tr._pick_type()
		counts[v["id"]] = counts.get(v["id"], 0) + 1
	var cat := {}
	for id in counts:
		var m: Dictionary = vh.roster.get(id, {})
		var k: String = m.get("category", id)
		cat[k] = cat.get(k, 0) + counts[id]
	var ordinary: int = cat.get("sedan", 0) + cat.get("suv", 0) + cat.get("pickup", 0) + cat.get("compact", 0) + cat.get("minivan", 0)
	var rare: int = cat.get("sports", 0) + cat.get("exotic", 0) + cat.get("luxury", 0) + cat.get("muscle", 0)
	for id in counts:
		var t: Dictionary = tr._type(id)
		if String(t.get("name", "")).contains("Vapid") or String(t.get("name", "")).contains("Declasse"): return [false, "a GTA brand name is still in traffic"]
	if ordinary < 3000 or rare > 200: return [false, "mix: ordinary %d, sports/luxury %d of 4000" % [ordinary, rare]]
	return [true, "%d models in traffic; ordinary %d%%, sports/luxury/exotic %.1f%%" % [counts.size(), ordinary * 100 / 4000, rare * 100.0 / 4000.0]]

func t_carjack() -> Array:
	var tr = main.traffic; var vh = main.vehicles
	var f: Vector3 = main.focus_world()
	# an AI car stopped next to the player
	var tc: Dictionary = {}
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		if e["cls"] > 5 or e["len"] < 12.0: continue
		var q: Vector3 = tr.lane_point(e, 4.0, 0)
		if Vector2(q.x - f.x, q.z - f.z).length() < 40.0 and not tr._occupied(i, 4.0, 10.0):
			tc = tr._spawn_on(i, 4.0, "takumi_corsa"); break
	if tc.is_empty(): return [false, "no road near the player"]
	tc["pers"] = 0.0; tc["v"] = 0.0
	await _frames(2)            # placed on the road
	var keep: Vector3 = main.player.global_position
	main.player.global_position = tc["pos"] - main.world_offset + Vector3(2.2, 0.5, 0)
	var n0: int = main.cars.size()
	main.police.lose_them()
	var car = vh.try_carjack(main.player.global_position)
	main.player.global_position = keep
	if car == null: return [false, "couldn't take the stopped car"]
	var ok: bool = main.cars.size() == n0 + 1 and car.stolen and car.spec_id == "takumi_corsa" and not tr.cars.has(tc)
	var crime: Array = main.police.crimes[-1] if not main.police.crimes.is_empty() else []
	main.cars.erase(car); car.queue_free(); main.police.lose_them()
	if not ok: return [false, "stolen car not set up right"]
	if crime.is_empty() or crime[0] != "car_theft": return [false, "no car theft recorded"]
	return [true, "took a %s from traffic; marked stolen; theft %s" % [car.model_name, "seen by " + crime[1] if crime[1] != "" else "unseen"]]

func t_dealer() -> Array:
	var vh = main.vehicles
	var c0: int = main.money.cash; var w0: int = main.money.wallet
	var newd := -1; var usedd := -1
	for d in vh.dealers:
		if d["used"] and usedd < 0: usedd = int(d["id"])
		if not d["used"] and newd < 0: newd = int(d["id"])
	var newo: Array = vh._offers(vh.dealers[newd]); var usedo: Array = vh._offers(vh.dealers[usedd])
	main.money.cash = 0; main.money.wallet = 10
	if vh.buy_offer(newd, 0) != null: return [false, "bought a new car with $10"]
	main.money.wallet = 1000000
	var n0: int = vh.owned.size()
	var car = vh.buy_offer(usedd, 0)
	var spent: int = 1000000 - main.money.wallet
	var ok: bool = car != null and vh.owned.size() == n0 + 1 and spent == int(usedo[0]["price"]) and car.health < 1000.0
	if car: main.cars.erase(car); car.queue_free(); vh.owned.pop_back()
	main.money.cash = c0; main.money.wallet = w0
	var newp: int = int(newo[0]["price"]); var usedp: int = int(usedo[0]["price"])
	if not ok: return [false, "used purchase wrong (spent %d)" % spent]
	return [true, "new %s $%d; used %s $%d (condition %d%%), delivered and owned" % [vh.spec(newo[0]["spec"])["model"], newp, vh.spec(usedo[0]["spec"])["model"], usedp, int(float(usedo[0]["health"]) / 10.0)]]

func t_damage() -> Array:
	var vh = main.vehicles
	var c = vh.spawn_car("halden_fairway", Color(0.3, 0.3, 0.8), main.focus_world() + Vector3(6, 0.5, 6), 0.0)
	c.owned_index = vh.add_owned(c)
	await _frames(3)
	var top0: float = c.TOP_SPEED; var eng0: float = c.MAX_ENGINE
	c.damage(700.0)
	var w0: int = main.money.wallet; var cs0: int = main.money.cash; main.money.wallet = 100000; main.money.cash = 0
	var cost: int = vh.repair_cost(c)
	vh.repair(c)
	var repaired: bool = c.health >= 1000.0 and 100000 - main.money.wallet == cost
	vh.upgrade(c)
	var faster: bool = c.MAX_ENGINE > eng0 and c.TOP_SPEED > top0
	# a crash damages it
	c.linear_velocity = Vector3(0, 0, -25); await _frames(1)
	c._prev_v = Vector3(0, 0, -25); c.linear_velocity = Vector3.ZERO; c._check_damage()
	var crashed: bool = c.health < 1000.0
	# camera views
	var views := 0
	for i in vh.VIEWS.size():
		vh.cam_view = i
		if i >= 2 and vh.view_offset(c) != null: views += 1
	vh.cam_view = 0
	main.money.wallet = w0; main.money.cash = cs0
	main.cars.erase(c); c.queue_free(); vh.owned.pop_back()
	if not repaired: return [false, "repair didn't fix it / charge $%d" % cost]
	if not faster: return [false, "engine upgrade didn't add power"]
	if not crashed: return [false, "a 25 m/s stop didn't damage the car"]
	if views != 3: return [false, "only %d interior/hood/bumper views" % views]
	return [true, "repair $%d at 30%% health; engine upgrade +12%%; crash damage works; 5 camera views" % cost]

func t_homes() -> Array:
	var hm = main.homes; var tod = main.tod
	var c0: int = main.money.cash; var w0: int = main.money.wallet; var keep_h: float = tod.total_hours
	var hid := -1
	for h in hm.homes:
		if int(h["price"]) > 0 and h.get("garage", false): hid = int(h["id"]); break
	var h: Dictionary = hm.listing(hid)
	main.money.cash = 0; main.money.wallet = int(h["rent_week"]) * 2 + 10
	if not hm.rent(hid): return [false, "couldn't rent"]
	tod.total_hours = float(hm.home["next_rent_day"]) * 24.0 + 1.0
	hm._process(0.016)
	var paid_twice: bool = main.money.wallet == 10 and not hm.home.is_empty()
	tod.total_hours = float(hm.home["next_rent_day"]) * 24.0 + 1.0
	hm._process(0.016)
	var evicted: bool = hm.home.is_empty()
	main.money.wallet = int(h["price"]) + 5
	if not hm.buy(hid): return [false, "couldn't buy for $%d" % int(h["price"])]
	tod.total_hours = floor(tod.total_hours / 24.0) * 24.0 + 22.0
	hm.sleep()
	var hr: float = fposmod(tod.total_hours, 24.0)
	# garage: store the nearest player car
	var car = main.cars[2]
	var keep_pos: Vector3 = car.global_position
	car.global_position = main.player.global_position + Vector3(3, 0.5, 0)
	var stored: bool = hm.store_car()
	var hidden: bool = not car.visible
	var snap: Dictionary = main.world_state.snapshot()
	hm.home = {}; hm.garage = []
	main.world_state.restore(snap, ["home"])
	var restored: bool = not hm.home.is_empty() and hm.garage.size() == 1
	var took: bool = hm.take_car(main.player.global_position)
	car.global_position = keep_pos
	hm.home = {}; hm.garage = []
	tod.total_hours = keep_h; tod.apply_now()
	main.money.cash = c0; main.money.wallet = w0
	if not paid_twice: return [false, "weekly rent not charged"]
	if not evicted: return [false, "not evicted when rent couldn't be paid"]
	if absf(hr - 8.0) > 0.05: return [false, "slept until %.2f" % hr]
	if not (stored and hidden and took and car.visible): return [false, "garage store/take failed"]
	if not restored: return [false, "home/garage not saved"]
	return [true, "%s: rent $%d/wk charged then eviction; bought for $%d; sleep to 8 AM; garage keeps a car; saved" % [h["address"], int(h["rent_week"]), int(h["price"])]]

func t_business() -> Array:
	var bz = main.business; var jb = main.jobs
	var c0: int = main.money.cash; var w0: int = main.money.wallet
	var near: Array = jb.openings_near(main.focus_world(), 3)
	var id: int = near[0][1]
	var far_id := -1
	for pl in jb.places:
		if Vector2(float(pl["x"]), float(pl["z"])).length() > 6000.0 and pl["kind"] == jb.place(id)["kind"]: far_id = int(pl["id"]); break
	var pr: int = bz.price(id)
	main.money.cash = 0; main.money.wallet = 100
	if bz.buy(id): return [false, "bought with only $100"]
	main.money.wallet = pr + 50
	if not bz.buy(id): return [false, "couldn't buy for $%d with $%d" % [pr, pr + 50]]
	if main.money.wallet != 50: return [false, "price not taken"]
	bz.auto_deposit = true
	var inc: int = bz.pay_day()
	var auto_ok: bool = main.money.wallet == 50 + inc and inc > 0
	bz.auto_deposit = false
	var inc2: int = bz.pay_day()
	var stored: int = int(bz.owned[id]["stored"])
	var got: int = bz.collect(id)
	var snap: Dictionary = main.world_state.snapshot()
	bz.owned = {}
	main.world_state.restore(snap, ["business"])
	var restored: bool = bz.owned.has(id)
	var price_dt: int = pr; var price_far: int = bz.price(far_id) if far_id >= 0 else 0
	bz.owned = {}; bz.auto_deposit = true
	main.money.cash = c0; main.money.wallet = w0
	if not auto_ok: return [false, "auto-deposit income wrong (%d)" % inc]
	if stored != inc2 or got != inc2: return [false, "stored %d collected %d of %d" % [stored, got, inc2]]
	if not restored: return [false, "ownership not saved"]
	return [true, "%s: $%d (same kind far out: $%d), about $%d/day; auto-deposit and collect work; saved" % [jb.place(id)["name"], price_dt, price_far, inc]]

func t_jobs() -> Array:
	var jb = main.jobs; var tod = main.tod
	var keep_h: float = tod.total_hours; var w0: int = main.money.wallet
	var near: Array = jb.openings_near(main.focus_world(), 6)
	if near.is_empty(): return [false, "no openings"]
	var pid: int = near[0][1]
	jb.hire(pid)
	var d: Dictionary = jb.def_for(jb.job["kind"])
	var sh: Array = d["shift"]
	tod.set_date("fall", 4, float(sh[0]) + 0.2)
	if not jb.clock_in(): return [false, "couldn't clock in at the start of the shift"]
	jb._new_task(d)
	if jb.task.is_empty(): return [false, "no task while on shift"]
	jb.complete_task(); jb._new_task(d); jb.complete_task()
	var earned: int = int(round(jb.earned_shift))
	var wb: int = main.money.wallet
	tod.set_date("fall", 4, float(sh[1]) + 0.05)
	jb._process(0.016)
	var paid: int = main.money.wallet - wb
	if jb.clocked_in: return [false, "still clocked in after the shift ended"]
	if paid != earned or paid < 2 * int(d["bonus"]): return [false, "paycheck $%d, earned $%d" % [paid, earned]]
	# miss two shifts -> fired
	tod.set_date("fall", 5, float(sh[0]) + 1.2); jb._process(0.016)
	var s1: int = jb.strikes
	tod.set_date("fall", 6, float(sh[0]) + 1.2); jb._process(0.016)
	var fired: bool = jb.job.is_empty()
	# save round trip
	jb.hire(pid)
	var snap: Dictionary = main.world_state.snapshot()
	jb.job = {}
	main.world_state.restore(snap, ["job"])
	var restored: bool = not jb.job.is_empty() and int(jb.job["place"]) == pid
	jb.job = {}
	tod.total_hours = keep_h; tod.apply_now(); main.money.wallet = w0
	if s1 != 1 or not fired: return [false, "strikes %d, fired %s" % [s1, fired]]
	if not restored: return [false, "job not restored from save"]
	return [true, "%s at %s: 2 tasks, paycheck $%d; 2 missed shifts = fired; saved" % [d["title"], jb.place(pid)["name"], paid]]

func _spawn_cop_near() -> Dictionary:
	var tr = main.traffic
	var f: Vector3 = main.focus_world()
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		if e["cls"] > 6 or e["len"] < 10.0: continue
		var sd := 0.0
		while sd < float(e["len"]):
			var q: Vector3 = tr.lane_point(e, sd, 0)
			var d: float = Vector2(q.x - f.x, q.z - f.z).length()
			if d > 22.0 and d < 42.0 and not tr._occupied(i, sd, 12.0): return tr._spawn_on(i, sd, "police")
			sd += 5.0
	return {}

func t_traffic_stop() -> Array:
	var po = main.police
	var cop := _spawn_cop_near()
	if cop.is_empty(): return [false, "no road to put a patrol car on"]
	var c0: int = main.money.cash; var w0: int = main.money.wallet
	main.money.cash = 0; main.money.wallet = 1000
	po.rng.seed = 3     # deterministic warning/ticket roll
	po.start_stop(cop, "speeding", 25.0)
	if po.stop.is_empty() or not cop.get("siren", false): return [false, "patrol didn't light up"]
	var amt: int = po.ticket_amount("speeding", 25.0)
	var res: String = po.resolve_stop()
	var paid: int = 1000 - main.money.wallet
	if res == "ticket" and paid != amt: return [false, "ticket $%d but paid $%d" % [amt, paid]]
	if res == "warning" and paid != 0: return [false, "warning but paid $%d" % paid]
	if cop.get("siren", false): return [false, "cop kept the siren on after the stop"]
	# now drive off during a stop
	po.start_stop(cop, "run_red", 0.0)
	po.stop["t"] = 999.0
	po._run_stop(0.016)
	var fled_stars: int = po.stars
	po.lose_them()
	main.money.cash = c0; main.money.wallet = w0
	if fled_stars != 1: return [false, "fleeing a stop gave %d stars" % fled_stars]
	return [true, "pulled over for 25 mph over: %s ($%d); fleeing a stop = 1 star" % [res, paid]]

func t_police_heli() -> Array:
	var po = main.police; var tr = main.traffic
	var cop := _spawn_cop_near()
	if cop.is_empty(): return [false, "no road to put a unit on"]
	cop["chase"] = true; cop["siren"] = true; cop["keep"] = true
	var pw: Vector3 = main.focus_world()
	po._approach(cop, pw, 6.0)
	if not cop.has("free_to"): return [false, "unit %.0f m away didn't leave the road" % (cop["pos"] - pw).length()]
	var d0: float = (cop["pos"] - pw).length()
	for i in 240: await _frames(1)
	var d1: float = (cop["pos"] - pw).length()
	po.stars = 4
	po._update_heli(0.016)
	var heli_ok: bool = po.heli != null and is_instance_valid(po.heli)
	po.lose_them()
	po._update_heli(0.016)
	var gone: bool = po.heli == null
	var back_on_road: bool = not cop.has("free_to")
	if d1 > d0 - 5.0 and d1 > 8.0: return [false, "unit didn't close in off-road (%.0f -> %.0f m)" % [d0, d1]]
	if not heli_ok: return [false, "no helicopter at 4 stars"]
	if not gone: return [false, "helicopter stayed after losing them"]
	if not back_on_road: return [false, "unit not back on the road after the chase"]
	return [true, "unit drove straight in %.0f -> %.0f m; helicopter at 4 stars, gone after; back on the road" % [d0, d1]]

func t_schedules() -> Array:
	var pd = main.peds
	if not pd.SCH.has("roles"): return [false, "no schedules loaded"]
	var keep: float = main.tod.total_hours
	main.tod.set_date("fall", 3, 8.5)     # a Wednesday-ish morning
	var morning: Dictionary = pd.role_weights("downtown", 8.5)
	var night_dt: Dictionary = pd.role_weights("nightlife", 23.0)
	var g_work_am: String = pd.goal_for("worker", 8.0); var g_work_pm: String = pd.goal_for("worker", 17.0)
	var g_owl: String = pd.goal_for("night_owl", 21.0)
	main.tod.total_hours = keep; main.tod.apply_now()
	var top_am: String = morning.keys().reduce(func(a, b): return a if morning[a] >= morning[b] else b)
	var top_night: String = night_dt.keys().reduce(func(a, b): return a if night_dt[a] >= night_dt[b] else b)
	if top_am != "worker": return [false, "downtown at 8:30 mostly %s" % top_am]
	if not (top_night in ["night_owl", "student"]): return [false, "bars at 11 pm mostly %s" % top_night]
	if g_work_am != "downtown" or g_work_pm != "home" or g_owl != "bar": return [false, "goals: worker %s/%s, night owl %s" % [g_work_am, g_work_pm, g_owl]]
	var roles := {}
	for p in pd.peds: roles[p.get("role", "")] = roles.get(p.get("role", ""), 0) + 1
	if roles.has(""): return [false, "people without a role: %d" % roles[""]]
	return [true, "8:30 downtown mostly workers, 11 pm bars mostly %s; on the street now %s" % [top_night, roles]]

func t_bus() -> Array:
	var sv = main.services
	if sv.routes.size() < 8: return [false, "only %d bus routes" % sv.routes.size()]
	var c: Dictionary = {}
	for i in 20:
		c = sv.spawn_bus(true)
		if not c.is_empty(): break
		await _frames(5)
	if c.is_empty(): return [false, "no bus route passes near the player"]
	var ns: Array = c["path"]
	var off_route := 0; var stopped_at_stop := false; var moved := 0.0
	var p0: Vector3 = c["pos"]
	for k in 1500:
		await _frames(1)
		if not tr_alive(c): break
		if moved > 40.0 and stopped_at_stop: break
		if c.has("path"):
			var i: int = c["pi"]
			if i <= 0 or i >= ns.size() or ns[i] != c["eb"] or ns[i - 1] != c["ea"]: off_route += 1
		if c.get("dwell", 0.0) > 0.5: stopped_at_stop = true
		moved = maxf(moved, (c["pos"] - p0).length())
	if off_route > 5: return [false, "bus left its route %d frames" % off_route]
	if moved < 20.0 and not stopped_at_stop:
		var tr = main.traffic
		var why: String = tr.control_for(tr.edges[c["edge"]], c["eb"]) if tr_alive(c) else "gone"
		var lead: Array = tr._leader(c, {}) if tr_alive(c) else [0.0, 0.0]
		if why == "stop" or lead[0] < 15.0: return [true, "bus waiting (%s, %.0f m gap) - route %s" % ["red light" if why == "stop" else "queued", lead[0], c["route_name"]]]
		return [false, "bus barely moved (%.0f m), control %s, gap ahead %.0f m" % [moved, why, lead[0]]]
	return [true, "route %s: %.0f m along it%s" % [c["route_name"], moved, ", stopped at a stop" if stopped_at_stop else ""]]

func tr_alive(c: Dictionary) -> bool:
	return main.traffic.cars.has(c)

func t_dispatch() -> Array:
	var sv = main.services
	var inc: Dictionary = {}
	for i in 10:
		inc = sv.dispatch("ambulance")
		if not inc.is_empty(): break
		await _frames(5)
	if inc.is_empty(): return [false, "could not dispatch"]
	var c: Dictionary = inc["car"]
	var ip: Vector3 = main.traffic.npos[inc["node"]]
	var d0: float = (c["pos"] - ip).length()
	var best := d0
	var p0: Vector3 = c["pos"]; var moved := 0.0; var pi0: int = c["pi"]
	for k in 1200:
		await _frames(1)
		if not tr_alive(c): break
		best = minf(best, (c["pos"] - ip).length())
		moved = maxf(moved, (c["pos"] - p0).length())
		if c.get("dwell", 0.0) > 0.0 and c.get("target", -1) == inc["node"]: break
	var lvl: float = main.audio.targets()["siren"] if main.audio else 0.0
	if not c.get("siren", false) and c.has("target"): return [false, "siren off before arriving"]
	var progressed: int = int(c.get("pi", pi0)) - pi0
	if moved < 25.0 and progressed < 3: return [false, "responder barely moved (%.0f m, %d route nodes)" % [moved, progressed]]
	main.traffic._despawn(c)
	return [true, "ambulance drove %.0f m along its %d-node route (%.0f -> %.0f m from the scene); siren level %.2f" % [moved, inc["car"]["path"].size() if inc["car"].has("path") else 0, d0, best, lvl]]

func t_world_state() -> Array:
	var ws = main.world_state
	if ws == null: return [false, "no world_state"]
	var ids: Array = ws.sections.map(func(x): return x[0])
	if not ("clock" in ids and "player" in ids and "stats" in ids): return [false, "sections registered: %s" % [ids]]
	main.stats.on_bar_entered("Test Bar")
	var snap0: Dictionary = ws.snapshot()
	main.stats.bars_visited = {}
	ws.restore(snap0)
	if not main.stats.bars_visited.has("Test Bar"): return [false, "stats not restored"]
	main.stats.bars_visited.erase("Test Bar")
	# your car (owned, section "vehicles"): move it, restore, and it's back where it was saved
	var c = null
	for cc in main.cars:
		if is_instance_valid(cc) and cc.owned_index >= 0: c = cc
	if c == null: return [false, "you don't own a car at the start"]
	var keep: Vector3 = c.global_position
	var snap: Dictionary = ws.snapshot()
	c.global_position += Vector3(40, 0, 0)
	ws.restore(snap, ["vehicles"])
	await _frames(2)
	var back := 999.0
	for cc in main.cars:
		if is_instance_valid(cc) and cc.owned_index == 0: back = Vector2(cc.global_position.x - keep.x, cc.global_position.z - keep.z).length()
	var legacy: Dictionary = ws._migrate({"total_hours": 5.0})
	if back > 1.0: return [false, "car not restored (%.1f m off)" % back]
	if not legacy["sections"].has("clock"): return [false, "old save format not migrated"]
	return [true, "sections %s restored; v1 saves migrate" % [ids]]

func t_grip() -> Array:
	var tod = main.tod
	var kw: float = tod.wetness; var kn: float = tod.snow_cover
	tod.wetness = 0.0; tod.snow_cover = 0.0
	var dry: float = tod.road_grip(); var ai_dry: float = tod.ai_speed_factor()
	tod.wetness = 1.0
	var wet: float = tod.road_grip()
	tod.wetness = 0.0; tod.snow_cover = 1.0
	var snow: float = tod.road_grip(); var ai_snow: float = tod.ai_speed_factor()
	tod.wetness = kw; tod.snow_cover = kn
	if not (dry > 0.99 and wet < dry and snow < wet): return [false, "grip dry %.2f wet %.2f snow %.2f" % [dry, wet, snow]]
	if ai_snow >= ai_dry: return [false, "AI not slower on snow"]
	return [true, "grip dry %.2f, wet %.2f, snow %.2f; AI speed on snow x%.2f" % [dry, wet, snow, ai_snow]]

func t_audio() -> Array:
	var au = main.audio
	if au == null: return [false, "no audio node"]
	var r0: float = au.engine_rpm(0.0, 0.0); var r1: float = au.engine_rpm(6.0, 1.0)
	if not (r1 > r0): return [false, "rpm does not rise with speed (%d -> %d)" % [r0, r1]]
	var w = main.weather; var ks: String = w.state
	w.set_state("clear"); var t_clear: Dictionary = au.targets()
	w.set_state("storm"); var t_storm: Dictionary = au.targets()
	w.set_state(ks); w.snap()
	if not (t_storm["rain"] > t_clear["rain"] and t_storm["wind"] > t_clear["wind"]): return [false, "rain/wind not louder in a storm"]
	return [true, "rpm %d -> %d; storm rain %.2f wind %.2f" % [r0, r1, t_storm["rain"], t_storm["wind"]]]

func t_hlod() -> Array:
	var h = main.streamer.hlod
	if h == null: return [false, "far city disabled"]
	for i in 600:
		if h.is_idle() and h.regions.size() > 0: break
		await _frames(1)
	await _frames(40)    # visibility is refreshed every 0.25 s
	var shown := 0; var far := 0
	var p: Vector3 = main.focus_world()
	for r in h.regions:
		var mi = h.regions[r]
		if mi is MeshInstance3D and mi.visible:
			shown += 1
			var c: Vector3 = h.region_center(r)
			far = maxi(far, int(Vector2(c.x - p.x, c.z - p.z).length()))
		if mi is MeshInstance3D and mi.visible and h.region_detailed(r): return [false, "region %s drawn twice (far + detail)" % r]
	if shown < 20 or far < 2000: return [false, "only %d far regions, reaching %d m" % [shown, far]]
	return [true, "%d far regions, out to %d m" % [shown, far]]

func t_manifest() -> Array:
	var m: Dictionary = main.streamer.manifest
	for k in ["chunk_size", "chunks", "bbox", "spawn", "origin_lat", "origin_lon"]:
		if not m.has(k): return [false, "manifest missing " + k]
	var bb: Array = m["bbox"]
	var w: float = bb[2] - bb[0]; var h: float = bb[3] - bb[1]
	if w < 2000 or h < 2000: return [false, "bbox too small %dx%d m" % [w, h]]
	return [true, "%d chunks, %.1f x %.1f km" % [m["chunks"].size(), w / 1000.0, h / 1000.0]]

func t_chunk_schema() -> Array:
	var ks: Array = main.streamer.available.keys()
	if ks.is_empty(): return [false, "no chunks available"]
	var rng := RandomNumberGenerator.new(); rng.seed = 7
	var checked := 0; var facade := 0
	var sample: Array = []
	var sp: Array = main.streamer.manifest["spawn"]
	var ck: Vector2i = main.streamer.key_for_world(Vector3(sp[0], 0, sp[1]))
	for dx in range(-2, 3):
		for dz in range(-2, 3):
			if main.streamer.available.has(ck + Vector2i(dx, dz)): sample.append(ck + Vector2i(dx, dz))   # downtown: facade layers
	for i in 40: sample.append(ks[rng.randi() % ks.size()])
	for k in sample:
		var d: Dictionary = main.streamer.read_chunk(k)
		if d.is_empty(): return [false, "chunk %s unreadable" % k]
		for key in ["layers", "col", "props", "labels", "streets"]:
			if not d.has(key): return [false, "chunk %s missing %s" % [k, key]]
		for L in d["layers"]:
			var nv: int = L["v"].size()
			if nv % 3 != 0: return [false, "chunk %s layer %s: %d verts not a triangle list" % [k, L["mat"], nv]]
			if L["n"].size() != nv or L["uv"].size() != nv: return [false, "chunk %s layer %s: n/uv length mismatch" % [k, L["mat"]]]
			if L.has("color"):
				facade += 1
				if L["uv2"].size() != nv or L["color"].size() != nv or L["c0"].size() != nv * 4:
					return [false, "chunk %s facade layer: attribute length mismatch" % k]
		if d["col"].size() % 3 != 0: return [false, "chunk %s collision not triangles" % k]
		checked += 1
	if facade == 0: return [false, "no facade layers found in downtown chunks"]
	return [true, "%d chunks ok, %d facade layers" % [checked, facade]]

func t_streaming() -> Array:
	var t0 := Time.get_ticks_msec()
	while not main.streamer.is_idle() and Time.get_ticks_msec() - t0 < 30000:
		await _frames(5)
	var n: int = main.streamer.loaded.size()
	return [n >= 9, "%d chunks loaded around spawn" % n]

func _on_ground(p: Vector3) -> bool:
	var q := PhysicsRayQueryParameters3D.create(p + Vector3(0, 1.0, 0), p + Vector3(0, -3.0, 0))
	return not main.get_world_3d().direct_space_state.intersect_ray(q).is_empty()

func t_spawn() -> Array:
	await _frames(60)
	var p: Vector3 = main.player.global_position
	if abs(p.y) > 3.0: return [false, "player at y=%.2f (expected street level)" % p.y]
	if not main.player.is_on_floor() and not _on_ground(p): return [false, "player not on the ground at %s" % p]
	return [true, "at %s" % p.snapped(Vector3(0.1, 0.1, 0.1))]

func t_walk() -> Array:
	var best := 0.0
	for yaw in [0.0, PI * 0.5, PI, -PI * 0.5]:
		main.cam_yaw = yaw
		var p0: Vector3 = main.player.global_position
		main.player.input_dir = Vector2(0, 1)
		await _frames(240)   # 2 s
		main.player.input_dir = Vector2.ZERO
		var d := Vector2(main.player.global_position.x - p0.x, main.player.global_position.z - p0.z).length()
		best = max(best, d)
		if d > 5.0 and abs(main.player.global_position.y - p0.y) < 2.0:
			return [true, "walked %.1f m in 2 s" % d]
	return [false, "best distance %.1f m in 2 s (blocked?)" % best]

func t_car() -> Array:
	var c = main.cars[0]
	if main.traffic:   # this test is about the player's car, not about traffic jams
		for tc in main.traffic.cars.duplicate():
			if (tc["pos"] - (c.global_position + main.world_offset)).length() < 80.0: main.traffic._despawn(tc)
	main.player.global_position = c.global_position + c.global_transform.basis.x * 2.0
	await _frames(5)
	main.toggle_vehicle()
	if main.current_car == null: return [false, "could not enter car"]
	var p0: Vector3 = c.global_position
	c.throttle = 1.0
	await _frames(360)   # 3 s
	c.throttle = 0.0
	var d: float = (c.global_position - p0).length()
	var up: float = c.global_transform.basis.y.y
	main.toggle_vehicle()
	if main.current_car != null: return [false, "could not exit car"]
	if d < 8.0: return [false, "car moved only %.1f m in 3 s" % d]
	if up < 0.7: return [false, "car flipped (up=%.2f)" % up]
	return [true, "drove %.1f m in 3 s, exited" % d]

func _a_door(far_from := Vector3.INF, min_dist := 0.0) -> Dictionary:
	# find a bar from the data, stream it in, return its door
	var j = JSON.parse_string(FileAccess.get_file_as_string("res://data/bars_index.json"))
	if j == null: return {}
	var here: Vector3 = main.player.global_position + main.world_offset
	var bb: Array = main.streamer.manifest["bbox"]
	for b in j:
		var at := Vector3(b["x"], 0, -b["y"])
		if at.x < bb[0] or at.x > bb[2] or at.z < bb[1] or at.z > bb[3]: continue
		if min_dist > 0.0 and Vector2(at.x - here.x, at.z - here.z).length() < min_dist: continue
		main.focus_override = at
		main.streamer.load_now(at)
		await _frames(3)
		var d: Dictionary = main.bars.nearest_door(at - main.world_offset, 90.0)
		if not d.is_empty(): return d
	return {}

func t_bar_roundtrip() -> Array:
	var d: Dictionary = await _a_door()
	if d.is_empty(): return [false, "no bar door found in the streamed data"]
	var n: Node3D = d["node"]
	main.player.global_position = n.global_transform * Vector3(0, 0.3, -1.6)
	await _frames(3)
	var pr: String = main.bars.prompt(main.player.global_position)
	if not pr.begins_with("Press E to enter"): return [false, "no enter prompt at the door (got '%s')" % pr]
	var door_world: Vector3 = n.global_position + main.world_offset
	if not main.bars.try_interact(main.player) or not main.bars.inside: return [false, "enter failed"]
	await _frames(60)
	if main.player.global_position.y > -2000.0: return [false, "player not in the interior (y=%.1f)" % main.player.global_position.y]
	if not main.player.is_on_floor(): return [false, "player not standing on the interior floor"]
	main.player.global_position = main.bars.interior.global_transform * main.bars.exit_point
	await _frames(3)
	if not main.bars.try_interact(main.player) or main.bars.inside: return [false, "exit failed"]
	await _frames(30)
	var back: Vector3 = main.player.global_position + main.world_offset
	var dist := Vector2(back.x - door_world.x, back.z - door_world.z).length()
	main.focus_override = null
	if dist > 4.0: return [false, "came out %.1f m from the door" % dist]
	return [true, "%s: in and out, %.1f m from door" % [d["theme"], dist]]

func t_bar_rebase() -> Array:
	# enter a bar far from the current origin, then let the world re-centre while inside, then leave
	var off0: Vector3 = main.world_offset
	var d: Dictionary = await _a_door(Vector3.INF, 2500.0)
	if d.is_empty(): return [false, "no far bar door found"]
	var n: Node3D = d["node"]
	main.focus_override = null
	main.player.global_position = n.global_transform * Vector3(0, 0.3, -1.6)
	var door_world: Vector3 = n.global_position + main.world_offset
	if not main.bars.try_interact(main.player): return [false, "enter failed"]
	await _frames(30)   # origin rebase happens here (player is > 1 km from the old origin)
	var shifted: bool = main.world_offset != off0
	main.player.global_position = main.bars.interior.global_transform * main.bars.exit_point
	await _frames(3)
	if not main.bars.try_interact(main.player): return [false, "exit failed"]
	await _frames(30)
	var back: Vector3 = main.player.global_position + main.world_offset
	var dist := Vector2(back.x - door_world.x, back.z - door_world.z).length()
	if not shifted: return [false, "origin did not rebase during the test (test setup)"]
	if dist > 4.0: return [false, "after rebase came out %.1f m from the door" % dist]
	return [true, "%s: rebased while inside, came out %.1f m from door" % [d["theme"], dist]]

func t_respawn() -> Array:
	var safe: Vector3 = main.last_safe
	main.player.global_position = Vector3(main.player.global_position.x, -10.0, main.player.global_position.z)
	await _frames(20)
	var y: float = main.player.global_position.y
	return [y > -3.0, "respawned to y=%.1f (last safe %s)" % [y, safe.snapped(Vector3.ONE)]]

# ------------------------------------------------------------------ time of day / weather
func t_clock() -> Array:
	var tod = main.tod
	var h0: float = tod.total_hours
	var ts: float = tod.time_scale
	tod.time_scale = 1.0
	for i in 3600: tod.total_hours += 1.0 * 24.0 / tod.sec_per_day * tod.time_scale   # same formula as _process
	var dh: float = tod.total_hours - h0
	tod.total_hours = h0; tod.time_scale = ts
	if abs(dh - 24.0) > 0.001: return [false, "3600 real seconds advanced %.3f game hours" % dh]
	return [true, "1 real hour = 24 game hours (sec_per_day=%d)" % tod.sec_per_day]

func t_sun() -> Array:
	var tod = main.tod
	var keep: float = tod.total_hours
	var out := []
	for se in ["spring", "summer", "fall", "winter"]:
		tod.set_date(se, 6, 0.0); var mid: float = tod.sun_position().x
		tod.set_date(se, 6, 13.0); var noon: float = tod.sun_position().x
		out.append("%s noon %.0f°" % [se, noon])
		if mid > -5.0: tod.total_hours = keep; return [false, "%s: sun at %.1f° at midnight" % [se, mid]]
		if noon < 20.0: tod.total_hours = keep; return [false, "%s: sun only %.1f° at 1 pm" % [se, noon]]
	tod.set_date("summer", 1, 21.0); var ss: float = tod.sun_position().x   # ~June 21: Toledo sunset about 9:12 pm
	tod.set_date("winter", 1, 17.5); var ws: float = tod.sun_position().x   # ~Dec 21: Toledo sunset about 5:08 pm
	tod.total_hours = keep; tod.apply_now()
	if ss < -1.0: return [false, "summer 9 pm sun already down (%.1f°): no long Ohio summer evenings" % ss]
	if ws > 0.0: return [false, "winter 5:30 pm sun still up (%.1f°)" % ws]
	return [true, ", ".join(out)]

func t_night() -> Array:
	var tod = main.tod
	var keep: float = tod.total_hours
	tod.set_date("fall", 3, 23.0)
	var n: float = tod.night
	var fac: ShaderMaterial = main.streamer.materials["facade"]
	var fn: float = fac.get_shader_parameter("night")
	var em := 0.0
	for m in tod._night_mats: em = max(em, m.emission_energy_multiplier)
	var lamp: float = tod._lamp_mat.emission_energy_multiplier if tod._lamp_mat else 0.0
	var amb_night: float = main.env.ambient_light_energy
	tod.set_date("fall", 3, 13.0)
	var day_n: float = tod.night
	var amb_day: float = main.env.ambient_light_energy
	var day_em := 0.0
	for m in tod._night_mats: day_em = max(day_em, m.emission_energy_multiplier)
	tod.total_hours = keep; tod.apply_now()
	if n < 0.9 or fn < 0.9: return [false, "11 pm not night (night=%.2f, facade=%.2f)" % [n, fn]]
	if em <= 0.05 or lamp <= 0.5: return [false, "lights not on at night (windows %.2f, lamps %.2f)" % [em, lamp]]
	if tod._night_mats.size() < 10: return [false, "only %d window materials registered" % tod._night_mats.size()]
	if day_n > 0.05 or day_em > 0.01: return [false, "lights still on at 1 pm"]
	if amb_night >= amb_day * 0.5: return [false, "night not darker (ambient %.2f vs %.2f)" % [amb_night, amb_day]]
	return [true, "%d window materials + facade + lamps on at night, off by day" % tod._night_mats.size()]

func t_weather_seasons() -> Array:
	var w = main.weather
	for i in 3000:
		if w.next_state("summer") == "snow": return [false, "snow chosen in summer"]
		if w.next_state("spring") == "snow": return [false, "snow chosen in spring"]
		if w.next_state("winter") == "storm": return [false, "thunderstorm chosen in winter"]
	var seen := {}
	for i in 3000: seen[w.next_state("winter")] = true
	if not seen.has("snow"): return [false, "winter never snows"]
	return [true, "3000 draws per season, winter states: %s" % ", ".join(seen.keys())]

func t_weather_look() -> Array:
	var w = main.weather; var tod = main.tod
	var keep_state: String = w.state; var keep: float = tod.total_hours
	tod.set_date("summer", 5, 13.0)
	w.set_state("clear"); w.snap(); tod.apply_now()
	var fog_clear: float = main.env.fog_density; var sun_clear: float = main.get_node("Sun").light_energy
	w.set_state("fog"); w.snap(); tod.apply_now()
	var fog_fog: float = main.env.fog_density
	w.set_state("storm"); w.snap(); tod.apply_now()
	var sun_storm: float = main.get_node("Sun").light_energy
	await _frames(5)
	var raining: bool = w.rain.emitting
	w.set_state(keep_state); w.snap(); tod.total_hours = keep; tod.apply_now()
	if fog_fog < fog_clear * 5.0: return [false, "fog state barely changes fog (%.5f vs %.5f)" % [fog_fog, fog_clear]]
	if sun_storm > sun_clear * 0.3: return [false, "storm sunlight %.2f vs clear %.2f" % [sun_storm, sun_clear]]
	if not raining: return [false, "no rain particles in a storm"]
	return [true, "fog x%.0f, storm sun %.0f%%, rain falling" % [fog_fog / fog_clear, 100.0 * sun_storm / sun_clear]]

func t_persist() -> Array:
	var tod = main.tod; var w = main.weather
	var keep: float = tod.total_hours; var ks: String = w.state
	tod.set_date("winter", 7, 18.25); w.set_state("snow", 3.0)
	var saved: float = tod.total_hours
	tod.save_state()
	tod.set_date("summer", 2, 9.0); w.set_state("clear")
	var ok: bool = tod.load_state()
	var back: float = tod.total_hours; var bs: String = w.state
	tod.total_hours = keep; w.set_state(ks); w.snap(); tod.apply_now()
	if not ok: return [false, "load_state failed"]
	if abs(back - saved) > 0.001 or bs != "snow": return [false, "restored %.2f h / %s, expected %.2f h / snow" % [back, bs, saved]]
	return [true, "time and weather restored"]

func t_lamps() -> Array:
	var tod = main.tod
	var keep: float = tod.total_hours
	var pools := 0; var heads := 0
	for k in main.streamer.loaded:
		var r: Node3D = main.streamer.loaded[k]
		if r.has_node("lamp_pools"): pools += (r.get_node("lamp_pools") as MultiMeshInstance3D).multimesh.instance_count
		if r.has_meta("lamp_heads"): heads += r.get_meta("lamp_heads").size()
	tod.set_date("fall", 3, 23.0)
	var gn: float = tod.globals["night_level"]
	var sl = main.get_node("StreetLights")
	sl._t = 0.0; sl._process(0.0)
	var lit := 0
	for o in sl.lights: if o.visible: lit += 1
	tod.set_date("fall", 3, 13.0)
	var gd: float = tod.globals["night_level"]
	sl._t = 0.0; sl._process(0.0)
	var lit_day := 0
	for o in sl.lights: if o.visible: lit_day += 1
	tod.total_hours = keep; tod.apply_now()
	if pools < 50: return [false, "only %d lamp light pools in %d loaded chunks" % [pools, main.streamer.loaded.size()]]
	if gn < 0.9 or gd > 0.05: return [false, "pool glow night=%.2f day=%.2f" % [gn, gd]]
	if lit < 8 or lit_day > 0: return [false, "real lamp lights: %d at night, %d by day" % [lit, lit_day]]
	return [true, "%d lamp pools, %d real lights at night, none by day" % [pools, lit]]

func t_headlights() -> Array:
	var tod = main.tod; var w = main.weather
	var keep: float = tod.total_hours; var ks: String = w.state
	w.set_state("clear"); w.snap()
	var c = main.cars[0]
	tod.set_date("summer", 4, 23.0)
	await _frames(2)
	var on_n: bool = c.lights_on; var e_n: float = c._hl_mat.emission_energy_multiplier
	tod.set_date("summer", 4, 12.0)
	await _frames(2)
	var on_d: bool = c.lights_on
	w.set_state(ks); w.snap(); tod.total_hours = keep; tod.apply_now()
	if not on_n or e_n < 1.0: return [false, "headlights off at 11 pm"]
	if on_d: return [false, "headlights on at noon in clear weather"]
	return [true, "on at night, off at noon"]

func t_wet() -> Array:
	var tod = main.tod; var w = main.weather
	var ks: String = w.state; var kw: float = tod.wetness; var kn: float = tod.snow_cover
	tod.wetness = 0.0; tod.snow_cover = 0.0
	w.set_state("rain"); tod.step_surface(1.0)
	var wet: float = tod.wetness
	tod.apply_now()
	var g: float = tod.globals["wetness"]
	var asphalt: StandardMaterial3D = main.streamer.materials["asphalt"]
	var r_wet: float = asphalt.roughness
	w.set_state("clear"); for i in 12: tod.step_surface(1.0)
	var dry: float = tod.wetness
	tod.apply_now()
	var r_dry: float = asphalt.roughness
	tod.wetness = kw; tod.snow_cover = kn; w.set_state(ks); w.snap(); tod.apply_now()
	if wet < 0.9 or g < 0.9: return [false, "after 1 h of rain wetness=%.2f (shader %.2f)" % [wet, g]]
	if r_wet > r_dry - 0.3: return [false, "wet asphalt not glossier (%.2f vs %.2f)" % [r_wet, r_dry]]
	if dry > 0.05: return [false, "still wet (%.2f) 12 h after rain" % dry]
	return [true, "1 h rain -> %.2f wet, dry again after 12 h" % wet]

func t_snow() -> Array:
	var tod = main.tod; var w = main.weather
	var keep: float = tod.total_hours; var ks: String = w.state; var kw: float = tod.wetness; var kn: float = tod.snow_cover
	tod.snow_cover = 0.0
	tod.set_date("winter", 3, 10.0); w.set_state("snow")
	for i in 6: tod.step_surface(1.0)
	var built: float = tod.snow_cover
	w.set_state("clear"); for i in 6: tod.step_surface(1.0)
	var winter_keep: float = tod.snow_cover
	tod.set_date("spring", 2, 12.0)
	for i in 6: tod.step_surface(1.0)
	var spring: float = tod.snow_cover
	tod.total_hours = keep; tod.wetness = kw; tod.snow_cover = kn; w.set_state(ks); w.snap(); tod.apply_now()
	if built < 0.9: return [false, "6 h of snow gave only %.2f cover" % built]
	if winter_keep < 0.6: return [false, "snow melted too fast in winter (%.2f left after 6 h)" % winter_keep]
	if spring > 0.1: return [false, "snow still %.2f after 6 spring hours" % spring]
	return [true, "6 h snow -> %.2f, winter 6 h later %.2f, spring melts to %.2f" % [built, winter_keep, spring]]

# ------------------------------------------------------------------ traffic
func _tr_reset_to_spawn() -> void:
	var sp: Array = main.streamer.manifest["spawn"]
	main.focus_override = null
	if main.current_car: main.toggle_vehicle()
	main.player.global_position = Vector3(sp[0], 0, sp[1]) - main.world_offset
	main.streamer.load_now(Vector3(sp[0], 0, sp[1]))
	main.player.global_position = main._clear_spot(Vector3(sp[0], 0, sp[1]), Vector3(0, 0, -1), [8.0, -8.0, 12.0]) - main.world_offset + Vector3(0, 0.2, 0)
	await _frames(10)

func t_tr_graph() -> Array:
	await _tr_reset_to_spawn()
	var tr = main.traffic
	tr.rebuild_graph()
	var sig := 0
	for n in tr.ix: if tr.ix[n]["ctrl"] == "signal": sig += 1
	if tr.edges.size() < 300: return [false, "only %d lane edges" % tr.edges.size()]
	if sig < 5: return [false, "only %d signalised intersections downtown" % sig]
	return [true, "%d directed edges, %d nodes, %d controlled intersections (%d signals)" % [tr.edges.size(), tr.npos.size(), tr.ix.size(), sig]]

func t_tr_density() -> Array:
	var tod = main.tod; var keep: float = tod.total_hours
	tod.set_date("fall", 3, 3.0); var night: int = main.traffic.target_count()
	tod.set_date("fall", 3, 17.0); var rush: int = main.traffic.target_count()
	tod.total_hours = keep; tod.apply_now()
	if rush < 20 or night > rush * 0.3: return [false, "3 am %d cars vs 5 pm %d (road km near %.2f, edges %d, focus %s)" % [night, rush, main.traffic._road_km_near, main.traffic.edges.size(), main.focus_world().snapped(Vector3.ONE)]]
	return [true, "3 am %d cars, 5 pm %d cars" % [night, rush]]

func t_tr_move() -> Array:
	var tod = main.tod; var keep: float = tod.total_hours
	tod.set_date("fall", 3, 17.0)
	await _frames(360)   # 3 s
	var tr = main.traffic
	var n: int = tr.count()
	if n < 10: tod.total_hours = keep; return [false, "only %d cars after 3 s (want %d)" % [n, tr.target_count()]]
	if n > int(tr.T["budget"]["max_cars"]): tod.total_hours = keep; return [false, "%d cars exceeds budget" % n]
	var start := {}
	for c in tr.cars: start[c["node"]] = c["pos"]
	await _frames(1200)  # 10 s
	var moved := 0; var worst_lane := 0.0; var tot := 0.0; var m := 0
	for c in tr.cars:
		if not start.has(c["node"]): continue
		var d: float = (c["pos"] - start[c["node"]]).length()
		tot += d; m += 1
		if d > 10.0: moved += 1
		var lp: Vector3 = tr.lane_point(tr.edges[c["edge"]], c["s"], c["lane"])
		worst_lane = max(worst_lane, Vector2(c["pos"].x - lp.x, c["pos"].z - lp.z).length())
	tod.total_hours = keep; tod.apply_now()
	if m == 0: return [false, "all cars despawned"]
	if moved < m * 0.4: return [false, "only %d of %d cars moved more than 10 m in 10 s" % [moved, m]]
	if worst_lane > 3.0: return [false, "a car is %.1f m off its lane" % worst_lane]
	return [true, "%d cars, %d moved >10 m in 10 s (avg %.1f m/s), worst lane error %.1f m" % [n, moved, tot / m / 10.0, worst_lane]]

func t_tr_overlap() -> Array:
	var tr = main.traffic
	var worst := 1e9; var pair := ""
	for i in tr.cars.size():
		for j in range(i + 1, tr.cars.size()):
			var a: Dictionary = tr.cars[i]; var b: Dictionary = tr.cars[j]
			var d: float = (a["pos"] - b["pos"]).length()
			if d < worst: worst = d; pair = "%s/%s" % [a["type"], b["type"]]
	if worst < 2.2: return [false, "two cars %.1f m apart (%s)" % [worst, pair]]
	return [true, "closest pair %.1f m apart" % worst]

func t_tr_red() -> Array:
	var tr = main.traffic
	# find a signal approach long enough to test on
	var eid := -1
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		var near: float = (tr.npos[e["b"]] - main.focus_world()).length()
		if near < 160.0 and e["len"] > 28.0 and tr.ix.has(e["b"]) and tr.ix[e["b"]]["ctrl"] == "signal" and not tr._occupied(i, e["len"] * 0.5, e["len"]):
			eid = i; break
	if eid < 0: return [false, "no clear signal approach found"]
	var e2: Dictionary = tr.edges[eid]
	# wind the signal clock until this approach has just turned red
	var guard := 0
	while tr.signal_state(eid) != "stop" and guard < 2000: tr.time_s += 0.1; guard += 1
	var c: Dictionary = tr._spawn_on(eid, 1.0)
	c["v"] = 6.0
	var stop_at: float = e2["len"] - float(tr.T["driver"]["stop_line_m"])
	var crossed := false
	for f in 600:   # 5 s while red
		await get_tree().physics_frame
		if not tr.cars.has(c): return [false, "test car vanished"]
		if c["ea"] != e2["a"] or c["eb"] != e2["b"] or c["s"] > stop_at + 0.8: crossed = true; break
		if tr.signal_state(c["edge"]) != "stop": break
	if crossed: return [false, "car ran the red light"]
	return [true, "stopped %.1f m before the line, speed %.1f m/s" % [stop_at - c["s"], c["v"]]]

func t_tr_player() -> Array:
	var tr = main.traffic
	var eid := -1
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		var near: float = (tr.npos[e["b"]] - main.focus_world()).length()
		if near < 160.0 and e["len"] > 35.0 and not tr._occupied(i, e["len"] * 0.5, e["len"]) and e["cls"] >= 2 and e["cls"] <= 5:
			var g: Vector3 = main._ground_from(tr.lane_point(e, e["len"] - 4.0, 0), 30.0)
			if absf(g.y) < 1.0:   # street level (not a bridge over the river, where the player would fall in)
				eid = i; break
	if eid < 0: return [false, "no clear straight edge"]
	var e2: Dictionary = tr.edges[eid]
	var block: Vector3 = tr.lane_point(e2, e2["len"] - 4.0, 0)
	main.player.global_position = block - main.world_offset + Vector3(0, 0.5, 0)
	var c: Dictionary = tr._spawn_on(eid, max(1.0, e2["len"] - 50.0))
	c["lane"] = 0; c["v"] = 5.0
	for f in 1440:
		await get_tree().physics_frame   # 12 s
	main.player.global_position = block - main.world_offset + Vector3(0, 0.5, 0)
	if not tr.cars.has(c): return [false, "test car vanished"]
	if c["ea"] != e2["a"] or c["eb"] != e2["b"]: return [false, "car drove past the player onto the next road"]
	var gap: float = (e2["len"] - 4.0) - c["s"] - c["len"] * 0.5
	if gap < 0.5: return [false, "drove into the player (gap %.1f m)" % gap]
	if c["v"] > 0.5: return [false, "still moving at %.1f m/s next to the player" % c["v"]]
	return [true, "stopped %.1f m short of the player" % gap]

# ------------------------------------------------------------------ pedestrians
func t_pd_density() -> Array:
	var tod = main.tod; var keep: float = tod.total_hours
	tod.set_date("fall", 3, 3.0); var night: int = main.peds.target_count()
	tod.set_date("fall", 3, 12.5); var noon: int = main.peds.target_count()
	tod.total_hours = keep; tod.apply_now()
	if noon < 30 or night > noon * 0.25: return [false, "3 am %d people vs 12:30 pm %d" % [night, noon]]
	return [true, "3 am %d people, 12:30 pm %d" % [night, noon]]

## Distance from a world point to the nearest drivable road surface (negative = inside the carriageway).
var _worst_info := ""
var _near_edge := ""
func _off_road(q: Vector3) -> float:
	var tr = main.traffic
	var best := 1e9
	for e in tr.edges:
		var a: Vector3 = tr.npos[e["a"]]; var b: Vector3 = tr.npos[e["b"]]
		if (a - q).length() > 200.0 and (b - q).length() > 200.0: continue
		var cp := Geometry3D.get_closest_point_to_segment(Vector3(q.x, 0, q.z), a, b)
		var dd := Vector2(cp.x - q.x, cp.z - q.z).length() - float(e.get("w", 8.0)) * 0.5
		if dd < best: _near_edge = "edge %s-%s w %.1f cls %s" % [e["a"], e["b"], float(e.get("w", 8.0)), e.get("cls", e.get("class", "?"))]
		best = min(best, dd)
	return best

func t_pd_walk() -> Array:
	var tod = main.tod; var keep: float = tod.total_hours
	tod.set_date("fall", 3, 12.5)
	await _frames(360)
	var pd = main.peds
	var n: int = pd.count()
	if n < 20: tod.total_hours = keep; return [false, "only %d people after 3 s (want %d)" % [n, pd.target_count()]]
	if n > int(pd.P["budget"]["max_peds"]) + 8: tod.total_hours = keep; return [false, "%d people exceeds budget" % n]
	var start := {}
	for p in pd.peds: start[p["node"]] = p["pos"]
	var in_road := 0; var worst := 1e9
	for f in 8:
		await _frames(150)
		for p in pd.peds:
			if p["state"] == "cross": continue
			var d := _off_road(p["pos"])
			if d < worst: _worst_info = "at %s state %s near %s; ped edge %s" % [p["pos"].snapped(Vector3.ONE * 0.1), p.get("state", ""), _near_edge, [p.get("ea"), p.get("eb"), p.get("edge")]]
			worst = min(worst, d)
			if d < -0.3: in_road += 1
	var moved := 0; var m := 0
	for p in pd.peds:
		if start.has(p["node"]):
			m += 1
			if (p["pos"] - start[p["node"]]).length() > 5.0: moved += 1
	tod.total_hours = keep; tod.apply_now()
	if moved < m * 0.5: return [false, "only %d of %d people walked more than 5 m in 10 s" % [moved, m]]
	if in_road > 0: return [false, "%d samples of people walking in the road (worst %.1f m inside %s)" % [in_road, -worst, _worst_info]]
	return [true, "%d people, %d of %d walked >5 m in 10 s, closest to traffic %.1f m from the curb" % [n, moved, m, worst]]

func t_pd_cross() -> Array:
	var pd = main.peds; var tr = main.traffic
	var c0: int = pd.crossings_started
	var bad := 0; var seen := 0
	for f in 40:
		await _frames(120)
		if f >= 20 and pd.crossings_started - c0 >= 2: break
		for p in pd.peds:
			if p["state"] != "cross": continue
			seen += 1
			var n: int = p["cross"][3]
			if pd.node_walk.get(n, []).size() < 3 and not tr.ix.has(n): bad += 1
	var started: int = pd.crossings_started - c0
	if started == 0: return [false, "nobody crossed a street in 40 s"]
	return [true, "%d crossings started, all at intersections" % started] if bad == 0 else [false, "%d crossings away from intersections" % bad]
	if bad > 0: return [false, "%d crossings away from intersections" % bad]
	return [true, "%d crossings started in 20 s, all at intersections" % started]

func t_pd_car_stops() -> Array:
	var tr = main.traffic; var pd = main.peds
	var eid := -1
	for i in tr.edges.size():
		var e: Dictionary = tr.edges[i]
		var near: float = (tr.npos[e["b"]] - main.focus_world()).length()
		if near < 160.0 and e["len"] > 40.0 and e["cls"] >= 2 and e["cls"] <= 5 and not tr._occupied(i, e["len"] * 0.5, e["len"]):
			eid = i; break
	if eid < 0: return [false, "no clear edge"]
	var e2: Dictionary = tr.edges[eid]
	# a person standing in the crosswalk in the car's lane
	var p: Dictionary = pd._spawn(pd.walk_edges[0], 0.0, 1)
	var spot: Vector3 = tr.lane_point(e2, e2["len"] - 5.0, 0)
	p["state"] = "cross"; p["cross"] = [spot, spot, eid, e2["b"]]; p["pos"] = spot
	var c: Dictionary = tr._spawn_on(eid, max(1.0, e2["len"] - 40.0))
	c["lane"] = 0; c["v"] = 5.0
	for f in 1080:
		await get_tree().physics_frame
		p["state"] = "cross"; p["pos"] = spot; p["cross"] = [spot, spot, eid, e2["b"]]
	var ok: bool = tr.cars.has(c) and c["ea"] == e2["a"] and c["eb"] == e2["b"]
	var gap: float = (e2["len"] - 5.0) - c["s"] - c["len"] * 0.5
	pd._despawn(p)
	if not ok: return [false, "car drove through the crosswalk"]
	if gap < 0.5 or c["v"] > 0.5: return [false, "car gap %.1f m, speed %.1f m/s" % [gap, c["v"]]]
	return [true, "car stopped %.1f m before the person" % gap]

func t_pd_umbrella() -> Array:
	var w = main.weather; var pd = main.peds; var tod = main.tod
	var keep: float = tod.total_hours; var ks: String = w.state
	tod.set_date("fall", 3, 12.5)
	w.set_state("rain"); w.snap()
	await _frames(240)
	var up := 0
	for p in pd.peds: if p["umbrella"] > 0.9: up += 1
	w.set_state("clear"); w.snap()
	await _frames(240)
	var dry := 0
	for p in pd.peds: if p["umbrella"] > 0.1: dry += 1
	w.set_state(ks); w.snap(); tod.total_hours = keep; tod.apply_now()
	if pd.count() == 0: return [false, "no people"]
	if up < pd.count() * 0.25: return [false, "only %d of %d umbrellas up in the rain" % [up, pd.count()]]
	if dry > 0: return [false, "%d umbrellas still up when dry" % dry]
	return [true, "%d of %d umbrellas up in rain, all down after" % [up, pd.count()]]

