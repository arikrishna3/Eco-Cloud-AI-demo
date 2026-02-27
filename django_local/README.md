# Local GreenOps Stack

## 1) Start Django backend

```powershell
cd "E:\personal\ecocloud\django_local"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install django==5.1.15
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Optional (recommended): set Groq keys via env vars before running backend.

```powershell
$env:GROQ_API_KEY_CHAT = "<api-1>"
$env:GROQ_API_KEY_OPT = "<api-2>"
$env:GROQ_API_KEY_FORECAST = "<api-3>"
```

Fallback option: put all keys in `E:\personal\ecocloud\groq api key.txt` in order (chat, optimizer, forecast).

## 2) Start Streamlit frontend (separate terminal)

```powershell
cd "E:\personal\ecocloud\Frontend"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:API_BASE_URL = "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8080
```

Open `http://localhost:8080`.

## Backend endpoints

- `POST /apps/<app_name>/users/<user_id>/sessions/<session_id>`
- `POST /run`
- `GET /health`
- `GET /monitoring/summary`
- `GET|POST /optimization/policy`
- `POST /optimization/tick`
- `GET /optimization/actions`
- `GET /forecast/graph`
- `GET /agent/status`
- `GET /admin/`

## Notes

- Backend AI mode is local deterministic orchestration in `appname/services/ai_engine.py`.
- Monitoring logs are stored in SQLite table `ApiRequestLog`.
