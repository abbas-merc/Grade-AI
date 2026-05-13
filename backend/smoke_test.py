"""
smoke_test.py -- End-to-end smoke test for the GradeAI backend.

Run BEFORE this script:
    uvicorn main:app --reload --port 8000

Run THIS script (from backend/):
    python smoke_test.py

Checks performed:
    1. Database has at least 1 paper and 10 questions
    2. GET  /health                      -> 200
    3. GET  /papers                      -> 200
    4. GET  /papers/1/questions          -> 200, >=10 items
    5. POST /grade/paper with a white test image (paper_id=1, one page)
       -> 200, returns valid PaperGradingResult shape
    6. Prints total Anthropic cost from the test call

Exit code 0 if every check passes, 1 otherwise.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO

# Force UTF-8 output so we never crash on the Windows cp1252 codec
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

BASE_URL = "http://localhost:8000"

PASS_TAG = "[ PASS ]"
FAIL_TAG = "[ FAIL ]"

_passed = 0
_failed = 0


def _report(label: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    tag = PASS_TAG if ok else FAIL_TAG
    line = f"{tag} {label}"
    if detail:
        line += f"  --  {detail}"
    print(line, flush=True)
    if ok:
        _passed += 1
    else:
        _failed += 1


def _http_get(path: str, timeout: int = 15) -> tuple[int, object]:
    req = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body)


def _http_post(path: str, body: dict, timeout: int = 180) -> tuple[int, object]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body_text = resp.read().decode("utf-8")
        return resp.status, json.loads(body_text)


def _make_white_image_b64(width: int = 800, height: int = 1000) -> str:
    """Generate a raw base64 JPEG of a solid white page."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def check_database() -> None:
    """Section 1: DB has >=1 paper and >=10 questions."""
    print("\n--- Database checks ---")
    try:
        from database import SessionLocal
        from models import Paper, Question
    except Exception as exc:
        _report("Import database/models", False, str(exc))
        return

    db = SessionLocal()
    try:
        paper_count = db.query(Paper).count()
        _report(
            "DB has at least 1 paper",
            paper_count >= 1,
            f"{paper_count} paper(s) found",
        )

        question_count = db.query(Question).count()
        _report(
            "DB has at least 10 questions",
            question_count >= 10,
            f"{question_count} question(s) found",
        )
    finally:
        db.close()


def check_http_endpoints() -> None:
    """Section 2: /health, /papers, /papers/1/questions all return 200."""
    print("\n--- HTTP endpoint checks ---")

    # /health
    try:
        status, body = _http_get("/health")
        ok = status == 200 and isinstance(body, dict) and body.get("status") == "ok"
        _report("GET /health -> 200", ok, f"status={status}, body={body}")
    except Exception as exc:
        _report("GET /health -> 200", False, str(exc))

    # /papers
    try:
        status, body = _http_get("/papers/")
        ok = status == 200 and isinstance(body, list) and len(body) >= 1
        detail = f"status={status}, {len(body) if isinstance(body, list) else 'non-list'} paper(s)"
        _report("GET /papers -> 200", ok, detail)
    except Exception as exc:
        _report("GET /papers -> 200", False, str(exc))

    # /papers/1/questions
    try:
        status, body = _http_get("/papers/1/questions")
        ok = status == 200 and isinstance(body, list) and len(body) >= 10
        detail = (
            f"status={status}, "
            f"{len(body) if isinstance(body, list) else 'non-list'} question(s)"
        )
        _report("GET /papers/1/questions -> 200", ok, detail)
    except Exception as exc:
        _report("GET /papers/1/questions -> 200", False, str(exc))


def check_grade_paper() -> dict | None:
    """Section 3: POST /grade/paper with one white test page."""
    print("\n--- Full-paper grading check ---")

    try:
        img_b64 = _make_white_image_b64()
    except Exception as exc:
        _report("Generate white test image", False, str(exc))
        return None

    _report("Generate white test image", True, "800x1000 JPEG")

    print(
        "  ... POST /grade/paper with one white page "
        "(real Anthropic call, may take 30-90s) ..."
    )
    t0 = time.time()
    try:
        status, body = _http_post(
            "/grade/paper",
            {"paper_id": 1, "page_images": [img_b64]},
            timeout=240,
        )
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        _report(
            "POST /grade/paper -> 200",
            False,
            f"HTTP {exc.code}: {err_body[:300]}",
        )
        return None
    except Exception as exc:
        _report("POST /grade/paper -> 200", False, str(exc))
        return None
    elapsed = time.time() - t0

    if status != 200:
        _report("POST /grade/paper -> 200", False, f"status={status}")
        return None

    if not isinstance(body, dict):
        _report("POST /grade/paper -> 200", False, "response is not a dict")
        return None

    _report(
        "POST /grade/paper -> 200",
        True,
        f"completed in {elapsed:.1f}s",
    )

    # Shape checks
    required_keys = {
        "paper_id",
        "total_marks_awarded",
        "total_marks_available",
        "cost_usd",
        "results",
        "cost_cap_reached",
    }
    missing = required_keys - set(body.keys())
    _report(
        "Response has all required keys",
        not missing,
        f"missing={sorted(missing) if missing else 'none'}",
    )

    results = body.get("results")
    _report(
        "Response.results is a list",
        isinstance(results, list),
        f"len={len(results) if isinstance(results, list) else 'n/a'}",
    )

    if isinstance(results, list) and results:
        first = results[0]
        item_keys = {
            "question_number",
            "question_text",
            "extracted_answer",
            "marks_awarded",
            "marks_available",
            "mark_breakdown",
            "feedback",
        }
        missing_item = item_keys - set(first.keys())
        _report(
            "Each result item has correct shape",
            not missing_item,
            f"missing={sorted(missing_item) if missing_item else 'none'}",
        )

    return body


def main() -> int:
    print("=" * 64)
    print("  GradeAI smoke test")
    print(f"  target: {BASE_URL}")
    print("=" * 64)

    check_database()
    check_http_endpoints()
    result = check_grade_paper()

    print("\n--- Cost summary ---")
    if result is not None:
        cost = result.get("cost_usd", 0.0)
        cap = result.get("cost_cap_reached", False)
        awarded = result.get("total_marks_awarded", 0)
        available = result.get("total_marks_available", 0)
        print(f"  Total cost (USD)       : ${cost:.4f}")
        print(f"  Cost cap reached       : {cap}")
        print(f"  Total marks awarded    : {awarded} / {available}")
    else:
        print("  (no grading result -- see failures above)")

    print()
    print("=" * 64)
    print(f"  {_passed} passed  |  {_failed} failed")
    print("=" * 64)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
