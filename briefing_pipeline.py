#!/usr/bin/env python3
"""
BVI Know Before You Go — Social Media Edition

Generates the weekly charter briefing and produces ready-to-post content for:
  - Facebook
  - Instagram
  - X (Twitter)
  - Mighty Networks

No website publishing. No GitLab. No Hugo. Social media only.

Environment variables (set as GitHub Secrets or .env):
  OWM_API_KEY           - OpenWeatherMap API key
  FACEBOOK_PAGE_ID      - Facebook Page ID
  FACEBOOK_ACCESS_TOKEN - Facebook Page access token
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bvi-briefing")

# ─── Config ──────────────────────────────────────────────────────────────────

OWM_API_KEY           = os.getenv("OWM_API_KEY", "")
FACEBOOK_PAGE_ID      = os.getenv("FACEBOOK_PAGE_ID", "")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN", "")

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
    {"name": "Hillbilly Flotilla", "start": "2026-03-07", "end": "2026-03-14",
     "impact": "Large flotilla group — expect busier moorings at Jost Van Dyke (Mar 8), Bitter End/North Sound (Mar 9), Anegada (Mar 10), Leverick Bay (Mar 11), Norman Island (Mar 12), and Cooper Island (Mar 13). Book moorings early!"},
    {"name": "Salty Dog Rally", "start": "2026-03-07", "end": "2026-03-08",
     "impact": "11+ boat flotilla at Anegada (Mar 7–8). Expect busier anchorage and mooring field at Anegada's Setting Point."},
    {"name": "Governor's Cup Regatta", "start": "2026-04-25", "end": "2026-04-25",
     "impact": "Racing in Sir Francis Drake Channel. Some mooring areas may be busy."},
    {"name": "The Moorings Interline Regatta", "start": "2026-10-20", "end": "2026-10-29",
     "impact": "Charter fleet event. Popular anchorages busier than usual."},
]

# ─── Helper Functions ────────────────────────────────────────────────────────

def fetch_json(url):
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BoatyBall-BVI-Briefing/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.error(f"Failed to fetch {url}: {e}")
        return None


def wind_description(speed_knots):
    if speed_knots < 1:   return "Calm"
    elif speed_knots < 4:  return "Light air"
    elif speed_knots < 7:  return "Light breeze"
    elif speed_knots < 11: return "Gentle breeze"
    elif speed_knots < 17: return "Moderate breeze"
    elif speed_knots < 22: return "Fresh breeze"
    elif speed_knots < 28: return "Strong breeze"
    elif speed_knots < 34: return "Near gale"
    elif speed_knots < 41: return "Gale"
    else:                  return "Storm"


def sea_state(wave_height_m):
    if wave_height_m is None:  return "Unknown"
    elif wave_height_m < 0.1:  return "Calm (glassy)"
    elif wave_height_m < 0.5:  return "Calm (rippled)"
    elif wave_height_m < 1.25: return "Smooth"
    elif wave_height_m < 2.5:  return "Slight"
    elif wave_height_m < 4.0:  return "Moderate"
    elif wave_height_m < 6.0:  return "Rough"
    else:                      return "Very rough"


def degrees_to_cardinal(deg):
    if deg is None: return "N/A"
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(deg / 22.5) % 16]


def ms_to_knots(ms): return ms * 1.94384 if ms else 0
def m_to_ft(m):      return m * 3.28084 if m else 0
def c_to_f(c):       return c * 9 / 5 + 32 if c is not None else None


# ─── Data Fetchers ───────────────────────────────────────────────────────────

def fetch_weather(week_start):
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
            "temp_high_f": round(c_to_f(max(d["temps"]))),
            "temp_low_f":  round(c_to_f(min(d["temps"]))),
            "wind_knots":  round(ms_to_knots(avg_wind_ms)),
            "gust_knots":  round(ms_to_knots(max_gust_ms)),
            "wind_dir":    degrees_to_cardinal(avg_dir),
            "wind_desc":   wind_description(ms_to_knots(avg_wind_ms)),
            "description": max(set(d["descriptions"]), key=d["descriptions"].count),
            "rain_mm":     round(d["rain"], 1),
        })

    return result if result else None


def fetch_marine(week_start):
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
        wave_h  = daily["wave_height_max"][i] if daily.get("wave_height_max") else None
        swell_h = daily["swell_wave_height_max"][i] if daily.get("swell_wave_height_max") else None
        wave_dir = daily["wave_direction_dominant"][i] if daily.get("wave_direction_dominant") else None
        result.append({
            "date":           date_str,
            "wave_height_ft": round(m_to_ft(wave_h), 1) if wave_h else None,
            "swell_height_ft":round(m_to_ft(swell_h), 1) if swell_h else None,
            "sea_state":      sea_state(wave_h) if wave_h else "Unknown",
        })
    return result


def load_cruise_ships(week_start):
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
                "date":       entry["date"],
                "day_name":   visit_date.strftime("%A"),
                "ship":       entry.get("ship", "Unknown"),
                "cruise_line":entry.get("cruise_line", ""),
                "passengers": entry.get("passengers"),
            })
    return ships


def get_holidays(week_start):
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
    events = []
    week_end = week_start + timedelta(days=6)
    for ev in BVI_EVENTS:
        ev_start = datetime.strptime(ev["start"], "%Y-%m-%d")
        ev_end   = datetime.strptime(ev["end"],   "%Y-%m-%d")
        if ev_start <= week_end and ev_end >= week_start:
            events.append(ev)
    return events


def generate_advisories(weather, marine, ships, holidays, events):
    advisories = []

    if weather:
        max_gust = max(d["gust_knots"] for d in weather)
        if max_gust >= 25:
            advisories.append(f"💨 Wind Advisory: Gusts up to {max_gust} kts expected. "
                              f"Secure dinghies and check mooring lines.")

    if marine:
        wave_heights = [d["wave_height_ft"] for d in marine if d["wave_height_ft"]]
        if wave_heights:
            max_wave = max(wave_heights)
            if max_wave >= 5:
                advisories.append(f"🌊 Sea State Advisory: Waves up to {max_wave:.1f} ft. "
                                  f"Drake Channel crossing may be uncomfortable.")

    if ships:
        total_pax = sum(s.get("passengers", 0) or 0 for s in ships)
        if total_pax > 5000:
            advisories.append(f"🚢 Cruise Ship Alert: {len(ships)} cruise ships visiting "
                              f"({total_pax:,} passengers). Road Town, The Baths, and Jost Van Dyke "
                              f"will be busier on ship days.")

    for h in holidays:
        advisories.append(f"🏛️ {h['name']} ({h['day_name']}): {h['note']} "
                          f"Plan your customs/immigration needs accordingly.")

    for ev in events:
        advisories.append(f"⛵ {ev['name']} ({ev['start']} to {ev['end']}): {ev['impact']}")

    return advisories


# ─── Social Media Post Builders ──────────────────────────────────────────────

def build_facebook_post(week_start, weather, marine, ships, holidays, events, advisories, edition):
    """Facebook — detailed, conversational, full briefing."""
    week_end = week_start + timedelta(days=6)
    edition_label = "PRE-TRIP BRIEFING" if edition == "pre-trip" else "ARRIVAL BRIEFING"

    lines = []
    lines.append(f"⚓ BVI KNOW BEFORE YOU GO — {week_start.strftime('%b %d')}–{week_end.strftime('%b %d, %Y')}")
    lines.append(f"📋 {edition_label}")
    lines.append("")

    if edition == "pre-trip":
        lines.append("Planning your BVI charter? Here's everything you need to know before you go!")
    else:
        lines.append("Welcome to the BVI! Here's your updated conditions and planning report for the week.")
    lines.append("")

    if advisories:
        lines.append("⚠️ THIS WEEK'S ADVISORIES")
        for a in advisories:
            lines.append(f"• {a}")
        lines.append("")

    if weather:
        temps = [d["temp_high_f"] for d in weather]
        winds = [d["wind_knots"] for d in weather]
        gusts = [d["gust_knots"] for d in weather]
        lines.append("🌤️ WEATHER SNAPSHOT")
        lines.append(f"🌡️ Temps: {min(temps)}–{max(temps)}°F")
        lines.append(f"💨 Winds: {min(winds)}–{max(winds)} kts ({weather[0]['wind_dir']}), gusts to {max(gusts)} kts")
        if marine:
            wave_heights = [d["wave_height_ft"] for d in marine if d["wave_height_ft"]]
            if wave_heights:
                lines.append(f"🌊 Seas: Up to {max(wave_heights):.1f} ft")
        lines.append("")

    if ships:
        seen = set()
        ship_days = []
        for s in sorted(ships, key=lambda x: x["date"]):
            if s["day_name"] not in seen:
                seen.add(s["day_name"])
                ship_days.append(s["day_name"])
        total_pax = sum(s.get("passengers", 0) or 0 for s in ships)
        lines.append("🚢 CRUISE SHIPS IN PORT")
        lines.append(f"{len(ships)} ship(s) this week — {', '.join(ship_days)}")
        if total_pax:
            lines.append(f"~{total_pax:,} passengers — plan around busy days at The Baths & Jost!")
        lines.append("")

    if holidays:
        lines.append("🏛️ GOVERNMENT HOLIDAYS")
        for h in holidays:
            lines.append(f"• {h['day_name']}: {h['name']} — {h['note']}")
        lines.append("")

    if events:
        lines.append("⛵ REGATTAS & EVENTS")
        for ev in events:
            lines.append(f"• {ev['name']} ({ev['start']} to {ev['end']})")
            lines.append(f"  {ev['impact']}")
        lines.append("")

    lines.append("🔗 USEFUL LINKS")
    lines.append("• Windy BVI: windy.com/?18.428,-64.619,10")
    lines.append("• BVI Customs: bvi.gov.vg")
    lines.append("• Marine Traffic: marinetraffic.com")
    lines.append("")
    lines.append("⚓ When in doubt, don't go out!")
    lines.append("")
    lines.append("#BVI #KnowBeforeYouGo #BoatyBall #BVICharter #SailingBVI "
                 "#BritishVirginIslands #BareboatCharter #SailingLife #CaribbeanSailing")

    return "\n".join(lines)


def build_instagram_post(week_start, weather, marine, ships, holidays, events, advisories, edition):
    """Instagram — visual-first, punchy, emoji-heavy, hashtag block."""
    week_end = week_start + timedelta(days=6)
    edition_tag = "PRE-TRIP" if edition == "pre-trip" else "ARRIVAL"

    lines = []
    lines.append(f"⚓ BVI KNOW BEFORE YOU GO — {week_start.strftime('%b %d').upper()}–{week_end.strftime('%b %d').upper()}")
    lines.append(f"📋 {edition_tag} EDITION")
    lines.append("")

    if weather:
        temps = [d["temp_high_f"] for d in weather]
        winds = [d["wind_knots"] for d in weather]
        lines.append(f"🌡️ {min(temps)}–{max(temps)}°F")
        lines.append(f"💨 {min(winds)}–{max(winds)} kts {weather[0]['wind_dir']}")

    if marine:
        wave_heights = [d["wave_height_ft"] for d in marine if d["wave_height_ft"]]
        if wave_heights:
            lines.append(f"🌊 Seas up to {max(wave_heights):.1f} ft")

    lines.append("")

    if ships:
        total_pax = sum(s.get("passengers", 0) or 0 for s in ships)
        lines.append(f"🚢 {len(ships)} cruise ship(s) in port this week")
        if total_pax:
            lines.append(f"   ~{total_pax:,} passengers — plan accordingly!")
        lines.append("")

    if holidays:
        for h in holidays:
            lines.append(f"🏛️ {h['name']} — {h['day_name']}")
        lines.append("")

    if events:
        for ev in events:
            lines.append(f"⛵ {ev['name']}")
        lines.append("")

    if advisories:
        lines.append("⚠️ Check advisories before heading out!")
        lines.append("")

    lines.append("⚓ When in doubt, don't go out!")
    lines.append("")
    lines.append(".")
    lines.append(".")
    lines.append(".")
    lines.append(
        "#BVI #KnowBeforeYouGo #BoatyBall #BVICharter #SailingBVI "
        "#BritishVirginIslands #BareboatCharter #SailingLife #CaribbeanSailing "
        "#TortolaBVI #VirginGorda #JostVanDyke #Anegada #SailorsLife #IslandLife"
    )

    return "\n".join(lines)


def build_twitter_post(week_start, weather, marine, ships, holidays, events, advisories, edition):
    """X (Twitter) — under 280 chars, punchy."""
    week_end = week_start + timedelta(days=6)
    edition_tag = "Pre-Trip" if edition == "pre-trip" else "Arrival"

    parts = [f"⚓ BVI {edition_tag} Briefing {week_start.strftime('%b %d')}–{week_end.strftime('%b %d')} —"]

    if weather:
        winds = [d["wind_knots"] for d in weather]
        parts.append(f"💨 {min(winds)}–{max(winds)} kts")

    if marine:
        wave_heights = [d["wave_height_ft"] for d in marine if d["wave_height_ft"]]
        if wave_heights:
            parts.append(f"🌊 seas to {max(wave_heights):.1f} ft")

    if ships:
        parts.append(f"🚢 {len(ships)} cruise ship(s)")

    if holidays:
        parts.append(f"🏛️ {holidays[0]['name']}")

    if events:
        parts.append(f"⛵ {events[0]['name']}")

    parts.append("#BVI #BoatyBall #SailingBVI")

    post = "  ".join(parts)
    if len(post) > 280:
        post = post[:277] + "..."

    return post


def build_mighty_networks_post(week_start, weather, marine, ships, holidays, events, advisories, edition):
    """Mighty Networks — community tone, full detail, conversational."""
    week_end = week_start + timedelta(days=6)
    edition_label = "Pre-Trip Edition" if edition == "pre-trip" else "Arrival Edition"

    lines = []
    lines.append(f"⚓ BVI KNOW BEFORE YOU GO — {week_start.strftime('%B %d')}–{week_end.strftime('%B %d, %Y')}")
    lines.append(f"📋 {edition_label}")
    lines.append("")

    if edition == "pre-trip":
        lines.append("Hey crew! Planning your BVI charter? Here's your full weekly briefing "
                     "so you can show up prepared and ready to sail.")
    else:
        lines.append("Welcome to the BVI, BoatyBall crew! Here's your updated arrival briefing "
                     "with the latest conditions for your charter week.")
    lines.append("")

    if advisories:
        lines.append("⚠️ CAPTAIN'S ADVISORIES")
        lines.append("─────────────────────")
        for a in advisories:
            lines.append(f"• {a}")
        lines.append("")

    if weather:
        lines.append("🌤️ 7-DAY WEATHER SNAPSHOT")
        lines.append("─────────────────────────")
        for d in weather:
            lines.append(f"{d['day_name'][:3]} {d['date'][5:]}: "
                         f"{d['temp_high_f']}°F  💨 {d['wind_knots']} kts {d['wind_dir']}  "
                         f"gusts {d['gust_knots']} kts  —  {d['description'].title()}")
        lines.append("")

    if marine:
        lines.append("🌊 SEA CONDITIONS")
        lines.append("─────────────────")
        for d in marine:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            wave = f"{d['wave_height_ft']} ft" if d["wave_height_ft"] else "—"
            swell = f"{d['swell_height_ft']} ft" if d.get("swell_height_ft") else "—"
            lines.append(f"{dt.strftime('%a %m/%d')}: Waves {wave}  Swell {swell}  — {d['sea_state']}")
        lines.append("")

    if ships:
        lines.append("🚢 CRUISE SHIPS THIS WEEK")
        lines.append("─────────────────────────")
        for s in sorted(ships, key=lambda x: x["date"]):
            pax = f"{s['passengers']:,}" if s.get("passengers") else "N/A"
            lines.append(f"{s['day_name'][:3]} {s['date'][5:]}: {s['ship']} ({s['cruise_line']}) — {pax} pax")
        total_pax = sum(s.get("passengers", 0) or 0 for s in ships)
        if total_pax:
            lines.append(f"Total: ~{total_pax:,} passengers — expect busy days at The Baths & Jost!")
        lines.append("")

    if holidays:
        lines.append("🏛️ GOVERNMENT HOLIDAYS")
        lines.append("───────────────────────")
        for h in holidays:
            lines.append(f"• {h['day_name']} {h['date']}: {h['name']}")
            lines.append(f"  {h['note']}")
        lines.append("")

    if events:
        lines.append("⛵ REGATTAS & EVENTS")
        lines.append("────────────────────")
        for ev in events:
            lines.append(f"• {ev['name']} ({ev['start']} to {ev['end']})")
            lines.append(f"  {ev['impact']}")
        lines.append("")

    lines.append("🔗 USEFUL LINKS")
    lines.append("───────────────")
    lines.append("• Windy BVI: windy.com/?18.428,-64.619,10")
    lines.append("• BVI Customs & Immigration: bvi.gov.vg")
    lines.append("• Marine Traffic: marinetraffic.com")
    lines.append("")
    lines.append("Stay safe and have an amazing charter week! ⚓")
    lines.append("When in doubt, don't go out.")
    lines.append("")
    lines.append("Source: OpenWeatherMap · Open-Meteo · CruiseDig.com")

    return "\n".join(lines)


# ─── Facebook Auto-Poster ────────────────────────────────────────────────────

def post_to_facebook(message: str) -> dict:
    import urllib.request
    import urllib.parse
    if not FACEBOOK_PAGE_ID or not FACEBOOK_ACCESS_TOKEN:
        raise RuntimeError("FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN must be set in .env")
    data = urllib.parse.urlencode({
        "message": message,
        "access_token": FACEBOOK_ACCESS_TOKEN,
    }).encode()
    req = urllib.request.Request(
        f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed",
        data=data, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


# ─── Save All Posts ──────────────────────────────────────────────────────────

def save_social_posts(week_start, posts: dict, edition: str) -> Path:
    """Save all platform posts to a single text file for easy copy-paste."""
    _dl = Path(os.path.expanduser("~/Downloads"))
    out_dir = _dl if _dl.exists() else Path(".")
    out_path = out_dir / f"briefing-social-posts-{week_start.strftime('%Y-%m-%d')}-{edition}.txt"

    divider = "=" * 60

    lines = []
    lines.append(f"BOATYBALL BRIEFING — SOCIAL MEDIA POSTS")
    lines.append(f"Week of {week_start.strftime('%B %d, %Y')} — {edition.upper()} EDITION")
    lines.append(divider)
    lines.append("")

    platform_order = [
        ("FACEBOOK",        "facebook"),
        ("INSTAGRAM",       "instagram"),
        ("X (TWITTER)",     "twitter"),
        ("MIGHTY NETWORKS", "mighty_networks"),
    ]

    for platform_label, key in platform_order:
        lines.append(divider)
        lines.append(f"📱 {platform_label}")
        lines.append(divider)
        lines.append(posts.get(key, ""))
        lines.append("")

    lines.append(divider)
    lines.append("POST CHECKLIST")
    lines.append(divider)
    lines.append("[ ] Facebook       — https://business.facebook.com")
    lines.append("[ ] Instagram      — https://business.facebook.com (Meta Business Suite)")
    lines.append("[ ] X / Twitter    — https://x.com")
    lines.append("[ ] Mighty Networks — post in your community feed")
    lines.append("")
    lines.append("⚓ When in doubt, don't go out.")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Social posts saved: {out_path}")
    return out_path


# ─── Main Pipeline ───────────────────────────────────────────────────────────

def run_pipeline(edition="auto", dry_run=False):
    log.info("=== BVI Know Before You Go Pipeline (Social Media Edition) ===")

    # Determine edition
    if edition == "auto":
        dow = datetime.now().weekday()
        edition = "pre-trip" if dow in (2, 3, 4) else "arrival"

    edition_label = "Pre-Trip Edition" if edition == "pre-trip" else "Arrival Edition"
    log.info(f"Edition: {edition_label}")

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

    # Fetch all data
    weather  = fetch_weather(week_start)
    marine   = fetch_marine(week_start)
    ships    = load_cruise_ships(week_start)
    holidays = get_holidays(week_start)
    events   = get_events(week_start)

    log.info(f"Data: weather={len(weather) if weather else 0}, "
             f"marine={len(marine) if marine else 0}, "
             f"ships={len(ships)}, holidays={len(holidays)}, events={len(events)}")

    # Generate advisories and all platform posts
    advisories = generate_advisories(weather, marine, ships, holidays, events)

    posts = {
        "facebook":       build_facebook_post(week_start, weather, marine, ships, holidays, events, advisories, edition),
        "instagram":      build_instagram_post(week_start, weather, marine, ships, holidays, events, advisories, edition),
        "twitter":        build_twitter_post(week_start, weather, marine, ships, holidays, events, advisories, edition),
        "mighty_networks": build_mighty_networks_post(week_start, weather, marine, ships, holidays, events, advisories, edition),
    }

    if dry_run:
        print("\n" + "=" * 60)
        print(f"DRY RUN — {edition_label} Posts Preview")
        print("=" * 60)
        for platform, post in posts.items():
            print(f"\n── {platform.upper()} ──")
            print(post)
        return

    # Save all posts to file
    posts_file = save_social_posts(week_start, posts, edition)

    # Auto-post to Facebook
    log.info("Posting to Facebook...")
    try:
        result = post_to_facebook(posts["facebook"])
        log.info(f"Facebook posted: {result.get('id')}")
    except Exception as e:
        log.error(f"Facebook auto-post failed: {e}")
        log.info(f"Post manually using: {posts_file}")
        try:
            subprocess.Popen(["open", "https://business.facebook.com"])
        except Exception:
            pass

    log.info(f"\n✅ Done! All posts saved to: {posts_file}")
    log.info("Instagram, X, and Mighty Networks posts are ready to copy-paste from that file.")
    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BVI Know Before You Go — Social Media Edition")
    parser.add_argument("--edition",  default="auto", choices=["auto", "pre-trip", "arrival"])
    parser.add_argument("--dry-run",  action="store_true", help="Preview posts without sending")
    args = parser.parse_args()

    run_pipeline(edition=args.edition, dry_run=args.dry_run)
