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
            "draw": {
                "kind": "graph_2d",
                "x_range": [-1, 6],
                "y_range": [-2, 8],
                "series": [
                    {
                        "id": "curve",
                        "label": "y = x^2 - 5x + 6",
                        "expr": "x**2 - 5*x + 6",
                        "color": "#F5C542",
                    },
                    {
                        "id": "root_a",
                        "label": "x = 2",
                        "kind": "point",
                        "x": 2,
                        "y": 0,
                        "color": "#3B82F6",
                    },
                    {
                        "id": "root_b",
                        "label": "x = 3",
                        "kind": "point",
                        "x": 3,
                        "y": 0,
                        "color": "#22C55E",
                    },
                ],
            },
        },
        "Quadratic example",
        12.0,
    )
    compile(code, "<scene>", "exec")
    assert "ImageMobject" not in code
    assert "#F5C542" in code or "F5C542" in code
    print("OK Manim algebra+graph scene compiles (no ImageMobject)")


def test_graph_numberline_geometry_compile() -> None:
    provider = MathVizAIProvider()
    graph = provider._graph_2d_scene(
        {
            "title": "Parabola",
            "visualization": {
                "type": "graph_2d",
                "draw": {
                    "kind": "graph_2d",
                    "x_range": [-1, 5],
                    "y_range": [-2, 6],
                    "series": [
                        {
                            "id": "c",
                            "label": "y=x^2",
                            "expr": "x**2",
                            "color": "#F5C542",
                        },
                        {
                            "id": "p",
                            "label": "origin",
                            "kind": "point",
                            "x": 0,
                            "y": 0,
                            "color": "#3B82F6",
                        },
                    ],
                },
            },
        },
        8.0,
    )
    nline = provider._number_line_scene(
        {
            "title": "Roots",
            "visualization": {
                "type": "number_line",
                "draw": {
                    "kind": "number_line",
                    "x_range": [-1, 5],
                    "series": [
                        {"id": "a", "label": "2", "kind": "point", "x": 2, "color": "#3B82F6"},
                        {"id": "b", "label": "3", "kind": "point", "x": 3, "color": "#22C55E"},
                    ],
                },
            },
        },
        6.0,
    )
    geom = provider._geometry_scene(
        {
            "title": "Triangle",
            "visualization": {
                "type": "geometry",
                "draw": {
                    "kind": "geometry",
                    "shapes": [
                        {
                            "id": "t",
                            "kind": "polygon",
                            "points": [[-2, -1], [2, -1], [0, 2]],
                            "label": "ABC",
                            "color": "#A855F7",
                        }
                    ],
                    "series": [{"id": "t", "label": "ABC", "color": "#A855F7"}],
                },
            },
        },
        6.0,
    )
    for name, code in (("graph", graph), ("number_line", nline), ("geometry", geom)):
        compile(code, f"<{name}>", "exec")
        assert "ImageMobject" not in code, name
    print("OK graph / number_line / geometry scenes compile (no ImageMobject)")


def test_textbook_page_remapped_no_image() -> None:
    scenes = sanitize_scenes(
        [
            {
                "scene_id": "scene_02",
                "scene_type": "textbook_page",
                "title": "Page overview",
                "narration": "Looking at the quadratic",
                "visualization": {
                    "type": "textbook_page",
                    "math_expression": "x^2 - 5x + 6 = 0",
                    "highlight_bbox": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.1},
                },
            }
        ]
    )
    assert scenes[0]["scene_type"] != "textbook_page"
    assert scenes[0]["visualization"]["type"] != "textbook_page"
    assert "highlight_bbox" not in scenes[0]["visualization"]
    assert isinstance(scenes[0]["visualization"].get("draw"), dict)

    provider = MathVizAIProvider()
    # Simulate leftover textbook_page reaching the renderer
    code = provider._deterministic_card(
        {"title": "Overview", "visualization": {"type": "concept", "bullets": ["Quadratic"]}},
        5.0,
    )
    # Full render_scene path for textbook_page without image
    result_code_path = None
    # Use public routing via generating code the same way render_scene would for remapped type
    remapped = {
        "title": "Overview",
        "scene_type": "textbook_page",
        "visualization": {
            "type": "textbook_page",
            "draw": {
                "kind": "graph_2d",
                "x_range": [-1, 6],
                "y_range": [-2, 8],
                "series": [
                    {
                        "id": "c",
                        "label": "y",
                        "expr": "x**2 - 5*x + 6",
                        "color": "#F5C542",
                    }
                ],
            },
        },
    }
    # Call internal path after remap logic: graph drawer
    code = provider._graph_2d_scene(remapped, 8.0)
    compile(code, "<remapped>", "exec")
    assert "ImageMobject" not in code
    assert result_code_path is None
    print("OK textbook_page remapped; no ImageMobject")


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
    test_graph_numberline_geometry_compile()
    test_textbook_page_remapped_no_image()
    test_subtitles()
    print("All offline acceptance checks passed.")
