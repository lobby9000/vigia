"""Request and response schemas (marshmallow).

They do three jobs at once: validate input, serialize output and generate the
OpenAPI document that Swagger UI renders at /docs.

Python code uses snake_case; the JSON contract uses camelCase, the same
convention as the Java ingest service. ``CamelSchema`` does that translation
for every field automatically.
"""

from __future__ import annotations

from datetime import UTC

from marshmallow import Schema, fields, validate

from .anomaly import DetectorConfig

BUCKET_SIZES = (5, 15, 30, 60)
INCIDENT_STATUSES = ("OPEN", "ACKNOWLEDGED", "RESOLVED")


def camelize(name: str) -> str:
    """errors_5xx -> errors5xx, p95_latency_ms -> p95LatencyMs."""
    head, *tail = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class CamelSchema(Schema):
    def on_bind_field(self, field_name, field_obj):
        field_obj.data_key = camelize(field_obj.data_key or field_name)


# --- Auth ---------------------------------------------------------------------
class LoginSchema(CamelSchema):
    username = fields.String(required=True, validate=validate.Length(min=1, max=50))
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=1, max=200))


class TokenSchema(CamelSchema):
    access_token = fields.String()
    token_type = fields.String()
    expires_in = fields.Integer(metadata={"description": "Seconds until the token expires"})
    role = fields.String()


# --- Applications ---------------------------------------------------------------
class ApplicationSchema(CamelSchema):
    code = fields.String()
    name = fields.String()
    team = fields.String()
    tier = fields.Integer(metadata={"description": "1 = business critical, 3 = best effort"})
    slo_availability = fields.Float()
    slo_latency_p95_ms = fields.Integer()
    active = fields.Boolean()


class TimeWindowArgs(CamelSchema):
    hours = fields.Integer(load_default=24, validate=validate.Range(min=1, max=720))
    bucket_minutes = fields.Integer(load_default=15, validate=validate.OneOf(BUCKET_SIZES))
    end = fields.AwareDateTime(
        load_default=None,
        default_timezone=UTC,
        metadata={"description": "End of the window (ISO 8601). Defaults to now."},
    )


class HealthPointSchema(CamelSchema):
    bucket = fields.DateTime()
    requests = fields.Integer()
    errors_5xx = fields.Integer()
    error_rate = fields.Float()
    avg_latency_ms = fields.Float()
    p50_latency_ms = fields.Float()
    p95_latency_ms = fields.Float()


class HealthSeriesSchema(CamelSchema):
    app_code = fields.String()
    start = fields.DateTime()
    end = fields.DateTime()
    bucket_minutes = fields.Integer()
    points = fields.List(fields.Nested(HealthPointSchema))


# --- Anomaly detection ------------------------------------------------------------
class AnomalyScanArgs(TimeWindowArgs):
    # Defaults come from DetectorConfig, the single place where they are calibrated.
    hours = fields.Integer(load_default=72, validate=validate.Range(min=1, max=720))
    window = fields.Integer(
        load_default=DetectorConfig.window,
        validate=validate.Range(min=4, max=96),
        metadata={"description": "Trailing buckets used as the statistical baseline"},
    )
    latency_threshold = fields.Float(
        load_default=DetectorConfig.latency_threshold, validate=validate.Range(min=1.0, max=20.0)
    )
    error_threshold = fields.Float(
        load_default=DetectorConfig.error_threshold, validate=validate.Range(min=1.0, max=20.0)
    )
    open_incidents = fields.Boolean(load_default=True)


class EpisodeSchema(CamelSchema):
    start = fields.DateTime()
    end = fields.DateTime()
    buckets = fields.Integer()
    metrics = fields.List(fields.String())
    peak_latency_p95_ms = fields.Float()
    peak_error_rate = fields.Float()
    max_score = fields.Float()
    requests = fields.Integer()
    errors_5xx = fields.Integer()
    severity = fields.String()
    incident_id = fields.Integer(allow_none=True)


class AnomalyScanSchema(CamelSchema):
    report_id = fields.String()
    app_code = fields.String()
    created_at = fields.DateTime()
    created_by = fields.String()
    start = fields.DateTime()
    end = fields.DateTime()
    bucket_minutes = fields.Integer()
    buckets_analyzed = fields.Integer()
    anomalous_buckets = fields.Integer()
    episodes = fields.List(fields.Nested(EpisodeSchema))
    incidents_opened = fields.List(fields.Integer())


class LimitArgs(CamelSchema):
    limit = fields.Integer(load_default=10, validate=validate.Range(min=1, max=100))


# --- Incidents ----------------------------------------------------------------------
class IncidentSchema(CamelSchema):
    id = fields.Integer()
    app_code = fields.String()
    app_name = fields.String()
    title = fields.String()
    description = fields.String(allow_none=True)
    severity = fields.String()
    status = fields.String()
    source = fields.String()
    opened_at = fields.DateTime()
    acknowledged_at = fields.DateTime(allow_none=True)
    resolved_at = fields.DateTime(allow_none=True)
    window_start = fields.DateTime(allow_none=True)
    window_end = fields.DateTime(allow_none=True)
    report_id = fields.String(allow_none=True)


class IncidentListArgs(CamelSchema):
    status = fields.String(validate=validate.OneOf(INCIDENT_STATUSES))
    app = fields.String(metadata={"description": "Application code, e.g. payments-api"})
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    page_size = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))


class IncidentPageSchema(CamelSchema):
    items = fields.List(fields.Nested(IncidentSchema))
    page = fields.Integer()
    page_size = fields.Integer()
    total = fields.Integer()


class IncidentUpdateSchema(CamelSchema):
    status = fields.String(required=True, validate=validate.OneOf(("ACKNOWLEDGED", "RESOLVED")))


# --- Reports -------------------------------------------------------------------------
class SloArgs(CamelSchema):
    days = fields.Integer(load_default=7, validate=validate.Range(min=1, max=90))


class SloRowSchema(CamelSchema):
    app_code = fields.String()
    app_name = fields.String()
    team = fields.String()
    tier = fields.Integer()
    requests = fields.Integer()
    errors_5xx = fields.Integer()
    availability = fields.Float()
    slo_availability = fields.Float()
    error_budget_consumed = fields.Float(
        metadata={"description": "Share of the allowed errors already spent (1.0 = budget exhausted)"}
    )
    days_breaching_latency = fields.Integer()
    days_with_data = fields.Integer()
    worst_rank = fields.Integer()
    status = fields.String(metadata={"description": "OK, AT_RISK or BREACHED"})


class SloReportSchema(CamelSchema):
    days = fields.Integer()
    generated_at = fields.DateTime()
    applications = fields.List(fields.Nested(SloRowSchema))


class RefreshResultSchema(CamelSchema):
    refreshed = fields.String()
    seconds = fields.Float()


# --- Error breakdown (MongoDB) ---------------------------------------------------------
class BreakdownArgs(CamelSchema):
    minutes = fields.Integer(load_default=60, validate=validate.Range(min=5, max=1440))


class BreakdownRowSchema(CamelSchema):
    app_version = fields.String()
    region = fields.String()
    requests = fields.Integer()
    errors_5xx = fields.Integer()
    error_rate = fields.Float()
    avg_latency_ms = fields.Float()


class BreakdownSchema(CamelSchema):
    app_code = fields.String()
    minutes = fields.Integer()
    total_requests = fields.Integer()
    rows = fields.List(fields.Nested(BreakdownRowSchema))


# --- Service health ------------------------------------------------------------------------
class ServiceHealthSchema(CamelSchema):
    status = fields.String()
    database = fields.String()
    mongo = fields.String()
