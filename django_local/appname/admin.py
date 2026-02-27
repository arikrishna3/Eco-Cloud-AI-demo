from django.contrib import admin

from .models import ApiRequestLog, ChatMessage, ChatSession, MetricSnapshot


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("session_id", "user_id", "app_name", "last_active_at")
    search_fields = ("session_id", "user_id", "app_name")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("content", "session__session_id")


@admin.register(ApiRequestLog)
class ApiRequestLogAdmin(admin.ModelAdmin):
    list_display = ("id", "method", "path", "status_code", "latency_ms", "created_at")
    list_filter = ("method", "status_code")


@admin.register(MetricSnapshot)
class MetricSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "cpu_percent", "memory_percent", "disk_percent", "created_at")
