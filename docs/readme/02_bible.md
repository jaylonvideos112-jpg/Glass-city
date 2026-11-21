## 13. The Development Bible v1.0, section by section

**Source:** `docs/GLASS_CITY_Development_Bible_v1.0.pdf`, 19 pages, November 2026. It was written by the owner with ChatGPT as the planning blueprint.

**Labels:**
- **LOCKED:** the owner selected it explicitly.
- **UNDECIDED:** deliberately deferred.
- **PROPOSED IMPLEMENTATION:** a practical staging of a locked goal.

**Precedence:** the latest explicit owner decision wins over the bible. Changes since v1.0 are in section 11 and `docs/DECISIONS.md`.

**Scope rule:** build in vertical slices, validate performance, and polish a Downtown Toledo prototype before expanding. Never attempt every simulation at once.

### §1 Project identity and creative direction
- **Title and franchise:** GLASS CITY, an original franchise. GTA is a genre reference only. Own identity, branding, characters, assets and presentation.
- **Genre:** open-world action-adventure and a life/crime sandbox with a highly simulated modern city.
- **Setting:** Toledo, Ohio and the surrounding communities in the 2020s. A major single-player story backed by a deep sandbox. The city must stay compelling when no mission is active.
- **Tone:** serious storytelling, grounded local atmosphere, dark humour and satire.
- **Philosophy:**
  - authentic place with fictional brands;
  - gameplay-first realism;
  - a wide sandbox with focused, understandable systems (not spreadsheets);
  - persistent consequences in single-player;
  - staged ambition: prototype representative examples before scaling.
- **Protagonist:** fixed and authored, not a free character creator. A young adult of about 22–25 making a name in Toledo.
  - The player can change hair, clothes, outfits and accessories.
  - Personality is defined, but choices shape attitude, behaviour and relationships.
  - Lifestyle affects weight and condition gradually, as a game consequence, not an appearance rating.
  - The story was deliberately deferred to the end of planning: do not invent a plot, cast or missions.
  - Voice acting and the dialogue model are undecided. The owner later said he will voice it himself.

### §2 Platform, engine, technical strategy
- **Platform and engine:** PC first; consoles later. Godot 4 first, then a full rebuild in UE5 for higher-end graphics. This is not a one-click conversion.
- **Visual target:** between GTA V and GTA VI, toward near-photorealism. A Bully-like stylisation is under test as of 2026-11-21.
- **Hardware:** scalable from entry-level to high-end PCs.
- **Budget:** prefer free and open-source tools and assets, with licence checks.
- **Architecture:** modular, reusable systems with documented APIs, automated tests and standards.
- **Documentation:** a master bible plus technical, world, gameplay, asset, QA, roadmap and migration documents.
- **Cross-engine preparation:**
  - reusable source formats;
  - consistent naming, scale and coordinates;
  - documented materials, shaders, rigs, input actions, schemas and interfaces;
  - minimal engine coupling in data;
  - migration notes kept from day one.
- **Performance:**
  - LOD, occlusion, culling, instancing and streaming;
  - NPC, traffic and effects scale with hardware;
  - district streaming with persistent world state;
  - AI simulation tiers;
  - budgets set before content expands.

### §3 World map, geography, districts, infrastructure
- **Coverage:** Toledo plus Maumee, Oregon, Sylvania, Perrysburg, Rossford, Northwood and nearby communities, at near 1:1.
- **Accuracy:** real street layouts and names, road hierarchy, neighbourhoods, landmarks, bridges, highways, interchanges and infrastructure.
  - Street names became parodies (decision of 2026-11-15).
  - Start downtown. One seamless world organised in districts. Release as the complete region.
- **Data pipeline:**
  - geographic datasets, aerial imagery, elevation and 3D building data;
  - manual verification of important places;
  - a provenance and licence register;
  - procedural generation for scale plus hand correction passes;
  - priorities: footprints, heights, roofs, facades, road geometry, lane markings, sidewalks, parking, signage, elevation.
- **Roads:**
  - highways, exits, interchanges, ramps and signage;
  - lane markings, lights, stop signs, crosswalks, sidewalks, parking, bridges and utilities;
  - road repairs, construction sites, closures and new developments over time.
