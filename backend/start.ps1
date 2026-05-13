# Start the GradeAI FastAPI backend.
# Must be run from the backend/ directory with the venv activated.
# --host 0.0.0.0  lets the iPhone reach the server over LAN.
# --reload        restarts on code changes during development.

uvicorn main:app --reload --host 0.0.0.0 --port 8000
