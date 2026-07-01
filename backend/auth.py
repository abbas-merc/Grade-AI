"""
auth.py — Firebase Admin authentication for the GradeAI backend.

Initializes the Firebase Admin SDK from a service account and exposes:
  - verify_token(token)  : verify a Firebase ID token, return its uid
  - get_current_uid      : FastAPI dependency that pulls the Bearer token from
                           the Authorization header and returns the verified uid

Service account credentials are loaded from one of three environment variables,
checked in this order of decreasing robustness:

  FIREBASE_SERVICE_ACCOUNT_B64   — the service account JSON, base64-encoded. This
                                   is the PREFERRED option on Railway and any
                                   hosted env: it is a single line of
                                   [A-Za-z0-9+/=] with no quotes, spaces, or
                                   newlines, so a dashboard/shell cannot mangle
                                   it (raw JSON with embedded quotes and \n was
                                   the historical cause of "Invalid service
                                   account certificate" on deploy).
  FIREBASE_SERVICE_ACCOUNT_JSON  — the entire service account JSON as a single
                                   string. Works, but pasteable-JSON is fragile.
  FIREBASE_SERVICE_ACCOUNT_PATH  — filesystem path to the service account JSON.
"""

import base64
import json
import os

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from fastapi import Depends, HTTPException, Request

# Load environment variables from .env before reading any Firebase config below.
load_dotenv()


def _auth_required() -> bool:
    """
    Whether incoming requests must carry a valid Firebase ID token.

    Defaults to True (secure by default). Set AUTH_REQUIRED=false in the
    environment to bypass token verification for local development / demos.
    """
    return os.getenv("AUTH_REQUIRED", "true").strip().lower() not in (
        "false",
        "0",
        "no",
        "off",
    )


def _build_credentials() -> credentials.Certificate:
    """
    Build Firebase credentials from the environment.

    Checks, in order: FIREBASE_SERVICE_ACCOUNT_B64 (base64 JSON — most robust),
    FIREBASE_SERVICE_ACCOUNT_JSON (inline JSON string), then
    FIREBASE_SERVICE_ACCOUNT_PATH (file path). Raises RuntimeError if none are
    set or a provided value is malformed.
    """
    raw_b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")
    if raw_b64 and raw_b64.strip():
        try:
            decoded = base64.b64decode(raw_b64.strip()).decode("utf-8")
            service_account_info = json.loads(decoded)
        except (ValueError, UnicodeDecodeError) as exc:
            # ValueError covers binascii.Error (bad base64) and JSONDecodeError.
            raise RuntimeError(
                "FIREBASE_SERVICE_ACCOUNT_B64 is set but is not valid "
                "base64-encoded JSON"
            ) from exc
        return credentials.Certificate(service_account_info)

    raw_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if raw_json and raw_json.strip():
        try:
            service_account_info = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "FIREBASE_SERVICE_ACCOUNT_JSON is set but is not valid JSON"
            ) from exc
        return credentials.Certificate(service_account_info)

    path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    if path:
        return credentials.Certificate(path)

    raise RuntimeError(
        "Firebase service account not configured. Set FIREBASE_SERVICE_ACCOUNT_B64 "
        "(recommended), FIREBASE_SERVICE_ACCOUNT_JSON, or FIREBASE_SERVICE_ACCOUNT_PATH."
    )


def _init_firebase_app() -> None:
    """Initialize the default Firebase Admin app exactly once (idempotent)."""
    if firebase_admin._apps:
        return
    cred = _build_credentials()
    firebase_admin.initialize_app(cred)


# Initialize eagerly at import so the SDK is ready before the first request.
# If credentials aren't configured yet, don't crash the whole app on import —
# defer to the first token verification, which surfaces a clear 500. When auth
# is disabled (AUTH_REQUIRED=false) skip init entirely — no credentials needed.
if _auth_required():
    try:
        _init_firebase_app()
    except Exception as exc:  # noqa: BLE001 — log and continue; retried lazily below
        print(f"[auth] Firebase Admin not initialized at startup: {exc}")
else:
    print("[auth] AUTH_REQUIRED=false — token verification is DISABLED (dev mode).")


def verify_token(token: str) -> str:
    """
    Verify a Firebase ID token and return the user's uid.

    Raises HTTPException(401) if the token is invalid or expired.
    Raises HTTPException(500) if the Firebase Admin SDK is not configured.
    """
    # Ensure the app is initialized (handles the case where credentials were
    # not available at import time). A config failure here is a 500, not a 401.
    try:
        _init_firebase_app()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Authentication not configured: {exc}"
        ) from exc

    try:
        decoded_token = firebase_auth.verify_id_token(token)
    except Exception as exc:  # noqa: BLE001 — any verification failure is a 401
        raise HTTPException(
            status_code=401, detail="Invalid or expired authentication token"
        ) from exc

    uid = decoded_token.get("uid")
    if not uid:
        raise HTTPException(
            status_code=401, detail="Invalid or expired authentication token"
        )
    return uid


def get_current_uid(request: Request) -> str:
    """
    FastAPI dependency: extract the Bearer token from the Authorization header
    and return the verified Firebase uid.

    When AUTH_REQUIRED is false (dev/demo mode), verification is skipped and a
    placeholder uid ("anonymous") is returned so every route stays functional.

    Raises HTTPException(401) if the Authorization header is missing or is not
    a well-formed "Bearer <token>" value.
    """
    if not _auth_required():
        return "anonymous"

    header = request.headers.get("Authorization")
    if not header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=401, detail="Invalid Authorization header; expected 'Bearer <token>'"
        )

    token = parts[1].strip()
    return verify_token(token)