- **Navigation:** a minimap and a smartphone map with real street names, GPS, traffic, alternate routes, transit, restrictions and ETAs.
- **Nature:** the Maumee River, Lake Erie, parks and wetlands.
  - Waterways with boats, marinas, docks, waterfront businesses, fishing and recreational boating.
  - Seasonal vegetation.
  - Regional wildlife with habitats and seasons (no full ecosystem).
- **Airports:**
  - Toledo Express and Toledo Executive are functional locations. No commercial flights out of the region.
  - A small aircraft selection with arcade flight. Helicopters at airports, hospital helipads and some rooftops.
  - AI police and medical helicopters.
  - Rental cars, taxis, rideshare, shuttles, buses and parking.
  - Airport security as an abstract game system (never real-world bypass detail).

### §4 Buildings, interiors, public facilities
- **Access:** nearly every building enterable, including multistorey ones with stairs and elevators. Handcrafted interiors for landmarks, procedural interiors for ordinary buildings. Most rooftops reachable.
- **Underground:** garages, basements, maintenance tunnels, utilities and sewers.
- **Interiors:** distinct and lived-in (lighting, ambient sound, clutter, environmental storytelling). Moderate furniture customisation.
- **Required facility simulations:**
  - hospitals: ER, patients, staff, ambulances, heliports;
  - fire: multiple stations, schedules, engines, ladders, rescue, dispatch;
  - police stations: admin, evidence, dispatch, cells, schedules, patrols;
  - schools and universities: schedules, students, teachers, classes, campus life, sports;
  - sports venues: courts, stadiums, spectators, playable sports, leagues;
  - industry: factories, warehouses, shipping, workers, shifts, deliveries.
- **Urban change:** curated periodic construction and renovation, not a self-rewriting city.

### §5 Living city: NPCs, traffic, public behaviour
- **NPC lives:** identities, personalities, jobs, homes, routines, relationships, and memory of significant player interactions. Deep employment: hiring, firing, promotion, commutes, wages. Simple finances.
- **Density:** follows time, weather, events and neighbourhood. Simulation tiers.
- **Social networks:** family, friends, romance, coworkers, neighbours, rivals. Dialogue depends on context: location, time, relationship, history, events, weather.
- **Pedestrians:** shop, eat, talk, wait for buses, use phones, react to weather.
- **Crowds:** react to incidents (panic, calling 911, helping, filming, talking about it). Incidents can make the news and leave neighbourhood memory.
- **Traffic:**
  - driver personalities, accidents, congestion and rush hour;
  - weather, events, closures, signals, stop signs and crossings;
  - a realistic Toledo mix: mostly ordinary sedans, old used cars, SUVs, pickups, minivans, work and delivery trucks, buses and emergency vehicles;
  - sports, luxury and exotic cars rare; old and new cars mixed; seasonal driving conditions.

### §6 Weather, seasons, time, calendar
- **Weather:** four seasons with lake-effect snow, severe storms, flooding, fog, wind and hail. Seasonal traffic effects.
- **Day length:** a full accelerated day.
  - The bible said 48 real minutes per day; changed on 2026-11-14 to **60 minutes**.
  - Four seasons of 12 days each, so a year is 48 days.
- **Sleep:** advances to morning and is a save point. Major single-player changes persist.
- **Calendar:** weekdays and weekends, holidays, birthdays, festivals and sports seasons. The mapping to named dates is undecided.
- **Persistence:** property, business, NPC relationships, vehicles, decisions and city changes persist; transient activity regenerates.

### §7 Player character and everyday systems
- **Attributes:** health and stamina are the only formal attributes. There is no RPG sheet or skill tree. Skills improve by use. Needs: health, stamina, hunger and basic fitness.
- **Inventory:** simple categories (weapons, food, misc). No weight or volume simulation.
- **Activities:** shopping, eating out, gyms, watching sports, socialising, entertainment.
- **Hobbies:** fishing, bowling, photography (camera with zoom, filters, poses, challenges), gaming, collecting, recreational sports. Bicycles. Parks with courts, picnic areas, playgrounds, trails and events.
- **Food:** restaurants with menus, prices and eating animations. Groceries stored in the home fridge. Interactive (not overly detailed) cooking. Food and grocery delivery.
- **Homes:** rent or buy, customise interiors, garages, multiple properties. Renting properties to NPCs after the story. No mandatory bills; rent is charged only if renting.

