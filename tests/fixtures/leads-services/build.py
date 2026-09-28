#!/usr/bin/env python3
"""Build a fixture census for the segment paths of `leads` (ROADMAP B44).

    build.py OUT.db                     # a standalone census: place_cache + restaurants (empty) + businesses
    build.py OUT.db --from wasatch.db   # a copy of the real census with the fixture businesses added
    build.py OUT.db --no-businesses     # the same standalone census before B43 (no businesses table)

The businesses table is plan 18 § Contract's DDL verbatim; every row is made up
(FX_ place ids, 555 numbers) and sits around American Fork, Lehi, Pleasant Grove and Orem.
"""
import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

BUSINESSES_DDL = """CREATE TABLE IF NOT EXISTS businesses (
  place_id         TEXT PRIMARY KEY,
  segment          TEXT NOT NULL,
  category         TEXT NOT NULL,
  categories       TEXT,
  city             TEXT,
  first_seen       TEXT,
  source           TEXT,
  presence_class   TEXT,
  presence_url     TEXT,
  presence_checked TEXT,
  is_chain         INTEGER,
  chain_override   TEXT
)"""

PLACE_CACHE_DDL = """CREATE TABLE IF NOT EXISTS place_cache (
    place_id TEXT PRIMARY KEY, name TEXT, address TEXT, phone TEXT, website TEXT, has_website TEXT,
    rating REAL, reviews INTEGER, price_level TEXT, cuisine TEXT, lat REAL, lng REAL, refreshed_at TEXT,
    locality TEXT, postal_code TEXT, primary_type TEXT, types TEXT, business_status TEXT, google_maps_uri TEXT)"""

RESTAURANTS_DDL = """CREATE TABLE IF NOT EXISTS restaurants (
    place_id TEXT PRIMARY KEY, first_seen TEXT, source TEXT, city TEXT, on_doordash TEXT, on_uber TEXT,
    pos_system TEXT, contact_name TEXT, contact_email TEXT, status TEXT DEFAULT 'Open', last_action_date TEXT,
    last_action_notes TEXT, next_step TEXT, next_followup TEXT, ordering_platform TEXT, website_checked TEXT,
    on_grubhub TEXT, doordash_url TEXT, uber_url TEXT, grubhub_url TEXT, storefront_url TEXT, marketplace_checked TEXT,
    channel_class TEXT, is_chain INTEGER, chain_override TEXT, toast_url TEXT, serp_top3 TEXT, parasite_url TEXT,
    serp_checked TEXT, maps_checked TEXT, maps_status TEXT, maps_order TEXT, maps_direct_url TEXT, v3_exclude TEXT)"""

