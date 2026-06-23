# Grant beta access to the teachers listed in scripts/setup_beta_users.py.
# Run from anywhere; paths are resolved relative to this script. Requires the
# backend venv and Firebase credentials in backend/.env (same as the server).
& "$PSScriptRoot/../venv/Scripts/python.exe" "$PSScriptRoot/setup_beta_users.py"
