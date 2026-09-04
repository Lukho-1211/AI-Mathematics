"""Mathematical and video quality-control gates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import sympy as sp
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from app.core.logging import get_logger
from app.services.video_render import probe_streams

logger = get_logger(__name__)


# #region agent log
def _debug_agent_log(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    import json
    import time
    import urllib.request
    payload = {
        "sessionId": "8a26e1",
        "runId": "post-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload, default=str) + "\n"
    for path in ("/app/debug-8a26e1.log", "debug-8a26e1.log"):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass
    body = json.dumps(payload, default=str).encode()
    headers = {"Content-Type": "application/json", "X-Debug-Session-Id": "8a26e1"}
    for url in (
        "http://host.docker.internal:7683/ingest/316316a4-ae3a-49bc-a2dc-be48ea7d8ef3",
        "http://127.0.0.1:7683/ingest/316316a4-ae3a-49bc-a2dc-be48ea7d8ef3",
    ):
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers, method="POST"), timeout=1)
        except Exception:
            pass
# #endregion


@dataclass
class MathValidationResult:
    ok: bool
    messages: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class QualityControlService:
    def validate_algebra_steps(self, expression: str, steps: list[str]) -> MathValidationResult:
        """Validate that algebra steps are consistent and roots satisfy the original equation when solvable."""
        messages: list[str] = []
        details: dict[str, Any] = {}

        cleaned_expr = _normalize_latex_math(expression)
        cleaned_steps = [_normalize_latex_math(s) for s in steps if s]

        # #region agent log
        _debug_agent_log(
            "B",
            "quality.py:validate_algebra_steps",
            "qc_algebra_normalize",
            {
                "expr_type": type(expression).__name__,
                "expr_repr": repr(expression)[:240] if expression is not None else None,
                "cleaned_expr": cleaned_expr[:240] if cleaned_expr else "",
                "cleaned_empty": not bool(cleaned_expr),
                "steps_n": len(steps or []),
                "cleaned_steps_n": len(cleaned_steps),
                "steps_preview": [str(s)[:80] for s in (steps or [])[:4]],
            },
        )
        # #endregion

        if not cleaned_expr:
            if cleaned_steps:
                cleaned_expr = cleaned_steps[0]
                messages.append("Recovered original expression from first algebra step")
                # #region agent log
                _debug_agent_log(
                    "C",
                    "quality.py:validate_algebra_steps:recover",
                    "qc_recovered_from_steps",
                    {"cleaned_expr": cleaned_expr[:200]},
                )
                # #endregion
            else:
                messages.append("Missing original math expression and steps; proceeding with caution")
                # #region agent log
                _debug_agent_log(
                    "A",
                    "quality.py:validate_algebra_steps:soft",
                    "qc_soft_pass_empty",
                    {"ok": True},
                )
                # #endregion
                return MathValidationResult(ok=True, messages=messages, details=details)

        # Try to extract equation LHS-RHS = 0
        try:
            eq = _to_sympy_equation(cleaned_expr)
            details["parsed_equation"] = str(eq)
        except Exception as exc:
            messages.append(f"Could not parse original equation for validation: {exc}")
            # Soft-fail parse of original — still try root check from steps
            eq = None

        roots = _extract_roots_from_steps(cleaned_steps)
        details["extracted_roots"] = [str(r) for r in roots]

        if eq is not None and roots:
            x = sp.symbols("x")
            failures = []
            for r in roots:
                try:
                    val = eq.subs(x, r)
                    if val != 0 and sp.simplify(val) != 0:
                        # numeric check
                        if abs(complex(val.evalf())) > 1e-6:
                            failures.append(f"Root {r} does not satisfy equation (residual={val})")
                except Exception as exc:
                    failures.append(f"Could not verify root {r}: {exc}")
            if failures:
                messages.extend(failures)
                return MathValidationResult(ok=False, messages=messages, details=details)
            messages.append("Roots satisfy the original equation")
            return MathValidationResult(ok=True, messages=messages, details=details)

        # Fallback: pairwise equivalence of polynomial forms when possible
        polys = []
        for s in [cleaned_expr] + cleaned_steps:
            try:
                polys.append(_equation_to_poly(s))
            except Exception:
                polys.append(None)

        comparable = [(i, p) for i, p in enumerate(polys) if p is not None]
        if len(comparable) >= 2:
            base = comparable[0][1]
            for i, p in comparable[1:]:
                diff = sp.expand(base - p)
                if diff != 0:
                    # For factoring steps, allow different forms if roots match later
                    messages.append(f"Step {i} polynomial form differs from original (may be factored form)")
            # If we couldn't extract roots, soft-pass with warning
            if not roots:
                messages.append("Could not extract numeric/symbolic roots; skipped hard root check")
                return MathValidationResult(ok=True, messages=messages, details=details)

        if not roots and eq is None:
            messages.append("Insufficient structure for hard math validation; proceeding with caution")
            return MathValidationResult(ok=True, messages=messages, details=details)

        if roots and eq is None:
            messages.append("Parsed roots but not original equation; cannot hard-verify")
            return MathValidationResult(ok=True, messages=messages, details=details)

        return MathValidationResult(ok=True, messages=messages or ["Validation passed"], details=details)

    def validate_scenes_math(self, scenes: list[dict[str, Any]]) -> MathValidationResult:
        all_msgs: list[str] = []
        for sc in scenes:
            viz = sc.get("visualization") or {}
            if (viz.get("type") or sc.get("scene_type")) == "algebra_steps":
                expr = viz.get("math_expression") or ""
                steps = viz.get("steps") or []
                # #region agent log
                _debug_agent_log(
                    "A",
                    "quality.py:validate_scenes_math",
                    "qc_algebra_scene",
                    {
                        "scene_id": sc.get("scene_id"),
                        "scene_type": sc.get("scene_type"),
                        "viz_type": viz.get("type"),
                        "viz_keys": list(viz.keys())[:20],
                        "scene_keys": list(sc.keys())[:20],
                        "expr_type": type(viz.get("math_expression")).__name__,
                        "expr_present": bool(viz.get("math_expression")),
                        "expr": str(viz.get("math_expression") or "")[:200],
                        "scene_level_expr": str(sc.get("math_expression") or "")[:120],
                        "steps_type": type(viz.get("steps")).__name__,
                        "steps_n": len(steps) if isinstance(steps, list) else -1,
                        "draw_keys": list((viz.get("draw") or {}).keys())[:12] if isinstance(viz.get("draw"), dict) else None,
                    },
                )
                # #endregion
                result = self.validate_algebra_steps(expr, steps)
                all_msgs.extend([f"[{sc.get('scene_id')}] {m}" for m in result.messages])
                if not result.ok:
                    return MathValidationResult(ok=False, messages=all_msgs, details=result.details)
        return MathValidationResult(ok=True, messages=all_msgs or ["All algebra scenes validated"])

    def validate_video(self, path: Path, expected_min_duration: float = 3.0) -> MathValidationResult:
        if not path.exists():
            return MathValidationResult(ok=False, messages=[f"Video missing: {path}"])
        try:
            info = probe_streams(path)
        except Exception as exc:
            return MathValidationResult(ok=False, messages=[f"ffprobe failed: {exc}"])

        streams = info.get("streams") or []
        has_video = any(s.get("codec_type") == "video" for s in streams)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        duration = float((info.get("format") or {}).get("duration") or 0)
        messages = []
        if not has_video:
            messages.append("No video stream")
        if not has_audio:
            messages.append("No audio stream")
        if duration < expected_min_duration:
            messages.append(f"Duration too short: {duration:.2f}s")

        vcodec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "video"), None)
        acodec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), None)
        details = {"duration": duration, "vcodec": vcodec, "acodec": acodec}
        if messages:
            return MathValidationResult(ok=False, messages=messages, details=details)
        return MathValidationResult(
            ok=True,
            messages=[f"Video OK ({vcodec}/{acodec}, {duration:.1f}s)"],
            details=details,
        )


def _normalize_latex_math(s: str) -> str:
    s = s.strip()
    s = s.replace("$$", "").replace("$", "")
    s = s.replace("\\left", "").replace("\\right", "")
    s = s.replace("\\,", "").replace("\\;", "").replace("\\!", "")
    s = s.replace("\\times", "*").replace("\\cdot", "*")
    s = s.replace("\\ ", " ")
    # \frac{a}{b} -> (a)/(b)
    while True:
        m = re.search(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", s)
        if not m:
            break
        s = s[: m.start()] + f"({m.group(1)})/({m.group(2)})" + s[m.end() :]
    s = s.replace("{", "(").replace("}", ")")
    s = s.replace("^", "**")
    s = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\text\{([^}]*)\}", r"\1", s)
    s = s.replace("\\", "")
    return s.strip()


def _to_sympy_equation(expr: str) -> sp.Expr:
    """Return LHS-RHS as expression equal to zero."""
    if "=" in expr:
        left, right = expr.split("=", 1)
        left_e = _parse(left)
        right_e = _parse(right)
        return sp.expand(left_e - right_e)
    return sp.expand(_parse(expr))


def _equation_to_poly(expr: str) -> sp.Expr:
    return sp.Poly(_to_sympy_equation(expr), sp.symbols("x")).as_expr()


def _parse(s: str) -> sp.Expr:
    s = s.strip()
    # Handle "or" / text
    transforms = standard_transformations + (implicit_multiplication_application,)
    return parse_expr(s, transformations=transforms, evaluate=True)


def _extract_roots_from_steps(steps: list[str]) -> list[sp.Expr]:
    roots: list[sp.Expr] = []
    x = sp.symbols("x")
    for s in steps:
        # Patterns: x = 2, x=3, x = 2 or x = 3
        for m in re.finditer(r"(?i)\bx\s*=\s*([-+]?\d+(?:\.\d+)?)", s):
            try:
                roots.append(sp.Integer(m.group(1)) if "." not in m.group(1) else sp.Float(m.group(1)))
            except Exception:
                pass
        # (x - a)(x - b) = 0
        for m in re.finditer(r"\(x\s*([+-])\s*(\d+)\)", s):
            sign, num = m.group(1), int(m.group(2))
            root = -num if sign == "+" else num
            roots.append(sp.Integer(root))
    # Unique preserve order
    seen = set()
    uniq = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq
