#!/usr/bin/env python3
"""
BVI Know Before You Go — GitHub Actions Pipeline

Generates the weekly charter briefing, pushes to GitLab Hugo repo,
triggers deploy, and saves Facebook post for email.

Environment variables (set as GitHub Secrets):
  OWM_API_KEY           - OpenWeatherMap API key
  GITLAB_REPO_URL       - GitLab repo HTTPS URL (e.g. https://gitlab.com/klarrious/boatyball/bbsite.git)
  GITLAB_USERNAME       - GitLab username for push
  GITLAB_ACCESS_TOKEN   - GitLab personal access token (write access)
  GITLAB_PROJECT_ID     - GitLab project path (e.g. klarrious/boatyball/bbsite)
  GITLAB_TRIGGER_TOKEN  - Pipeline trigger token
  EDITION               - pre-trip or arrival (optional, auto-detects)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bvi-briefing")

# ─── Config ──────────────────────────────────────────────────────────────────

OWM_API_KEY = os.getenv("OWM_API_KEY", "")
GITLAB_REPO_URL = os.getenv("GITLAB_REPO_URL", "https://gitlab.com/klarrious/boatyball/bbsite.git")
GITLAB_USERNAME = os.getenv("GITLAB_USERNAME", "")
GITLAB_ACCESS_TOKEN = os.getenv("GITLAB_ACCESS_TOKEN", "")
GITLAB_PROJECT_ID = os.getenv("GITLAB_PROJECT_ID", "klarrious/boatyball/bbsite")
GITLAB_TRIGGER_TOKEN = os.getenv("GITLAB_TRIGGER_TOKEN", "")
HUGO_CONTENT_DIR = "content/blog"
GIT_BRANCH = "master"
GIT_AUTHOR_NAME = "BoatyBall Bot"
GIT_AUTHOR_EMAIL = "bot@boatyball.com"

# BVI coordinates
BVI_LAT = 18.4267
BVI_LON = -64.62

# ─── BVI Holidays ────────────────────────────────────────────────────────────

BVI_HOLIDAYS = {
    "2025-01-01": {"name": "New Year's Day", "note": "Government offices and customs closed."},
    "2025-03-03": {"name": "H. Lavity Stoutt's Birthday", "note": "Government offices and customs closed."},
    "2025-04-18": {"name": "Good Friday", "note": "Government closed. No liquor sales until 6 PM."},
    "2025-04-19": {"name": "Easter Saturday", "note": "Limited services."},
    "2025-04-21": {"name": "Easter Monday", "note": "Government offices closed."},
    "2025-06-16": {"name": "Sovereign's Birthday", "note": "Government offices closed."},
    "2025-07-01": {"name": "Territory Day", "note": "Government offices closed."},
    "2025-08-04": {"name": "Festival Monday", "note": "Emancipation Festival. Government closed."},
    "2025-08-05": {"name": "Festival Tuesday", "note": "Emancipation Festival. Government closed."},
    "2025-08-06": {"name": "Festival Wednesday", "note": "Emancipation Festival. Government closed."},
    "2025-10-21": {"name": "St. Ursula's Day", "note": "Government offices closed."},
    "2025-11-28": {"name": "Remembrance Day (observed)", "note": "Government offices closed."},
    "2025-12-25": {"name": "Christmas Day", "note": "Government offices and customs closed."},
    "2025-12-26": {"name": "Boxing Day", "note": "Government offices closed."},
    "2026-01-01": {"name": "New Year's Day", "note": "Government offices and customs closed."},
    "2026-03-09": {"name": "H. Lavity Stoutt's Birthday (observed)", "note": "Government offices and customs closed."},
    "2026-04-03": {"name": "Good Friday", "note": "Government closed. No liquor sales until 6 PM."},
    "2026-04-04": {"name": "Easter Saturday", "note": "Limited services."},
    "2026-04-06": {"name": "Easter Monday", "note": "Government offices closed."},
    "2026-06-15": {"name": "Sovereign's Birthday", "note": "Government offices closed."},
    "2026-06-30": {"name": "250th Anniversary of Freedom at Nottingham Estate", "note": "One-off public holiday for 2026. Government offices closed."},
    "2026-07-01": {"name": "Territory Day", "note": "Government offices closed."},
    "2026-08-03": {"name": "Festival Monday", "note": "Emancipation Festival. Government closed 3 days."},
    "2026-08-04": {"name": "Festival Tuesday", "note": "Emancipation Festival. Government closed."},
    "2026-08-05": {"name": "Festival Wednesday", "note": "Emancipation Festival. Government closed."},
    "2026-10-21": {"name": "St. Ursula's Day", "note": "Government offices closed."},
    "2026-11-27": {"name": "Remembrance Day (observed)", "note": "Government offices closed."},
    "2026-12-25": {"name": "Christmas Day", "note": "Government offices and customs closed."},
    "2026-12-26": {"name": "Boxing Day", "note": "Government offices closed."},
    "2027-01-01": {"name": "New Year's Day", "note": "Government offices and customs closed."},
    "2027-03-01": {"name": "H. Lavity Stoutt's Birthday", "note": "Government offices and customs closed."},
    "2027-03-26": {"name": "Good Friday", "note": "Government closed. No liquor sales until 6 PM."},
    "2027-03-27": {"name": "Easter Saturday", "note": "Limited services."},
    "2027-03-29": {"name": "Easter Monday", "note": "Government offices closed."},
}

# ─── BVI Events & Regattas ───────────────────────────────────────────────────

BVI_EVENTS = [
    {"name": "Dark and Stormy Regatta", "start": "2026-02-14", "end": "2026-02-14",
     "impact": "Racing near West End. Minimal mooring impact."},
    {"name": "51st BVI Spring Regatta & Sailing Festival", "start": "2026-03-23", "end": "2026-03-29",
     "impact": "Major event — Nanny Cay, Norman Island, Peter Island, and Cooper Island moorings will be very busy. Book early!"},
    {"name": "Governor's Cup Regatta", "start": "2026-04-25", "end": "2026-04-25",
     "impact": "Racing in Sir Francis Drake Channel. Some mooring areas may be busy."},
    {"name": "The Moorings Interline Regatta", "start": "2026-10-20", "end": "2026-10-29",
     "impact": "Charter fleet event. Popular anchorages busier than usual."},
]

# ─── Helper Functions ────────────────────────────────────────────────────────

def fetch_json(url):
    """Fetch JSON from a URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BoatyBall-BVI-Briefing/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.error(f"Failed to fetch {url}: {e}")
        return None


