# 🏃 Garmin Export → Strava

> Bulk-upload your entire Garmin Connect activity history to Strava — no Garmin login required.

![Python](https://img.shields.io/badge/python-3.8%2B-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

---

## Why this exists

Garmin's live API has been blocked by aggressive Cloudflare bot-detection since late 2024, making automated logins unreliable. This tool **bypasses that entirely** by reading the official Garmin data export — the same ZIP file you can download directly from your account — and uploading each activity's FIT file straight to Strava.

It's designed as a **one-time historical migration tool**. Once your history is on Strava, just enable the native Garmin → Strava integration for all future activities.

---

## Features

- ✅ No Garmin login — works entirely from your local data export
- ✅ Supports all activity types (running, cycling, swimming, hiking, rowing, skiing, and more)
- ✅ Skips duplicates intelligently — both via a local database and Strava's own duplicate detection
- ✅ Resumable — safely re-run after hitting Strava's rate limits; already-uploaded activities are skipped
- ✅ Dry-run mode — preview what will be uploaded before committing
- ✅ FIT index cache — after the first scan, subsequent runs are instant
- ✅ Handles Strava's rate limits gracefully (100 uploads / 15 min, 1,000 / day)

---

## Supported Activity Types

| Garmin | Strava |
|---|---|
| running, trail_running | Run, TrailRun |
| treadmill_running, indoor_running | VirtualRun |
| cycling, road_biking | Ride |
| mountain_biking | MountainBikeRide |
| gravel_cycling | GravelRide |
| indoor_cycling | VirtualRide |
| swimming, lap_swimming, open_water_swimming | Swim |
| walking | Walk |
| hiking | Hike |
| strength_training | WeightTraining |
| yoga | Yoga |
| elliptical | Elliptical |
| rowing, indoor_rowing | Rowing |
| skiing | AlpineSki |
| cross_country_skiing | NordicSki |

---

## Setup

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Request your Garmin data export

1. Go to [garmin.com/account/datamanagement/exportdata](https://www.garmin.com/account/datamanagement/exportdata)
2. Click **Export Your Data** and wait for the email (usually a few hours)
3. Download and unzip the archive — you'll get a folder called something like `DI_CONNECT/`

### 3. Connect your Strava account

```bash
python3 setup_strava.py
```

This will:
- Ask for your Strava API **Client ID** and **Client Secret**
  *(create a free app at [strava.com/settings/api](https://www.strava.com/settings/api) — set Authorization Callback Domain to `localhost`)*
- Open your browser for Strava authorization
- Save your credentials to `.env`

---

## Usage

### Preview before uploading (no changes made)

```bash
python3 upload_export.py /path/to/unzipped_export --dry-run
```

### Upload only running activities

```bash
python3 upload_export.py /path/to/unzipped_export --type running
```

### Upload everything

```bash
python3 upload_export.py /path/to/unzipped_export
```

### Test with a small batch first

```bash
python3 upload_export.py /path/to/unzipped_export --type running --limit 5
```

### Re-run after hitting Strava's rate limit

Just run the same command again — `synced.db` tracks what's already been uploaded and skips it automatically.

---

## How it works

```
Garmin export ZIP
       │
       ▼
summarizedActivities.json   ←  activity metadata (name, type, timestamp)
       │
       ▼
UploadedFiles_*.zip         ←  raw FIT files for each activity
       │
       ▼
  Timestamp match           ←  pairs each activity to its FIT file (±60s window)
       │
       ▼
  Strava API upload         ←  POST /api/v3/uploads with FIT file
       │
       ▼
    synced.db               ←  records Garmin ID → Strava ID so re-runs skip duplicates
```

---

## Rate limits

Strava allows:
- **100 uploads per 15 minutes**
- **1,000 uploads per day**

The script sleeps briefly between uploads and stops cleanly if it hits the limit. Re-run it later and it picks up exactly where it left off.

---

## Going forward

After this one-time sync, enable the **native Garmin → Strava integration** so future activities upload automatically — no scripts needed:

> **Garmin Connect** → Menu → Settings → **Connected Apps** → Strava → Connect

---

## Project files

| File | Purpose |
|---|---|
| `upload_export.py` | Main upload script |
| `setup_strava.py` | Interactive Strava OAuth setup |
| `requirements.txt` | Python dependencies |
| `.env` | Your Strava credentials *(gitignored)* |
| `synced.db` | Upload history database *(gitignored)* |
| `.fit_index.pkl` | Cached FIT file index *(delete to force re-scan)* |

---

## License

MIT — do whatever you like with it.