### §8 Vehicles and transportation
- **Identity:** GTA-style. Models inspired by real cars with changed designs, fictional makes and original badges.
- **Roster:** no fixed count. It mirrors real Toledo traffic. Categories: civilian, sports/luxury, trucks/SUVs, motorcycles, commercial, buses, emergency, specialty.
- **Driving:** fun, arcade GTA-style.
- **Customisation:** engine, body kits, paint and wraps, wheels, suspension, interiors, sound systems.
- **Ownership:** garages, retrieval, no fuel, no insurance. Damage affects handling and speed. Repairs at shops and owned garages. Stolen cars can be kept (police attention).
- **Market:** dealers, used lots, private sellers, auctions, player trading.
- **Cameras and interiors:** detailed interiors; views: third-person, cinematic, bumper, hood, cockpit. Entry and exit animations vary by vehicle. Passengers behave (talk, phones, react).
- **Transit:**
  - TARTA-inspired buses with routes, stops, schedules, fares and paratransit;
  - taxis, rideshare and shuttles;
  - freight and passenger trains with crossings.
- **Water and air:** boats, marinas, swimming, kayaking, jet skis. Fishing with species, bait, gear and conditions. A small aircraft set.

### §9 Economy, jobs, properties, businesses
- **Money:** cash plus a fictional peer-to-peer payment app (never Cash App branding). ATM transfers both ways. No bank accounts, credit or loans.
- **Jobs:**
  - blue-collar: construction, warehouse, manufacturing, delivery, maintenance, labour;
  - retail and service: grocery, clothing, restaurants, fast food, gas stations, convenience stores;
  - simple activities, shifts and paychecks; apply by phone or in person;
  - public-service careers (police, fire, EMS) are **not playable**; they are NPC systems.
- **Businesses:** buy nearly any category. NPC staff, passive income, no management depth. Price varies with location, size, profit and area. Income auto-deposits or is collected. It does not carry over to multiplayer.
- **Properties:** rent or buy, customise, garages, NPC tenants after the story. Not a property-management sim.

### §10 Crime, police, justice, emergency services
- **Crime sandbox:** multiple criminal paths, crews, territory, heists, criminal businesses and escalating investigations. Compete with NPC organisations. Reputation tracks police attention, rivals, loyalty, respect, alliances, neighbourhood influence and public perception. Fictional mechanics only.
- **Police:**
  - GTA wanted levels plus advanced AI, escalation, search, dispatch and pursuits;
  - traffic stops, warnings, tickets, ID checks;
  - enforcement for speeding, reckless driving, collisions and parking;
  - agencies: city police, sheriff, Ohio State Highway Patrol, fire, EMS, special units.
- **Justice:** arrest, **one night** in an explorable jail (inmates, guards, routines), court, fines, possible loss of items.
- **Emergency response:** coordinated fire, police and EMS. AI helicopters.

### §11 Sports, schools, recreation, entertainment
- **Pro teams (fictional, original branding):**
  - basketball: Glass City Fishmen (inspired by the Glass City Wranglers);
  - baseball: Mud Hens-inspired (in game: Glass City Swamp Hens);
  - hockey: Walleye-inspired;
  - college: Glass City Flight (UToledo Rockets-inspired), with a full athletic department.
  - Leagues have schedules, standings, rivalries and playable pro games. College games are events only.
- **University:** fully simulated (students, professors, classes, dorms, dining, libraries, events, athletics). The player watches and plays casual sports.
- **High schools:** fictionalised real schools with campuses, colours, mascots and rivalries, fully simulated. Youth leagues exist; the adult protagonist can't join them.
- **Adults:** pickup sports only. Fully interactive gyms. Parks with courts and trails.
- **Entertainment:** bars, restaurants, nightclubs, cinemas, arcades, bowling, comedy, music venues, concerts, festivals, nightlife districts.
- **Shopping:** malls, independent stores, clothing, electronics, grocery, online, sales, player-owned retail.

### §12 Media, smartphone, internet, audio
- **Phone:** contacts, messages, internet, social media, payment app, GPS, mission notifications, business apps.
- **Internet:** websites, search, social media, shopping, news, job applications. Phone customisation. A social profile with posts, followers and trending.
- **News:** TV, radio, web, newspapers and social media covering crime, sports, business, weather and events.
- **Audio:** detailed environment (engines, traffic, neighbourhood, interior vs exterior, weather, conversations, sirens). Dynamic music desired. Soundtrack scope, radio stations and vehicle audio are **undecided**.

