# Start the GradeAI FastAPI backend.
# Must be run from the backend/ directory with the venv activated.
# --host 0.0.0.0  lets the iPhone reach the server over LAN.
# --reload        restarts on code changes during development.
# Port 8001: 8000 is prone to conflicts/reserved-range issues on this machine.
# AUTH_REQUIRED=false is set inline (dev mode) so curl/Expo work without a token
# and we don't depend on a separately exported env var.

$env:AUTH_REQUIRED = "false"
uvicorn main:app --reload --host 0.0.0.0 --port 8001
