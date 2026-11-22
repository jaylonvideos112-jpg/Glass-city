# Changelog

## Lived-in windows (2026-11-21)
* Every house pane paints its own curtains, blinds or sheet and a parallax room behind; lit rooms at night
  (`shaders/window_interior.gdshader`). Own character system started (`tools/blender/glasshuman/`), then paused.
* Wooden utility poles (3 variants) with sagging overhead wires along alleys and alley-less residential streets.
* Road wear (patches, cracks, tar snakes, oil), manholes and storm drains. East Toledo chunks rebuilt.
* Back-yard fences (chain-link / wood, instanced panels) and Toledo-style trash and clutter: 30 models, 5 per kind of
  place (litter, residential bulk, alley, business, parking, industrial) on gutters, sidewalks, grass strips, paths, lots.
* Sidewalk wear (cracks, weeds, gum, dirt) and lived-in cars (grime, faded beaters with rust).
* `source_data/toledo_fleet.json`: estimated top-200 vehicles on Toledo roads (model + generation, body family, share).
* 20-minute work backups (`tools/backup.py`).

## Bully look and 3D grass (2026-11-21)
* Art direction is now "4K upscaled Bully" on modern geometry: hand-painted texture set (`textures_bully/`,
  `make_bully_textures.py`), `scripts/look.gd` switch (`source_data/look.json`, `--look=classic`), warm soft lighting.
* **3D grass** (`scripts/grass.gd`, `shaders/grass.gdshader`): instanced blade clumps on every lawn within 46 m,
  wind sway, distance fade, snow. Test `grass_grows_on_lawns`.
* Character creator (MPFB2): photo face fitting, stylized mode; EASTGATE theater marquee; README is the complete brief.

## Smartphone (2026-11-15)
* **Phone (`scripts/phone.gd`):** Tab opens it; arrows move, Enter opens, Backspace goes back. Apps:
  * **Maps** - a map of the whole island (`textures/phone_map.png` from `make_phone_map.py`), 13 categories of
    places (my places, food, groceries, bars, ATMs, jobs, dealers, auto shops, gyms & bowling, ballparks & cinemas,
    fishing, homes for rent, police & hospitals), nearest first; Enter sets the **GPS**: purple route along the roads
    on the radar, distance in miles, a light beam at the destination, "You've arrived".
  * **GlassPay** balance, cash and recent transactions · **Jobs** apply/quit from the phone · **Messages** - every
    on-screen notice is kept here · **Contacts** - Mike's Towing brings your car to you ($150), boss, landlord, transit,
    Mom · **My Stuff** cars (GPS to them), businesses, home · **News** - the Glass City Gazette, headlines from the
    weather, Swamp Hens, police and economy · **Profile** - needs, stats, fish log · **Camera** - photo mode: zoom
    (Z/X or wheel), filters (normal, black & white, warm, vivid), Space saves a PNG to `user://photos` ·
    **Settings** - wallpaper.
* Saved as section `phone`. 1 new test. Fixed a crash when quitting while far-city meshes were still building.

