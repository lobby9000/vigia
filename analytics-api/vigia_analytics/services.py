"""Use cases: the rules that combine PostgreSQL, MongoDB and the detector.

Views stay thin (parse input, call one function here, return its result).
These functions know nothing about HTTP, so they are easy to test and to
reuse from the CLI.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from bson import ObjectId
from pymongo.database import Database
from sqlalchemy import Engine

from . import repository as repo
from .anomaly import DetectorConfig, Episode, classify_severity, detect
from .security import verify_password


class NotFoundError(Exception):
    """The requested resource does not exist (HTTP 404)."""


class ConflictError(Exception):
    """The request is valid but clashes with the current state (HTTP 409)."""


# Incident life cycle. RESOLVED is terminal: reopening means a new incident.
ALLOWED_TRANSITIONS = {
    "OPEN": {"ACKNOWLEDGED", "RESOLVED"},
    "ACKNOWLEDGED": {"RESOLVED"},
    "RESOLVED": set(),
}

METRIC_LABELS = {"latency_p95": "high p95 latency", "error_rate": "elevated 5xx errors"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_plain(value):
    """NumPy and pandas scalars -> plain Python (BSON and JSON cannot encode NaN or int64)."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    return value


def _require_application(conn, app_code: str) -> dict:
    app = repo.get_application(conn, app_code)
    if app is None:
        raise NotFoundError(f"Application '{app_code}' does not exist.")
    return app


# ---------------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------------
def authenticate(engine: Engine, username: str, password: str) -> dict | None:
    with engine.connect() as conn:
        user = repo.find_active_user(conn, username)
    stored_hash = user["password_hash"] if user else None
    if not verify_password(stored_hash, password):
        return None
    return {"username": user["username"], "role": user["role"]}


# ---------------------------------------------------------------------------------
# Health series
# ---------------------------------------------------------------------------------
def health_series(engine: Engine, app_code: str, hours: int, bucket_minutes: int, end: datetime | None) -> dict:
    end = end or utcnow()
    start = end - timedelta(hours=hours)
    with engine.connect() as conn:
        app = _require_application(conn, app_code)
        frame = repo.fetch_bucket_series(conn, app["id"], start, end, bucket_minutes)
    points = [{key: to_plain(value) for key, value in row.items()} for row in frame.to_dict("records")]
    return {"app_code": app_code, "start": start, "end": end, "bucket_minutes": bucket_minutes, "points": points}


# ---------------------------------------------------------------------------------
# Anomaly scans
# ---------------------------------------------------------------------------------
def run_anomaly_scan(engine: Engine, mongo: Database, app_code: str, args: dict, requested_by: str) -> dict:
    """Detect anomalies, store the full report in MongoDB, open incidents in PostgreSQL."""
    end = args.get("end") or utcnow()
    start = end - timedelta(hours=args["hours"])
    bucket_minutes = args["bucket_minutes"]
    config = DetectorConfig(
        window=args["window"],
        latency_threshold=args["latency_threshold"],
        error_threshold=args["error_threshold"],
    )

    with engine.connect() as conn:
        app = _require_application(conn, app_code)
        series = repo.fetch_bucket_series(conn, app["id"], start, end, bucket_minutes)

    scored, episodes = detect(series, config, bucket_minutes)
    report_id = ObjectId()  # generated client side, so incidents can reference it
    created_at = utcnow()
    episode_docs = [_episode_document(episode, app) for episode in episodes]
    anomalous = scored[scored["anomalous"]] if len(scored) else scored
    detail_columns = [
        "bucket",
        "requests",
        "errors_5xx",
        "error_rate",
        "p95_latency_ms",
        "latency_baseline_ms",
        "latency_score",
        "error_baseline_rate",
        "error_score",
    ]

    # The report is a nested, variable-size document (a list of episodes, a list
    # of buckets with their scores): a natural fit for MongoDB.
    report = {
        "_id": report_id,
        "app_code": app_code,
        "created_at": created_at,
        "created_by": requested_by,
        "start": start,
        "end": end,
        "bucket_minutes": bucket_minutes,
        "params": {
            "window": config.window,
            "latency_threshold": config.latency_threshold,
            "min_relative_increase": config.min_relative_increase,
            "error_threshold": config.error_threshold,
            "min_requests": config.min_requests,
            "min_errors": config.min_errors,
        },
        "buckets_analyzed": int(len(scored)),
        "anomalous_buckets": int(len(anomalous)),
        "episodes": episode_docs,
        "anomalous_bucket_details": [
            {key: to_plain(value) for key, value in row.items()} for row in anomalous[detail_columns].to_dict("records")
        ]
        if len(anomalous)
        else [],
    }
    mongo.anomaly_reports.insert_one(report)

    incidents_opened: list[int] = []
    if args["open_incidents"] and episode_docs:
        with engine.begin() as conn:  # all incidents of one scan commit together
            for doc in episode_docs:
                incident_id = repo.insert_detector_incident(
                    conn,
                    app_id=app["id"],
                    title=_incident_title(app_code, doc),
                    description=_incident_description(doc, app, bucket_minutes, report_id),
                    severity=doc["severity"],
                    window_start=doc["start"],
                    window_end=doc["end"],
                    report_id=str(report_id),
                )
                doc["incident_id"] = incident_id
                if incident_id is not None:
                    incidents_opened.append(incident_id)
        mongo.anomaly_reports.update_one({"_id": report_id}, {"$set": {"episodes": episode_docs}})

    return {
        "report_id": str(report_id),
        "app_code": app_code,
        "created_at": created_at,
        "created_by": requested_by,
        "start": start,
        "end": end,
        "bucket_minutes": bucket_minutes,
        "buckets_analyzed": report["buckets_analyzed"],
        "anomalous_buckets": report["anomalous_buckets"],
        "episodes": episode_docs,
        "incidents_opened": incidents_opened,
    }


