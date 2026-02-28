# BVI Know Before You Go — Automated Briefing Pipeline

Generates weekly charter captain briefings for the BVI and publishes them to the BoatyBall blog.

## Schedule

| Day | Time (EST) | Edition | Purpose |
|-----|-----------|---------|---------|
| Wednesday | 7:00 AM | Pre-Trip | Helps charterers plan before flying down |
| Saturday | 7:00 AM | Arrival | Updated conditions for charter start day |

## What It Does

1. Fetches weather from OpenWeatherMap (5-day forecast)
2. Fetches marine conditions from Open-Meteo (wave height, swell, sea state)
3. Loads cruise ship schedule from `bvi_cruise_schedule.json`
4. Checks BVI holidays and regatta calendar
5. Generates Hugo blog post + Facebook text
6. Pushes blog post to GitLab Hugo repo
7. Triggers GitLab CI/CD deploy pipeline
8. Emails you the Facebook post text to copy/paste

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `OWM_API_KEY` | OpenWeatherMap API key |
| `GITLAB_REPO_URL` | `https://gitlab.com/klarrious/boatyball/bbsite.git` |
| `GITLAB_USERNAME` | GitLab username |
| `GITLAB_ACCESS_TOKEN` | GitLab personal access token (write_repository) |
| `GITLAB_PROJECT_ID` | `klarrious/boatyball/bbsite` |
| `GITLAB_TRIGGER_TOKEN` | GitLab pipeline trigger token |
| `GMAIL_CREDENTIALS` | Gmail OAuth credentials.json content |
| `GMAIL_TOKEN` | Gmail OAuth token.json content |

## Manual Trigger

Go to Actions → "BVI Know Before You Go Briefing" → Run workflow → Select edition.

## Updating Cruise Data

Edit `bvi_cruise_schedule.json` to add/update cruise ship visits.
Source: https://cruisedig.com/ports/tortola-british-virgin-islands/arrivals
