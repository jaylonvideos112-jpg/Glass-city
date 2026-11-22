"""Toledo's 200 most-driven vehicles (model + generation), as weights for GLASS CITY traffic and parked cars.

There is no public per-model registration count for Toledo / Lucas County, so this is an ESTIMATE built from:
  * Toledo used-car market (CarGurus "popular models" for Toledo, 2026) - what is actually on local roads,
  * Ohio DMV registrations (Vinitel 2026: Chevrolet top make, Silverado 1500 = 3.9% of Ohio cars),
  * US vehicles-in-operation (Experian Q2 2026: F-150 3.7%, Silverado 2.8%, Ram 1500 1.3%, Tundra 0.9%;
    US fleet average age 12.8 years, ~1 in 5 vehicles 15+ years old, 8.3% older than 25 model years),
  * Toledo new sales (CarEdge, late 2026: Ram 1500 #1, RAV4, Grand Cherokee, CR-V, Camry ...),
  * local factors: Jeep's Toledo Assembly (Wrangler / Gladiator, earlier Liberty / Cherokee / Nitro), union and
    domestic-brand loyalty, Chrysler minivans, GM Toledo Transmission, old Big-3 sedans kept running.
weight = relative share on the road (sums to 1000). body = the GLASS CITY car body family it is modelled from.
usage: python3 tools/pipeline/make_toledo_fleet.py   -> source_data/toledo_fleet.json"""
import json, os

