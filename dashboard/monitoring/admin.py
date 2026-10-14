"""Django admin: a complete back-office for incidents in a few lines."""

from django.contrib import admin, messages
from django.db.models.functions import Coalesce, Now

from .models import Application, Incident, Team


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "team",
        "tier",
        "slo_availability",
        "slo_latency_p95_ms",
        "active",
    )
    list_filter = ("tier", "active", "team")
    search_fields = ("code", "name")
    list_select_related = ("team",)
    readonly_fields = ("api_key_hash", "created_at")

    # Applications are registered through the ingest service, which issues
    # their API key. The back-office can tune objectives but not create them.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application",
        "title",
        "severity",
        "status",
        "source",
        "opened_at",
        "resolved_at",
    )
    list_filter = ("status", "severity", "source", "application__team")
    search_fields = ("title", "application__code", "application__name")
    list_select_related = ("application",)
    date_hierarchy = "opened_at"
    readonly_fields = (
        "source",
        "window_start",
        "window_end",
        "report_id",
        "acknowledged_at",
        "resolved_at",
    )
    actions = ("acknowledge", "resolve")

    @admin.action(description="Acknowledge selected incidents")
    def acknowledge(self, request, queryset):
        # One UPDATE statement for the whole selection (no Python loop over rows).
        updated = queryset.filter(status=Incident.Status.OPEN).update(
            status=Incident.Status.ACKNOWLEDGED, acknowledged_at=Now()
        )
        self.message_user(request, f"{updated} incident(s) acknowledged.", messages.SUCCESS)

    @admin.action(description="Resolve selected incidents")
    def resolve(self, request, queryset):
        updated = queryset.exclude(status=Incident.Status.RESOLVED).update(
            status=Incident.Status.RESOLVED,
            acknowledged_at=Coalesce("acknowledged_at", Now()),
            resolved_at=Now(),
        )
        self.message_user(request, f"{updated} incident(s) resolved.", messages.SUCCESS)