def wind_description(speed_knots):
    """Convert wind speed in knots to a sailor-friendly description."""
    if speed_knots < 1:
        return "Calm"
    elif speed_knots < 4:
        return "Light air"
    elif speed_knots < 7:
        return "Light breeze"
    elif speed_knots < 11:
        return "Gentle breeze"
    elif speed_knots < 17:
        return "Moderate breeze"
    elif speed_knots < 22:
        return "Fresh breeze"
    elif speed_knots < 28:
        return "Strong breeze"
    elif speed_knots < 34:
        return "Near gale"
    elif speed_knots < 41:
        return "Gale"
    else:
        return "Storm"


def sea_state(wave_height_m):
    """Convert wave height in meters to sea state description."""
    if wave_height_m is None:
        return "Unknown"
    elif wave_height_m < 0.1:
        return "Calm (glassy)"
    elif wave_height_m < 0.5:
        return "Calm (rippled)"
    elif wave_height_m < 1.25:
        return "Smooth"
    elif wave_height_m < 2.5:
        return "Slight"
    elif wave_height_m < 4.0:
        return "Moderate"
    elif wave_height_m < 6.0:
        return "Rough"
    else:
        return "Very rough"


def degrees_to_cardinal(deg):
    """Convert degrees to cardinal direction."""
    if deg is None:
        return "N/A"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(deg / 22.5) % 16
    return dirs[idx]


def ms_to_knots(ms):
    return ms * 1.94384 if ms else 0


