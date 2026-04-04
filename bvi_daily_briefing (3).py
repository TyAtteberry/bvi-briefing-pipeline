#!/usr/bin/env python3
"""
BVI Daily Briefing — Email Only
=================================
Reads the morning lifeguard email, pulls weather + cruise data,
builds a Facebook post, and emails it to Ty. That's it.

No auto-posting. No image generation. No website. No Mighty Networks.
Just the post in your inbox every morning, ready to copy and paste.

GitHub Secrets required:
  GMAIL_CREDENTIALS   - contents of credentials.json (Google OAuth client)
  GMAIL_TOKEN         - contents of token.json (generated via --setup)
  WINDY_API_KEY       - Windy point forecast API key
  OWM_API_KEY         - OpenWeatherMap API key (fallback if Windy fails)
  NOTIFY_EMAIL        - where to deliver the briefing (your personal email)
  NOTIFY_FROM         - Gmail address sending the email

Local setup (one-time, on your Mac):
  pip install google-auth google-auth-oauthlib google-auth-httplib2
              google-api-python-client requests beautifulsoup4
  python bvi_daily_briefing.py --setup
"""

import os
import sys
import base64
import re
import math
import json
import datetime
import argparse
import logging
import smtplib
from pathlib import Path
from email import message_from_bytes
from email.utils import parsedate_to_datetime
from email.message import EmailMessage

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — all values come from GitHub Secrets / environment variables
# ─────────────────────────────────────────────────────────────────────────────

GMAIL_SENDER_FILTER = "beachadvisory@surflifesavingbvi.org"

BVI_LAT       = 18.4207
BVI_LON       = -64.6400

WINDY_API_KEY = os.getenv("WINDY_API_KEY", "")
WINDY_MODEL   = "gfs"
OWM_API_KEY   = os.getenv("OWM_API_KEY", "")

NOTIFY_EMAIL  = os.getenv("NOTIFY_EMAIL", "")
NOTIFY_FROM   = os.getenv("NOTIFY_FROM", "")

FACEBOOK_PAGE_ID      = os.getenv("FACEBOOK_PAGE_ID", "")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN", "")

FACEBOOK_PAGE_ID      = os.getenv("FACEBOOK_PAGE_ID", "")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN", "")

# ─────────────────────────────────────────────────────────────────────────────
# BVI HOLIDAYS
# ─────────────────────────────────────────────────────────────────────────────

BVI_HOLIDAYS = {
    "2026-04-03": {"name": "Good Friday",              "note": "Government closed. No liquor sales until 6 PM."},
    "2026-04-04": {"name": "Easter Saturday",           "note": "Limited services."},
    "2026-04-06": {"name": "Easter Monday",             "note": "Government offices closed."},
    "2026-06-15": {"name": "Sovereign's Birthday",      "note": "Government offices closed."},
    "2026-06-30": {"name": "250th Anniversary of Freedom", "note": "Public holiday. Government offices closed."},
    "2026-07-01": {"name": "Territory Day",             "note": "Government offices closed."},
    "2026-08-03": {"name": "Festival Monday",           "note": "Emancipation Festival. Government closed."},
    "2026-08-04": {"name": "Festival Tuesday",          "note": "Emancipation Festival. Government closed."},
    "2026-08-05": {"name": "Festival Wednesday",        "note": "Emancipation Festival. Government closed."},
    "2026-10-21": {"name": "St. Ursula's Day",          "note": "Government offices closed."},
    "2026-11-27": {"name": "Remembrance Day",           "note": "Government offices closed."},
    "2026-12-25": {"name": "Christmas Day",             "note": "Government offices and customs closed."},
    "2026-12-26": {"name": "Boxing Day",                "note": "Government offices closed."},
    "2027-01-01": {"name": "New Year's Day",            "note": "Government offices and customs closed."},
}

# ─────────────────────────────────────────────────────────────────────────────
# BVI EVENTS & FLOTILLAS
# ─────────────────────────────────────────────────────────────────────────────

