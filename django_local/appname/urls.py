from django.urls import include, path
from . import views
from .auth_views import login_view, logout_view

urlpatterns = [
    # ── Auth ───────────────────────────────────────────────
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),

    # Social auth routes:
    # /auth/login/google-oauth2/
    # /auth/complete/google-oauth2/
    path("auth/", include("social_django.urls", namespace="social")),

    # ── Core Routes ───────────────────────────────────────
    path("", views.index, name="index"),

    path(
        "apps/<str:app_name>/users/<str:user_id>/sessions/<str:session_id>/",
        views.create_session,
        name="create_session",
    ),

    path("run/", views.run_agent, name="run_agent"),
    path("health/", views.health, name="health"),

    # Monitoring
    path("monitoring/summary/", views.monitoring_summary, name="monitoring_summary"),

    # Metrics
    path("metrics/current/", views.current_metrics, name="current_metrics"),
    path("metrics/history/", views.metrics_trend, name="metrics_history"),

    # Optimization
    path("optimization/recommendations/", views.optimization_recommendations, name="optimization_recommendations"),
    path("optimization/policy/", views.optimization_policy, name="optimization_policy"),
    path("optimization/tick/", views.optimization_tick, name="optimization_tick"),
    path("optimization/actions/", views.optimization_actions, name="optimization_actions"),

    # Forecast
    path("forecast/graph/", views.forecast_graph, name="forecast_graph"),

    # Agent
    path("agent/status/", views.agent_status, name="agent_status"),

    # Impact
    path("impact/calculate/", views.impact_calculation, name="impact_calculation"),
    path("impact/auto/", views.impact_auto, name="impact_auto"),
]