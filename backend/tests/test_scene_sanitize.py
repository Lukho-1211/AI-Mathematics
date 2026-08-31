"""Tests for scene sanitization and draw inference."""

from app.services.understanding import (
    sanitize_scenes,
    safe_parse_function,
    safe_substitute_param,
)
from app.services.providers.mathviz_ai import MathVizAIProvider


def test_sanitize_removes_textbook_page_and_bbox():
    scenes = sanitize_scenes(
        [
            {
                "scene_id": "s1",
                "scene_type": "textbook_page",
                "title": "Overview",
                "visualization": {
                    "type": "textbook_page",
                    "math_expression": "x^2 - 5x + 6 = 0",
                    "highlight_bbox": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.2},
                },
            }
        ]
    )
    assert scenes[0]["scene_type"] != "textbook_page"
    assert scenes[0]["visualization"]["type"] != "textbook_page"
    assert "highlight_bbox" not in scenes[0]["visualization"]
    draw = scenes[0]["visualization"].get("draw")
    # Remap may yield concept or an inferred drawable with a draw block
    if scenes[0]["visualization"]["type"] in ("graph_2d", "number_line", "geometry"):
        assert isinstance(draw, dict)


def test_render_textbook_page_never_uses_imagemobject(tmp_path):
    provider = MathVizAIProvider()
    spec = {
        "title": "From page",
        "scene_type": "textbook_page",
        "visualization": {
            "type": "textbook_page",
            "math_expression": "x^2 - 5x + 6 = 0",
            "draw": {
                "kind": "graph_2d",
                "x_range": [-1, 6],
                "y_range": [-2, 8],
                "series": [
                    {
                        "id": "c",
                        "label": "curve",
                        "expr": "x**2 - 5*x + 6",
                        "color": "YELLOW",
                    }
                ],
            },
        },
    }
    viz = dict(spec["visualization"])
    viz_type = viz["type"]
    if viz_type == "textbook_page":
        viz_type = viz["draw"]["kind"]
        viz["type"] = viz_type
    code = provider._graph_2d_scene({**spec, "visualization": viz}, 5.0)
    assert "ImageMobject" not in code
    compile(code, "<t>", "exec")


def test_sanitize_infers_graph_from_parabola_narration():
    scenes = sanitize_scenes(
        [
            {
                "scene_id": "scene_03",
                "order_index": 0,
                "title": "Effect of a",
                "narration": "When a is positive the parabola opens upward.",
                "scene_type": "concept",
                "visualization": {
                    "type": "concept",
                    "math_expression": "y = a x^2",
                    "bullets": ["a controls direction"],
                },
            }
        ]
    )
    assert scenes[0]["scene_type"] == "graph_2d"
    draw = scenes[0]["visualization"].get("draw")
    assert isinstance(draw, dict)
    assert draw.get("kind") == "graph_2d"
    assert draw.get("series")
    colors = {s.get("color") for s in draw["series"]}
    assert colors & {"YELLOW", "TEAL", "ORANGE", "PINK", "GREEN", "BLUE", "RED", "WHITE"}


def test_sanitize_keeps_algebra_steps():
    scenes = sanitize_scenes(
        [
            {
                "scene_id": "scene_04",
                "title": "Solve",
                "narration": "Factor the quadratic.",
                "scene_type": "algebra_steps",
                "visualization": {
                    "type": "algebra_steps",
                    "math_expression": "x^2 - 5x + 6 = 0",
                    "steps": ["(x-2)(x-3)=0", "x=2 or x=3"],
                },
            }
        ]
    )
    assert scenes[0]["visualization"]["type"] == "algebra_steps"
    assert scenes[0]["visualization"]["steps"]


def test_sanitize_number_line_from_roots():
    scenes = sanitize_scenes(
        [
            {
                "scene_id": "scene_05",
                "title": "Roots on a number line",
                "narration": "Mark the solutions on the number line.",
                "scene_type": "why_explanation",
                "visualization": {
                    "type": "none",
                    "math_expression": "x^2 - 5x + 6 = 0",
                    "steps": ["x = 2 or x = 3"],
                },
            }
        ]
    )
    assert scenes[0]["scene_type"] == "number_line"
    draw = scenes[0]["visualization"]["draw"]
    assert draw["kind"] == "number_line"
    values = {p["value"] for p in draw["points"]}
    assert 2.0 in values and 3.0 in values


def test_sanitize_preserves_explicit_draw_series():
    scenes = sanitize_scenes(
        [
            {
                "scene_id": "scene_06",
                "title": "Horizontal shift",
                "narration": "Notice h moves the parabola left or right.",
                "scene_type": "graph_2d",
                "visualization": {
                    "type": "graph_2d",
                    "draw": {
                        "kind": "graph_2d",
                        "notice": "h > 0 shifts right.",
                        "series": [
                            {"expr": "x**2", "label": "h = 0", "color": "YELLOW"},
                            {"expr": "(x-2)**2", "label": "h = 2", "color": "TEAL"},
                        ],
                        "parameter_sweep": {
                            "param": "h",
                            "family": "(x - h)**2",
                            "values": [0, 1, 2, -1],
                        },
                    },
                },
            }
        ]
    )
    draw = scenes[0]["visualization"]["draw"]
    assert len(draw["series"]) >= 2
    assert draw["parameter_sweep"]["param"] == "h"
    assert draw["notice"].startswith("h > 0")


def test_safe_parse_rejects_injection():
    assert safe_parse_function("__import__('os').system('x')") is None
    assert safe_parse_function("x**2 + 1") is not None


def test_safe_substitute_param():
    result = safe_substitute_param("a * x**2", "a", -1)
    assert result is not None
    assert "-" in result or result.startswith("-")
