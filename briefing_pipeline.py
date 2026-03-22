#!/usr/bin/env python3
"""
BVI Know Before You Go — Email-Only Pipeline

Generates the weekly charter briefing Facebook post and emails it to Ty.
No website, no GitLab, no Hugo — just the post, delivered to your inbox.

Environment variables (set as GitHub Secrets):
  OWM_API_KEY     - OpenWeatherMap API key
  GMAIL_SENDER    - Gmail address sending the email (e.g. bot@boatyball.com)
  EMAIL_RECIPIENT - Where to send the briefing (e.g. ty@boatyball.com)
  GMAIL_APP_PWD   - Gmail App Password for the sender account
  EDITION         - pre-trip or arrival (optional, auto-detects)
"""

import argparse
import json
import logging
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bvi-briefing")

# ─── Config ──────────────────────────────────────────────────────────────────

OWM_API_KEY     = os.getenv("OWM_API_KEY", "")
GMAIL_SENDER    = os.getenv("GMAIL_SENDER", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")
GMAIL_APP_PWD   = os.getenv("GMAIL_APP_PWD", "")

# BVI coordinates
BVI_LAT = 18.4267
BVI_LON = -64.62

# ─── BVI Holidays ────────────────────────────────────────────────────────────

BVI_HOLIDAYS = {
    "2025-01-01": {"name": "New Year's Day",                        "note": "Government offices and customs closed."},
    "2025-03-03": {"name": "H. Lavity Stoutt's Birthday",           "note": "Government offices and customs closed."},
    "2025-04-18": {"name": "Good Friday",                           "note": "Government closed. No liquor sales until 6 PM."},
    "2025-04-19": {"name": "Easter Saturday",                       "note": "Limited services."},
    "2025-04-21": {"name": "Easter Monday",                         "note": "Government offices closed."},
    "2025-06-16": {"name": "Sovereign's Birthday",                  "note": "Government offices closed."},
    "2025-07-01": {"name": "Territory Day",                         "note": "Government offices closed."},
    "2025-08-04": {"name": "Festival Monday",                       "note": "Emancipation Festival. Government closed."},
    "2025-08-05": {"name": "Festival Tuesday",                      "note": "Emancipation Festival. Government closed."},
    "2025-08-06": {"name": "Festival Wednesday",                    "note": "Emancipation Festival. Government closed."},
    "2025-10-21": {"name": "St. Ursula's Day",                      "note": "Government offices closed."},
    "2025-11-28": {"name": "Remembrance Day (observed)",            "note": "Government offices closed."},
    "2025-12-25": {"name": "Christmas Day",                         "note": "Government offices and customs closed."},
    "2025-12-26": {"name": "Boxing Day",                            "note": "Government offices closed."},
    "2026-01-01": {"name": "New Year's Day",                        "note": "Government offices and customs closed."},
    "2026-03-09": {"name": "H. Lavity Stoutt's Birthday (observed)","note": "Government offices and customs closed."},
    "2026-04-03": {"name": "Good Friday",                           "note": "Government closed. No liquor sales until 6 PM."},
    "2026-04-04": {"name": "Easter Saturday",                       "note": "Limited services."},
    "2026-04-06": {"name": "Easter Monday",                         "note": "Government offices closed."},
    "2026-06-15": {"name": "Sovereign's Birthday",                  "note": "Government offices closed."},
    "2026-06-30": {"name": "250th Anniversary of Freedom at Nottingham Estate", "note": "One-off public holiday for 2026. Government offices closed."},
    "2026-07-01": {"name": "Territory Day",                         "note": "Government offices closed."},
    "2026-08-03": {"name": "Festival Monday",                       "note": "Emancipation Festival. Government closed 3 days."},
    "2026-08-04": {"name": "Festival Tuesday",                      "note": "Emancipation Festival. Government closed."},
    "2026-08-05": {"name": "Festival Wednesday",                    "note": "Emancipation Festival. Government closed."},
    "2026-10-21": {"name": "St. Ursula's Day",                      "note": "Government offices closed."},
    "2026-11-27": {"name": "Remembrance Day (observed)",            "note": "Government offices closed."},
    "2026-12-25": {"name": "Christmas Day",                         "note": "Government offices and customs closed."},
    "2026-12-26": {"name": "Boxing Day",                            "note": "Government offices closed."},
    "2027-01-01": {"name": "New Year's Day",                        "note": "Government offices and customs closed."},
    "2027-03-01": {"name": "H. Lavity Stoutt's Birthday",           "note": "Government offices and customs closed."},
    "2027-03-26": {"name": "Good Friday",                           "note": "Government closed. No liquor sales until 6 PM."},
    "2027-03-27": {"name": "Easter Saturday",                       "note": "Limited services."},
    "2027-03-29": {"name": "Easter Monday",                         "note": "Government offices closed."},
}

# ─── BVI Events & Regattas ───────────────────────────────────────────────────

BVI_EVENTS = [
    {"name": "Dark and Stormy Regatta",              "start": "2026-02-14", "end": "2026-02-14",
     "impact": "Racing near West End. Minimal mooring impact."},
    {"name": "51st BVI Spring Regatta & Sailing Festival", "start": "2026-03-23", "end": "2026-03-29",
     "impact": "Major event — Nanny Cay, Norman Island, Peter Island, and Cooper Island moorings will be very busy. Book early!"},
    {"name": "Hillbilly Flotilla",                   "start": "2026-03-07", "end": "2026-03-14",
     "impact": "Large flotilla group — expect busier moorings at Jost Van Dyke (Mar 8), Bitter End/North Sound (Mar 9), Anegada (Mar 10), Leverick Bay (Mar 11), Norman Island (Mar 12), and Cooper Island (Mar 13). Book moorings early!"},
    {"name": "Salty Dog Rally",                      "start": "2026-03-07", "end": "2026-03-08",
     "impact": "11+ boat flotilla at Anegada (Mar 7–8). Expect busier anchorage and mooring field at Anegada's Setting Point. Plan accordingly if heading to Anegada this weekend."},
    {"name": "Governor's Cup Regatta",               "start": "2026-04-25", "end": "2026-04-25",
     "impact": "Racing in Sir Francis Drake Channel. Some mooring areas may be busy."},
    {"name": "The Moorings Interline Regatta",        "start": "2026-10-20", "end": "2026-10-29",
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
    if wave_height_m is None:   return "Unknown"
    elif wave_height_m < 0.1:   return "Calm (glassy)"
    elif wave_height_m < 0.5:   return "Calm (rippled)"
    elif wave_height_m < 1.25:  return "Smooth"
    elif wave_height_m < 2.5:   return "Slight"
    elif wave_height_m < 4.0:   return "Moderate"
    elif wave_height_m < 6.0:   return "Rough"
    else:                       return "Very rough"


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
    import urllib.request
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
                "date": date_str, "day_name": entry_date.strftime("%A"),
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
        avg_wind_ms  = sum(d["winds"]) / len(d["winds"])
        max_gust_ms  = max(d["gusts"]) if d["gusts"] else 0
        avg_dir      = sum(d["wind_dirs"]) / len(d["wind_dirs"])
        result.append({
            "date": date_str, "day_name": d["day_name"],
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
        wave_h  = daily["wave_height_max"][i]       if daily.get("wave_height_max")       else None
        swell_h = daily["swell_wave_height_max"][i] if daily.get("swell_wave_height_max") else None
        wave_dir= daily["wave_direction_dominant"][i]if daily.get("wave_direction_dominant")else None
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
            h["date"]     = date_str
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


# ─── Advisories ──────────────────────────────────────────────────────────────

def generate_advisories(weather, marine, ships, holidays, events):
    advisories = []
    if weather:
        max_gust = max(d["gust_knots"] for d in weather)
        if max_gust >= 25:
            advisories.append(f"💨 Wind Advisory: Gusts up to {max_gust} kts expected. Secure dinghies and check mooring lines.")
    if marine:
        waves = [d["wave_height_ft"] for d in marine if d["wave_height_ft"]]
        if waves and max(waves) >= 5:
            advisories.append(f"🌊 Sea State Advisory: Waves up to {max(waves):.1f} ft. Drake Channel crossing may be uncomfortable.")
    if ships:
        total_pax = sum(s.get("passengers", 0) or 0 for s in ships)
        if total_pax > 5000:
            advisories.append(f"🚢 Cruise Ship Alert: {len(ships)} ships this week (~{total_pax:,} passengers). The Baths and Jost Van Dyke will be busy on ship days.")
    for h in holidays:
        advisories.append(f"🏛️ {h['name']} ({h['day_name']}, {h['date']}): {h['note']}")
    for ev in events:
        advisories.append(f"⛵ {ev['name']} ({ev['start']} to {ev['end']}): {ev['impact']}")
    return advisories


# ─── Facebook Post Generator ─────────────────────────────────────────────────

def generate_facebook_post(week_start, weather, marine, ships, holidays, events, advisories, edition):
    week_end      = week_start + timedelta(days=6)
    edition_label = "PRE-TRIP" if edition == "pre-trip" else "ARRIVAL"

    lines = []
    lines.append(f"⚓ BVI KNOW BEFORE YOU GO — {week_start.strftime('%b %d')}–{week_end.strftime('%b %d, %Y')} ({edition_label})")
    lines.append("Your charter week briefing from BoatyBall!")
    if edition == "pre-trip":
        lines.append("📋 Planning your trip? Here's what to expect this week:")
    else:
        lines.append("🏝️ Welcome to the BVI! Here's your updated conditions report:")
    lines.append("")

    # Captain's advisories
    if advisories:
        lines.append("⚠️ CAPTAIN'S ADVISORY:")
        for a in advisories:
            lines.append(f"  • {a}")
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
        waves = [d["wave_height_ft"] for d in marine if d["wave_height_ft"]]
        if waves:
            lines.append(f"🌊 SEAS: Waves up to {max(waves):.1f} ft")
            lines.append("")

    # Cruise ships
    if ships:
        seen = set()
        ship_days = []
        for s in sorted(ships, key=lambda x: x["date"]):
            abbr = s["day_name"][:3]
            if abbr not in seen:
                seen.add(abbr)
                ship_days.append(abbr)
        total_pax = sum(s.get("passengers", 0) or 0 for s in ships)
        lines.append(f"🚢 CRUISE SHIPS: {len(ships)} ship(s) in port ({', '.join(ship_days)})")
        if total_pax:
            lines.append(f"   ~{total_pax:,} passengers — plan around busy days at The Baths & Jost!")
        lines.append("")

    # Holidays
    if holidays:
        lines.append("🏛️ GOVERNMENT HOLIDAY:")
        for h in holidays:
            lines.append(f"  {h['day_name']}: {h['name']} — {h['note']}")
        lines.append("")

    # Events
    if events:
        for ev in events:
            lines.append(f"⛵ {ev['name'].upper()}: {ev['impact']}")
        lines.append("")

    lines.append("📌 Reserve your moorings: www.boatyball.com")
    lines.append("")
    lines.append("#BVI #CharterSailing #KnowBeforeYouGo #BoatyBall #SailingBVI "
                 "#BritishVirginIslands #BareboatCharter #SailingLife")

    return "\n".join(lines)


# ─── Email Sender ─────────────────────────────────────────────────────────────

def send_email(subject, body, week_start, edition):
    """Send the Facebook post to Ty via Gmail App Password (no OAuth needed)."""
    if not all([GMAIL_SENDER, EMAIL_RECIPIENT, GMAIL_APP_PWD]):
        log.warning("Email credentials not set — printing post to console instead.")
        print("\n" + "=" * 60)
        print(f"SUBJECT: {subject}")
        print("=" * 60)
        print(body)
        print("=" * 60)
        return False

    log.info(f"Sending email to {EMAIL_RECIPIENT}...")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT

    # Plain text version (copy-paste ready)
    plain = (
        f"Copy and paste this into Facebook when ready to post.\n"
        f"Generated: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}\n"
        f"Charter Week: {week_start.strftime('%b %d')} – {(week_start + timedelta(days=6)).strftime('%b %d, %Y')}\n"
        f"Edition: {'Pre-Trip' if edition == 'pre-trip' else 'Arrival'}\n\n"
        f"{'=' * 60}\n\n"
        f"{body}\n\n"
        f"{'=' * 60}\n"
        f"Post at: https://business.facebook.com\n"
    )

    # HTML version (cleaner to read in Gmail)
    html_body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html_body = html_body.replace("\n", "<br>")
    html = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px;">
      <h2 style="color: #1877F2;">📘 Facebook Post Ready to Publish</h2>
      <p style="color: #666;">
        Generated: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}<br>
        Charter Week: {week_start.strftime('%b %d')} – {(week_start + timedelta(days=6)).strftime('%b %d, %Y')}<br>
        Edition: {'Pre-Trip' if edition == 'pre-trip' else 'Arrival'}
      </p>
      <hr>
      <div style="background: #f0f2f5; border-radius: 8px; padding: 16px; white-space: pre-wrap; font-size: 14px; line-height: 1.6;">
{html_body}
      </div>
      <hr>
      <p style="text-align: center;">
        <a href="https://business.facebook.com" style="background: #1877F2; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;">
          → Open Facebook Business Manager
        </a>
      </p>
    </body></html>
    """

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_SENDER, GMAIL_APP_PWD)
    server.sendmail(GMAIL_SENDER, EMAIL_RECIPIENT, msg.as_bytes())
        log.info("✅ Email sent successfully!")
        return True
    except Exception as e:
        log.error(f"Email send failed: {e}")
        return False


# ─── Main Pipeline ───────────────────────────────────────────────────────────

def run_pipeline(edition="auto"):
    log.info("=== BVI Know Before You Go — Email Pipeline ===")

    # Determine edition
    if edition == "auto":
        dow     = datetime.now().weekday()
        edition = "pre-trip" if dow in (2, 3, 4) else "arrival"  # Wed/Thu/Fri = pre-trip

    edition_label = "Pre-Trip Edition" if edition == "pre-trip" else "Arrival Edition"

    # Determine charter week (Saturday to Friday)
    today              = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        week_start = today
    elif today.weekday() < 5:
        week_start = today + timedelta(days=days_until_saturday)
    else:
        week_start = today + timedelta(days=6)

    week_end = week_start + timedelta(days=6)
    log.info(f"Charter Week : {week_start.strftime('%A %b %d')} – {week_end.strftime('%A %b %d, %Y')}")
    log.info(f"Edition      : {edition_label}")

    # Fetch data
    weather  = fetch_weather(week_start)
    marine   = fetch_marine(week_start)
    ships    = load_cruise_ships(week_start)
    holidays = get_holidays(week_start)
    events   = get_events(week_start)

    log.info(f"Data: weather={len(weather) if weather else 0}, marine={len(marine) if marine else 0}, "
             f"ships={len(ships)}, holidays={len(holidays)}, events={len(events)}")

    # Generate content
    advisories  = generate_advisories(weather, marine, ships, holidays, events)
    fb_post     = generate_facebook_post(week_start, weather, marine, ships, holidays, events, advisories, edition)

    # Build email subject
    subject = (f"⚓ BVI Charter Briefing — {week_start.strftime('%b %d')}–"
               f"{week_end.strftime('%b %d, %Y')} ({edition_label}) | Facebook Post Ready")

    # Send email
    send_email(subject, fb_post, week_start, edition)

    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BVI Know Before You Go — Email Pipeline")
    parser.add_argument("--edition",  default="auto", choices=["auto", "pre-trip", "arrival"])
    parser.add_argument("--dry-run",  action="store_true", help="Generate and print without emailing")
    args = parser.parse_args()

    if args.dry_run:
        # Clear email creds so send_email falls back to console print
        os.environ.pop("GMAIL_APP_PWD", None)

    run_pipeline(edition=args.edition)
