"""HTTP layer. Each module is one flask-smorest Blueprint (one resource)."""

from . import applications, auth, health, incidents, reports

ALL_BLUEPRINTS = (health.blp, auth.blp, applications.blp, incidents.blp, reports.blp)
