import json

from django.db.models import Avg
from django.http import HttpResponseNotAllowed, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import ApiRequestLog, ChatMessage, ChatSession, OptimizationAction
from .services.agents import run_forecast_agent, run_optimizer_agent, status_snapshot, update_policy_from_payload
from .services.ai_engine import generate_ai_response
from .services.impact import auto_impact_from_averages, average_utilization, calculate_impact, demo_non_zero_impact
from .services.monitoring import metrics_history, sample_metrics


def index(request):
    return JsonResponse(
        {
            "service": "greenops-django-backend",
            "status": "ok",
            "docs": {
                "create_session": "POST /apps/<app_name>/users/<user_id>/sessions/<session_id>",
                "run": "POST /run",
                "health": "GET /health",
                "monitoring": "GET /monitoring/summary",
                "policy": "GET/POST /optimization/policy",
                "optimizer_tick": "POST /optimization/tick",
                "forecast": "GET /forecast/graph",
            },
        }
    )


@csrf_exempt
def create_session(request, app_name: str, user_id: str, session_id: str):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    session, created = ChatSession.objects.get_or_create(
        session_id=session_id,
        defaults={"app_name": app_name, "user_id": user_id},
    )

    if not created:
        session.app_name = app_name
        session.user_id = user_id
        session.last_active_at = timezone.now()
        session.save(update_fields=["app_name", "user_id", "last_active_at"])

    return JsonResponse(
        {
            "app_name": session.app_name,
            "user_id": session.user_id,
            "session_id": session.session_id,
            "created": created,
        }
    )


