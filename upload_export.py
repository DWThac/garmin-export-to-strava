#!/usr/bin/env python3
"""
Upload activities from a Garmin Connect data export → Strava.

Bypasses Garmin login entirely by reading the official Garmin data export.

Usage:
    python3 upload_export.py /path/to/export_folder
    python3 upload_export.py /path/to/export_folder --dry-run
    python3 upload_export.py /path/to/export_folder --type running
"""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import io
import pickle

import fitparse
import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv(Path(__file__).parent / ".env")

DB_FILE = Path(__file__).parent / "synced.db"

ACTIVITY_MAP = {
    "running": "Run",
    "trail_running": "TrailRun",
    "treadmill_running": "VirtualRun",
    "indoor_running": "VirtualRun",
    "cycling": "Ride",
    "mountain_biking": "MountainBikeRide",
    "road_biking": "Ride",
    "gravel_cycling": "GravelRide",
    "swimming": "Swim",
    "lap_swimming": "Swim",
    "open_water_swimming": "Swim",
    "walking": "Walk",
    "hiking": "Hike",
    "strength_training": "WeightTraining",
    "yoga": "Yoga",
    "elliptical": "Elliptical",
    "rowing": "Rowing",
    "indoor_rowing": "Rowing",
    "skiing": "AlpineSki",
    "cross_country_skiing": "NordicSki",
    "virtual_ride": "VirtualRide",
    "indoor_cycling": "VirtualRide",
}


def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS synced (
            garmin_activity_id TEXT PRIMARY KEY,
            strava_activity_id TEXT,
            synced_at TEXT
        )
    """)
    conn.commit()
    return conn


def is_synced(conn, aid):
    return conn.execute("SELECT 1 FROM synced WHERE garmin_activity_id=?", (str(aid),)).fetchone() is not None


def mark_synced(conn, aid, sid):
    conn.execute("INSERT OR REPLACE INTO synced VALUES (?, ?, ?)",
                 (str(aid), str(sid), datetime.now(timezone.utc).isoformat()))
    conn.commit()


def find_activities_json(export_root: Path) -> Path:
    matches = list(export_root.rglob("*summarizedActivities.json"))
    if not matches:
        raise SystemExit(f"No summarizedActivities.json found under {export_root}")
    return matches[0]


def find_uploaded_zips(export_root: Path) -> list:
    zips = list(export_root.rglob("UploadedFiles_*.zip"))
    if not zips:
        raise SystemExit(f"No UploadedFiles_*.zip found under {export_root}")
    return sorted(zips)


def _read_fit_header(fit_bytes: bytes):
    """Return (type_str, time_created_epoch_ms) from a FIT file's file_id message, or None."""
    try:
        fit = fitparse.FitFile(io.BytesIO(fit_bytes))
        for msg in fit.get_messages('file_id'):
            type_str = None
            ts_ms = None
            for f in msg.fields:
                if f.name == 'type':
                    type_str = str(f.value)
                elif f.name == 'time_created' and f.value:
                    # fitparse returns naive UTC; treat explicitly as UTC
                    dt = f.value.replace(tzinfo=timezone.utc)
                    ts_ms = int(dt.timestamp() * 1000)
            return type_str, ts_ms
    except Exception:
        return None
    return None


def build_fit_index(zips: list, cache_file: Path) -> dict:
    """
    Scan all FIT files in the export, filter to activity-type files,
    return: {time_created_epoch_ms: (zip_path, internal_filename)}.

    Uses a pickle cache to skip rescanning on subsequent runs.
    """
    if cache_file.exists():
        try:
            with open(cache_file, "rb") as f:
                idx = pickle.load(f)
            print(f"Loaded FIT index from cache: {len(idx)} activity files")
            return idx
        except Exception:
            pass

    print(f"Scanning FIT files in {len(zips)} archive(s) (this takes a few minutes)...")
    index = {}
    skipped_small = 0
    skipped_nonactivity = 0
    for zp in zips:
        with zipfile.ZipFile(zp) as zf:
            members = [i for i in zf.infolist() if i.filename.endswith(".fit")]
            for info in tqdm(members, desc=f"  {zp.name}", unit="file"):
                if info.file_size < 2000:
                    skipped_small += 1
                    continue
                fit_bytes = zf.read(info.filename)
                hdr = _read_fit_header(fit_bytes)
                if not hdr:
                    continue
                file_type, ts_ms = hdr
                if file_type != "activity":
                    skipped_nonactivity += 1
                    continue
                if ts_ms is None:
                    continue
                # store first match for a given timestamp
                if ts_ms not in index:
                    index[ts_ms] = (str(zp), info.filename)

    print(f"  {len(index)} activity FIT files indexed")
    print(f"  Skipped: {skipped_small} small files, {skipped_nonactivity} non-activity files")

    try:
        with open(cache_file, "wb") as f:
            pickle.dump(index, f)
    except Exception:
        pass

    return index


def match_activities_to_fits(activities: list, fit_index: dict) -> tuple:
    """Match each activity to a FIT file by timestamp (within 60s window). Returns (matched, missing)."""
    matched = []
    missing = []
    fit_timestamps = sorted(fit_index.keys())
    for a in activities:
        target = a.get("beginTimestamp")
        if not target:
            missing.append(a)
            continue
        # binary search for closest ts
        import bisect
        i = bisect.bisect_left(fit_timestamps, target)
        candidates = []
        if i > 0: candidates.append(fit_timestamps[i-1])
        if i < len(fit_timestamps): candidates.append(fit_timestamps[i])
        best = min(candidates, key=lambda t: abs(t - target)) if candidates else None
        if best is not None and abs(best - target) <= 60_000:
            matched.append((a, fit_index[best]))
        else:
            missing.append(a)
    return matched, missing


