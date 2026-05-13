"""
test_pipeline.py — Standalone smoke test for the GradeAI grading pipeline.

Run from the backend/ directory:
    python test_pipeline.py

Behaviour:
    1. Ensures a 200x200 white JPEG test image exists on disk.
    2. Encodes it as base64.
    3. Loads the first Question from the SQLite database.
    4. Calls run_grading_pipeline(question_id, image_base64, db).
    5. Prints the full result dict (session_id, marks, breakdown,
       feedback, extracted_text, cost_usd) as pretty-printed JSON.

This is a real Anthropic API call — make sure ANTHROPIC_API_KEY is set
in backend/.env before running.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
import zlib
from pathlib import Path

from database import SessionLocal
from models import Question
from pipeline import run_grading_pipeline


TEST_IMAGE_PATH = Path(__file__).parent / "test_white.jpg"


def _write_minimal_white_jpeg(path: Path, size: int = 200) -> None:
    """
    Write a small, valid white image to `path`.

    Tries Pillow first (produces a real 200x200 JPEG). If Pillow isn't
    installed, falls back to writing a hand-rolled solid-white PNG so the
    test is still self-contained — Anthropic's vision API accepts PNG.
    """
    try:
        from PIL import Image  # type: ignore

        img = Image.new("RGB", (size, size), color=(255, 255, 255))
        img.save(path, format="JPEG", quality=85)
        return
    except ImportError:
        pass

    # PNG fallback — a single-IDAT solid white image, no extra deps.
    png_path = path.with_suffix(".png")

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    raw = b""
    row = b"\x00" + b"\xff\xff\xff" * size  # filter byte + RGB white pixels
    for _ in range(size):
        raw += row
    idat = zlib.compress(raw, 9)
    png_bytes = (
        signature
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )
    png_path.write_bytes(png_bytes)
    # Update the global path reference for the rest of the script.
    global TEST_IMAGE_PATH
    TEST_IMAGE_PATH = png_path


def _ensure_test_image() -> Path:
    """Create the test image if missing and return the final path."""
    if TEST_IMAGE_PATH.exists():
        return TEST_IMAGE_PATH
    png_alt = TEST_IMAGE_PATH.with_suffix(".png")
    if png_alt.exists():
        return png_alt
    print(f"[test] Creating fresh test image at {TEST_IMAGE_PATH} ...")
    _write_minimal_white_jpeg(TEST_IMAGE_PATH)
    final = TEST_IMAGE_PATH if TEST_IMAGE_PATH.exists() else png_alt
    print(f"[test] Test image ready: {final}")
    return final


def _image_to_base64(path: Path) -> str:
    """Read an image file and return its raw base64 (no data URI prefix)."""
    return base64.standard_b64encode(path.read_bytes()).decode("ascii")


def main() -> int:
    """Entry point for `python test_pipeline.py`."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        # database.py loads dotenv, but if the key is still missing surface it loudly.
        from dotenv import load_dotenv

        load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("[test] ERROR: ANTHROPIC_API_KEY is not set in backend/.env", file=sys.stderr)
        return 1

    image_path = _ensure_test_image()
    image_b64 = _image_to_base64(image_path)

    db = SessionLocal()
    try:
        question = db.query(Question).order_by(Question.id.asc()).first()
        if question is None:
            print(
                "[test] ERROR: no Question rows in DB. Run `python seed.py` first.",
                file=sys.stderr,
            )
            return 2

        print(
            f"[test] Using question id={question.id} "
            f"number={question.question_number} "
            f"marks={question.marks_available}"
        )

        result = run_grading_pipeline(
            question_id=question.id,
            image_base64=image_b64,
            db=db,
        )
    finally:
        db.close()

    print("\n[test] === FULL RESULT ===")
    print(json.dumps(result, indent=2, default=str))
    print(f"\n[test] cost_usd = {result.get('cost_usd')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
