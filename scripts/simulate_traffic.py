#!/usr/bin/env python3
"""Send live traffic to the ingest service, the way monitored applications would.

It backfills the last N minutes for every demo application through
POST /api/v1/events (batches, one API key per application), can inject a
failing canary release, and can keep streaming in real time afterwards.

Examples
    python scripts/simulate_traffic.py                        # last 60 minutes, all apps
    python scripts/simulate_traffic.py --canary checkout-web  # plus a bad release of checkout-web
    python scripts/simulate_traffic.py --follow               # then keep sending every 5 seconds

The demo applications use the development keys from database/03_seed_reference.sql
(dev-key-<code>). For an application registered through the API, pass its
real key with --api-key (only valid together with --apps <that code>).
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import requests
from traffic_model import PROFILES, canary_incident, generate_events

FOLLOW_INTERVAL_S = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080", help="ingest service URL")
    parser.add_argument("--minutes", type=int, default=60, help="minutes of history to backfill (default 60)")
    parser.add_argument("--apps", default="all", help="comma separated codes, or 'all'")
    parser.add_argument("--canary", metavar="APP", help="inject a failing canary release in this app")
    parser.add_argument("--canary-minutes", type=int, default=30, help="how long the canary has been live (default 30)")
    parser.add_argument("--scale", type=float, default=1.0, help="traffic multiplier")
    parser.add_argument("--batch-size", type=int, default=500, help="events per request (max 1000)")
    parser.add_argument("--api-key", help="override the dev key (single app only)")
    parser.add_argument("--follow", action="store_true", help="keep streaming until Ctrl+C")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    if args.canary and args.canary not in PROFILES:
        parser.error(f"unknown app for --canary: {args.canary}")
    if not 1 <= args.batch_size <= 1000:
        parser.error("--batch-size must be between 1 and 1000")
    return args


def to_payload(frame: pd.DataFrame) -> list[dict]:
    """DataFrame rows -> the JSON objects the Java service expects (camelCase)."""
    return [
        {
            "occurredAt": ts.isoformat().replace("+00:00", "Z"),
            "endpoint": endpoint,
            "method": method,
            "statusCode": int(status),
            "latencyMs": int(latency),
            "region": region,
            "metadata": {"appVersion": version, "client": client},
        }
        for ts, endpoint, method, status, latency, region, version, client in frame.itertuples(index=False, name=None)
    ]


def send(
    session: requests.Session, base_url: str, api_key: str, events: list[dict], batch_size: int
) -> tuple[int, int]:
    """POST the events in batches. Returns (accepted, rejected)."""
    accepted = rejected = 0
    for start in range(0, len(events), batch_size):
        batch = events[start : start + batch_size]
        try:
            response = session.post(
                f"{base_url}/api/v1/events",
                json={"events": batch},
                headers={"X-API-Key": api_key},
                timeout=10,
            )
        except requests.RequestException as exc:
            print(f"    request failed: {exc}")
            rejected += len(batch)
            continue
        if response.status_code == 202:
            accepted += response.json()["accepted"]
        else:
            rejected += len(batch)
            print(f"    HTTP {response.status_code}: {response.text[:200]}")
    return accepted, rejected


def main() -> int:
    args = parse_args()
    codes = list(PROFILES) if args.apps == "all" else [c.strip() for c in args.apps.split(",")]
    unknown = [c for c in codes if c not in PROFILES]
    if unknown:
        print(f"Unknown applications: {unknown}. Known: {list(PROFILES)}")
        return 1
    if args.api_key and len(codes) != 1:
        print("--api-key only makes sense with a single --apps value")
        return 1

    rng = np.random.default_rng(args.seed)
    now = datetime.now(UTC)
    incidents = []
    if args.canary:
        canary = canary_incident(args.canary, now, args.canary_minutes)
        if args.follow:  # keep the bad release live while streaming
            canary = dataclasses.replace(canary, minutes=canary.minutes + 24 * 60)
        incidents.append(canary)
        print(f"Canary: {canary.description} on {canary.app_code} since {canary.start:%H:%M} UTC")

    session = requests.Session()
    key_of = {code: args.api_key or f"dev-key-{code}" for code in codes}

    print(f"Backfilling {args.minutes} minutes to {args.base_url} ...")
    start = now - timedelta(minutes=args.minutes)
    for code in codes:
        frame = generate_events(PROFILES[code], start, now, rng, incidents, args.scale)
        accepted, rejected = send(session, args.base_url, key_of[code], to_payload(frame), args.batch_size)
        print(f"  {code:<18} accepted {accepted:>6}  rejected {rejected:>4}")

    if not args.follow:
        return 0

    print(f"Streaming every {FOLLOW_INTERVAL_S} s. Press Ctrl+C to stop.")
    window_start = now
    try:
        while True:
            time.sleep(FOLLOW_INTERVAL_S)
            window_end = datetime.now(UTC)
            total = 0
            for code in codes:
                # generate_events works per whole minute, so build the minute and keep our slice
                frame = generate_events(
                    PROFILES[code],
                    window_start.replace(second=0, microsecond=0),
                    window_end.replace(second=0, microsecond=0) + timedelta(minutes=1),
                    rng,
                    incidents,
                    args.scale,
                )
                frame = frame[(frame["occurred_at"] >= window_start) & (frame["occurred_at"] < window_end)]
                accepted, _ = send(session, args.base_url, key_of[code], to_payload(frame), args.batch_size)
                total += accepted
            print(f"  {window_end:%H:%M:%S} UTC  +{total} events")
            window_start = window_end
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
