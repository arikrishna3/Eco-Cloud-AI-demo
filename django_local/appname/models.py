from django.db import models


class ChatSession(models.Model):
    app_name = models.CharField(max_length=100)
    user_id = models.CharField(max_length=100)
    session_id = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_active_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_active_at"]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.session_id}"


class ChatMessage(models.Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
    ]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class ApiRequestLog(models.Model):
    path = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    status_code = models.IntegerField()
    latency_ms = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class MetricSnapshot(models.Model):
    cpu_percent = models.FloatField()
    memory_percent = models.FloatField()
    disk_percent = models.FloatField()
    bytes_sent = models.BigIntegerField(default=0)
    bytes_recv = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class OptimizationPolicy(models.Model):
    MODE_CHOICES = [
        ("low", "Low"),
        ("balanced", "Balanced"),
        ("high", "High"),
    ]

    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="balanced")
    optimization_enabled = models.BooleanField(default=True)
    sample_interval_seconds = models.IntegerField(default=10)
    cooldown_seconds = models.IntegerField(default=60)
    updated_at = models.DateTimeField(auto_now=True)


class OptimizationAction(models.Model):
    DECISION_CHOICES = [
        ("scale_down", "Scale Down"),
        ("scale_up", "Scale Up"),
        ("keep", "Keep"),
    ]
    STATUS_CHOICES = [
        ("recommended", "Recommended"),
        ("cooldown_skipped", "Cooldown Skipped"),
        ("simulated_applied", "Simulated Applied"),
    ]

    decision = models.CharField(max_length=20, choices=DECISION_CHOICES)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="recommended")
    current_instance = models.CharField(max_length=100, default="n2-standard-4")
    target_instance = models.CharField(max_length=100, default="n2-standard-4")
    reason = models.TextField(blank=True, default="")
    cost_savings_usd = models.FloatField(default=0.0)
    co2e_reduction_kg = models.FloatField(default=0.0)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ForecastSnapshot(models.Model):
    current_instance = models.CharField(max_length=100, default="n2-standard-4")
    target_instance = models.CharField(max_length=100, default="n2-standard-4")
    hours = models.IntegerField(default=720)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