def strava_refresh_access_token() -> str:
    resp = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def strava_upload(access_token: str, fit_path: Path, activity: dict) -> str:
    sport_type = ACTIVITY_MAP.get(activity.get("activityType", "running"), "Workout")
    name = activity.get("name") or "Imported activity"

    with open(fit_path, "rb") as f:
        resp = requests.post(
            "https://www.strava.com/api/v3/uploads",
            headers={"Authorization": f"Bearer {access_token}"},
            data={"data_type": "fit", "activity_type": sport_type, "name": name},
            files={"file": f},
        )

    if resp.status_code in (400, 409) and "duplicate" in resp.text.lower():
        return "duplicate"
    if resp.status_code == 429:
        # Strava rate limit (100/15min, 1000/day) — back off
        raise RuntimeError("Strava rate limit hit — wait 15 min and re-run")
    resp.raise_for_status()
    upload_id = resp.json()["id"]

    for _ in range(20):
        time.sleep(2)
        s = requests.get(f"https://www.strava.com/api/v3/uploads/{upload_id}",
                         headers={"Authorization": f"Bearer {access_token}"})
        s.raise_for_status()
        info = s.json()
        if info.get("activity_id"):
            return str(info["activity_id"])
        if info.get("error"):
            err = info["error"].lower()
            if "duplicate" in err:
                return "duplicate"
            raise RuntimeError(f"Strava: {info['error']}")
    raise TimeoutError(f"Strava upload {upload_id} timed out")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("export_folder", help="Path to unzipped Garmin data export folder")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--type", help="Filter to a single activityType (e.g. running)")
    parser.add_argument("--limit", type=int, help="Process at most N activities (for testing)")
    args = parser.parse_args()

    export_root = Path(args.export_folder).expanduser().resolve()
    if not export_root.exists():
        raise SystemExit(f"Path not found: {export_root}")

    for k in ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN"):
        if not os.environ.get(k):
            raise SystemExit(f"ERROR: {k} not set. Run: python3 setup_strava.py")

    # Load activity metadata
    acts_json = find_activities_json(export_root)
    with open(acts_json) as f:
        data = json.load(f)
    activities = data[0]["summarizedActivitiesExport"]
    print(f"Loaded {len(activities)} activities from {acts_json.name}")

    if args.type:
        activities = [a for a in activities if a.get("activityType") == args.type]
        print(f"Filtered to {len(activities)} '{args.type}' activities")

    # Build FIT index (filtered to activity-type files, keyed by timestamp)
    cache_file = Path(__file__).parent / ".fit_index.pkl"
    fit_index = build_fit_index(find_uploaded_zips(export_root), cache_file)

    # Match activities to FIT files by timestamp
    conn = init_db()
    matched, missing = match_activities_to_fits(activities, fit_index)

    print(f"\n{len(matched)} activities matched to FIT files")
    if missing:
        print(f"{len(missing)} activities had no FIT match (likely manual entries)")

    to_sync = [(a, loc) for a, loc in matched if not is_synced(conn, a.get("activityId"))]
    already = len(matched) - len(to_sync)
    print(f"{len(to_sync)} new to upload  ({already} already synced)")

    if args.limit:
        to_sync = to_sync[:args.limit]
        print(f"  --limit {args.limit}: processing first {len(to_sync)} only")

    if args.dry_run:
        for a, _ in to_sync[:50]:
            stl = str(a.get('startTimeLocal', ''))[:19]
            print(f"  {stl}  {a.get('activityType')}  {a.get('name','')}")
        if len(to_sync) > 50:
            print(f"  ... and {len(to_sync) - 50} more")
        return

    if not to_sync:
        print("Nothing to do.")
        return

    print("\nRefreshing Strava token...")
    access_token = strava_refresh_access_token()
    token_at = time.time()
    errors = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for activity, (zp, member) in tqdm(to_sync, desc="Uploading", unit="act"):
            aid = str(activity.get("activityId"))

            if time.time() - token_at > 3000:
                access_token = strava_refresh_access_token()
                token_at = time.time()

            try:
                # Extract FIT file from zip
                with zipfile.ZipFile(zp) as zf:
                    fit_path = Path(tmpdir) / f"{aid}.fit"
                    fit_path.write_bytes(zf.read(member))

                strava_id = strava_upload(access_token, fit_path, activity)
                mark_synced(conn, aid, strava_id)
                tag = "DUP" if strava_id == "duplicate" else "OK "
                stl = str(activity.get('startTimeLocal', ''))[:19]
                tqdm.write(f"  {tag} {stl}  {activity.get('name','')}  → {strava_id}")
            except Exception as e:
                err_str = str(e)
                stl = str(activity.get('startTimeLocal', ''))[:19]
                tqdm.write(f"  ERR {stl}  {activity.get('name','')}: {err_str}")
                errors.append((aid, activity.get("name", ""), err_str))
                if "rate limit" in err_str.lower():
                    print("\nStrava rate limit reached. Stopping. Re-run later to resume.")
                    break
            finally:
                time.sleep(0.4)  # ~150 uploads / 15-min Strava window

    print(f"\nDone. {len(to_sync) - len(errors)} processed, {len(errors)} failed.")
    if errors:
        print("\nFailures:")
        for aid, name, err in errors[:20]:
            print(f"  {aid}  {name}: {err}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")


if __name__ == "__main__":
    main()