# (id, segment, category, name, locality, lat, lng, phone, website, rating, reviews, primary_type, presence, extra)
ROWS = [
    ("FX_S01", "services", "pool service", "Mike's Pool Care", "American Fork", 40.3800, -111.7900, "(801) 555-0101",
     "https://www.facebook.com/mikespoolcare", 4.9, 14, "pool_cleaning_service", "page", {}),
    ("FX_S02", "services", "landscaping", "Blue Canyon Landscaping", "Lehi", 40.3920, -111.8200, "(801) 555-0102",
     None, 4.6, 31, "landscaper", "none", {}),
    ("FX_S03", "services", "pest control", "Wasatch Pest Pros", "Pleasant Grove", 40.3650, -111.7400, "(801) 555-0103",
     "https://wasatch-pest-pros.business.site/", 4.7, 22, "pest_control_service", "dead", {}),
    ("FX_S04", "services", "pressure washing", "Timp Pressure Washing", "American Fork", 40.3700, -111.8000, "(801) 555-0104",
     "https://www.thumbtack.com/ut/american-fork/pressure-washing/timp-pressure-washing", 5.0, 9, "service", "directory", {}),
    ("FX_S05", "services", "handyman", "Dave's Handyman Services", "Lehi", 40.4000, -111.8300, "(801) 555-0105",
     "https://daveshandyman.wixsite.com/home", 4.8, 27, "handyman", "builder", {}),
    ("FX_S06", "services", "plumber", "Summit Plumbing & Drain", "Orem", 40.2970, -111.6950, "(801) 555-0106",
     "https://summitplumbingutah.com/", 4.8, 120, "plumber", "own", {}),
    ("FX_S07", "services", "house cleaning", "Sparkle Home Cleaning", "American Fork", 40.3850, -111.7800, "",
     None, 4.9, 40, "house_cleaning_service", "none", {}),
    ("FX_S08", "services", "snow removal", "Glacier Snow Removal", "American Fork", 40.3790, -111.7990, "(801) 555-0108",
     "https://www.instagram.com/glaciersnowut/", 4.8, 6, "snow_removal_service", "unknown", {}),
    ("FX_S09", "services", "painter", "ProCoat Painters", "American Fork", 40.3771, -111.7960, "(801) 555-0109",
     None, 4.4, 80, "painter", "none", {"is_chain": 1}),
    ("FX_S10", "services", "garage door", "Elite Garage Doors", "American Fork", 40.3772, -111.7961, "(801) 555-0110",
     None, 4.2, 50, "garage_door_supplier", "none", {"business_status": "CLOSED_PERMANENTLY"}),
    ("FX_S11", "services", "HVAC", "Canyon Air HVAC", "Orem", 40.3000, -111.7000, "(801) 555-0111",
     None, 4.5, 40, "hvac_contractor", "none", {}),
    ("FX_S12", "services", "lawn care", "Lehi Lawn Bros", "Lehi", 40.3880, -111.8600, "(801) 555-0112",
     "https://www.angi.com/companylist/us/ut/lehi/lehi-lawn-bros-reviews-1.htm", 4.3, 12, "landscaper", "directory", {}),
    ("FX_C01", "creatives", "photographer", "Photography by Jenna", "American Fork", 40.3810, -111.7920, "(801) 555-0121",
     "https://www.instagram.com/photosbyjenna.ut/", 5.0, 45, "photographer", "page", {}),
    ("FX_C02", "creatives", "wedding DJ", "Beat Drop DJs", "Lehi", 40.3950, -111.8400, "(801) 555-0122",
     None, 4.9, 18, "event_planner", "none", {}),
    ("FX_C03", "creatives", "florist", "Rosie's Florals", "Pleasant Grove", 40.3640, -111.7380, "(801) 555-0123",
     "https://www.facebook.com/rosiesfloralsutah", 4.8, 60, "florist", "page", {}),
    ("FX_C04", "creatives", "cake", "Aspen Cake Co", "Orem", 40.2990, -111.6980, "(801) 555-0124",
     "https://aspencakeco.godaddysites.com/", 4.7, 25, "bakery", "builder", {}),
    ("FX_C05", "creatives", "music teacher", "Harmony Piano Studio", "American Fork", 40.3760, -111.8100, "(801) 555-0125",
     None, 5.0, 11, "music_school", "none", {}),
    ("FX_C06", "creatives", "personal trainer", "Peak Performance Training", "Lehi", 40.3990, -111.8500, "(801) 555-0126",
     "https://peak-performance-lehi.business.site/", 4.9, 8, "personal_trainer", "dead", {}),
    ("FX_C07", "creatives", "photographer", "Lens & Light Studio", "Orem", 40.2980, -111.6900, "(801) 555-0127",
     "https://lensandlightstudio.com/", 4.9, 70, "photographer", "own", {}),
    ("FX_R01", "retail", "bakery", "Sweet Crumb Cottage Bakery", "American Fork", 40.3830, -111.7950, "(801) 555-0131",
     "https://www.facebook.com/sweetcrumbcottage", 4.8, 33, "bakery", "page", {}),
    ("FX_R02", "retail", "bike shop", "Timpanogos Bike Works", "Pleasant Grove", 40.3660, -111.7420, "(801) 555-0132",
     "https://timpbikeworks.com/", 4.7, 150, "bicycle_store", "own", {}),
    ("FX_N01", "nonprofit", "youth league", "Lehi Youth Soccer League", "Lehi", 40.3910, -111.8480, "(801) 555-0141",
     None, 4.6, 15, "sports_club", "none", {}),
    ("FX_N02", "nonprofit", "church", "Grace Community Church", "Orem", 40.2960, -111.6960, "(801) 555-0142",
     "https://gracecommunityorem.org/", 4.8, 40, "church", "own", {}),
]


def build(out, src=None, businesses=True):
    out = Path(out)
    if out.exists():
        out.unlink()
    if src:
        shutil.copyfile(src, out)
    conn = sqlite3.connect(out)
    conn.execute(PLACE_CACHE_DDL)
    conn.execute(RESTAURANTS_DDL)
    if businesses:
        conn.execute(BUSINESSES_DDL)
    for (pid, seg, cat, name, loc, lat, lng, phone, web, rating, reviews, ptype, presence, extra) in ROWS:
        conn.execute("""INSERT OR REPLACE INTO place_cache (place_id, name, address, phone, website, has_website, rating, reviews,
                        lat, lng, refreshed_at, locality, postal_code, primary_type, types, business_status, google_maps_uri)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (pid, name, f"{100 + int(pid[-2:])} N Main St, {loc}, UT 84000, USA", phone, web, "yes" if web else "no",
                      rating, reviews, lat, lng, "2026-09-28T12:00:00", loc, "84000", ptype, json.dumps([ptype, "service"]),
                      extra.get("business_status", "OPERATIONAL"), f"https://maps.google.com/?cid={pid}&g_mp=x"))
        if businesses:
            conn.execute("""INSERT OR REPLACE INTO businesses (place_id, segment, category, categories, city, first_seen, source,
                            presence_class, presence_url, presence_checked, is_chain, chain_override)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (pid, seg, cat, json.dumps([cat]), f"{loc}, Utah", "2026-09-28", "scan_services", presence, web,
                          "2026-09-28T12:00:00", extra.get("is_chain", 0), None))
    conn.commit()
    conn.close()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--from", dest="src")
    ap.add_argument("--no-businesses", action="store_true")
    a = ap.parse_args()
    print(build(a.out, a.src, not a.no_businesses), file=sys.stderr)
