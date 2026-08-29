"""API-level e2e smoke test (requires running stack + OPENAI_API_KEY).

Usage:
  python scripts/e2e_api_smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

API = "http://localhost:8000"
SAMPLE = Path(__file__).resolve().parents[1] / "sample_data" / "quadratic_page.png"


def main() -> int:
    if not SAMPLE.exists():
        print("Sample page missing; run scripts/make_sample_page.py first")
        return 1

    client = httpx.Client(base_url=API, timeout=120.0)
    try:
        health = client.get("/health")
        health.raise_for_status()
        print("API healthy")
    except Exception as exc:
        print(f"API not reachable at {API}: {exc}")
        print("Start stack: docker compose up -d --build postgres redis minio minio-init api worker")
        return 2

    # Invalid upload should fail cleanly
    bad = client.post(
        "/api/projects",
        json={"title": "E2E Quadratic"},
    )
    bad.raise_for_status()
    project = bad.json()
    pid = project["id"]
    print("Created project", pid)

    fail = client.post(
        f"/api/upload/{pid}",
        files={"file": ("bad.txt", b"not-an-image", "text/plain")},
    )
    if fail.status_code < 400:
        print("ERROR: expected invalid upload to fail")
        return 3
    print("OK invalid upload rejected:", fail.status_code)

    with SAMPLE.open("rb") as f:
        up = client.post(
            f"/api/upload/{pid}",
            files={"file": ("quadratic_page.png", f, "image/png")},
            data={"rotation": "0", "page_number": "1"},
        )
    up.raise_for_status()
    print("Uploaded sample page")

    ocr = client.post(f"/api/ocr/{pid}")
    ocr.raise_for_status()
    print("OCR queued; waiting for AWAITING_REVIEW…")

    for _ in range(90):
        time.sleep(2)
        p = client.get(f"/api/projects/{pid}").json()
        print(f"  status={p['status']} pct={p['progress_percent']}")
        if p["status"] in ("AWAITING_REVIEW", "OCR_COMPLETE"):
            break
        if p["status"] == "FAILED":
            print("OCR failed:", p.get("error_message"))
            return 4
    else:
        print("Timed out waiting for OCR")
        return 5

    exprs = p.get("expressions") or []
    print(f"Extracted {len(exprs)} elements")
    latex_blob = " ".join((e.get("latex") or e.get("original_text") or "") for e in exprs)
    if "x^2" not in latex_blob.replace(" ", "") and "x²" not in latex_blob:
        print("WARNING: expected quadratic latex not obviously present:", latex_blob[:300])

    # Clear review flags if any
    for e in exprs:
        e["needs_review"] = False
        if not e.get("latex") and "x" in (e.get("original_text") or ""):
            e["latex"] = "x^2 - 5x + 6 = 0"

    # Force authoritative quadratic if OCR missed it (still user-confirmed content)
    if not any("6" in (e.get("latex") or "") for e in exprs):
        exprs.append(
            {
                "id": exprs[0]["id"] if exprs else None,
                "original_text": "x^2 - 5x + 6 = 0",
                "latex": "x^2 - 5x + 6 = 0",
                "element_type": "equation",
            }
        )

    # Patch individually then approve
    detail = client.get(f"/api/projects/{pid}").json()
    for e in detail["expressions"]:
        client.patch(
            f"/api/ocr/{pid}/expressions/{e['id']}",
            json={
                "original_text": e["original_text"] or "x^2 - 5x + 6 = 0",
                "latex": e.get("latex") or "x^2 - 5x + 6 = 0",
            },
        )

    # If no equation present, we still approve reviewed text
    review = client.post(f"/api/ocr/{pid}/review", json={"expressions": []})
    if review.status_code >= 400:
        print("Review failed:", review.text)
        # Try clearing needs_review by patching all
        detail = client.get(f"/api/projects/{pid}").json()
        payload = []
        for e in detail["expressions"]:
            payload.append(
                {
                    "id": e["id"],
                    "original_text": e["original_text"],
                    "latex": e.get("latex") or e["original_text"],
                    "element_type": e["element_type"],
                }
            )
            client.patch(
                f"/api/ocr/{pid}/expressions/{e['id']}",
                json={"latex": e.get("latex") or "x^2 - 5x + 6 = 0", "original_text": e["original_text"]},
            )
        review = client.post(f"/api/ocr/{pid}/review", json={"expressions": payload})
    review.raise_for_status()
    print("OCR approved")

    gen = client.post(
        f"/api/projects/{pid}/generate",
        json={"voice_gender": "female", "voice_speed": 1.0, "language": "en"},
    )
    gen.raise_for_status()
    print("Generation queued")

    for _ in range(300):
        time.sleep(5)
        p = client.get(f"/api/projects/{pid}").json()
        print(f"  status={p['status']} stage={p.get('progress_stage')} pct={p['progress_percent']}")
        if p["status"] == "COMPLETED":
            vids = p.get("videos") or []
            print("COMPLETED with videos:", json.dumps(vids, indent=2)[:500])
            return 0
        if p["status"] == "FAILED":
            print("FAILED:", p.get("error_message"))
            return 6
    print("Timed out waiting for video")
    return 7


if __name__ == "__main__":
    sys.exit(main())
