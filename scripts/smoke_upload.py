"""Upload + invalid-file smoke test against a running API."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

API = "http://localhost:8000"
SAMPLE = Path(__file__).resolve().parents[1] / "sample_data" / "quadratic_page.png"


def main() -> int:
    client = httpx.Client(base_url=API, timeout=60.0)
    health = client.get("/health")
    health.raise_for_status()
    print("health:", health.json())

    project = client.post("/api/projects", json={"title": "Quadratic Acceptance"}).json()
    pid = project["id"]
    print("project:", pid)

    bad = client.post(
        f"/api/upload/{pid}",
        files={"file": ("x.txt", b"nope", "text/plain")},
    )
    print("bad upload:", bad.status_code, bad.text[:120])
    assert bad.status_code >= 400

    with SAMPLE.open("rb") as f:
        up = client.post(
            f"/api/upload/{pid}",
            files={"file": ("quadratic_page.png", f, "image/png")},
            data={"rotation": "0", "page_number": "1"},
        )
    print("upload:", up.status_code)
    up.raise_for_status()
    data = up.json()
    print("status:", data["status"], "url:", (data.get("uploaded_page_url") or "")[:80])
    assert data["status"] == "UPLOADED"

    # OCR without API key should fail the job (not crash the API)
    ocr = client.post(f"/api/ocr/{pid}")
    print("ocr queue:", ocr.status_code)
    ocr.raise_for_status()
    print("Smoke OK — set OPENAI_API_KEY in .env and restart api/worker for full e2e")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("FAIL:", exc)
        raise
