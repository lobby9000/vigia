#!/usr/bin/env python3
"""Calibrate the anomaly detector by simulation (a small Monte Carlo study).

Replays what ``make seed``, ``make simulate`` (with a failing canary in
checkout-web) and ``make scan`` do, entirely in memory, for several
independent runs: different random seeds and different end times, so the
incidents fall at different positions inside the 15-minute buckets.

For every candidate latency threshold it counts:

* missed: injected incidents the detector did not report,
* canaries: runs in which the failing release of the last hour was caught,
* false alarms: episodes that do not overlap any injected problem.

This is how the defaults of DetectorConfig were chosen. Over 40 runs (2 400
application-days, 120 injected incidents) nothing was ever missed, and:

    min_requests  latency_threshold  false alarms
              30                3.5            18   (the starting point)
             100                3.5             4
             100                4.5             1   (the defaults)

Most false alarms came from night buckets of small applications, where the p95
of 40 requests is really the second slowest call. Judging latency only with at
least 100 requests (about 5 of them above the p95) fixed the cause; the higher
threshold added a safety margin.

The runs start from a fixed date, so the same arguments print the same table.

Examples
    python scripts/calibrate_detector.py                         # 10 runs, thresholds 3.5 4.0 4.5 5.0
    python scripts/calibrate_detector.py --runs 40 --thresholds 3.5 4.5
    python scripts/calibrate_detector.py --min-requests 30       # what the old rule did
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
from traffic_model import PROFILES, Incident, canary_incident, default_history_incidents, generate_events

ANOMALY_MODULE = Path(__file__).resolve().parents[1] / "analytics-api" / "vigia_analytics" / "anomaly.py"
HISTORY_DAYS = 10
LIVE_MINUTES = 60  # generate_history.py --leave-minutes, simulate_traffic.py --minutes
SCAN_HOURS = 240
REFERENCE_END = datetime(2026, 10, 1, 17, 0, tzinfo=UTC)  # any date works; a fixed one makes runs reproducible


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=10, help="independent simulations (default 10)")
    parser.add_argument(
        "--thresholds", type=float, nargs="+", default=[3.5, 4.0, 4.5, 5.0], help="latency thresholds to compare"
    )
    parser.add_argument("--canary-minutes", type=int, default=30, help="how long the canary has been live")
    parser.add_argument("--bucket-minutes", type=int, default=15, choices=(5, 15, 30, 60))
    parser.add_argument("--min-requests", type=int, help="override DetectorConfig.min_requests")
    parser.add_argument("--seed", type=int, default=2026, help="base random seed, for reproducible results")
    parser.add_argument(
        "--check",
        action="store_true",
        help="for CI: fail if the default threshold misses an incident or a canary, or exceeds --max-false-alarms",
    )
    parser.add_argument("--max-false-alarms", type=int, default=1, help="tolerance used by --check (default 1)")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    return args


def load_detector() -> ModuleType:
    """Import anomaly.py straight from its file.

    Importing the ``vigia_analytics`` package would also import Flask, which the
    scripts do not need: the detector itself only depends on NumPy, pandas and SciPy.
    """
    spec = importlib.util.spec_from_file_location("vigia_anomaly", ANOMALY_MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while being created
    spec.loader.exec_module(module)
    return module


def bucket_series(events: pd.DataFrame, start: datetime, end: datetime, minutes: int) -> pd.DataFrame:
    """The same numbers as repository.fetch_bucket_series, computed with pandas.

    ``date_bin`` with origin 2000-01-01 equals flooring to the bucket size, and
    PostgreSQL's ``percentile_cont`` interpolates linearly, like pandas' quantile.
    """
    window = events[(events["occurred_at"] >= start) & (events["occurred_at"] < end)]
    keys = window["occurred_at"].dt.floor(f"{minutes}min")
    grouped = window.assign(is_error=window["status_code"] >= 500).groupby(keys)
    series = pd.DataFrame(
        {
            "requests": grouped.size(),
            "errors_5xx": grouped["is_error"].sum(),
            "p95_latency_ms": grouped["latency_ms"].quantile(0.95),
        }
    )
    series = series.rename_axis("bucket").reset_index()
    series["error_rate"] = series["errors_5xx"] / series["requests"]
    return series


def simulate_run(rng: np.random.Generator, end: datetime, canary_minutes: int):
    """Events per application, built in the same order as the real scripts build them."""
    start = end - timedelta(days=HISTORY_DAYS)
    incidents = [incident for incident in default_history_incidents(end) if start <= incident.start < end]
    chunks: dict[str, list[pd.DataFrame]] = {code: [] for code in PROFILES}

    day_start = start  # generate_history.py: one day at a time, every application
    while day_start < end:
        day_end = min(day_start + timedelta(days=1), end)
        for code, profile in PROFILES.items():
            chunks[code].append(generate_events(profile, day_start, day_end, rng, incidents))
        day_start = day_end

    now = end + timedelta(minutes=LIVE_MINUTES)  # simulate_traffic.py sends the hour the history left out
    canary = canary_incident("checkout-web", now, canary_minutes)
    for code, profile in PROFILES.items():
        live = [canary] if code == canary.app_code else []
        chunks[code].append(generate_events(profile, end, now, rng, live))

    events = {code: pd.concat(parts, ignore_index=True) for code, parts in chunks.items()}
    return events, incidents, canary, now


def overlaps(episode, incident: Incident) -> bool:
    return episode.start <= pd.Timestamp(incident.end) and episode.end >= pd.Timestamp(incident.start)


def main() -> int:
    args = parse_args()
    detector = load_detector()
    overrides = {} if args.min_requests is None else {"min_requests": args.min_requests}
    missed = dict.fromkeys(args.thresholds, 0)
    canaries = dict.fromkeys(args.thresholds, 0)
    false_alarms = {threshold: Counter() for threshold in args.thresholds}

    for run in range(args.runs):
        rng = np.random.default_rng([args.seed, run])
        # An irregular shift (11 h 31 min) moves every incident to a new place in the day and in its bucket.
        end = REFERENCE_END + timedelta(minutes=691 * run)
        events, incidents, canary, now = simulate_run(rng, end, args.canary_minutes)
        scan_end = now + timedelta(minutes=1)

        for code, frame in events.items():
            series = bucket_series(frame, scan_end - timedelta(hours=SCAN_HOURS), scan_end, args.bucket_minutes)
            expected = [incident for incident in incidents if incident.app_code == code]
            for threshold in args.thresholds:
                config = detector.DetectorConfig(latency_threshold=threshold, **overrides)
                _, episodes = detector.detect(series, config, args.bucket_minutes)
                missed[threshold] += sum(not any(overlaps(ep, incident) for ep in episodes) for incident in expected)
                if code == canary.app_code and any(overlaps(ep, canary) for ep in episodes):
                    canaries[threshold] += 1
                known_problems = [*expected, canary] if code == canary.app_code else expected
                for episode in episodes:
                    if not any(overlaps(episode, problem) for problem in known_problems):
                        false_alarms[threshold][code] += 1
        print(f"  run {run + 1}/{args.runs} done", file=sys.stderr)

    injected = len(default_history_incidents(REFERENCE_END)) * args.runs
    print(
        f"\n{args.runs} runs x {HISTORY_DAYS} days x {len(PROFILES)} applications: "
        f"{injected} injected incidents and {args.runs} canary releases\n"
    )
    print(f"{'latency threshold':>17}  {'missed':>6}  {'canaries':>8}  false alarms")
    for threshold in args.thresholds:
        detail = ", ".join(f"{code}: {count}" for code, count in false_alarms[threshold].most_common())
        total = sum(false_alarms[threshold].values())
        print(
            f"{threshold:>17}  {missed[threshold]:>6}  {canaries[threshold]:>3} / {args.runs:<2}  "
            f"{total}{f' ({detail})' if detail else ''}"
        )
    return check(args, detector, missed, canaries, false_alarms) if args.check else 0


def check(args: argparse.Namespace, detector: ModuleType, missed, canaries, false_alarms) -> int:
    """Exit code for CI: a change that makes the detector worse turns the build red."""
    default = detector.DetectorConfig().latency_threshold
    if default not in args.thresholds:
        print(f"--check needs the default latency threshold ({default}) among --thresholds")
        return 2
    alarms = sum(false_alarms[default].values())
    failed = missed[default] > 0 or canaries[default] < args.runs or alarms > args.max_false_alarms
    print(
        f"\ncheck at the default threshold {default}: {'FAILED' if failed else 'passed'} "
        f"(missed {missed[default]}, canaries {canaries[default]}/{args.runs}, "
        f"false alarms {alarms}, tolerance {args.max_false_alarms})"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