BVI_EVENTS = [
    {"name": "51st BVI Spring Regatta & Sailing Festival", "start": "2026-03-23", "end": "2026-03-29",
     "impact": "Nanny Cay, Norman Island, Peter Island, and Cooper Island moorings very busy. Book early!"},
    {"name": "Hillbilly Flotilla", "start": "2026-03-07", "end": "2026-03-14",
     "impact": "Large flotilla — busier moorings at Jost Van Dyke, Bitter End, Anegada, Norman Island, and Cooper Island."},
    {"name": "Salty Dog Rally", "start": "2026-03-07", "end": "2026-03-08",
     "impact": "11+ boats at Anegada (Mar 7-8). Expect busier anchorage at Setting Point."},
    {"name": "Governor's Cup Regatta", "start": "2026-04-25", "end": "2026-04-25",
     "impact": "Racing in Sir Francis Drake Channel. Some mooring areas may be busy."},
    {"name": "The Moorings Interline Regatta", "start": "2026-10-20", "end": "2026-10-29",
     "impact": "Charter fleet event. Popular anchorages busier than usual."},
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. GMAIL — read the lifeguard email
# ─────────────────────────────────────────────────────────────────────────────

def get_gmail_service():
    """Build Gmail service from secrets stored as env vars."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ]

    creds = None

    # In GitHub Actions, secrets are stored as env vars
    gmail_token_json = os.getenv("GMAIL_TOKEN", "")
    gmail_creds_json = os.getenv("GMAIL_CREDENTIALS", "")

    if gmail_token_json:
        # Running in GitHub Actions — load from env var
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(gmail_token_json)
            token_path = f.name
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        os.unlink(token_path)
    elif Path("token.json").exists():
        # Running locally
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            # Save refreshed token back to file if local
            if Path("token.json").exists():
                Path("token.json").write_text(creds.to_json())
        else:
            if not gmail_creds_json:
                raise RuntimeError("No GMAIL_CREDENTIALS env var and no credentials.json found.")
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                f.write(gmail_creds_json)
                creds_path = f.name
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            os.unlink(creds_path)
            creds = flow.run_local_server(port=0)
            Path("token.json").write_text(creds.to_json())
            log.info("token.json saved. Add GMAIL_TOKEN secret to GitHub.")

    return build("gmail", "v1", credentials=creds)


def fetch_lifeguard_email() -> dict:
    """Fetch today's beach advisory email from Surf Life Saving BVI."""
    service = get_gmail_service()
    today_str = datetime.datetime.now().strftime("%Y/%m/%d")

    # Try today first
    query = f"from:{GMAIL_SENDER_FILTER} after:{today_str}"
    log.info(f"Gmail query: {query}")
    result = service.users().messages().list(userId="me", q=query, maxResults=10).execute()
    messages = result.get("messages", [])

    is_fresh = bool(messages)
    if not messages:
        log.warning("No email today — falling back to most recent from sender.")
        result = service.users().messages().list(
            userId="me", q=f"from:{GMAIL_SENDER_FILTER}", maxResults=10
        ).execute()
        messages = result.get("messages", [])

    if not messages:
        raise RuntimeError("No beach advisory email found in Gmail.")

    log.info(f"Found {len(messages)} email(s) — using most recent. Fresh today: {is_fresh}")
    msg = service.users().messages().get(userId="me", id=messages[0]["id"], format="raw").execute()
    raw = base64.urlsafe_b64decode(msg["raw"])
    email_msg = message_from_bytes(raw)

    # Decode subject
    from email.header import decode_header
    raw_subject = email_msg.get("Subject", "BVI Beach Advisory")
    decoded_parts = decode_header(raw_subject)
    subject = ""
    for part, enc in decoded_parts:
        if isinstance(part, bytes):
            subject += part.decode(enc or "utf-8", errors="replace")
        else:
            subject += str(part)
    subject = subject.strip()

    try:
        email_date = parsedate_to_datetime(email_msg.get("Date", ""))
    except Exception:
        email_date = datetime.datetime.now()

    # Extract body
    body = ""
    if email_msg.is_multipart():
        for part in email_msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="replace")
                break
    else:
        charset = email_msg.get_content_charset() or "utf-8"
        body = email_msg.get_payload(decode=True).decode(charset, errors="replace")

    log.info(f"Fetched: '{subject}' ({email_date.date()})")
    return {"subject": subject, "body": body.strip(), "date": email_date, "is_fresh": is_fresh}


