"""Synthetic traffic model shared by generate_history.py and simulate_traffic.py.

The goal is telemetry that *behaves* like production data, so that the SQL,
the anomaly detector and the dashboards have something realistic to chew on:

* Arrivals per minute follow a Poisson process whose rate follows the time of
  day in Mexico City (quiet around 4 am, busiest around 4 pm).
* Latency is log-normal: most requests are fast, with a long right tail.
  Latency also grows a little with load, as it does on real servers.
* A small, app-specific fraction of requests fails with 4xx or 5xx codes.
* Incidents are time windows that multiply latency and/or raise the 5xx
  probability. A "canary" incident only affects one application version,
  which is how a bad deploy usually looks.

Everything is vectorised with NumPy: no Python loop over individual requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# America/Mexico_City has no daylight saving time since 2022: UTC-6 all year.
LOCAL_UTC_OFFSET_HOURS = -6

REGIONS = np.array(["mx-central", "us-east", "mx-north"])
REGION_WEIGHTS = np.array([0.55, 0.25, 0.20])

CLIENTS = np.array(["android", "ios", "web"])
CLIENT_WEIGHTS = np.array([0.45, 0.30, 0.25])

SERVER_ERRORS = np.array([500, 502, 503, 504])
SERVER_ERROR_WEIGHTS = np.array([0.40, 0.20, 0.25, 0.15])

CLIENT_ERRORS = np.array([400, 401, 404, 409, 422])
CLIENT_ERROR_WEIGHTS = np.array([0.30, 0.15, 0.35, 0.10, 0.10])

SUCCESS_BY_METHOD = {"GET": 200, "POST": 201, "PUT": 200, "PATCH": 200, "DELETE": 204}


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str  # route template, e.g. /v1/payments/{id} (low cardinality on purpose)
    weight: float  # share of the app's traffic
    median_ms: float  # typical latency at low load


@dataclass(frozen=True)
class AppProfile:
    code: str
    rate_per_s: float  # requests per second at the daily peak
    endpoints: tuple[Endpoint, ...]
    error_5xx: float  # baseline probability of a server error
    error_4xx: float  # baseline probability of a client error
    latency_sigma: float = 0.35  # log-normal shape: bigger means a heavier tail
    versions: tuple[str, ...] = ("1.0.0", "1.1.0")  # (current, next release)


@dataclass(frozen=True)
class Incident:
    app_code: str
    start: datetime  # timezone-aware, UTC
    minutes: int
    latency_factor: float = 1.0
    error_5xx: float | None = None  # replaces the baseline probability when set
    version: str | None = None  # canary: only this version is affected
    version_share: float = 0.0  # share of traffic served by the canary version
    description: str = ""

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.minutes)


PROFILES: dict[str, AppProfile] = {
    p.code: p
    for p in (
        AppProfile(
            "payments-api",
            0.30,
            (
                Endpoint("POST", "/v1/payments", 0.55, 180),
                Endpoint("GET", "/v1/payments/{id}", 0.35, 45),
                Endpoint("POST", "/v1/refunds", 0.10, 240),
            ),
            error_5xx=0.0002,
            error_4xx=0.020,
            versions=("4.7.2", "4.8.0"),
        ),
        AppProfile(
            "checkout-web",
            0.50,
            (
                Endpoint("GET", "/checkout", 0.45, 220),
                Endpoint("POST", "/checkout/confirm", 0.25, 380),
                Endpoint("GET", "/cart", 0.30, 120),
            ),
            error_5xx=0.0004,
            error_4xx=0.015,
            versions=("3.1.4", "3.2.0"),
        ),
        AppProfile(
            "login-service",
            0.80,
            (
                Endpoint("POST", "/v1/login", 0.60, 90),
                Endpoint("POST", "/v1/token/refresh", 0.30, 35),
                Endpoint("POST", "/v1/logout", 0.10, 25),
            ),
            error_5xx=0.0002,
            error_4xx=0.050,
            versions=("2.12.1", "2.13.0"),
        ),
        AppProfile(
            "catalog-api",
            0.60,
            (
                Endpoint("GET", "/v1/products", 0.50, 150),
                Endpoint("GET", "/v1/products/{id}", 0.40, 60),
                Endpoint("GET", "/v1/search", 0.10, 260),
            ),
            error_5xx=0.0030,
            error_4xx=0.020,
            versions=("5.0.3", "5.1.0"),
        ),
        AppProfile(
            "loyalty-api",
            0.15,
            (Endpoint("GET", "/v1/points/{customer}", 0.70, 80), Endpoint("POST", "/v1/points/redeem", 0.30, 210)),
            error_5xx=0.0020,
            error_4xx=0.010,
            versions=("1.9.0", "1.10.0"),
        ),
        AppProfile(
            "notifications-api",
            0.20,
            (Endpoint("POST", "/v1/notifications", 0.80, 300), Endpoint("GET", "/v1/notifications/{id}", 0.20, 70)),
            error_5xx=0.0060,
            error_4xx=0.010,
            latency_sigma=0.50,
            versions=("0.14.2", "0.15.0"),
        ),
    )
}


def diurnal_factor(utc_hours: np.ndarray) -> np.ndarray:
    """Load multiplier in [0.25, 1.0] for a fractional UTC hour of day.

    A shifted cosine: minimum at 04:00 local time, maximum at 16:00.
    """
    local = (np.asarray(utc_hours, dtype=float) + LOCAL_UTC_OFFSET_HOURS) % 24
    return 0.25 + 0.75 * (0.5 - 0.5 * np.cos(2 * np.pi * (local - 4) / 24))


def generate_events(
    profile: AppProfile,
    start: datetime,
    end: datetime,
    rng: np.random.Generator,
    incidents: list[Incident] | tuple[Incident, ...] = (),
    scale: float = 1.0,
) -> pd.DataFrame:
    """Generate every request of one application between ``start`` and ``end``.

    Returns a DataFrame sorted by ``occurred_at`` with the columns
    occurred_at, endpoint, http_method, status_code, latency_ms, region,
    app_version and client.
    """
    minutes = pd.date_range(start, end, freq="min", inclusive="left")
    if len(minutes) == 0:
        return _empty_frame()

    # 1) How many requests arrive in each minute: Poisson(rate * load)
    utc_hours = minutes.hour + minutes.minute / 60
    load = diurnal_factor(utc_hours)
    counts = rng.poisson(profile.rate_per_s * 60 * scale * load)
    n = int(counts.sum())
    if n == 0:
        return _empty_frame()

    # 2) Exact timestamps: uniformly spread inside their minute
    minute_ns = minutes.as_unit("ns").asi8
    offsets_ns = (rng.random(n) * 60e9).astype(np.int64)
    occurred_at = pd.to_datetime(np.repeat(minute_ns, counts) + offsets_ns, utc=True)
    load_per_request = np.repeat(load, counts)

    # 3) Which endpoint each request hits
    weights = np.array([e.weight for e in profile.endpoints])
    endpoint_idx = rng.choice(len(profile.endpoints), size=n, p=weights / weights.sum())
    paths = np.array([e.path for e in profile.endpoints])[endpoint_idx]
    methods = np.array([e.method for e in profile.endpoints])[endpoint_idx]
    medians = np.array([e.median_ms for e in profile.endpoints])[endpoint_idx]

    # 4) Apply incidents (only the ones that belong to this application)
    latency_factor = np.ones(n)
    p_5xx = np.full(n, profile.error_5xx)
    versions = np.full(n, profile.versions[0], dtype=object)
    for incident in incidents:
        if incident.app_code != profile.code:
            continue
        in_window = (occurred_at >= incident.start) & (occurred_at < incident.end)
        if incident.version:
            affected = in_window & (rng.random(n) < incident.version_share)
            versions[affected] = incident.version
        else:
            affected = in_window
        latency_factor[affected] *= incident.latency_factor
        if incident.error_5xx is not None:
            p_5xx[affected] = incident.error_5xx

    # 5) Latency: log-normal around the endpoint median, slower under load
    mu = np.log(medians * (1 + 0.25 * load_per_request) * latency_factor)
    latency = rng.lognormal(mean=mu, sigma=profile.latency_sigma)
    latency_ms = np.clip(np.rint(latency), 1, 60_000).astype(np.int32)

    # 6) Status codes: one uniform draw decides 5xx / 4xx / success
    u = rng.random(n)
    is_5xx = u < p_5xx
    is_4xx = ~is_5xx & (u < p_5xx + profile.error_4xx)
    status = np.array([SUCCESS_BY_METHOD[m] for m in methods], dtype=np.int16)
    status[is_5xx] = rng.choice(SERVER_ERRORS, size=int(is_5xx.sum()), p=SERVER_ERROR_WEIGHTS)
    status[is_4xx] = rng.choice(CLIENT_ERRORS, size=int(is_4xx.sum()), p=CLIENT_ERROR_WEIGHTS)

    frame = pd.DataFrame(
        {
            "occurred_at": occurred_at,
            "endpoint": paths,
            "http_method": methods,
            "status_code": status,
            "latency_ms": latency_ms,
            "region": rng.choice(REGIONS, size=n, p=REGION_WEIGHTS),
            "app_version": versions.astype(str),
            "client": rng.choice(CLIENTS, size=n, p=CLIENT_WEIGHTS),
        }
    )
    return frame.sort_values("occurred_at", kind="stable").reset_index(drop=True)


def default_history_incidents(end: datetime) -> list[Incident]:
    """Three incidents placed relative to ``end`` (times are UTC, CDMX is UTC-6)."""
    day0 = end.replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        Incident(
            "payments-api",
            day0 - timedelta(days=3) + timedelta(hours=20),
            90,
            latency_factor=4.0,
            error_5xx=0.01,
            description="Database connection pool saturation (14:00 CDMX, 90 min)",
        ),
        Incident(
            "login-service",
            day0 - timedelta(days=5) + timedelta(hours=15),
            40,
            error_5xx=0.12,
            description="Identity provider timeouts (09:00 CDMX, 40 min)",
        ),
        Incident(
            "checkout-web",
            day0 - timedelta(days=1) + timedelta(hours=2),
            30,
            latency_factor=1.8,
            error_5xx=0.05,
            description="Bad deploy rolled back after 30 min (20:00 CDMX)",
        ),
    ]


def canary_incident(app_code: str, now: datetime, minutes: int = 30) -> Incident:
    """A bad release: the next version takes 30 % of traffic and 40 % of its calls fail.

    That is 12 % errors overall: enough errors per bucket to be caught even at
    5 a.m., when traffic is at its lowest (see scripts/calibrate_detector.py).
    """
    profile = PROFILES[app_code]
    return Incident(
        app_code,
        now - timedelta(minutes=minutes),
        minutes + 1,
        latency_factor=1.5,
        error_5xx=0.40,
        version=profile.versions[1],
        version_share=0.30,
        description=f"Canary release {profile.versions[1]} failing",
    )


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "occurred_at": pd.Series([], dtype="datetime64[ns, UTC]"),
            "endpoint": pd.Series([], dtype=object),
            "http_method": pd.Series([], dtype=object),
            "status_code": pd.Series([], dtype=np.int16),
            "latency_ms": pd.Series([], dtype=np.int32),
            "region": pd.Series([], dtype=object),
            "app_version": pd.Series([], dtype=object),
            "client": pd.Series([], dtype=object),
        }
    )
