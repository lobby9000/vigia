"""ORM models over tables that Django does NOT own.

``managed = False`` tells Django: "this table already exists, never create,
alter or drop it". The schema lives in database/*.sql and is shared with the
Java and Flask services. This is the usual situation when Django is added to
an existing database (``manage.py inspectdb`` generates a first draft).
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Team(models.Model):
    name = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = "teams"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Application(models.Model):
    class Tier(models.IntegerChoices):
        CRITICAL = 1, "1 - Business critical"
        IMPORTANT = 2, "2 - Important"
        BEST_EFFORT = 3, "3 - Best effort"

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=120)
    team = models.ForeignKey(Team, on_delete=models.PROTECT, db_column="team_id", related_name="applications")
    tier = models.SmallIntegerField(choices=Tier.choices)
    slo_availability = models.DecimalField(max_digits=6, decimal_places=5)
    slo_latency_p95_ms = models.IntegerField("p95 latency objective (ms)")
    api_key_hash = models.CharField(max_length=64, editable=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(editable=False)

    class Meta:
        managed = False
        db_table = "applications"
        ordering = ["tier", "code"]

    def __str__(self):
        return self.code


class Incident(models.Model):
    class Severity(models.TextChoices):
        SEV1 = "SEV1", "SEV1 - Critical"
        SEV2 = "SEV2", "SEV2 - Major"
        SEV3 = "SEV3", "SEV3 - Minor"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        RESOLVED = "RESOLVED", "Resolved"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        DETECTOR = "anomaly_detector", "Anomaly detector"

    id = models.BigAutoField(primary_key=True)
    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        db_column="app_id",
        related_name="incidents",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    severity = models.CharField(max_length=4, choices=Severity.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL, editable=False)
    window_start = models.DateTimeField(blank=True, null=True, editable=False)
    window_end = models.DateTimeField(blank=True, null=True, editable=False)
    report_id = models.CharField(max_length=24, blank=True, null=True, editable=False)
    opened_at = models.DateTimeField(default=timezone.now)
    acknowledged_at = models.DateTimeField(blank=True, null=True, editable=False)
    resolved_at = models.DateTimeField(blank=True, null=True, editable=False)

    class Meta:
        managed = False
        db_table = "incidents"
        ordering = ["-opened_at"]

    def __str__(self):
        return f"#{self.pk} {self.title}"

    def clean(self):
        """Rules shown as form errors in the admin before anything reaches the database."""
        if self.pk:
            previous = Incident.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if previous == self.Status.RESOLVED and self.status != self.Status.RESOLVED:
                raise ValidationError({"status": "Resolved incidents are final. Open a new incident instead."})

    def save(self, *args, **kwargs):
        """Keep the timestamps consistent with the status (the database CHECK requires it)."""
        now = timezone.now()
        if self.status in (self.Status.ACKNOWLEDGED, self.Status.RESOLVED) and self.acknowledged_at is None:
            self.acknowledged_at = now
        if self.status == self.Status.RESOLVED:
            self.resolved_at = self.resolved_at or now
        else:
            self.resolved_at = None
        super().save(*args, **kwargs)

    @property
    def duration(self):
        return (self.resolved_at or timezone.now()) - self.opened_at