def list_scan_reports(engine: Engine, mongo: Database, app_code: str, limit: int) -> list[dict]:
    with engine.connect() as conn:
        _require_application(conn, app_code)
    cursor = (
        mongo.anomaly_reports.find({"app_code": app_code}, {"anomalous_bucket_details": 0, "params": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    reports = []
    for document in cursor:
        document["report_id"] = str(document.pop("_id"))
        reports.append(document)
    return reports


def _episode_document(episode: Episode, app: dict) -> dict:
    return {
        "start": to_plain(episode.start),
        "end": to_plain(episode.end),
        "buckets": episode.buckets,
        "metrics": list(episode.metrics),
        "peak_latency_p95_ms": to_plain(episode.peak_latency_p95_ms),
        "peak_error_rate": to_plain(episode.peak_error_rate),
        "max_score": round(float(episode.max_score), 2),
        "requests": episode.requests,
        "errors_5xx": episode.errors_5xx,
        "severity": classify_severity(episode, app["tier"], app["slo_latency_p95_ms"]),
        "incident_id": None,
    }


def _incident_title(app_code: str, episode: dict) -> str:
    labels = " and ".join(METRIC_LABELS[m] for m in episode["metrics"])
    return f"{labels[:1].upper()}{labels[1:]} on {app_code}"


def _incident_description(episode: dict, app: dict, bucket_minutes: int, report_id: ObjectId) -> str:
    return (
        f"Anomaly detector: {episode['buckets']} anomalous {bucket_minutes}-minute buckets "
        f"from {episode['start']:%Y-%m-%d %H:%M} to {episode['end']:%Y-%m-%d %H:%M} UTC. "
        f"Peak p95 latency {episode['peak_latency_p95_ms']:.0f} ms (SLO {app['slo_latency_p95_ms']} ms), "
        f"peak 5xx rate {episode['peak_error_rate']:.2%}, max score {episode['max_score']:.1f}. "
        f"Full report: anomaly_reports/{report_id}."
    )


# ---------------------------------------------------------------------------------
# Error breakdown: which version or region is failing? (MongoDB aggregation)
# ---------------------------------------------------------------------------------
def error_breakdown(engine: Engine, mongo: Database, app_code: str, minutes: int) -> dict:
    """Group the raw events archived by the ingest service by version and region.

    Raw events carry free-form metadata (app version, client) that is not in
    the SQL schema. This is the query an on-call engineer runs first:
    "is one release or one region responsible for the errors?"
    """
    with engine.connect() as conn:
        _require_application(conn, app_code)
    since = utcnow() - timedelta(minutes=minutes)
    pipeline = [
        {"$match": {"appCode": app_code, "occurredAt": {"$gte": since}}},
        {
            "$group": {
                "_id": {"version": "$metadata.appVersion", "region": "$region"},
                "requests": {"$sum": 1},
                "errors": {"$sum": {"$cond": [{"$gte": ["$statusCode", 500]}, 1, 0]}},
                "latency": {"$avg": "$latencyMs"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "app_version": {"$ifNull": ["$_id.version", "unknown"]},
                "region": "$_id.region",
                "requests": 1,
                "errors_5xx": "$errors",
                "avg_latency_ms": "$latency",
                "error_rate": {"$divide": ["$errors", "$requests"]},
            }
        },
        {"$sort": {"error_rate": -1, "requests": -1}},
        {"$limit": 50},
    ]
    rows = list(mongo.raw_events.aggregate(pipeline))
    for row in rows:
        row["avg_latency_ms"] = round(row["avg_latency_ms"], 1) if row.get("avg_latency_ms") is not None else None
    return {
        "app_code": app_code,
        "minutes": minutes,
        "total_requests": sum(row["requests"] for row in rows),
        "rows": rows,
    }


# ---------------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------------
def change_incident_status(engine: Engine, incident_id: int, new_status: str) -> dict:
    with engine.begin() as conn:  # the row lock lasts until this block commits
        current = repo.lock_incident_status(conn, incident_id)
        if current is None:
            raise NotFoundError(f"Incident {incident_id} does not exist.")
        if new_status not in ALLOWED_TRANSITIONS[current]:
            raise ConflictError(f"Cannot move an incident from {current} to {new_status}.")
        repo.update_incident_status(conn, incident_id, new_status)
        return repo.get_incident(conn, incident_id)
