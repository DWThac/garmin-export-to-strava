# Garmin Export → Strava

Uploads activities from a Garmin Connect **data export** to Strava in bulk.

Bypasses Garmin's login API entirely (which Garmin broke in late 2024 with
aggressive Cloudflare bot-detection). Instead, it reads the official Garmin
data export ZIP and uploads each activity's FIT file directly to Strava.

## One-time setup

1. **Install dependencies:**
   ```bash
   pip3 install -r requirements.txt
   ```

2. **Request your Garmin data export:**
   - https://www.garmin.com/account/datamanagement/exportdata
   - Wait for the email (usually a few hours)
   - Download and unzip the archive

3. **Set up Strava API access:**
   ```bash
   python3 setup_strava.py
   ```
   - Create a Strava app at https://www.strava.com/settings/api
     (Authorization Callback Domain: `localhost`)
   - Paste the Client ID and Secret when prompted
   - Authorize in the browser when it opens

## Usage

Preview what will be uploaded (no changes made):
```bash
python3 upload_export.py /path/to/unzipped_export --dry-run --type running
```

Upload all running activities:
```bash
python3 upload_export.py /path/to/unzipped_export --type running
```

Upload everything (runs, rowing, etc.):
```bash
python3 upload_export.py /path/to/unzipped_export
```

Test with a small batch:
```bash
python3 upload_export.py /path/to/unzipped_export --type running --limit 3
```

## How it works

- Reads `summarizedActivities.json` to find every activity in the export
- Scans all FIT files in `UploadedFiles_*.zip`, filtering to actual activity-type files
- Matches each JSON activity to its FIT file by `time_created` timestamp (±60s)
- Uploads each FIT to Strava's `/api/v3/uploads` endpoint
- Tracks progress in `synced.db` — re-running skips already-uploaded items
- Handles Strava's "duplicate" responses gracefully

## Strava rate limits

- 100 uploads per 15-minute window
- 1,000 uploads per day

The script sleeps briefly between uploads. If it hits the limit, it stops
cleanly — just re-run later and it picks up where it left off.

## Going forward

After this one-time historical sync, enable the **native Garmin → Strava
integration** so future activities sync automatically:

> Garmin Connect → Settings → Connected Apps → Strava

You won't need this script again unless you switch services or replay history.

## Files

- `upload_export.py` — main upload script
- `setup_strava.py` — interactive Strava OAuth setup
- `.env` — Strava credentials (gitignored if you put this in git)
- `synced.db` — SQLite DB tracking which activities have been uploaded
- `.fit_index.pkl` — cached FIT file index (delete to force a re-scan)