def m_to_ft(m):
    return m * 3.28084 if m else 0


def c_to_f(c):
    return c * 9 / 5 + 32 if c is not None else None


# ─── Data Fetchers ───────────────────────────────────────────────────────────

def fetch_weather(week_start):
    """Fetch weather from OpenWeatherMap 5-day forecast."""
    if not OWM_API_KEY:
        log.warning("No OWM_API_KEY set — skipping weather")
        return None

    log.info("Fetching weather from OpenWeatherMap...")
    url = (f"https://api.openweathermap.org/data/2.5/forecast?"
           f"lat={BVI_LAT}&lon={BVI_LON}&appid={OWM_API_KEY}&units=metric")

    data = fetch_json(url)
    if not data or "list" not in data:
        log.error("Weather fetch failed")
        return None

    daily = {}
    week_end = week_start + timedelta(days=7)

    for entry in data["list"]:
        dt = datetime.fromtimestamp(entry["dt"])
        date_str = dt.strftime("%Y-%m-%d")

        entry_date = datetime.strptime(date_str, "%Y-%m-%d")
        if entry_date < week_start or entry_date >= week_end:
            continue

        if date_str not in daily:
            daily[date_str] = {
                "date": date_str,
                "day_name": entry_date.strftime("%A"),
                "temps": [], "winds": [], "gusts": [], "wind_dirs": [],
                "descriptions": [], "rain": 0,
            }

        d = daily[date_str]
        d["temps"].append(entry["main"]["temp"])
        wind = entry.get("wind", {})
        d["winds"].append(wind.get("speed", 0))
        d["gusts"].append(wind.get("gust", wind.get("speed", 0)))
        d["wind_dirs"].append(wind.get("deg", 0))
        d["descriptions"].append(entry["weather"][0]["description"])
        d["rain"] += entry.get("rain", {}).get("3h", 0)

    result = []
    for date_str in sorted(daily.keys()):
        d = daily[date_str]
        avg_wind_ms = sum(d["winds"]) / len(d["winds"])
        max_gust_ms = max(d["gusts"]) if d["gusts"] else 0
        avg_dir = sum(d["wind_dirs"]) / len(d["wind_dirs"])

        result.append({
            "date": date_str,
            "day_name": d["day_name"],
            "temp_high_c": max(d["temps"]),
            "temp_low_c": min(d["temps"]),
            "temp_high_f": round(c_to_f(max(d["temps"]))),
            "temp_low_f": round(c_to_f(min(d["temps"]))),
            "wind_knots": round(ms_to_knots(avg_wind_ms)),
            "gust_knots": round(ms_to_knots(max_gust_ms)),
            "wind_dir": degrees_to_cardinal(avg_dir),
            "wind_desc": wind_description(ms_to_knots(avg_wind_ms)),
            "description": max(set(d["descriptions"]), key=d["descriptions"].count),
            "rain_mm": round(d["rain"], 1),
        })

    return result if result else None


def fetch_marine(week_start):
    """Fetch marine forecast from Open-Meteo."""
    log.info("Fetching marine forecast from Open-Meteo...")
    end_date = week_start + timedelta(days=6)
    url = (f"https://marine-api.open-meteo.com/v1/marine?"
           f"latitude={BVI_LAT}&longitude={BVI_LON}"
           f"&daily=wave_height_max,wave_direction_dominant,wave_period_max,"
           f"swell_wave_height_max,swell_wave_direction_dominant,swell_wave_period_max"
           f"&start_date={week_start.strftime('%Y-%m-%d')}"
           f"&end_date={end_date.strftime('%Y-%m-%d')}"
           f"&timezone=America/Virgin")

    data = fetch_json(url)
    if not data or "daily" not in data:
        log.warning("Marine forecast unavailable")
        return None

    daily = data["daily"]
    result = []
    for i, date_str in enumerate(daily.get("time", [])):
        wave_h = daily["wave_height_max"][i] if daily.get("wave_height_max") else None
        swell_h = daily["swell_wave_height_max"][i] if daily.get("swell_wave_height_max") else None
        wave_dir = daily["wave_direction_dominant"][i] if daily.get("wave_direction_dominant") else None

        result.append({
            "date": date_str,
            "wave_height_m": wave_h,
            "wave_height_ft": round(m_to_ft(wave_h), 1) if wave_h else None,
            "wave_dir": degrees_to_cardinal(wave_dir) if wave_dir else "N/A",
            "swell_height_m": swell_h,
            "swell_height_ft": round(m_to_ft(swell_h), 1) if swell_h else None,
            "sea_state": sea_state(wave_h) if wave_h else "Unknown",
        })
    return result