### §13 Visuals, animation, camera, interaction
- **Visuals:** realistic characters, faces, clothing, lighting, reflections, rain, water, particles (under review: Bully style).
- **Animation:** mocap-quality movement, facial expressions, seamless transitions, contextual vehicle entry. Practical budgets.
- **Camera:** first and third person, with a full-body first-person view. Driving cams: chase, cinematic, bumper, hood, cockpit.
- **Interaction:** context menus plus animations. Pick up and carry everyday objects.
- **Destruction:** selective (windows, furniture, objects). Buildings are not destructible. Vehicle damage.
- **Accessibility:** remapping, subtitles, colour-blind options, scaling, difficulty. Keyboard, mouse and controllers. Original GLASS CITY UI.

### §14 Combat and progression
- **Combat:** arcade, GTA V feel.
- **Weapons:** pistols, shotguns, rifles, melee, explosives, with attachments and finishes.
- **Melee:** punches, kicks, combos, blocks, dodges, takedowns.
- **Cover:** cover and responsive animations, kept approachable.
- **Progression:** skills improve by use only. Fictional mechanics, no real weapon instruction.

### §15 Multiplayer (later stage)
- **Servers:** 32 players per server. Public, private and invite sessions. The same standard map baseline; nothing from single-player carries over. Player data persists; the world resets.
- **Online character:** a separate customisable character.
- **PvP:** allowed, with safe zones.
- **Progression and economy:** progression by money, XP, achievements and reputation. A shared economy and businesses (shared ownership), crews, car clubs, teams.
- **Activities:** online-only competitive, social, co-op and public events.
- **Communication:** voice, chat, mute, block, report.
- **Servers and mods:** official servers, friend-hosted servers, modded community servers with mod lists. Basic anti-cheat.

### §16 Workflow, QA, modding, roadmap
- **Roles:** owner = creative decision-maker; ChatGPT = creative director and planner; Claude = coder, working from small structured tasks.
- **Documentation package:** bible, world bible, system specs, architecture and APIs, asset catalogue and licence register, AI design, QA plans, benchmarks, roadmap, UE5 migration notes, task prompts, standards, changelog.
- **QA:** a custom asset library. Professional QA: automated tests, benchmarks, regression tests, bug tracking. Don't build on unstable foundations; every feature has acceptance criteria.
- **Priority: WORLD FIRST.** The world comes first; gameplay is built on top.
- **Roadmap:**

| Stage | Focus |
|---|---|
| 0 | Foundation |
| 1 | Downtown blockout |
| 2 | Downtown visual slice |
| 3 | City systems |
| 4 | Region expansion |
| 5 | Core gameplay |
| 6 | Story and content |
| 7 | Multiplayer |
| 8 | Release preparation |
| 9 | Unreal rebuild |

**Where the project actually stands:** stages 0–4 are largely done, and much of stage 5 (systems) exists. Stage 6 (missions and story) has not started, by owner choice. An accuracy re-pass of the region is under way.

### §17 Undecided items and guardrails
- **Undecided:** story, cast and missions; voice and dialogue model; radio stations and programming; soundtrack scope; vehicle audio details; the named calendar mapping.
- **Settled (don't re-ask):** PC first; Godot then UE5; Toledo and downtown first; realistic geography; hybrid interiors; broad building access; persistent single-player world; simple inventory; no fuel or insurance; cash, wallet and ATM; basic jobs; passive businesses; one-night jail; realistic traffic; the day length (now 60 min) and 12-day seasons; separate multiplayer progression; standard online map; 32 players; world first.
- **Guardrails:**
  - fictional brands unless licensed;
  - real map data only with rights and attribution;
  - don't claim the UE5 migration is automatic;
  - stage features;
  - single-player doesn't affect the multiplayer baseline;
  - public-service careers not playable;
  - businesses don't become a management sim;
  - the protagonist stays fixed.

### §18 Master brief for Claude (summary)
- **Task discipline:** one small, verifiable feature at a time. Before coding, state scope, dependencies, files and acceptance criteria. After coding, report files changed, tests run, limitations and doc updates. Never silently redesign locked decisions.
- **Profiling:** profile early; don't scale NPC or traffic systems before a slice meets budget.
- **Authority:** the bible is the source of truth; later owner decisions supersede it. Mark unknowns as undecided.
- **First deliverable** (done long ago): the downtown blockout. Work in small milestones with working builds and tests.
