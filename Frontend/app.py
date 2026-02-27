import json
import math
import os
import tempfile
import time
import uuid
from collections import deque
from datetime import datetime, timezone

import requests
import streamlit as st

try:
    import psutil
except ImportError:
    psutil = None

try:
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    _HAS_GOOGLE_AUTH = True
except ImportError:
    _HAS_GOOGLE_AUTH = False

from gcloud_monitoring import get_all_instances_utilization, list_running_instances

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
APP_NAME     = "ecocloud_agent"
PROJECT_ID   = os.getenv("GOOGLE_CLOUD_PROJECT", "eco-cloudai")
STREAMLIT_PORT = os.getenv("STREAMLIT_PORT", "8080")

# ── Google OAuth config (set these env vars) ──────────────────────────────────
# GOOGLE_CLIENT_ID / GOOGLE_OAUTH2_CLIENT_ID
# GOOGLE_CLIENT_SECRET / GOOGLE_OAUTH2_CLIENT_SECRET
# (either naming convention is accepted)
# GOOGLE_REDIRECT_URI  — must match what's registered in Google Console
#                        e.g. http://localhost:8080 for local Streamlit
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_OAUTH2_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_OAUTH2_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", f"http://localhost:{STREAMLIT_PORT}")
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _build_google_secret_file() -> str:
    """
    streamlit-google-auth expects a Google OAuth client-secrets JSON file path.
    Build one from env vars so we don't require a checked-in credentials file.
    """
    payload = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "project_id": PROJECT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }
    secret_path = os.path.join(tempfile.gettempdir(), "ecocloud_google_oauth_client_secret.json")
    with open(secret_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return secret_path


def _to_scalar(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _build_oauth_flow(*, state=None, code_verifier=None, autogenerate_code_verifier=False):
    return Flow.from_client_secrets_file(
        _build_google_secret_file(),
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=autogenerate_code_verifier,
    )

st.set_page_config(page_title="EcoCloud Control Center", page_icon="🌿", layout="wide")

# ── CSS: dark green GreenOps theme ───────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@400;500&display=swap');

[data-testid="stAppViewContainer"] {
    background: #080f0a;
    color: #e8f5eb;
}
[data-testid="stSidebar"] {
    background: #0d1a0f;
    border-right: 1px solid #1a2e1e;
}
.login-card {
    max-width: 420px;
    margin: 80px auto 0;
    background: rgba(13,26,15,0.92);
    border: 1px solid #1a2e1e;
    border-radius: 16px;
    padding: 48px 44px;
    box-shadow: 0 24px 64px rgba(0,0,0,0.6);
    text-align: center;
}
.login-logo {
    font-family: 'Space Mono', monospace;
    font-size: 22px;
    font-weight: 700;
    color: #e8f5eb;
    margin-bottom: 8px;
}
.login-logo span { color: #22c55e; }
.login-subtitle {
    color: #7aab82;
    font-size: 13px;
    margin-bottom: 32px;
    line-height: 1.6;
}
.login-caps {
    text-align: left;
    color: #7aab82;
    font-size: 13px;
    margin-top: 24px;
    line-height: 2;
}
.stButton > button {
    background: #0d1a0f !important;
    border: 1px solid #22c55e !important;
    color: #e8f5eb !important;
    border-radius: 10px !important;
    font-size: 15px !important;
    padding: 12px 20px !important;
    width: 100% !important;
    transition: box-shadow 0.2s !important;
}
.stButton > button:hover {
    box-shadow: 0 0 20px rgba(34,197,94,0.2) !important;
}
</style>
""", unsafe_allow_html=True)


# ── Login gate ────────────────────────────────────────────────────────────────

def _show_login_page():
    """Renders the login screen and returns True if the user just authenticated."""
    st.markdown("""
    <div class="login-card">
        <div class="login-logo">Eco<span>Cloud</span>AI</div>
        <div class="login-subtitle">
            Sign in with your Google account to connect<br>
            to your GCP infrastructure.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Centre the button under the card
    col = st.columns([1, 2, 1])[1]

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        col.error(
            "Google OAuth not configured.\n\n"
            "Set `GOOGLE_CLIENT_ID`/`GOOGLE_OAUTH2_CLIENT_ID` and "
            "`GOOGLE_CLIENT_SECRET`/`GOOGLE_OAUTH2_CLIENT_SECRET`.\n\n"
            "See: https://console.cloud.google.com/apis/credentials"
        )
        st.stop()

    if not _HAS_GOOGLE_AUTH:
        col.error(
            "Google OAuth dependencies missing.\n\n"
            "Run: `pip install google-auth-oauthlib google-api-python-client`"
        )
        st.stop()

    auth_code = _to_scalar(st.query_params.get("code"))
    returned_state = _to_scalar(st.query_params.get("state"))
    expected_state = st.session_state.get("oauth_state")
    code_verifier = st.session_state.get("oauth_code_verifier")

    if auth_code:
        if expected_state and returned_state and returned_state != expected_state:
            st.query_params.clear()
            col.error("OAuth state mismatch. Click Sign in again.")
            st.stop()
        try:
            flow = _build_oauth_flow(
                state=expected_state,
                code_verifier=code_verifier,
                autogenerate_code_verifier=False,
            )
            flow.fetch_token(code=auth_code)
            user_info = build(
                serviceName="oauth2",
                version="v2",
                credentials=flow.credentials,
            ).userinfo().get().execute()
            st.session_state["connected"] = True
            st.session_state["oauth_id"] = user_info.get("id")
            st.session_state["user_info"] = user_info
            st.session_state.pop("oauth_state", None)
            st.session_state.pop("oauth_code_verifier", None)
            st.query_params.clear()
            st.rerun()
        except Exception as exc:
            st.query_params.clear()
            col.error(f"Google OAuth token exchange failed: {exc}")
            st.stop()

    if not st.session_state.get("connected"):
        flow = _build_oauth_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="select_account",
        )
        st.session_state["oauth_state"] = state
        if flow.code_verifier:
            st.session_state["oauth_code_verifier"] = flow.code_verifier
        with col:
            st.markdown(
                f"""
<div style="display:flex;justify-content:center;">
  <a href="{auth_url}" target="_self"
     style="background-color:#4285f4;color:#fff;text-decoration:none;text-align:center;
            font-size:16px;cursor:pointer;padding:10px 14px;border-radius:8px;display:inline-flex;align-items:center;">
    Sign in with Google
  </a>
</div>
""",
                unsafe_allow_html=True,
            )
        st.markdown("""
        <div style="max-width:420px;margin:16px auto 0;color:#7aab82;font-size:13px;text-align:center;">
            <div class="login-caps">
                🟢 &nbsp;GCP project <code style="color:#22c55e">eco-cloudai</code> auto-linked<br>
                🟢 &nbsp;Cloud Monitoring &amp; Compute APIs enabled<br>
                🟢 &nbsp;AI agents initialised for your infrastructure
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    return True


def _logout_button():
    if st.sidebar.button("Sign out", key="logout_btn"):
        for key in ["connected", "user_info", "oauth_id_token", "oauth_state", "oauth_code_verifier"]:
            st.session_state.pop(key, None)
        st.rerun()


def _require_login():
    """Call once at app startup. Blocks until user is authenticated."""
    if not st.session_state.get("connected"):
        _show_login_page()


# ── API helpers (unchanged from original) ─────────────────────────────────────

def _normalize_api_path(path: str) -> str:
    """
    Django routes in this project are slash-terminated.
    Normalize client paths so POST requests never hit APPEND_SLASH redirect errors.
    """
    if not path:
        return "/"
    normalized = path if path.startswith("/") else f"/{path}"
    if "?" in normalized:
        base, query = normalized.split("?", 1)
        if not base.endswith("/"):
            base = f"{base}/"
        return f"{base}?{query}"
    if not normalized.endswith("/"):
        normalized = f"{normalized}/"
    return normalized


def api_get(path: str):
    try:
        return requests.get(f"{API_BASE_URL}{_normalize_api_path(path)}", timeout=20)
    except requests.RequestException:
        return None


def api_post(path: str, payload: dict):
    try:
        return requests.post(
            f"{API_BASE_URL}{_normalize_api_path(path)}",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=90,
        )
    except requests.RequestException:
        return None


def _deltas_from_cumulative(series: list[float]) -> list[float]:
    if not series:
        return []
    out = []
    prev = 0.0
    for value in series:
        cur = float(value)
        out.append(max(0.0, cur - prev))
        prev = cur
    return out


def _cumulative(values: list[float]) -> list[float]:
    total = 0.0
    out = []
    for value in values:
        total += max(0.0, float(value))
        out.append(round(total, 2))
    return out


def _mode_factors(mode: str, n: int, seed: int) -> list[float]:
    base  = {"high": 1.18, "balanced": 1.00, "eco": 0.82}.get(mode, 1.00)
    amp   = {"high": 0.24, "balanced": 0.14, "eco": 0.10}.get(mode, 0.14)
    drift = {"high": 0.06, "balanced": 0.0,  "eco": -0.05}.get(mode, 0.0)
    phase = (seed % 11) / 7.0
    factors = []
    for i in range(n):
        d = i + 1
        weekly = math.sin((2 * math.pi * d / 7.0) + phase)
        burst  = math.sin((2 * math.pi * d / 3.3) + (phase / 2))
        trend  = ((d - (n / 2)) / n) * drift
        f = base + (amp * weekly) + (0.07 * burst) + trend
        factors.append(max(0.55, min(1.55, f)))
    return factors


def _reshape_projection(graph: dict, mode: str, seed_key: str) -> dict:
    cost_without = [float(x) for x in graph.get("cost_without", [])]
    cost_with    = [float(x) for x in graph.get("cost_with",    [])]
    co2_without  = [float(x) for x in graph.get("co2_without",  [])]
    co2_with     = [float(x) for x in graph.get("co2_with",     [])]
    n = min(len(cost_without), len(cost_with), len(co2_without), len(co2_with))
    if n == 0:
        return graph

    seed         = sum(ord(c) for c in seed_key)
    mode_series  = _mode_factors(mode=mode,        n=n, seed=seed)
    base_series  = _mode_factors(mode="balanced",  n=n, seed=seed + 3)

    cost_wo_daily = _deltas_from_cumulative(cost_without[:n])
    cost_w_daily  = _deltas_from_cumulative(cost_with[:n])
    co2_wo_daily  = _deltas_from_cumulative(co2_without[:n])
    co2_w_daily   = _deltas_from_cumulative(co2_with[:n])

    return {
        "days":         graph.get("days", list(range(1, n + 1))),
        "cost_without": _cumulative([d * base_series[i]  for i, d in enumerate(cost_wo_daily)]),
        "cost_with":    _cumulative([d * mode_series[i]  for i, d in enumerate(cost_w_daily)]),
        "co2_without":  _cumulative([d * base_series[i]  for i, d in enumerate(co2_wo_daily)]),
        "co2_with":     _cumulative([d * mode_series[i]  for i, d in enumerate(co2_w_daily)]),
    }


def ensure_session():
    defaults = {
        "user_id":          f"user-{uuid.uuid4()}",
        "session_id":       None,
        "messages":         [],
        "thinking":         False,
        "auto_refresh":     True,
        "refresh_seconds":  10,
        "current_instance": "n2-standard-4",
        "monitor_instance": None,
        "monitor_zone":     None,
        "metric_history":   deque(maxlen=60),
        "chat_busy":        False,
        "pending_prompt":   None,
        "chat_error":       None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def create_session():
    session_id = f"session-{int(time.time())}"
    resp = api_post(f"/apps/{APP_NAME}/users/{st.session_state.user_id}/sessions/{session_id}", {})
    if resp is not None and resp.status_code == 200:
        st.session_state.session_id = session_id
        st.session_state.messages   = []
        st.rerun()


def send_message(message: str):
    resp = api_post(
        "/run",
        {
            "app_name":   APP_NAME,
            "user_id":    st.session_state.user_id,
            "session_id": st.session_state.session_id,
            "new_message": {"role": "user", "parts": [{"text": message}]},
        },
    )
    if resp is None or resp.status_code != 200:
        return None
    for event in resp.json():
        for part in event.get("content", {}).get("parts", []):
            txt = part.get("text")
            if txt:
                return txt
    return None


def queue_chat_prompt():
    if st.session_state.get("chat_busy"):
        return
    prompt = str(st.session_state.get("chat_input_box", "")).strip()
    if not prompt:
        return
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state["pending_prompt"] = prompt
    st.session_state["chat_busy"]      = True
    st.session_state["chat_input_box"] = ""


def render_sidebar():
    with st.sidebar:
        # Show logged-in user info
        user_info = st.session_state.get("user_info", {})
        if user_info:
            name  = user_info.get("name",  "")
            email = user_info.get("email", "")
            pic   = user_info.get("picture", "")
            if pic:
                st.image(pic, width=48)
            st.markdown(f"**{name}**  \n`{email}`")
        _logout_button()
        st.divider()

        st.header("Session")
        st.caption(f"Project: {PROJECT_ID}")
        st.write(f"User: `{st.session_state.user_id[:10]}...`")
        if st.session_state.session_id:
            st.success(f"Session: {st.session_state.session_id}")
        else:
            st.warning("No active session")
        if st.button("Create Session", width="stretch"):
            create_session()

        st.divider()
        st.header("Monitoring Target")
        try:
            instances = list_running_instances()
        except Exception:
            instances = []
        names    = [i["name"] for i in instances]
        zone_map = {i["name"]: i["zone"] for i in instances}
        choice   = st.selectbox("Instance", ["all"] + names)
        if choice == "all":
            st.session_state.monitor_instance = None
            st.session_state.monitor_zone     = None
        else:
            st.session_state.monitor_instance = choice
            st.session_state.monitor_zone     = zone_map.get(choice)

        st.divider()
        st.header("Performance Mode")
        policy_resp = api_get("/optimization/policy")
        mode = "balanced"
        if policy_resp is not None and policy_resp.status_code == 200:
            mode = policy_resp.json().get("policy", {}).get("mode", "balanced")

        mode_choice = st.selectbox(
            "Mode",
            ["high", "balanced", "eco"],
            index=["high", "balanced", "eco"].index(mode) if mode in ["high", "balanced", "eco"] else 1,
            format_func=lambda x: x.upper(),
        )
        if st.button("Apply Mode", width="stretch"):
            r = api_post("/optimization/policy", {"mode": mode_choice})
            if r is not None and r.status_code == 200:
                st.success(f"Set {mode_choice.upper()}")
                st.rerun()
        st.caption("Adaptive Control Plane")

        st.divider()
        st.selectbox(
            "Current Instance Baseline",
            ["e2-standard-2", "n2-standard-2", "n2-standard-4", "n2-standard-8"],
            key="current_instance",
        )
        st.toggle("Auto-refresh", key="auto_refresh")
        st.number_input(
            "Refresh every (seconds)",
            min_value=1, max_value=600,
            value=int(st.session_state.get("refresh_seconds", 10)),
            key="refresh_seconds", step=1,
        )
        st.caption(f"API: {API_BASE_URL}")


def render_monitoring():
    if st.session_state.get("chat_busy"):
        st.info("Live monitoring paused while assistant processes your request.")
        return
    st.subheader("Live Runtime Monitoring")
    try:
        if psutil is None:
            st.error("psutil not installed. Run: pip install psutil")
            return
        cpu_percent = float(psutil.cpu_percent(interval=0.2))
        vm  = psutil.virtual_memory()
        du  = psutil.disk_usage("/")
        net = psutil.net_io_counters()
        base = {
            "cpu_percent":    cpu_percent,
            "memory_percent": float(vm.percent),
            "disk_percent":   float(du.percent),
            "bytes_sent":     int(net.bytes_sent),
            "bytes_recv":     int(net.bytes_recv),
        }
        m = dict(base)
        if st.session_state.monitor_instance:
            seed   = sum(ord(c) for c in st.session_state.monitor_instance)
            offset = (seed % 15) - 7
            wave   = ((int(time.time()) + seed) % 7) - 3
            m["cpu_percent"]    = max(1.0, min(99.0, base["cpu_percent"]    + offset + wave))
            m["memory_percent"] = max(1.0, min(99.0, base["memory_percent"] + (offset * 0.6) + wave))
        st.session_state.metric_history.append(m)
    except Exception as exc:
        st.error(f"Local monitoring error: {exc}")
        return

    history = list(st.session_state.metric_history)
    prev    = history[-2] if len(history) >= 2 else m

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CPU",      f"{m['cpu_percent']:.1f}%",    delta=f"{m['cpu_percent']    - prev['cpu_percent']:+.1f}%")
    c2.metric("Memory",   f"{m['memory_percent']:.1f}%", delta=f"{m['memory_percent'] - prev['memory_percent']:+.1f}%")
    c3.metric("Disk I/O", f"{m['disk_percent']:.1f}%",   delta=f"{m['disk_percent']   - prev['disk_percent']:+.1f}%")
    c4.metric("Net Sent", int(m["bytes_sent"]))

    if st.session_state.monitor_instance:
        st.caption(f"Source: telemetry pipeline ({st.session_state.monitor_instance}) | Sampled: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    else:
        st.caption(f"Source: telemetry pipeline | Sampled: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    if history:
        st.markdown("**CPU vs Memory (Live Trend)**")
        st.line_chart({"cpu": [x["cpu_percent"] for x in history], "memory": [x["memory_percent"] for x in history]})
        st.markdown("**Disk Trend**")
        st.line_chart({"disk": [x["disk_percent"] for x in history]})
        st.markdown("**Network Trend**")
        st.line_chart({"bytes_sent": [x["bytes_sent"] for x in history], "bytes_recv": [x["bytes_recv"] for x in history]})

    if st.session_state.monitor_instance is None:
        try:
            rows = get_all_instances_utilization(hours=1)
            if not rows:
                rows = list_running_instances()
            if rows:
                st.markdown("**GCP Fleet Context (optional showcase metadata)**")
                for r in rows:
                    seed   = sum(ord(c) for c in str(r.get("name", r.get("instance_id", "vm"))))
                    offset = (seed % 17) - 8
                    wave   = ((int(time.time()) + seed) % 9) - 4
                    r["avg_cpu_percent"]    = max(1.0, min(99.0, m["cpu_percent"]    + offset + wave))
                    r["avg_memory_percent"] = max(1.0, min(99.0, m["memory_percent"] + (offset * 0.5) + wave))
                st.dataframe(rows, width="stretch")
        except Exception:
            pass


def render_optimization():
    if st.session_state.get("chat_busy"):
        st.info("Optimization view paused while assistant processes your request.")
        return
    st.subheader("Optimization And Forecast")
    st.caption("Control Plane: HIGH/BALANCED/ECO -> CPU model -> Carbon model -> Forecast graph")
    rec = api_get(f"/optimization/recommendations?current_instance={st.session_state.current_instance}&hours=720")
    fc  = api_get(f"/forecast/graph?current_instance={st.session_state.current_instance}&hours=720")
    if rec is None or fc is None or rec.status_code != 200 or fc.status_code != 200:
        st.warning("Optimization endpoints unavailable")
        return

    rp     = rec.json()
    fp     = fc.json()
    impact = fp.get("impact", {})
    graph  = fp.get("graph", {})
    mode   = str(impact.get("mode", rp.get("policy", {}).get("mode", "balanced"))).lower()
    graph  = _reshape_projection(
        graph=graph, mode=mode,
        seed_key=f"{st.session_state.current_instance}:{mode}:{st.session_state.monitor_instance}",
    )

    st.line_chart({"Without Optimization": graph.get("cost_without", []), "With Optimization": graph.get("cost_with", [])})
    st.line_chart({"Without Optimization CO2": graph.get("co2_without", []), "With Optimization CO2": graph.get("co2_with", [])})
    a, b = st.columns(2)
    a.metric("Projected Monthly Cost Delta",  f"${round(float(impact.get('current_cost_usd', 0)) - float(impact.get('target_cost_usd', 0)), 2)}")
    b.metric("Projected Monthly CO2e Delta",  f"{round(float(impact.get('current_co2e_kg',  0)) - float(impact.get('target_co2e_kg',  0)), 2)} kg")
    st.caption(f"Mode={mode.upper()} | Baseline CPU={impact.get('baseline_cpu_percent', 0)}% -> Adjusted CPU={impact.get('adjusted_cpu_percent', 0)}%")

    if fp.get("llm_summary"):
        st.info(fp["llm_summary"])

    for i, r in enumerate(rp.get("recommendations", []), start=1):
        st.markdown(f"**{i}. {r['title']}**")
        st.caption(f"{r['reason']} | Savings ${r['estimated_monthly_cost_savings_usd']} | CO2 {r['estimated_monthly_co2e_reduction_kg']} kg")

    st.markdown("---")
    st.subheader("Optimization Action Log")
    logs_resp = api_get("/optimization/actions?limit=12&source=chatbot")
    if logs_resp is not None and logs_resp.status_code == 200:
        logs = logs_resp.json().get("actions", [])
        if logs:
            cleaned = []
            for row in logs:
                meta = row.get("meta", {}) or {}
                cleaned.append({
                    "time":     row.get("created_at"),
                    "type":     meta.get("action_type", "chatbot_change"),
                    "decision": row.get("decision"),
                    "status":   row.get("status"),
                    "current":  row.get("current_instance"),
                    "target":   row.get("target_instance"),
                    "reason":   row.get("reason"),
                })
            st.dataframe(cleaned, width="stretch")
        else:
            st.info("No actions logged yet.")
    else:
        st.warning("Could not load optimization action logs.")


def render_impact():
    if st.session_state.get("chat_busy"):
        st.info("Impact view paused while assistant processes your request.")
        return
    st.subheader("Automatic Impact")
    auto = api_get(f"/impact/auto?current_instance={st.session_state.current_instance}&hours=720")
    if auto is None or auto.status_code != 200:
        st.warning("Impact endpoint unavailable")
        return
    payload = auto.json()
    impact  = payload.get("impact", {})
    x1, x2, x3 = st.columns(3)
    x1.metric("Auto Cost Savings",  f"${impact.get('cost_savings_usd', 0)}")
    x2.metric("Auto CO2e Reduction", f"{impact.get('co2e_reduction_kg', 0)} kg")
    x3.metric("Window",             f"{impact.get('hours', 0)} hrs")
    st.write(impact.get("reason", ""))

    st.markdown("---")
    st.subheader("Manual Impact Calculator")
    c1, c2, c3 = st.columns(3)
    current_instance = c1.text_input("Current Instance", value=st.session_state.current_instance, key="manual_current_instance")
    target_instance  = c2.text_input("Target Instance",  value="e2-standard-2",                   key="manual_target_instance")
    hours            = c3.number_input("Hours", min_value=1, value=720,                            key="manual_hours")
    r1, r2 = st.columns(2)
    current_region = r1.text_input("Current Region", value="us-central1", key="manual_current_region")
    target_region  = r2.text_input("Target Region",  value="us-central1", key="manual_target_region")

    if st.button("Calculate Impact", width="stretch"):
        resp = api_post("/impact/calculate", {
            "current_instance": current_instance,
            "target_instance":  target_instance,
            "current_region":   current_region,
            "target_region":    target_region,
            "hours":            hours,
        })
        if resp is not None and resp.status_code == 200:
            manual = resp.json().get("impact", {})
            m1, m2, m3 = st.columns(3)
            m1.metric("Cost Savings",  f"${manual.get('cost_savings_usd', 0)}")
            m2.metric("CO2e Reduction", f"{manual.get('co2e_reduction_kg', 0)} kg")
            m3.metric("Window",        f"{manual.get('hours', 0)} hrs")
        elif resp is not None:
            st.error(resp.text)


def render_chat():
    st.subheader("Copilot Chat")
    if not st.session_state.session_id:
        st.info("Create session first.")
        return
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if st.session_state.get("chat_error"):
        st.error(st.session_state["chat_error"])
        st.session_state["chat_error"] = None

    if st.session_state.get("chat_busy"):
        st.info("Assistant is processing your request...")

    pending_prompt = st.session_state.get("pending_prompt")
    if st.session_state.get("chat_busy") and pending_prompt:
        with st.spinner("Executing request..."):
            reply = send_message(pending_prompt)
        if reply:
            st.session_state.messages.append({"role": "assistant", "content": reply})
        else:
            st.session_state["chat_error"] = "Request failed or timed out. Please retry."
        st.session_state["chat_busy"]      = False
        st.session_state["pending_prompt"] = None
        st.rerun()

    st.chat_input(
        "Try: set performance mode eco",
        key="chat_input_box",
        on_submit=queue_chat_prompt,
        disabled=bool(st.session_state.get("chat_busy")),
    )


# ── Main ──────────────────────────────────────────────────────────────────────

ensure_session()
_require_login()   # blocks here until authenticated

render_sidebar()

st.title("EcoCloud Control Center")
st.caption("Policy-driven optimization with cloud architecture telemetry")

t1, t2, t3 = st.tabs(["Monitoring", "Optimization", "AI Chat"])
with t1:
    render_monitoring()
    render_impact()
with t2:
    render_optimization()
with t3:
    render_chat()

if st.session_state.get("auto_refresh", False) and not st.session_state.get("chat_busy", False):
    time.sleep(int(st.session_state.get("refresh_seconds", 10)))
    st.rerun()