def load_cruise_ships(week_start):
    """Load cruise ship data from bvi_cruise_schedule.json."""
    log.info("Loading cruise ship schedule...")
    json_path = Path(__file__).parent / "bvi_cruise_schedule.json"

    if not json_path.exists():
        log.warning(f"No cruise schedule at {json_path}")
        return []

    try:
        all_ships = json.loads(json_path.read_text())
    except Exception as e:
        log.error(f"Failed to read cruise schedule: {e}")
        return []

    ships = []
    week_end = week_start + timedelta(days=7)
    for entry in all_ships:
        try:
            visit_date = datetime.strptime(entry["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        if week_start <= visit_date < week_end:
            ships.append({
                "date": entry["date"],
                "day_name": visit_date.strftime("%A"),
                "ship": entry.get("ship", "Unknown"),
                "cruise_line": entry.get("cruise_line", ""),
                "passengers": entry.get("passengers"),
            })
    return ships


def get_holidays(week_start):
    """Return BVI holidays in the given week."""
    holidays = []
    for day_offset in range(7):
        check_date = week_start + timedelta(days=day_offset)
        date_str = check_date.strftime("%Y-%m-%d")
        if date_str in BVI_HOLIDAYS:
            h = BVI_HOLIDAYS[date_str].copy()
            h["date"] = date_str
            h["day_name"] = check_date.strftime("%A")
            holidays.append(h)
    return holidays


def get_events(week_start):
    """Return events overlapping the given week."""
    events = []
    week_end = week_start + timedelta(days=6)
    for ev in BVI_EVENTS:
        ev_start = datetime.strptime(ev["start"], "%Y-%m-%d")
        ev_end = datetime.strptime(ev["end"], "%Y-%m-%d")
        if ev_start <= week_end and ev_end >= week_start:
            events.append(ev)
    return events


# ─── Content Generators ──────────────────────────────────────────────────────

def generate_advisories(weather, marine, ships, holidays, events):
    """Generate captain's advisory items."""
    advisories = []

    if weather:
        max_gust = max(d["gust_knots"] for d in weather)
        if max_gust >= 25:
            advisories.append(f"💨 **Wind Advisory:** Gusts up to {max_gust} kts expected. "
                            f"Secure dinghies and check mooring lines.")

    if marine:
        max_wave = max(d["wave_height_ft"] for d in marine if d["wave_height_ft"])
        if max_wave and max_wave >= 5:
            advisories.append(f"🌊 **Sea State Advisory:** Waves up to {max_wave:.1f} ft. "
                            f"Drake Channel crossing may be uncomfortable.")

    if ships:
        total_pax = sum(s.get("passengers", 0) or 0 for s in ships)
        if total_pax > 5000:
            advisories.append(f"🚢 **Cruise Ship Alert:** {len(ships)} cruise ships visiting "
                            f"({total_pax:,} passengers). Road Town, The Baths, and Jost Van Dyke "
                            f"will be busier on ship days.")

    for h in holidays:
        advisories.append(f"🏛️ **{h['name']} ({h['day_name']}, {h['date']}):** {h['note']} "
                        f"Plan your customs/immigration needs accordingly.")

    for ev in events:
        advisories.append(f"⛵ **{ev['name']}** ({ev['start']} to {ev['end']}): {ev['impact']}")

    return advisories


def generate_hugo_post(week_start, weather, marine, ships, holidays, events, advisories, edition):
    """Generate a Hugo markdown blog post."""
    week_end = week_start + timedelta(days=6)
    edition_label = "Pre-Trip Edition" if edition == "pre-trip" else "Arrival Edition"
    title = (f"Know Before You Go: BVI Charter Briefing — "
             f"{week_start.strftime('%b %d')}–{week_end.strftime('%b %d, %Y')} "
             f"({edition_label})")
    slug = f"bvi-know-before-you-go-{week_start.strftime('%Y-%m-%d')}-{edition}"
    pub_date = datetime.now().strftime("%Y-%m-%d") + "T06:00:00-04:00"
    description = (f"Your weekly BVI charter captain's briefing for "
                   f"{week_start.strftime('%B %d')}–{week_end.strftime('%B %d, %Y')}. "
                   f"Weather, cruise ships, holidays, regattas, and everything you need to know.")

    lines = []

    # Frontmatter (matches BoatyBall site format)
    lines.append("---")
    lines.append(f'title: "{title}"')
    lines.append(f'description: "{description}"')
    lines.append(f'date: {pub_date}')
    lines.append(f'categories: ["Weekly Briefing", "Planning", "BVI Charter"]')
    lines.append(f'tags:')
    lines.append(f'  [')
    lines.append(f'    "BoatyBall",')
    lines.append(f'    "British Virgin Islands Moorings",')
    lines.append(f'    "BVI Charter",')
    lines.append(f'    "Know Before You Go",')
    lines.append(f'    "Weekly Briefing",')
    lines.append(f'    "BVI Weather",')
    lines.append(f'    "Cruise Ships",')
    lines.append(f'  ]')
    lines.append(f'image: /assets/img/blog/bvi-know-before-you-go.jpg')
    lines.append(f'search: true')
    lines.append(f'featured: True')
    lines.append("---")
    lines.append("")

    # Intro
    if edition == "pre-trip":
        lines.append(f"🗓️ **{edition_label}** — Planning your trip? Here's what to expect "
                     f"for your charter week starting **{week_start.strftime('%A, %B %d')}** "
                     f"through **{week_end.strftime('%A, %B %d, %Y')}**.")
        lines.append("")
        lines.append("Use this briefing to plan your provisioning, pick your itinerary, "
                     "and know what to expect when you arrive. We'll publish an updated "
                     "**Arrival Edition** on Saturday with the latest conditions.")
    else:
        lines.append(f"⚓ **{edition_label}** — Welcome to the BVI! Here's your updated briefing "
                     f"for your charter week: **{week_start.strftime('%A, %B %d')}** "
                     f"through **{week_end.strftime('%A, %B %d, %Y')}**.")
        lines.append("")
        lines.append("Fresh weather data, updated sea conditions, and everything you need "
                     "to plan your week on the water.")
    lines.append("")

    # Captain's Advisory
    if advisories:
        lines.append("## ⚠️ Captain's Advisory")
        lines.append("")
        for a in advisories:
            lines.append(f"- {a}")
            lines.append("")

    # Weather
    lines.append("## 🌤️ 7-Day Marine Weather Forecast")
    lines.append("")
    if weather:
        lines.append("| Day | Temp | Wind | Gusts | Direction | Conditions | Rain |")
        lines.append("|-----|------|------|-------|-----------|------------|------|")
        for d in weather:
            lines.append(f"| {d['day_name'][:3]} {d['date'][5:]} "
                        f"| {d['temp_high_f']}°F | {d['wind_knots']} kts "
                        f"| {d['gust_knots']} kts | {d['wind_dir']} "
                        f"| {d['description'].title()} | {d['rain_mm']}mm |")
        lines.append("")
    else:
        lines.append("*Weather data not yet available — check back closer to your charter date.*")
        lines.append("")

    # Sea Conditions
    lines.append("## 🌊 Sea Conditions")
    lines.append("")
    if marine:
        lines.append("| Day | Wave Height | Sea State | Swell |")
        lines.append("|-----|-------------|-----------|-------|")
        for d in marine:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            swell = f"{d['swell_height_ft']} ft" if d.get("swell_height_ft") else "—"
            lines.append(f"| {dt.strftime('%a %m/%d')} | {d['wave_height_ft']} ft "
                        f"| {d['sea_state']} | {swell} |")
        lines.append("")
    else:
        lines.append("*Marine forecast unavailable.*")
        lines.append("")

    # Cruise Ships
    lines.append("## 🚢 Cruise Ship Schedule")
    lines.append("")
    if ships:
        lines.append("| Day | Ship | Cruise Line | Passengers |")
        lines.append("|-----|------|-------------|------------|")
        for s in sorted(ships, key=lambda x: x["date"]):
            pax = f"{s['passengers']:,}" if s.get("passengers") else "N/A"
            lines.append(f"| {s['day_name'][:3]} {s['date'][5:]} "
                        f"| {s['ship']} | {s['cruise_line']} | {pax} |")
        lines.append("")

        total_pax = sum(s.get("passengers", 0) or 0 for s in ships)
        seen = set()
        ship_days = []
        for s in sorted(ships, key=lambda x: x["date"]):
            if s["day_name"] not in seen:
                seen.add(s["day_name"])
                ship_days.append(s["day_name"])

        lines.append(f"**Impact:** On cruise ship days ({', '.join(ship_days)}), expect heavier "
                     f"traffic at The Baths, Road Town waterfront, and popular "
                     f"beach bars at Jost Van Dyke.")
        lines.append("")
    else:
        lines.append("No cruise ships scheduled this week — enjoy the quieter waters! 🎉")
        lines.append("")

    # Holidays
    lines.append("## 🏛️ BVI Holidays & Government Closures")
    lines.append("")
    if holidays:
        for h in holidays:
            lines.append(f"- **{h['name']}** ({h['day_name']}, {h['date']}): {h['note']}")
            lines.append("")
    else:
        lines.append("No public holidays this week. Government offices and customs on normal hours.")
        lines.append("")

    # Events
    lines.append("## ⛵ Regattas & Sailing Events")
    lines.append("")
    if events:
        for ev in events:
            lines.append(f"- **{ev['name']}** ({ev['start']} to {ev['end']}): {ev['impact']}")
            lines.append("")
    else:
        lines.append("No major regattas or events this week.")
        lines.append("")

    # Links
    lines.append("## 🔗 Useful Links")
    lines.append("")
    lines.append("- [BoatyBall Mooring Reservations](https://www.boatyball.com) — Reserve your moorings now!")
    lines.append("- [BVI Customs & Immigration](https://bvi.gov.vg) — Hours and requirements")
    lines.append("- [Windy.com - BVI](https://www.windy.com/?18.428,-64.619,10) — Real-time wind and weather")
    lines.append("- [Marine Traffic - BVI](https://www.marinetraffic.com/en/ais/home/centerx:-64.6/centery:18.4/zoom:11) — See ships in real-time")
    lines.append("- [BVI Tourism](https://www.bvitourism.com) — Official BVI tourism info")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*This briefing is brought to you by [BoatyBall](https://www.boatyball.com) — "
                 "the easiest way to reserve moorings in the BVI. Book your balls before you go!*")
    lines.append("")
    lines.append(f"*Published {datetime.now().strftime('%B %d, %Y')}. "
                 f"Weather data from OpenWeatherMap & Open-Meteo. "
                 f"Cruise schedule sourced from CruiseDig.com. "
                 f"Always confirm conditions before departure.*")

    return "\n".join(lines)


def generate_facebook_post(week_start, weather, marine, ships, holidays, events, advisories, edition):
    """Generate a Facebook-friendly text version."""
    week_end = week_start + timedelta(days=6)
    edition_label = "PRE-TRIP" if edition == "pre-trip" else "ARRIVAL"
    slug = f"bvi-know-before-you-go-{week_start.strftime('%Y-%m-%d')}-{edition}"

    lines = []
    lines.append(f"⚓ BVI KNOW BEFORE YOU GO — {week_start.strftime('%b %d')}–{week_end.strftime('%b %d, %Y')} ({edition_label})")
    lines.append(f"Your charter week briefing from BoatyBall!")
    if edition == "pre-trip":
        lines.append("📋 Planning your trip? Here's what to expect this week:")
    else:
        lines.append("🏝️ Welcome to the BVI! Here's your updated conditions report:")
    lines.append("")

    # Weather summary
    if weather:
        temps = [d["temp_high_f"] for d in weather]
        winds = [d["wind_knots"] for d in weather]
        lines.append(f"🌡️ TEMPS: {min(temps)}–{max(temps)}°F")
        lines.append(f"💨 WINDS: {min(winds)}–{max(winds)} kts ({weather[0]['wind_dir']})")
        lines.append("")

    # Sea conditions
    if marine:
        max_wave = max(d["wave_height_ft"] for d in marine if d["wave_height_ft"])
        if max_wave:
            lines.append(f"🌊 SEAS: Waves up to {max_wave:.1f} ft")
            lines.append("")

    # Cruise ships
    if ships:
        seen_fb = set()
        ship_days = []
        for s in sorted(ships, key=lambda x: x["date"]):
            abbr = s["day_name"][:3]
            if abbr not in seen_fb:
                seen_fb.add(abbr)
                ship_days.append(abbr)
        total_pax = sum(s.get("passengers", 0) or 0 for s in ships)
        lines.append(f"🚢 CRUISE SHIPS: {len(ships)} ship(s) in port this week ({', '.join(ship_days)})")
        if total_pax:
            lines.append(f"   ~{total_pax:,} passengers — plan around busy days at The Baths & Jost!")
        lines.append("")

    # Holidays
    if holidays:
        lines.append("🏛️ GOVERNMENT HOLIDAY:")
        for h in holidays:
            lines.append(f"  {h['day_name']}: {h['name']} — Customs CLOSED")
        lines.append("")

    # Events
    if events:
        for ev in events:
            lines.append(f"⛵ {ev['name'].upper()}: {ev['impact']}")
            lines.append("")

    lines.append(f"📌 Reserve your moorings: www.boatyball.com")
    lines.append(f"📖 Full briefing on our blog: https://boatyball.com/blog/{slug}.html")
    lines.append("")
    lines.append("#BVI #CharterSailing #KnowBeforeYouGo #BoatyBall #SailingBVI "
                 "#BritishVirginIslands #BareboatCharter #SailingLife")

    return "\n".join(lines)


# ─── GitLab Integration ──────────────────────────────────────────────────────

def push_to_gitlab(filename, content):
    """Clone GitLab repo, add file, commit, push."""
    import git

    repo_path = Path("/tmp/boatyball-hugo")

    # Clone if not already there
    if repo_path.exists():
        import shutil
        shutil.rmtree(repo_path)

    auth_url = GITLAB_REPO_URL.replace(
        "https://", f"https://{GITLAB_USERNAME}:{GITLAB_ACCESS_TOKEN}@"
    )
    log.info(f"Cloning Hugo repo...")
    subprocess.run(["git", "clone", "--depth", "1", auth_url, str(repo_path)],
                   check=True, capture_output=True)

    # Write the file
    dest_dir = repo_path / HUGO_CONTENT_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / filename
    dest_file.write_text(content, encoding="utf-8")
    log.info(f"Wrote: {dest_file}")

    # Git config and commit
    repo = git.Repo(repo_path)
    repo.config_writer().set_value("user", "name", GIT_AUTHOR_NAME).release()
    repo.config_writer().set_value("user", "email", GIT_AUTHOR_EMAIL).release()

    repo.index.add([str(dest_file.relative_to(repo_path))])
    repo.index.commit(f"Add BVI briefing: {filename}")

    log.info("Pushing to GitLab...")
    repo.remotes.origin.push()
    log.info("Push complete!")


def trigger_deploy():
    """Trigger the GitLab deploy pipeline."""
    if not GITLAB_TRIGGER_TOKEN or not GITLAB_PROJECT_ID:
        log.warning("No trigger token/project ID — skipping deploy trigger")
        return False

    try:
        project_encoded = urllib.parse.quote(GITLAB_PROJECT_ID, safe="")
        url = f"https://gitlab.com/api/v4/projects/{project_encoded}/trigger/pipeline"
        data = urllib.parse.urlencode({
            "token": GITLAB_TRIGGER_TOKEN,
            "ref": GIT_BRANCH,
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode())
        pipeline_id = result.get("id", "?")
        log.info(f"Deploy triggered! Pipeline #{pipeline_id}")
        return True
    except Exception as e:
        log.error(f"Deploy trigger failed: {e}")
        return False


# ─── Main Pipeline ───────────────────────────────────────────────────────────

def run_pipeline(edition="auto"):
    log.info("=== BVI Know Before You Go Pipeline ===")

    # Determine edition
    if edition == "auto":
        dow = datetime.now().weekday()
        edition = "pre-trip" if dow in (2, 3, 4) else "arrival"

    edition_label = "Pre-Trip Edition" if edition == "pre-trip" else "Arrival Edition"

    # Determine charter week (Saturday to Friday)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        week_start = today
    elif today.weekday() < 5:
        week_start = today + timedelta(days=days_until_saturday)
    else:
        week_start = today + timedelta(days=6)

    week_end = week_start + timedelta(days=6)
    log.info(f"Charter Week: {week_start.strftime('%A %b %d')} – {week_end.strftime('%A %b %d, %Y')}")
    log.info(f"Edition: {edition_label}")

    # Fetch data
    weather = fetch_weather(week_start)
    marine = fetch_marine(week_start)
    ships = load_cruise_ships(week_start)
    holidays = get_holidays(week_start)
    events = get_events(week_start)

    log.info(f"Data: weather={len(weather) if weather else 0}, marine={len(marine) if marine else 0}, "
             f"ships={len(ships)}, holidays={len(holidays)}, events={len(events)}")

    # Generate content
    advisories = generate_advisories(weather, marine, ships, holidays, events)
    hugo_content = generate_hugo_post(week_start, weather, marine, ships, holidays, events, advisories, edition)
    fb_content = generate_facebook_post(week_start, weather, marine, ships, holidays, events, advisories, edition)

    slug = f"bvi-know-before-you-go-{week_start.strftime('%Y-%m-%d')}-{edition}"
    hugo_filename = f"{slug}.md"

    # Save Facebook post locally (for email step)
    fb_path = Path(f"facebook-post-{week_start.strftime('%Y-%m-%d')}-{edition}.txt")
    fb_post_content = (
        f"FACEBOOK POST — {edition_label}\n"
        f"{'=' * 60}\n"
        f"POST LINK: https://boatyball.com/blog/{slug}.html\n"
        f"{'=' * 60}\n\n"
        f"{fb_content}\n\n"
        f"{'=' * 60}\n"
        f"Post at: https://business.facebook.com\n"
    )
    fb_path.write_text(fb_post_content, encoding="utf-8")
    log.info(f"Facebook post saved: {fb_path}")

    # Push to GitLab
    if GITLAB_ACCESS_TOKEN:
        try:
            push_to_gitlab(hugo_filename, hugo_content)
            trigger_deploy()
        except Exception as e:
            log.error(f"GitLab push failed: {e}")
    else:
        log.warning("No GITLAB_ACCESS_TOKEN — skipping push")
        # Save locally instead
        Path(hugo_filename).write_text(hugo_content)
        log.info(f"Saved locally: {hugo_filename}")

    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BVI Know Before You Go Pipeline")
    parser.add_argument("--edition", default="auto", choices=["auto", "pre-trip", "arrival"])
    parser.add_argument("--dry-run", action="store_true", help="Generate without pushing")
    args = parser.parse_args()

    if args.dry_run:
        os.environ.pop("GITLAB_ACCESS_TOKEN", None)

    run_pipeline(edition=args.edition)