@csrf_exempt
def run_agent(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    app_name = payload.get("app_name")
    user_id = payload.get("user_id")
    session_id = payload.get("session_id")
    new_message = payload.get("new_message", {})
    parts = new_message.get("parts", [])
    text = ""
    if parts and isinstance(parts, list):
        text = parts[0].get("text", "")

    if not all([app_name, user_id, session_id, text]):
        return JsonResponse({"error": "Missing required fields."}, status=400)

    try:
        session = ChatSession.objects.get(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )
    except ChatSession.DoesNotExist:
        return JsonResponse({"error": "Session not found. Create a session first."}, status=404)

    ChatMessage.objects.create(session=session, role="user", content=text)
    history = list(session.messages.all())
    try:
        assistant_text = generate_ai_response(prompt=text, history=history)
    except Exception as exc:  # noqa: BLE001
        assistant_text = f"Chatbot backend error. Details: {exc}."

    ChatMessage.objects.create(session=session, role="assistant", content=assistant_text)
    session.last_active_at = timezone.now()
    session.save(update_fields=["last_active_at"])
    return JsonResponse([{"content": {"parts": [{"text": assistant_text}]}}], safe=False)


def health(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse(
        {
            "status": "ok",
            "time": timezone.now().isoformat(),
            "sessions": ChatSession.objects.count(),
            "messages": ChatMessage.objects.count(),
        }
    )


def monitoring_summary(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    avg_latency = ApiRequestLog.objects.aggregate(value=Avg("latency_ms"))["value"]
    latest = ApiRequestLog.objects.first()
    return JsonResponse(
        {
            "totals": {
                "sessions": ChatSession.objects.count(),
                "messages": ChatMessage.objects.count(),
                "requests": ApiRequestLog.objects.count(),
            },
            "performance": {
                "avg_latency_ms": round(avg_latency, 2) if avg_latency is not None else None,
                "latest_request_at": latest.created_at.isoformat() if latest else None,
            },
        }
    )


def current_metrics(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        return JsonResponse({"metrics": sample_metrics()})
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=500)


def metrics_trend(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    limit = int(request.GET.get("limit", "30"))
    return JsonResponse({"history": metrics_history(limit=limit)})


def optimization_recommendations(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        current_instance = request.GET.get("current_instance", "n2-standard-4")
        run = run_optimizer_agent(
            current_instance=current_instance,
            current_region=request.GET.get("current_region", "us-central1"),
            target_region=request.GET.get("target_region", "us-central1"),
            hours=float(request.GET.get("hours", 24 * 30)),
        )
        averages = run["averages"]
        impact = run["impact"]
        decision = impact.get("decision")
        recommendations = []
        if decision == "scale_down":
            recommendations.append(
                {
                    "title": f"Scale down {impact['current_instance']} -> {impact['target_instance']}",
                    "priority": "high",
                    "estimated_monthly_cost_savings_usd": impact["cost_savings_usd"],
                    "estimated_monthly_co2e_reduction_kg": impact["co2e_reduction_kg"],
                    "reason": impact["reason"],
                }
            )
        elif decision == "scale_up":
            recommendations.append(
                {
                    "title": f"Scale up {impact['current_instance']} -> {impact['target_instance']}",
                    "priority": "high",
                    "estimated_monthly_cost_savings_usd": impact["cost_savings_usd"],
                    "estimated_monthly_co2e_reduction_kg": impact["co2e_reduction_kg"],
                    "reason": impact["reason"],
                }
            )
        else:
            recommendations.append(
                {
                    "title": "Keep current size",
                    "priority": "low",
                    "estimated_monthly_cost_savings_usd": impact["cost_savings_usd"],
                    "estimated_monthly_co2e_reduction_kg": impact["co2e_reduction_kg"],
                    "reason": impact["reason"],
                }
            )
            if averages["avg_cpu"] < 35 and averages["avg_memory"] >= 40:
                unlock = auto_impact_from_averages(
                    avg_cpu=averages["avg_cpu"],
                    avg_memory=39.0,
                    current_instance=current_instance,
                    current_region=request.GET.get("current_region", "us-central1"),
                    target_region=request.GET.get("target_region", "us-central1"),
                    hours=float(request.GET.get("hours", 24 * 30)),
                )
                recommendations.append(
                    {
                        "title": f"Unlock downsize path: optimize memory, then move to {unlock['target_instance']}",
                        "priority": "medium",
                        "estimated_monthly_cost_savings_usd": unlock["cost_savings_usd"],
                        "estimated_monthly_co2e_reduction_kg": unlock["co2e_reduction_kg"],
                        "reason": (
                            f"CPU is low ({averages['avg_cpu']}%), but memory is high ({averages['avg_memory']}%). "
                            "Reduce memory pressure below 40% to enable safe downsizing."
                        ),
                    }
                )
        return JsonResponse(
            {
                "metrics": run["metrics"],
                "averages": averages,
                "impact": impact,
                "policy": run["policy"],
                "latest_action": run["action"],
                "recommendations": recommendations,
            }
        )
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@csrf_exempt
def impact_calculation(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    result = calculate_impact(
        current_instance=payload.get("current_instance", "n2-standard-4"),
        target_instance=payload.get("target_instance", "e2-standard-2"),
        current_region=payload.get("current_region", "us-central1"),
        target_region=payload.get("target_region", payload.get("current_region", "us-central1")),
        hours=float(payload.get("hours", 24 * 30)),
    )
    return JsonResponse({"impact": result})


def impact_auto(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        sample_metrics()
        history = metrics_history(limit=30)
        averages = average_utilization(history)
        current_instance = request.GET.get("current_instance", "n2-standard-4")
        impact = auto_impact_from_averages(
            avg_cpu=averages["avg_cpu"],
            avg_memory=averages["avg_memory"],
            current_instance=current_instance,
            current_region=request.GET.get("current_region", "us-central1"),
            target_region=request.GET.get("target_region", "us-central1"),
            hours=float(request.GET.get("hours", 24 * 30)),
        )
        if float(impact.get("cost_savings_usd", 0.0)) == 0.0 and float(impact.get("co2e_reduction_kg", 0.0)) == 0.0:
            impact = demo_non_zero_impact(
                current_instance=current_instance,
                current_region=request.GET.get("current_region", "us-central1"),
                target_region=request.GET.get("target_region", "us-central1"),
                hours=float(request.GET.get("hours", 24 * 30)),
            )
        return JsonResponse({"averages": averages, "impact": impact, "history_points": len(history)})
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@csrf_exempt
def optimization_policy(request):
    if request.method == "GET":
        return JsonResponse({"policy": status_snapshot()["policy"]})
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)
    policy = update_policy_from_payload(payload)
    return JsonResponse(
        {
            "policy": {
                "mode": policy.mode,
                "optimization_enabled": policy.optimization_enabled,
                "sample_interval_seconds": policy.sample_interval_seconds,
                "cooldown_seconds": policy.cooldown_seconds,
                "updated_at": policy.updated_at.isoformat(),
            }
        }
    )


@csrf_exempt
def optimization_tick(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)
    run = run_optimizer_agent(
        current_instance=payload.get("current_instance", "n2-standard-4"),
        current_region=payload.get("current_region", "us-central1"),
        target_region=payload.get("target_region", "us-central1"),
        hours=float(payload.get("hours", 24 * 30)),
    )
    return JsonResponse(run)


def optimization_actions(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    limit = int(request.GET.get("limit", "20"))
    actions = OptimizationAction.objects.all()[:limit]
    return JsonResponse(
        {
            "actions": [
                {
                    "decision": row.decision,
                    "status": row.status,
                    "current_instance": row.current_instance,
                    "target_instance": row.target_instance,
                    "reason": row.reason,
                    "cost_savings_usd": row.cost_savings_usd,
                    "co2e_reduction_kg": row.co2e_reduction_kg,
                    "meta": row.meta,
                    "created_at": row.created_at.isoformat(),
                }
                for row in actions
            ]
        }
    )


def forecast_graph(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    current_instance = request.GET.get("current_instance", "n2-standard-4")
    hours = int(request.GET.get("hours", "720"))
    payload = run_forecast_agent(current_instance=current_instance, hours=hours)
    return JsonResponse(payload)


def agent_status(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse(status_snapshot())
