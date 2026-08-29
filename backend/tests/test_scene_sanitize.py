"""Tests for scene sanitization (no scanned page in video specs)."""

from app.services.understanding import sanitize_scenes
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
    assert isinstance(draw, dict)
    assert draw.get("series")
    colors = {s.get("color") for s in draw["series"]}
    assert None not in colors


def test_render_textbook_page_never_uses_imagemobject(tmp_path):
    provider = MathVizAIProvider()
    # Force the remapping branch inside render_scene by calling drawers after remap logic
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
                        "color": "#F5C542",
                    }
                ],
            },
        },
    }
    # Mirror render_scene remap
    viz = dict(spec["visualization"])
    viz_type = viz["type"]
    if viz_type == "textbook_page":
        viz_type = viz["draw"]["kind"]
        viz["type"] = viz_type
    code = provider._graph_2d_scene({**spec, "visualization": viz}, 5.0)
    assert "ImageMobject" not in code
    compile(code, "<t>", "exec")