# ─────────────────────────────────────────────────────────────────────────────
# 2. PARSE EMAIL — extract beach flags, wind, swell
# ─────────────────────────────────────────────────────────────────────────────

def parse_email_conditions(body: str, subject: str = "") -> dict:
    conditions = {
        "wind": "", "swell": "", "conditions": "",
        "flags": [], "advisories": [],
        "alert_level": "none", "alert_title": "", "danger_zones": [],
    }

    # Strip boilerplate
    BOILERPLATE_MARKERS = [
        "This Safety Advisory is current for the day",
        "This message and any attachments are confidential",
        "Whilst Visiting The Beach Please Take Away",
        "Please consider the environment before printing",
        "Liability for loss",
    ]
    clean_body = body
    for marker in BOILERPLATE_MARKERS:
        idx = clean_body.find(marker)
        if idx > 0:
            clean_body = clean_body[:idx]

    clean_body = re.sub(r'\*+', '', clean_body)
    lines = [l.strip() for l in clean_body.splitlines() if l.strip()]

    # Alert level from subject AND body
    subject_clean = re.sub(r'\*+', '', subject)

    # Extract advisory from subject — format is "Date – Time – Advisory Title!"
    # Split on any dash/em-dash variant and grab the last meaningful segment
    subject_parts = re.split(r'[–—\-]+', subject_clean)
    for part in reversed(subject_parts):
        part = part.strip().rstrip('!')
        if any(kw in part.upper() for kw in ['ADVISORY', 'CAUTION', 'WARNING', 'ALERT']):
            conditions["alert_title"] = part
            break

    # Also check first 10 body lines for advisory pattern as fallback
    if not conditions["alert_title"]:
        for line in lines[:10]:
            m = re.search(r'\d{1,2}:\d{2}[ap]m\s*[–—\-]+\s*(.+)', line, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip().rstrip('!')
                if any(kw in candidate.upper() for kw in ['ADVISORY', 'CAUTION', 'WARNING', 'ALERT']):
                    conditions["alert_title"] = candidate
                    break

    scan = (subject_clean + " " + " ".join(lines[:10])).upper()
    if any(kw in scan for kw in ['GALE WARNING', 'STORM WARNING', 'HURRICANE']):
        conditions["alert_level"] = "danger"
    elif any(kw in scan for kw in ['HIGH SURF ADVISORY', 'SMALL CRAFT WARNING']):
        conditions["alert_level"] = "warning"
    elif any(kw in scan for kw in ['SMALL CRAFT CAUTION', 'SURF ADVISORY', 'SMALL CRAFT ADVISORY', 'YELLOW FLAG', 'TAKE CARE']):
        conditions["alert_level"] = "caution"

    # Wind
    wind_match = re.search(
        r'wind\s+([\w\s\-]+?)\s+force\s+(\d[\w\s]*?)(?:\s+gusting\s+force\s+(\d[\w\s]*?))?'
        r'(?:...|\.{2,}|\.|!|$)',
        clean_body, re.IGNORECASE | re.MULTILINE
    )
    if wind_match:
        direction = wind_match.group(1).strip()
        force     = wind_match.group(2).strip()
        gust      = wind_match.group(3).strip() if wind_match.group(3) else ""
        conditions["wind"] = f"{direction} Force {force}"
        if gust:
            conditions["wind"] += f", gusting {gust}"

    # Swell
    swell_match = re.search(r'((?:[\w]+\s+){0,3}swell\s*(?:\([\d\.\s\w]+\))?)', clean_body, re.IGNORECASE)
    if swell_match:
        conditions["swell"] = swell_match.group(1).strip()

    # Sky conditions
    cond_matches = re.findall(
        r'(partly sunny|mostly sunny|sunny|partly cloudy|mostly cloudy|cloudy|'
        r'chance of showers|showers|rain|clear|overcast)',
        clean_body, re.IGNORECASE
    )
    if cond_matches:
        conditions["conditions"] = ", ".join(dict.fromkeys(c.title() for c in cond_matches))

    # Beach flags — track The Baths, Josiah's Bay, Smugglers Cove
    TRACKED = [
        ("baths",    "The Baths",       "npt mooring"),
        ("josiah",   "Josiah's Bay",    None),
        ("smuggler", "Smugglers Cove",  None),
    ]
    for key, beach_name, alt_key in TRACKED:
        for line in lines:
            ll = line.lower()
            if key in ll or (alt_key and alt_key in ll):
                if any(skip in ll for skip in ['north shore', 'bubbly pool', 'anegada', 'call:', 'information call']):
                    continue
                if 'red flag' in ll or 'no mooring' in ll:
                    color, emoji = "red", "🔴"
                    nearby = " ".join(lines[max(0, lines.index(line)-1):lines.index(line)+4]).lower()
                    if 'no swimming' in nearby or 'no snorkel' in nearby:
                        status_text = "RED FLAG — No Mooring / No Swimming"
                    elif 'no mooring' in ll:
                        status_text = "RED FLAG — No Mooring"
                    else:
                        status_text = "RED FLAG — Closed"
                elif 'green flag' in ll:
                    color, emoji, status_text = "green", "🟢", "Green Flag — Safe"
                elif 'yellow flag' in ll:
                    color, emoji, status_text = "yellow", "🟡", "Yellow Flag — Caution"
                elif 'extreme caution' in ll:
                    color, emoji, status_text = "red", "🔴", "No Lifeguard — Extreme Caution"
                elif 'no lifeguard' in ll or 'caution' in ll:
                    color, emoji, status_text = "yellow", "🟡", "No Lifeguard — Caution"
                elif 'lifeguard on duty' in ll:
                    color, emoji, status_text = "yellow", "🟡", "Lifeguard On Duty"
                else:
                    color, emoji, status_text = "yellow", "🟡", "Check Conditions"

                conditions["flags"].append({
                    "beach": beach_name, "status": status_text,
                    "color": color, "emoji": emoji,
                })
                break

    # Danger zones
    for line in lines:
        ll = line.lower()
        if ('take' in ll and 'care' in ll and
                any(z in ll for z in ['north shore', 'bubbly pool', 'rip current', 'surf', 'currents'])):
            conditions["danger_zones"].append(line.strip()[:300])
            break

    if conditions["alert_title"]:
        conditions["advisories"] = [conditions["alert_title"]]

    log.info(
        f"Parsed: level='{conditions['alert_level']}' flags={len(conditions['flags'])} "
        f"wind='{conditions['wind']}' swell='{conditions['swell']}'"
    )
    return conditions


# ─────────────────────────────────────────────────────────────────────────────
# 3. NOAA ALERTS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_noaa_alerts() -> list:
    try:
        r = requests.get(
            "https://api.weather.gov/alerts/active?area=VI",
            headers={"User-Agent": "BoatyBallWeatherBot/1.0"},
            timeout=15
        )
        r.raise_for_status()
        seen, alerts = set(), []
        for a in r.json().get("features", []):
            event = a["properties"]["event"]
            if event not in seen:
                seen.add(event)
                alerts.append(event)
        log.info(f"NOAA alerts: {alerts or 'none'}")
        return alerts
    except Exception as e:
        log.warning(f"NOAA fetch failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 4. WINDY — 3-day outlook
# ─────────────────────────────────────────────────────────────────────────────

def fetch_windy_outlook() -> list:
    if not WINDY_API_KEY:
        log.warning("WINDY_API_KEY not set — skipping.")
        return []
    try:
        r = requests.post(
            "https://api.windy.com/api/point-forecast/v2",
            timeout=15,
            headers={"Content-Type": "application/json"},
            json={
                "lat": BVI_LAT, "lon": BVI_LON, "model": WINDY_MODEL,
                "parameters": ["wind", "windGust"],
                "levels": ["surface"], "key": WINDY_API_KEY,
            }
        )
        r.raise_for_status()
        raw = r.json()

        def ms_to_kt(u, v): return round(math.sqrt(u**2 + v**2) * 1.94384, 1)
        def kt_from_ms(ms): return round(ms * 1.94384, 1)

        ts     = raw.get("ts", [])
        wind_u = raw.get("wind_u-surface", [])
        wind_v = raw.get("wind_v-surface", [])
        gusts  = raw.get("gust-surface", [])

        daily = {}
        for i, t in enumerate(ts):
            dt = datetime.datetime.utcfromtimestamp(t / 1000)
            date_str = dt.strftime("%Y-%m-%d")
            if date_str not in daily:
                daily[date_str] = {"winds": [], "gusts": []}
            u = wind_u[i] if i < len(wind_u) else 0
            v = wind_v[i] if i < len(wind_v) else 0
            daily[date_str]["winds"].append(ms_to_kt(u, v))
            daily[date_str]["gusts"].append(kt_from_ms(gusts[i] if i < len(gusts) else 0))

        outlook = []
        for date_str in sorted(daily.keys())[:4]:
            d = daily[date_str]
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            outlook.append({
                "date":      date_str,
                "day_name":  dt.strftime("%A"),
                "day_short": dt.strftime("%a"),
                "wind_avg":  round(sum(d["winds"]) / len(d["winds"])),
                "wind_max":  round(max(d["winds"])),
                "gust_max":  round(max(d["gusts"])),
            })
        log.info(f"Windy OK: {len(outlook)} days of outlook data")
        return outlook
    except Exception as e:
        log.warning(f"Windy error: {e}")
        return []


def fetch_owm_outlook() -> list:
    """OWM fallback if Windy fails."""
    if not OWM_API_KEY:
        return []
    try:
        r = requests.get(
            f"https://api.openweathermap.org/data/2.5/forecast?"
            f"lat={BVI_LAT}&lon={BVI_LON}&appid={OWM_API_KEY}&units=metric",
            timeout=15
        )
        r.raise_for_status()
        data = r.json()

        def ms_to_kt(ms): return round(ms * 1.94384)

        daily = {}
        for entry in data.get("list", []):
            dt = datetime.datetime.fromtimestamp(entry["dt"])
            date_str = dt.strftime("%Y-%m-%d")
            if date_str not in daily:
                daily[date_str] = {"winds": [], "descs": []}
            daily[date_str]["winds"].append(ms_to_kt(entry.get("wind", {}).get("speed", 0)))
            daily[date_str]["descs"].append(entry["weather"][0]["description"])

        outlook = []
        for date_str in sorted(daily.keys())[:4]:
            d = daily[date_str]
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            desc = max(set(d["descs"]), key=d["descs"].count)
            outlook.append({
                "date":        date_str,
                "day_name":    dt.strftime("%A"),
                "day_short":   dt.strftime("%a"),
                "wind_avg":    round(sum(d["winds"]) / len(d["winds"])),
                "wind_max":    round(max(d["winds"])),
                "description": desc.title(),
            })
        log.info(f"OWM fallback OK: {len(outlook)} days")
        return outlook
    except Exception as e:
        log.warning(f"OWM outlook failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 5. CRUISE SHIPS — scrape cruisedig.com for today + next 2 days
# ─────────────────────────────────────────────────────────────────────────────

def fetch_cruise_ships(today: datetime.datetime) -> dict:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.warning("beautifulsoup4 not installed — cruise data skipped.")
        return {}

    try:
        r = requests.get(
            "https://cruisedig.com/ports/tortola-british-virgin-islands",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BoatyBallBot/1.0)"}
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        today_dt = today.replace(tzinfo=None).date()

        target_dates = {}
        for i in range(3):
            d = today_dt + datetime.timedelta(days=i)
            label = "Today" if i == 0 else d.strftime("%a")
            target_dates[d] = label

        ships_by_day = {d: [] for d in target_dates}

        for block in soup.find_all("div", class_=re.compile(r"schedule")):
            links = block.find_all("a")
            if not links:
                continue
            occupancy_divs = block.find_all("div", class_="occupancy")
            if len(occupancy_divs) < 2:
                continue

            ship_name = links[0].get_text(strip=True)
            if ship_name.lower() in ("arrivals", "departures", "see all arrivals", "see all departures"):
                continue

            cruise_line = occupancy_divs[0].get_text(strip=True)
            pax_text    = occupancy_divs[1].get_text(strip=True)
            pax_match   = re.search(r'([\d][,.\d]*)', pax_text)
            pax = None
            if pax_match:
                try:
                    pax = int(pax_match.group(1).replace(".", "").replace(",", ""))
                except ValueError:
                    pass

            full_text  = block.get_text(" ", strip=True)
            date_match = re.search(r'(\d{1,2}\s+\w{3}\s+\d{4})', full_text)
            if not date_match:
                continue
            try:
                arrival_dt = datetime.datetime.strptime(date_match.group(1), "%d %b %Y").date()
            except ValueError:
                continue

            if arrival_dt in target_dates:
                ships_by_day[arrival_dt].append({
                    "ship": ship_name, "cruise_line": cruise_line, "passengers": pax,
                })

        # Deduplicate
        for d in ships_by_day:
            seen = set()
            ships_by_day[d] = [s for s in ships_by_day[d] if s["ship"] not in seen and not seen.add(s["ship"])]

        total = sum(len(v) for v in ships_by_day.values())
        log.info(f"Cruise ships found: {total} across 3 days")
        return {"by_day": ships_by_day, "labels": target_dates}

    except Exception as e:
        log.warning(f"Cruise scrape failed: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 6. HOLIDAYS & EVENTS
# ─────────────────────────────────────────────────────────────────────────────

def get_upcoming_holidays(today: datetime.datetime, days_ahead: int = 7) -> list:
    today = today.replace(tzinfo=None)
    holidays = []
    for i in range(days_ahead + 1):
        check = today + datetime.timedelta(days=i)
        date_str = check.strftime("%Y-%m-%d")
        if date_str in BVI_HOLIDAYS:
            h = BVI_HOLIDAYS[date_str].copy()
            h["date"]     = date_str
            h["day_name"] = check.strftime("%A")
            h["days_away"] = i
            holidays.append(h)
    return holidays


def get_active_events(today: datetime.datetime) -> list:
    today    = today.replace(tzinfo=None)
    week_end = today + datetime.timedelta(days=7)
    events   = []
    for ev in BVI_EVENTS:
        ev_start = datetime.datetime.strptime(ev["start"], "%Y-%m-%d")
        ev_end   = datetime.datetime.strptime(ev["end"],   "%Y-%m-%d")
        if ev_start <= week_end and ev_end >= today:
            ev = ev.copy()
            ev["active_today"] = ev_start <= today <= ev_end
            events.append(ev)
    return events


# ─────────────────────────────────────────────────────────────────────────────
# 7. BUILD FACEBOOK POST
# ─────────────────────────────────────────────────────────────────────────────

def sky_emoji(conditions_str: str) -> str:
    c = conditions_str.lower()
    if "shower" in c or "rain" in c: return "🌧️"
    if "partly" in c: return "⛅"
    if "sunny" in c or "clear" in c: return "☀️"
    if "cloudy" in c or "overcast" in c: return "☁️"
    return "🌤️"


def build_facebook_post(email_data: dict, parsed: dict, noaa_alerts: list,
                        outlook: list, cruise_data: dict,
                        holidays: list, events: list) -> str:
    today = email_data["date"]
    alert_level = parsed.get("alert_level", "none")
    lines = []

    lines.append(f"🏝️ BVI DAILY BRIEFING — {today.strftime('%A, %B %d, %Y')}")
    lines.append("")

    # Advisory
    if alert_level != "none" and parsed.get("alert_title"):
        lines.append(f"🚨 {parsed['alert_title']}")
        dz = parsed.get("danger_zones", [])
        if dz:
            lines.append(f"⛔ {dz[0]}")
        lines.append("")

    # NOAA alerts
    for alert in noaa_alerts:
        lines.append(f"⚠️ {alert} in effect")
    if noaa_alerts:
        lines.append("")

    # Beach flags
    lines.append("🏖️ BEACH FLAGS")
    flags = parsed.get("flags", [])
    if flags:
        for f in flags:
            lines.append(f"{f['emoji']} {f['beach']} — {f['status']}")
    else:
        lines.append("🟡 Check local conditions")
    lines.append("")

    # Wind & swell
    lines.append("🌊 CONDITIONS")
    if parsed.get("wind"):
        lines.append(f"💨 Wind: {parsed['wind']}")
    if parsed.get("swell"):
        lines.append(f"🌊 Swell: {parsed['swell']}")
    if parsed.get("conditions"):
        lines.append(f"{sky_emoji(parsed['conditions'])} Sky: {parsed['conditions'].title()}")
    lines.append("")

    # 3-day outlook
    if outlook and len(outlook) >= 2:
        lines.append("📅 3-DAY OUTLOOK")
        for day in outlook[1:4]:
            wind = f"{day['wind_avg']}-{day['wind_max']} kts"
            desc = f"  {day.get('description', '')}" if day.get("description") else ""
            lines.append(f"{day['day_short']}: 💨 {wind}{desc}")
        lines.append("")

    # Cruise ships
    by_day = cruise_data.get("by_day", {})
    labels = cruise_data.get("labels", {})
    has_ships = any(by_day.get(d) for d in by_day)
    if has_ships:
        lines.append("🚢 CRUISE SHIPS")
        for d, label in sorted(labels.items()):
            day_ships = by_day.get(d, [])
            for s in day_ships:
                pax = f" ({s['passengers']:,} pax)" if s.get("passengers") else ""
                lines.append(f"{label}: {s['ship']} — {s['cruise_line']}{pax}")
        lines.append("")

    # Holidays
    if holidays:
        lines.append("🏛️ UPCOMING HOLIDAY")
        for h in holidays[:2]:
            days_away = h["days_away"]
            when = "Today!" if days_away == 0 else f"in {days_away} day{'s' if days_away > 1 else ''}"
            lines.append(f"• {h['name']} ({h['day_name']}, {when}) — {h['note']}")
        lines.append("")

    # Events
    if events:
        lines.append("⛵ FLOTILLAS & EVENTS")
        for ev in events[:2]:
            status = "Active now" if ev.get("active_today") else f"Starts {ev['start']}"
            lines.append(f"• {ev['name']} ({status})")
            lines.append(f"  {ev['impact']}")
        lines.append("")

    lines.append("⚓ When in doubt, don't go out.")
    lines.append("")
    lines.append("#BVI #BoatyBall #BVIWeather #BVIDailyBriefing #Sailing #BritishVirginIslands")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 8. SEND EMAIL
# ─────────────────────────────────────────────────────────────────────────────

def send_briefing_email(email_data: dict, fb_post: str):
    """Send the Facebook post to Ty via Gmail API (uses same OAuth as reading)."""
    if not NOTIFY_EMAIL or not NOTIFY_FROM:
        log.warning("NOTIFY_EMAIL or NOTIFY_FROM not set — printing to console.")
        print("\n" + "=" * 60)
        print(fb_post)
        print("=" * 60)
        return

    today   = email_data["date"]
    subject = f"BVI Daily Briefing — {today.strftime('%A, %B %d, %Y')} | Facebook Post Ready"

    plain = (
        f"Copy and paste the post below into Facebook.\n"
        f"Generated: {datetime.datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}\n\n"
        f"{'=' * 60}\n\n"
        f"{fb_post}\n\n"
        f"{'=' * 60}\n"
        f"Post at: https://business.facebook.com\n"
    )

    # HTML version
    html_body = fb_post.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html_body = html_body.replace("\n", "<br>")
    html = f"""<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px;">
<h2 style="color: #1877F2;">Facebook Post Ready to Publish</h2>
<p style="color: #666;">Generated: {datetime.datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}</p>
<hr>
<div style="background: #f0f2f5; border-radius: 8px; padding: 16px; white-space: pre-wrap; font-size: 14px; line-height: 1.6;">
{html_body}
</div>
<hr>
<p style="text-align: center;">
  <a href="https://business.facebook.com" style="background: #1877F2; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;">
    Open Facebook Business Manager
  </a>
</p>
</body></html>"""

    try:
        service = get_gmail_service()

        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = NOTIFY_FROM
        msg["To"]      = NOTIFY_EMAIL
        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(html,  "html",  "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        log.info(f"Email sent to {NOTIFY_EMAIL}")
    except Exception as e:
        log.error(f"Email send failed: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# 8. POST TO FACEBOOK
# ─────────────────────────────────────────────────────────────────────────────

def post_to_facebook(fb_post: str) -> bool:
    if not FACEBOOK_PAGE_ID or not FACEBOOK_ACCESS_TOKEN:
        log.warning("FACEBOOK credentials not set — skipping Facebook post.")
        return False
    try:
        r = requests.post(
            f"https://graph.facebook.com/v25.0/{FACEBOOK_PAGE_ID}/feed",
            data={"message": fb_post, "access_token": FACEBOOK_ACCESS_TOKEN},
            timeout=30
        )
        r.raise_for_status()
        post_id = r.json().get("id", "unknown")
        log.info(f"Facebook post published! Post ID: {post_id}")
        return True
    except Exception as e:
        log.error(f"Facebook post failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(dry_run: bool = False, force: bool = False):
    log.info("=== BVI Daily Briefing Pipeline starting ===")

    log.info("Step 1: Fetching lifeguard email...")
    email_data = fetch_lifeguard_email()

    log.info("Step 2: Parsing beach conditions...")
    parsed = parse_email_conditions(email_data["body"], email_data["subject"])

    log.info("Step 3: Fetching NOAA alerts...")
    noaa_alerts = fetch_noaa_alerts()

    log.info("Step 4: Fetching 3-day wind outlook...")
    outlook = fetch_windy_outlook()
    if not outlook:
        log.info("Windy unavailable — trying OWM fallback...")
        outlook = fetch_owm_outlook()

    log.info("Step 5: Fetching cruise ship schedule...")
    today       = email_data["date"]
    cruise_data = fetch_cruise_ships(today)
    holidays    = get_upcoming_holidays(today)
    events      = get_active_events(today)

    log.info("Step 6: Building Facebook post...")
    fb_post = build_facebook_post(
        email_data, parsed, noaa_alerts, outlook, cruise_data, holidays, events
    )

    if dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN — Facebook Post Preview")
        print("=" * 60)
        print(fb_post)
        print("=" * 60)
        return

    if not email_data.get("is_fresh", False) and not force:
        log.info("No fresh email today — skipping. Use --force to override.")
        return

    log.info("Step 7: Sending briefing email...")
    send_briefing_email(email_data, fb_post)

    log.info("Step 8: Posting to Facebook...")
    post_to_facebook(fb_post)

    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BVI Daily Briefing — Email Only")
    parser.add_argument("--dry-run", action="store_true", help="Preview post without emailing")
    parser.add_argument("--force",   action="store_true", help="Run even if no fresh email today")
    parser.add_argument("--setup",   action="store_true", help="Run Gmail OAuth setup (local only)")
    args = parser.parse_args()

    if args.setup:
        log.info("Running Gmail OAuth setup...")
        get_gmail_service()
        log.info("Done! token.json created. Copy contents into GMAIL_TOKEN GitHub secret.")
        sys.exit(0)

    run_pipeline(dry_run=args.dry_run, force=args.force)
