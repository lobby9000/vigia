#!/usr/bin/env python3
"""Load N days of synthetic request history straight into PostgreSQL.

Bulk loads skip the ingest API on purpose: COPY is the fastest way to put a
million rows into PostgreSQL (one round trip per day of data instead of one
INSERT per row). Live traffic goes through the API with simulate_traffic.py.

The history stops an hour ago (--leave-minutes): that last hour is the one
simulate_traffic.py sends through the Java API, so no minute is counted twice.

Examples
    python scripts/generate_history.py                      # 10 days, real scale
    python scripts/generate_history.py --days 3 --scale 0.2 # small and fast
    python scripts/generate_history.py --truncate           # wipe events first
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import psycopg
from traffic_model import PROFILES, default_history_incidents, generate_events

DEFAULT_DB = "postgresql://vigia:vigia@localhost:5432/vigia"

COPY_SQL = """
COPY request_events (app_id, occurred_at, received_at, endpoint, http_method,
                     status_code, latency_ms, region)
FROM STDIN WITH (FORMAT csv)
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=10, help="days of history (default 10)")
    parser.add_argument(
        "--leave-minutes", type=int, default=60, help="stop this many minutes ago, room for the live simulation"
    )
    parser.add_argument("--scale", type=float, default=1.0, help="traffic multiplier (default 1.0)")
    parser.add_argument("--seed", type=int, default=42, help="random seed, for reproducible data")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DB))
    parser.add_argument("--truncate", action="store_true", help="delete existing events and incidents first")
    parser.add_argument("--no-incidents", action="store_true", help="generate only healthy traffic")
    return parser.parse_args()


def to_psycopg_url(url: str) -> str:
    """Accept SQLAlchemy style URLs (postgresql+psycopg://) too."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def main() -> int:
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    end = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=args.leave_minutes)
    start = end - timedelta(days=args.days)
    incidents = [] if args.no_incidents else [i for i in default_history_incidents(end) if start <= i.start < end]

    started = time.perf_counter()
    with psycopg.connect(to_psycopg_url(args.database_url)) as conn:
        app_ids = dict(conn.execute("SELECT code, id FROM applications").fetchall())
        missing = sorted(set(PROFILES) - set(app_ids))
        if missing:
            print(f"Missing applications in the database: {missing}. Did 03_seed_reference.sql run?")
            return 1

        if args.truncate:
            conn.execute("TRUNCATE request_events, incidents RESTART IDENTITY")
            print("Truncated request_events and incidents.")

        rows_per_app = dict.fromkeys(PROFILES, 0)
        day_start = start
        while day_start < end:
            day_end = min(day_start + timedelta(days=1), end)
            frames = []
            for code, profile in PROFILES.items():
                frame = generate_events(profile, day_start, day_end, rng, incidents, args.scale)
                frame.insert(0, "app_id", app_ids[code])
                rows_per_app[code] += len(frame)
                frames.append(frame)

            # Interleave all apps in time order so the table's physical order
            # follows occurred_at. That is what makes the BRIN index useful.
            day = pd.concat(frames, ignore_index=True).sort_values("occurred_at", kind="stable")
            delay_ms = rng.lognormal(mean=np.log(120), sigma=0.6, size=len(day))
            day["received_at"] = day["occurred_at"] + pd.to_timedelta(delay_ms, unit="ms")
            columns = [
                "app_id",
                "occurred_at",
                "received_at",
                "endpoint",
                "http_method",
                "status_code",
                "latency_ms",
                "region",
            ]

            buffer = io.StringIO()
            day[columns].to_csv(buffer, index=False, header=False, date_format="%Y-%m-%d %H:%M:%S.%f%z")
            with conn.cursor() as cur, cur.copy(COPY_SQL) as copy:
                copy.write(buffer.getvalue())
            conn.commit()
            print(f"  {day_start:%Y-%m-%d %H:%M} -> {day_end:%Y-%m-%d %H:%M} UTC  {len(day):>9,} rows")
            day_start = day_end

        # Fresh statistics for the planner, then rebuild the daily view.
        conn.execute("ANALYZE request_events")
        conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_app_daily_stats")
        conn.commit()

    elapsed = time.perf_counter() - started
    total = sum(rows_per_app.values())
    print(f"\nLoaded {total:,} events in {elapsed:.1f} s ({total / max(elapsed, 1e-9):,.0f} rows/s)")
    for code, rows in rows_per_app.items():
        print(f"  {code:<18} {rows:>10,}")
    if incidents:
        print("\nInjected incidents (UTC):")
        for incident in incidents:
            print(f"  {incident.app_code:<15} {incident.start:%Y-%m-%d %H:%M}  {incident.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