## Needs, inventory, activities (2026-11-15)
* **Needs (`scripts/needs.gd`, `source_data/life.json`):** health and stamina (the Bible's only formal attributes),
  hunger and fitness. Hunger empties over ~30 game hours (starving slowly costs health); sprinting uses stamina; max
  stamina and sprint speed grow with fitness; fitness rises with the gym and running and fades slowly. Weight moves
  each day with calories eaten vs burned (shown in lb; a simulation, not a body ideal). HUD line under the job line.
* **Inventory (`scripts/inventory.gd`):** weapons / food / misc, no weight limits. I opens it; numbers eat food.
* **Activities (`scripts/activities.gd`, places in `source_data/activities.json` from `make_activities.py`),
  T at each place:** eat at restaurants and fast food; buy groceries (3 home meals + a snack) and cook at home;
  gyms (17) - an hour's workout; bowling alleys (9) - a 10-frame game with a timing meter (Space); ballparks (42) -
  watch the Glass City Swamp Hens (minor-league baseball, evenings on game days); cinemas (4) - a movie; fishing
  (20 spots on the river and creeks) - cast, wait for the bite, Space; 7 local species, biggest catches logged,
  fish can be cooked at home.
* 2 new tests (50 game tests + 9 data tests in all).

## Vehicles: roster, ownership, dealers, stealing, damage, shops, camera views (2026-11-15)
* **Roster (`source_data/vehicles.json`):** 18 made-up models from 10 made-up makes (Halden, Corvane, Takumi, Hanzo,
  Overmark - "built in Glass City", Bulward, Kessler, Strato, Pellam, Freightline), each with size, body shape,
  price and performance. AI traffic is built from it, weighted like real Toledo traffic (about 86 % ordinary sedans,
  SUVs, pickups, compacts and minivans; under 3 % sports/luxury/exotic). The old placeholder names borrowed from GTA
  (Vapid, Declasse, Karin, Bravado, Albany, Grotti, Brute) are gone.
* **Your cars (`scripts/vehicles.gd`):** you start owning a beat-up Corvane Dutchess; the other cars at the start are
  other people's. Owned cars are saved (model, paint, damage, upgrades, where you left them or in the garage).
* **Buying:** 41 dealerships from the map (25 new-car dealers, 16 used lots, made-up names). K at the sign shows the
  cars, 1-9 buys; used lots sell 6 cars a day at 40-70 % of new in worse condition. The car waits at the curb.
* **Stealing:** E next to a stopped or slow AI car takes it (1 star if seen; 2 for a police car); unowned parked cars
  too. Stolen cars show STOLEN on the HUD; drive one into your garage (G) and it's yours.
* **Damage:** hard hits lower the car's health; a damaged car loses power and top speed and smokes below 35 %; at 0
  the engine dies. Health shows next to the speed.
* **Auto shops** (the 48 auto-shop workplaces): P repair (4 % of the car's price per 100 % damage), C respray $250,
  U upgrade engine/brakes/suspension (3 levels each).
* **Camera views:** V cycles chase, far chase, hood, bumper, cockpit (no modelled interior yet).
* Car physics now follow each model's size, mass, power, grip and steering. 4 new tests; `@roster` screenshot.

## Jobs, businesses, homes (2026-11-15)
* **Jobs (`scripts/jobs.gd`, `source_data/jobs.json`):** 11 basic jobs (stocker, cashier, attendant, crew member,
  server, sales associate, mechanic helper, delivery driver, warehouse worker, line worker...) at 706 real workplaces
  with made-up names (`source_data/workplaces.json` from `make_workplaces.py`). Apply in person at the "Now hiring"
  sign (E) or on the phone job board (J, then 1-6; 0 quits). Clock in with E at the sign during your shift. On shift
  you earn the hourly rate near work plus a bonus per task: a yellow beam marks the spot (restock, move a load, take
  an order, serve a customer, or drive a parcel 300-900 m away). Paycheck to your wallet at the end of the shift;
  missing a shift by an hour is a strike, 2 strikes = fired. HUD line under the stars. No construction sites in the
  map data yet.
* **Businesses (`scripts/business.gd`, `source_data/business.json`):** buy any of those workplaces at its sign (B).
  Price from kind, size and location (downtown +35 %); about 2 %/day income, +/-25 %. Auto-deposit to the wallet, or
  turn it off (N) and collect in person (B).
* **Homes (`scripts/homes.gd`, `source_data/homes.json` from `make_homes.py`):** 220 real houses/apartments with
  made-up addresses and For Rent / For Sale signs. R rents (charged every 7 game days; can't pay = evicted), B buys.
  At your home: E sleeps until 8 AM and saves; G stores the car next to you in the garage or takes it out.
* Saved sections `job`, `business`, `home`. 3 new tests. Sirens drive past cars that have pulled over; pedestrians
  only wait for moving cars on the street they're crossing; steadier service/police tests.

## Police: traffic stops, closing in, helicopter (2026-11-15)
* **Traffic stops:** a patrol car that sees you more than 15 mph over the limit, or running a red light, lights up
  and follows you ("Police: pull over!"). Stop within 30 m for 3 s; the officer checks your license (4 s), then it's a
  warning (30 %) or a ticket paid from your money: speeding $75 + $6 per mph beyond 10 over, red light $150. Drive
  off (130 m away, or not stopped in 25 s, or leaving mid-check) = 1 star for failure to stop, and that car chases you.
  1 minute cooldown between stops. During a chase a red light still adds a star.
* **Closing in:** units within 50 m of you that can see you leave the road and drive straight at you, stopping
  about 6 m away; they rejoin the roads when the chase ends or you get 90 m away (`traffic.gd` free-driving mode).
* **Helicopter** at 4+ stars: circles you (or where you were last seen) at 55 m, sees you from 130 m, so it's harder
  to lose; searchlight at night.
* Settings in `police.json` (`traffic_stop`, `helicopter`, `approach_*`). 2 new tests. Far-city worker threads no
  longer touch the streamer node (a shutdown crash).

## Money and wanted level (2026-11-15)
* **Money (`scripts/money.gd`, `source_data/economy.json`):** cash plus a digital wallet in a made-up payment app
  (placeholder name "GlassPay"). You start with $120 cash and $400 in the app. Paying takes cash first, then the app.
  72 ATMs, one outside every bank (made-up bank names, `source_data/atms.json` from `make_atms.py`):
  E withdraws $100, R deposits all your cash. Drinks at the bar counter cost $7. Saved (section `money`). HUD top-left.
* **Wanted level (`scripts/police.gd`, `source_data/police.json`):** hitting a car (1 star), hitting a person (2),
  ramming a police car (2), running a red light in front of police (1). It counts if police see it or a bystander
  reports it. Police units (stars, +1 from 3 stars) come with sirens, re-routing to where you were last seen. Stay out
  of sight 12 s + 5 s per star and you lose them (stars blink while they search). If a unit stops next to you while
  you're stopped: busted - one night in jail (Bible), released 8 am outside the nearest police station, fined $150
  per star. Your car now physically bumps AI cars. Police/fire/hospital locations in `source_data/stations.json`.
* `@chase` screenshot shot. 2 new tests.

## NPC schedules and stats saves (2026-11-15)
* **NPC schedules (Bible stage 3), `source_data/npc_schedules.json`:** pedestrians have roles (worker, student,
  shopper, resident, night owl), each with an hourly routine per area type (downtown, near bars, residential) and
  goals by hour (head downtown, home, to the nearest bar, or wander). How many people are out, and who, now follows
  those routines; walkers steer toward their goal at corners and cross the street when it's on the other side.
* **Stats (`scripts/stats.gd`), saved as world-state section `stats`:** distance walked and driven, top speed,
  days played, bars visited, emergencies seen. Time tests now restore only the clock section.
* Traffic doesn't cap itself before the road graph is measured (a flaky start-up case).

## Public services (Bible stage 3) (2026-11-15)
* **Buses:** 12 Glass City Transit routes from downtown to each town (`source_data/bus_routes.json`, made by
  `tools/pipeline/make_bus_routes.py` because the real route data couldn't be downloaded). Buses follow their route,
  obey one-way streets, stop about every 350 m for 7 s; stops get blue sign posts. Up to 4 buses near you.
* **Emergencies (`scripts/services.gd`):** every 1-3 minutes an incident happens near you and a police car, ambulance
  (new) or fire engine (new) drives there on the shortest route with flashing lights and a siren, through red lights
  at reduced speed, stays 30 s on scene, then rejoins traffic. Cars ahead pull right and slow down. HUD notice.
* Siren sound added to the procedural audio. Pedestrians may cross past a bus waiting at its stop.
* Chase-cam screenshots: `@bus` / `@responder` shot names. 2 new tests.

## Rough edges (2026-11-15)
* Traffic count now scales with how much road is near you (`traffic.json` `budget.cars_per_road_km`), so a lone
  country road no longer gets every car in the budget (it jammed).
* Far city has its own shader (`shaders/hlod.gdshader`): lit windows at night (window grid by floor and bay,
  occupancy by hour, like the near facades), slightly brighter to match the detailed materials, and guards against
  zero normals in merged meshes (they made coloured speckles).
* `--hour=H` for demo/screenshot runs.

## Performance, countryside, data, driving feel, audio, world state (2026-11-15)
* **Far city (HLOD), `scripts/hlod.gd`:** past the detailed streets the city is drawn as one merged low-detail mesh per
  400 m region (no porches, curbs, lines or shadows; ground coloured from the aerial photos), out to 3.2 km. Detail
  now loads whole regions so near and far never overlap. Benchmark peak draw calls **4,699 -> 2,711** (budget 3,000),
  peak loaded chunks 455 -> 116, and the skyline is visible from anywhere instead of ending at 650 m. `--no-hlod` turns it off.
* **Countryside:** crop fields (wheat, corn, soy, hay, plowed; new crop-row texture `textures/field.png`) fill the
  made-up land; farms are about twice as dense (about 1,180).
* **Map data:** aerial photos for every real-area chunk (16,000 new); LiDAR building heights and county records re-run
  over all real tiles.
* **Slippery roads:** wet roads cut tyre grip about 28 %, snow about 55 % (`climate.json` `surface.grip`); AI traffic
  drives slower on them.
* **Audio, `scripts/audio.gd`:** procedural (no sound files): engine with a 6-gear rpm model and wet-tyre hiss, rain,
  gusty wind, distant city hum, thunder after lightning. Levels in `source_data/audio.json`; `--mute`.
* **World state (Bible stage 3), `scripts/world_state.gd`:** one versioned save file with sections that any system
  registers (`clock`, `player`). Autosaves every 2 minutes and on quit; the game resumes where you left off
  (`--new-game` to start fresh). Old saves migrate.
* Pedestrians no longer walk a sidewalk that would overlap another road running alongside (found once more of the
  map loads at a time).
* 4 new game tests (grip, audio, far city, world state); `--only=name` runs a subset. 38 game + 9 data tests pass.

## Island countryside and town names (2026-11-15)
* The island is now real data in the middle and made-up countryside around it: about 690 farmsteads (house, barn,
  some silos, driveways), 160 woodlots, 4 villages, 101 real roads continued outward and a 166 km coast road.
* Real data is clipped to the real box (roads split at the edge so made-up roads join the traffic graph).
* New parody town names (Glass City, Pinewick, Kingsferry, ...) and river/lake names (Stone Ridge River, Northfork River,
  Mallard Creek, Lake Glassmere), from `source_data/place_names.json`.
* Build box grown to the whole island (`tools/build.sh`); all real tiles are staged in `osm/city_all`.
* Known limits: no aerial imagery or LiDAR for the made-up land yet (plain green ground); fields are not drawn.

## v0.5 (in progress), Step 3a: time of day and weather
* **Clock and calendar:** 1 real hour per game day (decision log 2026-11-14); 4 seasons × 12 days, weekdays, years.
  HUD shows time, date and weather. F6 = time ×60.
* **Sun path:** computed from Toledo's latitude and the season (DST honoured), so a June sunset is around 9:10 pm and a
  December one about 5:10 pm. A moonlight takes over at night.
* **Sky:** night, dusk and day palettes; a cloud layer that thickens with the weather; golden-hour colours.
* **Night lighting:** lit windows on every textured building (emission masks made by `make_textures.py`) and on
  facade-shader buildings (per-room warm and cool light, occupancy by hour), plus glowing street lamps.
* **Weather:** clear, partly cloudy, overcast, rain, thunderstorm (with lightning), fog and snow; spells follow
  per-season odds from `source_data/climate.json`; rain and snow particles; looks blend over about 45 game minutes.
  F7 cycles the weather.
* **Persistence:** time and weather are saved on quit (`user://world_state.json`).
* 6 new in-game tests and 1 new data test (23 total).
* **Street lamps:** about 4× more downtown (the map builder had been dropping every lamp that stood on a sidewalk);
  each casts a warm pool of light, and the 24 nearest the camera give off real light.
* **Car lights:** headlights at night or in dark weather (real spotlights on the driven car); tail lights brighten
  when braking.
* **Wet and snowy ground:** rain darkens roads and makes them glossy (lamp light reflects), then they dry over a few
  hours. Snow builds on flat ground and roofs, roads stay clearer than sidewalks (plowed), it melts by season, and
  melting leaves slush.
* **Traffic (step 3b part 1):**
  * The pipeline exports the drivable road network per chunk (segments with OSM node ids, road class, lanes,
    one-way, speed limit) and 11,030 intersection controls.
  * Controls are inferred from road classes: signals where major roads meet, stop signs on side streets,
    all-way stops on 4-way residential corners. Real OSM signal data replaces this automatically once
    `osm/extra/signals.json` downloads (Overpass was overloaded).
  * Up to 60 cars around the player (`source_data/traffic.json`), with density by hour, weekend and weather.
    The mix is ordinary Toledo traffic (sedans, SUVs, pickups, minivans, vans, box trucks, transit buses, rare
    sports cars and police cruisers; fictional makers).
  * Cars keep their lane, follow at safe gaps (Intelligent Driver Model), slow for turns, stop at red lights and
    stop signs, yield, drive slower in rain and snow, and stop for the player and the player's cars.
  * Headlights and tail lights glow at night. Cars are one draw call each plus their lights.
  * 6 traffic tests.
* **Pedestrians (step 3b part 2):**
  * Up to 80 people walk the real sidewalks (road widths now exported per segment). They turn at the
    corners and never walk down the median of a divided road.
  * They cross only at intersections: on the walk phase at signals, otherwise when no car is close. Cars
    stop for anyone in the crosswalk.
  * 32 procedural people (skin tones, clothes, heights, builds, some in dresses), with walk cycles animated
    in the shader (one draw call each). About half put up umbrellas in the rain.
  * Density by hour, weekday, weather and area (downtown vs. elsewhere); `source_data/pedestrians.json`.
  * 5 pedestrian tests.
* **Names:** all 184 schools in the full region have fictional names (`source_data/school_names.json`); University of
  Toledo is the University of Glass City. Every street has a parody name (`source_data/street_names.json`, 4,416
  names); numbered streets and routes keep their numbers.
* Test harness now fails a test that crashes instead of silently skipping it.
* Fix: window emission masks lit whole walls (Godot's emission ADD operator); now MULTIPLY.

## v0.4 (in progress), Stage 0 foundation + realistic city
### Foundation (Bible stage 0)
* Project renamed **GLASS CITY**; development bible v1.0 added under `docs/`.
* Git repository; generated data kept out of git; pipeline scripts and hand-authored data moved into the repo
  (`tools/pipeline/`, `source_data/`).
* `tools/build.sh` (one-command city rebuild), `tools/run_tests.sh` / `.bat` (all tests),
  `tools/run_benchmark.bat`.
* Automated tests: 9 in-game tests and 7 data tests.
* F3 performance overlay and `--benchmark` mode with JSON report; budgets in `docs/PERF_BUDGETS.md`.
* Docs: architecture, build, coding standards, data sources and licence register, performance budgets.
### City
* Whole map rebuilt on Lucas County footprints (132k) with county records: era- and material-correct house
  siding/brick, porches, garages, roof shapes; apartments, offices, hotels, churches and schools styled by record.
* Downtown: exact LiDAR massing for 670 buildings (0.5 m grid) with squared-up outlines; hand overrides with sources
  (One SeaGate tower, DiSalle, Four SeaGate, ProMedica Senior Care, Hotel SeaGate removed, Secor carved out of the
  convention centre).
* Facade shader: parametric windows, brick/stone coursing (with distance fade), storefronts and curtain walls;
  25 buildings matched to photos or published facts; era brick palettes; Italianate arched windows on pre-1900 brick.
### Bars
* 48 bars, 15 brands: neon signs, awnings and doors on the street; an enterable themed interior per brand (E to enter/leave).
### Fixes
* Leaving a bar after the world had re-centred put the player in the wrong place. Fixed: the return point is now
  stored in world coordinates (covered by test `bar_exit_after_origin_rebase`).
* Standart Lofts facade had been put on the wrong building (now 34 S Erie).

## v0.3: real-looking Toledo
LiDAR heights and roofs, landmarks, Anthony Wayne Bridge and Skyway, ballparks, aerial imagery, parody sign names.

## v0.2: whole city
## v0.1: downtown prototype

## Polish pass 3
- Player is visible in the driver's seat (legless seated body) through tinted see-through windows on drivable cars.
- Bowling has a graphical aim meter (red / yellow / green sweet spot) instead of a text bar.
- Inter is the project-wide UI font.

## Overhaul (playtest feedback)
- Ground: no more aerial-photo smears. Lots use the blurred photo only to decide lawn vs paving; new grass and concrete-slab textures.
- Your starting cars park in the curb lane of the real street, with a clear run ahead of your own car.
- GPS: proper A* routing (one-way streets ignored on foot); the route starts at you and ends at the place.
- Place signs sit just past the curb and their text shrinks to fit.
- Phone: portrait phone in the bottom-right (money and stars stay visible), status bar, app-icon home grid with a message badge, coloured app headers and card lists.
- Street furniture beside lamps: hydrants, trash cans, benches, news boxes, mailboxes.
- Building windows are glossy and pick up the sky; no more yellow "spreadsheet" squares by day. Downtown towers get storefront ground floors (city rebuilt).
- Denser traffic (90 cars max, 26 per road km).
- People: rounded torso and shoulders, idle breathing / weight shift / arm sway, soft rim light.
- Night: brighter sky and ambient, stronger moon and street lamps, a soft fill light on the player.
- Police: spawn closer (60-200 m), more units from 2 stars, faster dispatch.
- Minimap: a live top-down picture of the city (roofs, lawns, water, trees) under the road lines.

## Polish pass 4
- Emergency vehicles: glowing red/blue light bars that alternate (readable by day).
- Faces: eye whites, irises and pupils, eyelids, ears, lips; hands with thumbs.
- Title screen: clear air for the skyline (less haze); repeated notices refresh instead of stacking.
- Minimap picture refreshes twice a second (cheaper).
- Fishing: rod, line and bobber, plus a bite widget (only at fishing spots).

## Core mechanics pass
- Driving retuned from measurements (new feel probe test): family sedan 0-60 mph ~5-6 s, 60-0 braking ~25-30 m,
  stays on its wheels in a 60 mph swerve. Teleports/tows/rebases no longer register as crashes.
- Injury and death: hard landings, being hit by traffic, big crashes and bailing out of a moving car hurt you; red
  damage flash and a low-health pulse. At 0 health: WASTED, wake at the nearest hospital (bill, 6 hours gone,
  wanted level cleared). Falling in the river costs health instead of a fake "wasted".
- Getting out of a car picks a free spot (driver side, passenger side, front/back, or over the roof).
- Camera collision ignores passing traffic (no more camera jumps).
- F gets in and out of cars; E is only for using things (no more applying for a job when you meant to get in your car).
- Pedestrians hit by a car are knocked down (thrown, land, lie there) and get up and run, or stay injured and an
  ambulance is sent; people nearby scatter. Police still log it as a crime.

## Hand-to-hand combat (Bible section 14)
- Left click punch (tap for jab-cross-hook combos), right click kick, hold Q to guard (blocks ~80%), Ctrl to dodge.
- Auto lock-on to the nearest person in front; you turn to face them; red marker + their health over their head.
- People have health; hits make them flinch, heavy hits can floor them, at 0 they go down (get up later and run).
- Some fight back (step in, guard up, throw punches that hurt you), the rest run; bystanders scatter.
- A witnessed assault is a crime (1 star). Punches cost stamina; tired fighters swing slower.
- Poses come from the people shader (punch, kick, guard, flinch). Street furniture no longer renders inside-out.

## Advanced fighting AI
- Fighter styles (life.json-overridable): boxer, brawler, kicker, grappler, dirty - each with its own move mix,
  speed, guard, slip rate and nerve.
- Telegraphed moves: jab, hook (staggers), front kick (pushes back), leg sweep (puts you down), shove, tackle
  (lunges from ~3.5 m, takes you down and PINS you - mash Space to break free while they rain ground punches),
  stomp / ground punches when you're down.
- Opponents circle and keep range, block or slip when they see you wind up, counter after a block, and only two
  press you at a time while friends who joined circle. Beaten with low nerve they run or put their hands up.
- They adapt to how you fight: turtle behind your guard and they grab and shove; spam punches and they block and
  counter; dodge a lot and they sweep.
- You: tap Q right before a hit to PARRY (they stagger, your next hit x1.5), Z / middle click to tackle someone,
  ground punches on a downed opponent, Space to get up faster. Tackled opponents get up swinging.
- HUD: struggle meter when pinned, knockdown prompt.

## Weapons (Bible section 14)
- source_data/weapons.json: bat, knife, pistol, pump shotgun, carbine rifle, grenades; ammo types; 8 gun stores
  (E at the sign: buy guns and ammo with number keys).
- 1-6 select fists / melee / pistol / shotgun / rifle / grenades. Hold right mouse to aim (over-the-shoulder camera,
  crosshair, soft lock-on near the crosshair), left mouse to fire (rifle is automatic), R reload (auto when empty),
  C crouch. Hip fire spreads wide; moving spreads more; crouching tightens it. Headshots x2.5.
- Hitscan through the crosshair: people (capsule test), your cars (damage), the city (impacts); tracers, muzzle
  flash, procedural gunshot and explosion sounds, hit markers. Grenades arc, bounce and blow after a fuse
  (knock people and cars around, hurt you if you're close).
- People shot go down injured (ambulance comes); gunfire makes everyone nearby run; melee weapons swing through
  the fighting system with more damage and reach.
- Police: gunfire, shooting people or officers, explosions are serious crimes; a burst of fire is one incident.
  At 3+ stars (2 if you're armed) officers leave their cars armed (rifles at 5 stars) and fight on foot: they keep
  distance, strafe, aim (telegraphed), fire bursts, need a clear line to your chest (cars and walls are cover,
  crouching helps), move up when they lose sight of you. Some dirty fighters carry a pistol.

## GTA V-style gunplay and gun stores
- Controls now follow GTA V: Tab (hold) weapon wheel - time slows, move the mouse to pick, release; Up arrow
  takes the phone out (Backspace puts it away).
- Q snaps into cover against the wall or car in front (back to it, crouched behind low cover, slide along it,
  push away to leave). Aiming from low cover pops you up; firing without aiming is blind fire (wild).
- Right mouse hard-locks onto the person in front (hostiles first); the camera tracks them, nudge the mouse to
  fine-aim (go for the head), flick it to switch targets. Red lock marker.
- Recoil climbs the muzzle and kicks the camera; screen shake from firing and blasts; muzzle flash sprite;
  bullet holes on walls (decals); armed people drop their gun when they go down - walk over it to pick it up.
- Walk-in gun stores: shop floor with a glass counter, wall racks and a clerk. At the counter: GTA-style menu
  (categories, weapon on a turntable, stat bars, prices), ammo, attachments (scope = tighter + zoom, extended
  magazine, suppressor = quiet: no flash, people/police barely hear, grip = less recoil/spread, flashlight at
  night) and finishes (black, olive, tan, steel, gold, pink) shown on the gun.

## Own look for weapons and the gun store
- Weapon models with real proportions (scripts/gun_models.gd): slides, angled grips, trigger guards, sights, rails,
  barrels, pump forends, curved magazines, tapered stocks, a turned bat, a clip-point knife, grenade spoon and pin;
  attachments and finishes show on them; merged per material.
- Gun store interior redesigned as a Glass City armory in an old brick warehouse: photo brick and polished
  concrete, steel columns, exposed ducts and pendant lamps, a dark slatwall of long guns lit by cool LED strips, a
  backlit pistol cabinet, a walnut-and-glass counter, a window onto the shooting lanes, the store name in neon.
- Store menu in its own style: smoked-glass panels with an ice-blue accent, breadcrumb pills, segmented stat bars
  with your current gun as a comparison tick, weapon card, keycap hints; the gun turns on a lit display disc.
- Weapon wheel redrawn: a segmented glass ring with weapon silhouettes, ice-blue selection, the world dims.

## Blender model pass 1: street props, street lights, cars, weapons
- New Blender pipeline (bpy 5.0 as a Python module, `tools/blender/`): scripts build or convert models and export
  `.glb` into `assets/models/`; `scripts/model_lib.gd` loads a .glb into one ArrayMesh for MultiMesh/instance use.
- Street furniture: real CC0 photoscans (Poly Haven fire hydrant, metal trash can) decimated to ~2k tris in Blender
  (`decimate_scan.py`), plus Blender-modelled USPS-style mailbox, newspaper box and park bench (`street_props.py`).
- Street lights: modelled cobra-head light (tapered pole, swept arm, head, glass bowl bound to the day/night lamp material).
- Cars: `cars.py` generates every body type (sedan, coupe, sports, hatch, wagon, SUV, pickup, van, box truck, bus):
  lofted sections -> subdivision with creased shoulder/roof lines -> side-only wheel-arch booleans -> glass/trim/paint
  by region -> raycast-placed head/tail lights with housings, grille, bumpers, plates, mirrors, handles, door seams.
  `traffic.vehicle_mesh` scales the body to each roster size and re-codes it into the car-paint vertex conventions;
  police get white door panels. Wheels stay the game's own (now on every modelled body).
- Weapons: `guns.py` models pistol, shotgun, carbine, bat, knife, grenade and every attachment per weapon;
  `GunModels.build` uses them (finish colours still apply), old code is the fallback.

## Blender model pass 2: realistic people
- `tools/blender/people.py` builds 8 body variants (male/female x three ancestries + a heavier build) from the
  MakeHuman CC0 base mesh and targets (`tools/blender/mh/`, see SOURCE.md): arms reposed from the A-pose with the
  real rig's skin weights, elbows relaxed, stature normalised, decimated with the face kept dense (~4.5k tris body).
- Every vertex is tagged for `pedestrian.gdshader`: UV2 = part + blend weight (smooth hips/shoulders), UV = knee /
  elbow bend weight and joint height. The shader now bends knees through the stride and elbows at rest, in guards
  and when running, and rotates normals with the limbs.
- Faces carry regions (head, scalp, jaw, lips, neck, chest, hips, arms, hands, legs, feet). `humans.gd` dresses each
  person from their look: skin regions, a separate softened garment shell for clothes (tee / long sleeves / open
  jacket over a shirt, jeans / shorts / dress with the base mesh's skirt), beard on the jaw, hair or cap on the
  scalp (+ long-hair drape, bun, cap brim), real eyes (white/iris/pupil), brows and sneaker shells with soles.
  One draw call per person as before; the old code-built person is the fallback.

## Sky with substance
- `shaders/sky.gdshader` replaces the procedural gradient sky: deeper saturated zenith over a bright hazy horizon,
  warm forward-scatter glow around the sun and a dusk band toward it, limb-darkened sun disc; drifting cumulus with
  puffy relief (density read as a height map and lit by the sun), self-shadowing toward the sun, grey bellies,
  silver linings and aerial perspective into the horizon; high cirrus streaks; an overcast stratus sheet for bad
  weather; stars, moon and dark night clouds lit from below by the city glow.
- `time_of_day.gd` drives it from the climate palette and weather (fair-weather cumulus even on "clear" days, more
  cover, overcast and storm-dark bases as weather worsens). The sky's lighting probe updates incrementally with a
  cheap cloud pass. Demo shot `@sky` frames the sky over the street.

## Real-building replicas (Blender, one by one)
- Pipeline: `source_data/replicas.json` (candidates: every Toledo building with a Wikidata link in OSM + the
  downtown landmarks) -> `fetch_refs.py` / `fetch_named.py` (reference photos from Wikimedia Commons, reference
  only) -> `replica_massing.py` (exact LiDAR footprint/tiers per building) -> hand-written
  `tools/blender/replicas/<key>/spec.json` (floor rhythm, bays, window groups, piers, belts, cornice, storefronts,
  curtain walls, or composed parts with gable/hip/pyramid roofs, towers, arched and rose windows) ->
  `tools/blender/replica.py` -> `assets/models/bld_<key>.glb`.
- The city build leaves out a replica's generic geometry (and any footprint inside it); `scripts/replicas.gd`
  places the model in its chunk with trimesh collision, binds materials by name to the PBR textures and lights a
  share of the windows at night.
- Builder features: punched masonry facades (window groups, end bays, arched heads, transoms, sills, piers, belts,
  cornices, parapets, battlements), curtain walls, solid walls, Art Deco spandrels, storefronts, per-LiDAR-tier specs,
  outline orthogonalisation for noisy LiDAR, composed parts (gable/hip/pyramid/mansard roofs, towers, pinnacles,
  rose windows), giant-order porticos with or without pediments, domes on colonnaded drums with lanterns.
- Done so far (11): Nicholas Building, Fiberglas Tower / Tower on the Maumee, Fifth Third Center at One SeaGate,
  PNC Bank Building, Michael DiSalle Government Center, Spitzer Building, Lucas County Courthouse, Valentine
  Theatre building, Toledo Museum of Art, Ashland Avenue Baptist Church, Collingwood Arts Center.
- Reference photos: `fetch_named.py` downloads named Commons files with curl (Python urllib is throttled);
  `demo.gd` shots `@replica <key> <angle>` and `@cam [pos] [look]` for checking replicas in game.
- Fix: the exact downtown LiDAR massing was keyed to county-footprint ids from an older county join, so 638
  downtown buildings had their heights applied to unrelated houses (floating penthouses, wrong heights).
  Regenerated; the Hotel SeaGate demolition override now finds the building by county address.
