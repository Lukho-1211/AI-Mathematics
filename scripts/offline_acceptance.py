"""End-to-end smoke helpers and offline acceptance checks."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.quality import QualityControlService
from app.services.providers.mathviz_ai import MathVizAIProvider
from app.services.understanding import sanitize_scenes
from app.services.video_render import SubtitleService


def test_acceptance_math_steps() -> None:
    qc = QualityControlService()
    steps = [
        "(x - 2)(x - 3) = 0",
        "x - 2 = 0    OR    x - 3 = 0",
        "x = 2        OR    x = 3",
    ]
    result = qc.validate_algebra_steps("x^2 - 5x + 6 = 0", steps)
    assert result.ok, result.messages
    print("OK math validation:", result.messages)


def test_deterministic_algebra_manim_syntax() -> None:
    provider = MathVizAIProvider()
    code = provider._algebra_steps_scene(
        {
            "math_expression": "x^2 - 5x + 6 = 0",
            "steps": ["(x-2)(x-3)=0", "x=2", "x=3"],
        },
        "Quadratic example",
        12.0,
    )
    compile(code, "<scene>", "exec")
    print("OK Manim algebra scene compiles")


def test_deterministic_graph_manim_syntax() -> None:
    provider = MathVizAIProvider()
    code = provider._graph_2d_scene(
        {
            "title": "Effect of a",
            "visualization": {
                "type": "graph_2d",
                "draw": {
                    "kind": "graph_2d",
                    "title": "Effect of a",
                    "notice": "When a changes sign, the parabola reflects.",
                    "series": [
                        {"expr": "x**2", "label": "a = 1", "color": "YELLOW"},
                        {"expr": "-x**2", "label": "a = -1", "color": "TEAL"},
                    ],
                    "parameter_sweep": {
                        "param": "a",
                        "family": "a * x**2",
                        "values": [1, 2, 0.5, -1],
                    },
                },
            },
        },
        14.0,
    )
    compile(code, "<graph>", "exec")
    print("OK Manim graph_2d scene compiles")


def test_sanitize_quadratic_concept() -> None:
    scenes = sanitize_scenes(
        [
            {
                "scene_id": "scene_03",
                "title": "Parabola opens",
                "narration": "If a is positive the parabola opens upward.",
                "scene_type": "concept",
                "visualization": {"type": "concept", "math_expression": "y = a x^2"},
            }
        ]
    )
    assert scenes[0]["visualization"]["type"] == "graph_2d"
    assert scenes[0]["visualization"]["draw"]["series"]
    print("OK sanitize remaps quadratic concept to graph_2d")


def test_subtitles() -> None:
    srt, vtt = SubtitleService().from_scene_audio(
        [
            {"narration": "Let's solve this quadratic equation.", "duration_actual": 4.0},
            {"narration": "The roots are 2 and 3.", "duration_actual": 3.0},
        ]
    )
    assert "quadratic" in srt.lower()
    assert "WEBVTT" in vtt
    print("OK subtitles")


if __name__ == "__main__":
    test_acceptance_math_steps()
    test_deterministic_algebra_manim_syntax()
    test_deterministic_graph_manim_syntax()
    test_sanitize_quadratic_concept()
    test_subtitles()
    print("All offline acceptance checks passed.")