F = [  # make, model, years, body, weight (raw, normalized below)
# ---- full-size pickups (the biggest segment)
("Ford", "F-150", "2015-2020", "pickup", 16), ("Ford", "F-150", "2009-2014", "pickup", 14), ("Ford", "F-150", "2021-2026", "pickup", 12),
("Ford", "F-150", "2004-2008", "pickup", 7), ("Ford", "F-150", "1997-2003", "pickup", 4),
("Chevrolet", "Silverado 1500", "2014-2018", "pickup", 15), ("Chevrolet", "Silverado 1500", "2007-2013", "pickup", 13),
("Chevrolet", "Silverado 1500", "2019-2026", "pickup", 13), ("Chevrolet", "Silverado 1500", "1999-2006", "pickup", 7),
("Ram", "1500", "2009-2018", "pickup", 12), ("Ram", "1500", "2019-2026", "pickup", 11), ("Dodge", "Ram 1500", "2002-2008", "pickup", 5),
("GMC", "Sierra 1500", "2014-2018", "pickup", 6), ("GMC", "Sierra 1500", "2019-2026", "pickup", 6), ("GMC", "Sierra 1500", "2007-2013", "pickup", 5),
("Toyota", "Tundra", "2007-2021", "pickup", 5), ("Toyota", "Tundra", "2022-2026", "pickup", 2), ("Nissan", "Titan", "2004-2015", "pickup", 1),
# ---- heavy-duty pickups / work trucks
("Ford", "F-250 Super Duty", "2017-2026", "pickup_hd", 5), ("Ford", "F-250 Super Duty", "2008-2016", "pickup_hd", 4),
("Ford", "F-350 Super Duty", "2017-2026", "pickup_hd", 2), ("Chevrolet", "Silverado 2500HD", "2015-2026", "pickup_hd", 4),
("Chevrolet", "Silverado 2500HD", "2007-2014", "pickup_hd", 2), ("Ram", "2500", "2010-2026", "pickup_hd", 4), ("GMC", "Sierra 2500HD", "2015-2026", "pickup_hd", 2),
# ---- mid-size pickups
("Toyota", "Tacoma", "2016-2023", "pickup_mid", 6), ("Toyota", "Tacoma", "2005-2015", "pickup_mid", 4), ("Toyota", "Tacoma", "2024-2026", "pickup_mid", 1),
("Chevrolet", "Colorado", "2015-2022", "pickup_mid", 4), ("GMC", "Canyon", "2015-2022", "pickup_mid", 2), ("Ford", "Ranger", "2019-2026", "pickup_mid", 4),
("Ford", "Ranger", "1998-2011", "pickup_mid", 4), ("Jeep", "Gladiator", "2020-2026", "pickup_mid", 6), ("Nissan", "Frontier", "2005-2021", "pickup_mid", 3),
("Honda", "Ridgeline", "2017-2026", "pickup_mid", 2), ("Dodge", "Dakota", "2005-2011", "pickup_mid", 2), ("Chevrolet", "S-10", "1994-2004", "pickup_mid", 2),
# ---- Jeep (built in Toledo)
("Jeep", "Wrangler", "2018-2026", "jeep", 12), ("Jeep", "Wrangler", "2007-2018", "jeep", 12), ("Jeep", "Wrangler", "1997-2006", "jeep", 4),
("Jeep", "Grand Cherokee", "2011-2021", "suv_m", 15), ("Jeep", "Grand Cherokee", "2022-2026", "suv_m", 8), ("Jeep", "Grand Cherokee", "2005-2010", "suv_m", 6),
("Jeep", "Grand Cherokee", "1999-2004", "suv_m", 3), ("Jeep", "Cherokee", "2014-2023", "suv_c", 9), ("Jeep", "Cherokee", "1984-2001", "suv_box", 3),
("Jeep", "Liberty", "2002-2012", "suv_box", 6), ("Jeep", "Compass", "2017-2026", "suv_c", 8), ("Jeep", "Compass", "2007-2016", "suv_c", 3),
("Jeep", "Patriot", "2007-2017", "suv_box", 5), ("Jeep", "Renegade", "2015-2023", "suv_sub", 4), ("Jeep", "Grand Cherokee L", "2021-2026", "suv_f", 2),
("Dodge", "Nitro", "2007-2011", "suv_box", 2),
# ---- compact crossovers
("Chevrolet", "Equinox", "2018-2024", "suv_c", 13), ("Chevrolet", "Equinox", "2010-2017", "suv_c", 10), ("Chevrolet", "Equinox", "2025-2026", "suv_c", 2),
("Honda", "CR-V", "2017-2022", "suv_c", 9), ("Honda", "CR-V", "2012-2016", "suv_c", 7), ("Honda", "CR-V", "2023-2026", "suv_c", 5), ("Honda", "CR-V", "2007-2011", "suv_c", 4),
("Toyota", "RAV4", "2019-2025", "suv_c", 9), ("Toyota", "RAV4", "2013-2018", "suv_c", 6), ("Toyota", "RAV4", "2006-2012", "suv_c", 3), ("Toyota", "RAV4", "2026", "suv_c", 1),
("Ford", "Escape", "2013-2019", "suv_c", 10), ("Ford", "Escape", "2020-2026", "suv_c", 5), ("Ford", "Escape", "2008-2012", "suv_box", 5),
("Nissan", "Rogue", "2014-2020", "suv_c", 9), ("Nissan", "Rogue", "2021-2026", "suv_c", 5), ("Nissan", "Rogue", "2008-2013", "suv_c", 3),
("Hyundai", "Tucson", "2016-2021", "suv_c", 4), ("Hyundai", "Tucson", "2022-2026", "suv_c", 4), ("Kia", "Sportage", "2017-2022", "suv_c", 3),
("Mazda", "CX-5", "2017-2026", "suv_c", 5), ("Subaru", "Forester", "2014-2026", "suv_c", 5), ("Subaru", "Crosstrek", "2018-2026", "suv_sub", 4),
("GMC", "Terrain", "2018-2026", "suv_c", 4), ("GMC", "Terrain", "2010-2017", "suv_box", 3), ("Buick", "Encore", "2013-2022", "suv_sub", 4),
("Buick", "Envision", "2016-2026", "suv_c", 2), ("Buick", "Envista", "2024-2026", "suv_sub", 2), ("Chevrolet", "Trax", "2015-2022", "suv_sub", 3),
("Chevrolet", "Trax", "2024-2026", "suv_sub", 3), ("Ford", "EcoSport", "2018-2022", "suv_sub", 2), ("Kia", "Soul", "2014-2025", "hatch_box", 4),
("Nissan", "Kicks", "2018-2026", "suv_sub", 2), ("Hyundai", "Kona", "2018-2026", "suv_sub", 2), ("Kia", "Seltos", "2021-2026", "suv_sub", 2),
("Mitsubishi", "Outlander Sport", "2011-2024", "suv_sub", 2), ("Volkswagen", "Tiguan", "2018-2026", "suv_c", 2), ("Mazda", "CX-30", "2020-2026", "suv_sub", 2),
("Honda", "HR-V", "2016-2026", "suv_sub", 3), ("Toyota", "Corolla Cross", "2022-2026", "suv_sub", 1), ("Dodge", "Journey", "2009-2020", "suv_c", 5),
("Chevrolet", "Blazer", "2019-2026", "suv_m", 3), ("Ford", "Edge", "2015-2024", "suv_m", 5), ("Ford", "Edge", "2007-2014", "suv_m", 4),
("Ford", "Bronco Sport", "2021-2026", "suv_box", 2), ("Ford", "Bronco", "2021-2026", "jeep", 3),
# ---- mid-size / 3-row SUVs
("Ford", "Explorer", "2011-2019", "suv_m", 10), ("Ford", "Explorer", "2020-2026", "suv_m", 7), ("Ford", "Explorer", "2002-2010", "suv_box", 5),
("Chevrolet", "Traverse", "2018-2023", "suv_f", 5), ("Chevrolet", "Traverse", "2009-2017", "suv_f", 4), ("GMC", "Acadia", "2007-2016", "suv_f", 4),
("GMC", "Acadia", "2017-2026", "suv_m", 3), ("Buick", "Enclave", "2008-2026", "suv_f", 4), ("Toyota", "Highlander", "2014-2026", "suv_m", 5),
("Honda", "Pilot", "2016-2026", "suv_m", 4), ("Honda", "Pilot", "2009-2015", "suv_box", 2), ("Nissan", "Pathfinder", "2013-2026", "suv_m", 3),
("Dodge", "Durango", "2011-2026", "suv_m", 5), ("Kia", "Sorento", "2016-2026", "suv_m", 4), ("Hyundai", "Santa Fe", "2013-2026", "suv_m", 4),
("Kia", "Telluride", "2020-2026", "suv_m", 2), ("Subaru", "Outback", "2015-2026", "wagon", 5), ("Chevrolet", "TrailBlazer", "2002-2009", "suv_box", 4),
("Toyota", "4Runner", "2010-2024", "suv_box", 3), ("Ford", "Flex", "2009-2019", "suv_box", 1), ("Lincoln", "MKX/Nautilus", "2011-2023", "suv_m", 2),
("Cadillac", "XT5/SRX", "2010-2026", "suv_m", 2), ("Lexus", "RX", "2010-2026", "suv_m", 2), ("Mazda", "CX-9", "2016-2023", "suv_m", 1),
("Chrysler", "Aspen", "2007-2009", "suv_f", 1),
# ---- full-size SUVs
("Chevrolet", "Tahoe", "2015-2020", "suv_f", 5), ("Chevrolet", "Tahoe", "2007-2014", "suv_f", 5), ("Chevrolet", "Tahoe", "2021-2026", "suv_f", 3),
("Chevrolet", "Suburban", "2007-2026", "suv_f", 3), ("GMC", "Yukon", "2007-2026", "suv_f", 4), ("Cadillac", "Escalade", "2007-2026", "suv_f", 2),
("Ford", "Expedition", "2007-2026", "suv_f", 3), ("Lincoln", "Navigator", "2007-2026", "suv_f", 1), ("Chevrolet", "Tahoe", "2000-2006", "suv_f", 2),
# ---- midsize sedans
("Chevrolet", "Impala", "2006-2013", "sedan_big", 12), ("Chevrolet", "Impala", "2014-2020", "sedan_big", 6), ("Chevrolet", "Impala", "2000-2005", "sedan_big", 3),
("Chevrolet", "Malibu", "2016-2025", "sedan", 12), ("Chevrolet", "Malibu", "2008-2012", "sedan", 7), ("Chevrolet", "Malibu", "2013-2015", "sedan", 4),
("Ford", "Fusion", "2013-2020", "sedan", 12), ("Ford", "Fusion", "2006-2012", "sedan", 7), ("Ford", "Taurus", "2010-2019", "sedan_big", 6),
("Ford", "Taurus", "1996-2007", "sedan_big", 3), ("Toyota", "Camry", "2018-2024", "sedan", 9), ("Toyota", "Camry", "2012-2017", "sedan", 9),
("Toyota", "Camry", "2007-2011", "sedan", 6), ("Toyota", "Camry", "2025-2026", "sedan", 2), ("Honda", "Accord", "2013-2017", "sedan", 8),
("Honda", "Accord", "2008-2012", "sedan", 6), ("Honda", "Accord", "2018-2022", "sedan", 6), ("Honda", "Accord", "2003-2007", "sedan", 3),
("Nissan", "Altima", "2013-2018", "sedan", 9), ("Nissan", "Altima", "2007-2012", "sedan", 6), ("Nissan", "Altima", "2019-2026", "sedan", 5),
("Hyundai", "Sonata", "2011-2019", "sedan", 7), ("Hyundai", "Sonata", "2020-2026", "sedan", 2), ("Kia", "Optima/K5", "2011-2026", "sedan", 5),
("Chrysler", "200", "2011-2017", "sedan", 4), ("Dodge", "Avenger", "2008-2014", "sedan", 3), ("Chrysler", "Sebring", "2001-2010", "sedan", 3),
("Pontiac", "G6", "2005-2010", "sedan", 4), ("Pontiac", "Grand Prix", "1997-2008", "sedan_big", 3), ("Buick", "LaCrosse", "2010-2019", "sedan_big", 4),
("Buick", "LeSabre", "2000-2005", "sedan_big", 3), ("Buick", "Lucerne", "2006-2011", "sedan_big", 3), ("Buick", "Century", "1997-2005", "sedan_big", 2),
("Buick", "Regal", "2011-2017", "sedan", 2), ("Oldsmobile", "Alero", "1999-2004", "sedan", 1), ("Mercury", "Grand Marquis", "1998-2011", "sedan_big", 3),
("Ford", "Crown Victoria", "1998-2011", "sedan_big", 2), ("Mercury", "Milan", "2006-2011", "sedan", 1), ("Saturn", "Aura", "2007-2009", "sedan", 1),
("Volkswagen", "Jetta", "2011-2026", "sedan_small", 3), ("Volkswagen", "Passat", "2012-2022", "sedan", 2), ("Subaru", "Legacy", "2015-2026", "sedan", 2),
("Mazda", "Mazda6", "2014-2021", "sedan", 2), ("Lincoln", "MKZ", "2013-2020", "sedan", 2), ("Cadillac", "CTS", "2008-2019", "sedan", 1),
# ---- full-size / muscle
("Chrysler", "300", "2011-2023", "sedan_big", 7), ("Chrysler", "300", "2005-2010", "sedan_big", 5), ("Dodge", "Charger", "2011-2023", "sedan_big", 8),
("Dodge", "Charger", "2006-2010", "sedan_big", 3), ("Dodge", "Challenger", "2008-2023", "coupe", 4), ("Chevrolet", "Camaro", "2010-2024", "coupe", 4),
("Ford", "Mustang", "2015-2023", "coupe", 4), ("Ford", "Mustang", "2005-2014", "coupe", 3), ("Chevrolet", "Corvette", "2005-2026", "sports", 1),
("Chevrolet", "Monte Carlo", "2000-2007", "coupe", 1),
# ---- compacts
("Honda", "Civic", "2016-2021", "sedan_small", 9), ("Honda", "Civic", "2012-2015", "sedan_small", 6), ("Honda", "Civic", "2006-2011", "sedan_small", 5),
("Honda", "Civic", "2022-2026", "sedan_small", 4), ("Toyota", "Corolla", "2014-2019", "sedan_small", 8), ("Toyota", "Corolla", "2020-2026", "sedan_small", 6),
("Toyota", "Corolla", "2009-2013", "sedan_small", 4), ("Chevrolet", "Cruze", "2011-2016", "sedan_small", 10), ("Chevrolet", "Cruze", "2016-2019", "sedan_small", 5),
("Ford", "Focus", "2012-2018", "sedan_small", 8), ("Ford", "Focus", "2008-2011", "sedan_small", 4), ("Ford", "Focus", "2000-2007", "sedan_small", 2),
("Chevrolet", "Cobalt", "2005-2010", "sedan_small", 5), ("Pontiac", "Grand Am", "1999-2005", "sedan", 2), ("Chevrolet", "Cavalier", "1995-2005", "sedan_small", 2),
("Nissan", "Sentra", "2013-2019", "sedan_small", 6), ("Nissan", "Sentra", "2020-2026", "sedan_small", 4), ("Nissan", "Versa", "2012-2026", "sedan_small", 4),
("Hyundai", "Elantra", "2011-2020", "sedan_small", 7), ("Hyundai", "Elantra", "2021-2026", "sedan_small", 3), ("Kia", "Forte", "2014-2024", "sedan_small", 4),
("Kia", "K4", "2025-2026", "sedan_small", 1), ("Dodge", "Dart", "2013-2016", "sedan_small", 2), ("Dodge", "Neon", "2000-2005", "sedan_small", 1),
("Chevrolet", "Sonic", "2012-2020", "hatch", 3), ("Ford", "Fiesta", "2011-2019", "hatch", 2), ("Chevrolet", "Spark", "2013-2022", "hatch", 1),
("Mazda", "Mazda3", "2010-2026", "hatch", 3), ("Toyota", "Prius", "2010-2022", "hatch", 2), ("Volkswagen", "Golf", "2010-2021", "hatch", 1),
("Chevrolet", "HHR", "2006-2011", "hatch_box", 2), ("Pontiac", "Vibe", "2003-2010", "hatch", 1), ("Dodge", "Caliber", "2007-2012", "hatch", 2),
("Chrysler", "PT Cruiser", "2001-2010", "hatch_box", 3), ("Ford", "Five Hundred/Taurus X", "2005-2009", "sedan_big", 1), ("Saturn", "Ion", "2003-2007", "sedan_small", 1),
("Tesla", "Model 3", "2017-2026", "sedan", 1), ("Tesla", "Model Y", "2020-2026", "suv_c", 1),
# ---- minivans / vans (Chrysler vans are a Toledo staple)
("Dodge", "Grand Caravan", "2008-2020", "minivan", 14), ("Chrysler", "Town & Country", "2008-2016", "minivan", 8), ("Chrysler", "Pacifica", "2017-2026", "minivan", 7),
("Dodge", "Grand Caravan", "2001-2007", "minivan", 3), ("Honda", "Odyssey", "2011-2026", "minivan", 6), ("Toyota", "Sienna", "2011-2026", "minivan", 5),
("Kia", "Sedona/Carnival", "2015-2026", "minivan", 2), ("Chrysler", "Voyager", "2020-2025", "minivan", 1), ("Chevrolet", "Uplander", "2005-2008", "minivan", 1),
("Ford", "Transit", "2015-2026", "van", 4), ("Chevrolet", "Express", "2003-2026", "van", 4), ("Ford", "E-Series", "1992-2014", "van", 3),
("Ram", "ProMaster", "2014-2026", "van", 2), ("Ford", "Transit Connect", "2010-2023", "van_small", 2), ("GMC", "Savana", "2003-2026", "van", 1),
]
assert len(F) >= 200, len(F)
F = sorted(F, key=lambda r: -r[4])[:200]
tot = sum(r[4] for r in F)
out = [dict(rank=i + 1, make=m, model=md, years=y, body=b, weight=round(1000.0 * w / tot, 2))
       for i, (m, md, y, b, w) in enumerate(F)]
R = os.path.join(os.path.dirname(__file__), "..", "..", "source_data", "toledo_fleet.json")
json.dump({"note": __doc__.split("\n\n")[1].strip(), "vehicles": out}, open(R, "w"), indent=1)
from collections import Counter
bc = Counter(); mk = Counter()
for v in out: bc[v["body"]] += v["weight"]; mk[v["make"]] += v["weight"]
print(len(out), "vehicles; by body:", {k: round(x) for k, x in bc.most_common()})
print("by make:", {k: round(x) for k, x in mk.most_common(12)})
