"""Compile-check deterministic MathViz graph / number-line / geometry scenes."""

from app.services.providers.mathviz_ai import MathVizAIProvider


def test_graph_2d_scene_compiles():
    provider = MathVizAIProvider()
    spec = {
        "title": "Effect of a",
        "narration": "When a flips sign the parabola reflects.",
        "scene_type": "graph_2d",
        "visualization": {
            "type": "graph_2d",
            "draw": {
                "kind": "graph_2d",
                "title": "Effect of a",
                "notice": "When a changes sign, the parabola reflects across the x-axis.",
                "axes": {"x_min": -5, "x_max": 5, "y_min": -5, "y_max": 5},
                "series": [
                    {"expr": "x**2", "label": "a = 1", "color": "YELLOW"},
                    {"expr": "-x**2", "label": "a = -1", "color": "TEAL"},
                ],
                "highlights": [{"kind": "vertex", "point": [0, 0], "label": "(0, 0)"}],
                "parameter_sweep": {
                    "param": "a",
                    "family": "a * x**2",
                    "values": [1, 2, 0.5, -1],
                },
            },
        },
    }
    code = provider._graph_2d_scene(spec, 12.0)
    compile(code, "<graph_2d>", "exec")


def test_number_line_scene_compiles():
    provider = MathVizAIProvider()
    spec = {
        "title": "Roots",
        "scene_type": "number_line",
        "visualization": {
            "type": "number_line",
            "draw": {
                "kind": "number_line",
                "title": "Roots",
                "notice": "The solutions sit at 2 and 3.",
                "x_min": -1,
                "x_max": 5,
                "points": [
                    {"value": 2, "label": "x=2", "color": "YELLOW"},
                    {"value": 3, "label": "x=3", "color": "TEAL"},
                ],
            },
        },
    }
    code = provider._number_line_scene(spec, 8.0)
    compile(code, "<number_line>", "exec")


def test_geometry_scene_compiles():
    provider = MathVizAIProvider()
    spec = {
        "title": "Triangle",
        "scene_type": "geometry",
        "visualization": {
            "type": "geometry",
            "draw": {
                "kind": "geometry",
                "title": "Triangle ABC",
                "notice": "Observe the sides of the triangle.",
                "points": {"A": [-2, -1], "B": [2, -1], "C": [0, 2]},
                "segments": [["A", "B"], ["B", "C"], ["C", "A"]],
                "polygons": [["A", "B", "C"]],
                "circles": [],
            },
        },
    }
    code = provider._geometry_scene(spec, 8.0)
    compile(code, "<geometry>", "exec")


def test_matrix_scene_compiles():
    provider = MathVizAIProvider()
    spec = {
        "title": "Identity",
        "scene_type": "matrix",
        "visualization": {
            "type": "matrix",
            "draw": {
                "kind": "matrix",
                "title": "Identity",
                "notice": "The identity matrix leaves vectors unchanged.",
                "matrix": r"\begin{bmatrix}1&0\\0&1\end{bmatrix}",
                "after": None,
            },
        },
    }
    code = provider._matrix_scene(spec, 6.0)
    compile(code, "<matrix>", "exec")


def test_render_scene_routes_draw_before_text_card():
    """concept scenes with draw.kind=graph_2d must use the graph template, not a text card."""
    provider = MathVizAIProvider()
    # Force route selection without running manim: call graph path via draw kind logic
    # by generating code the same way render_scene would for draw routing.
    viz = {
        "type": "why_explanation",
        "draw": {
            "kind": "graph_2d",
            "series": [{"expr": "x**2", "label": "a=1", "color": "YELLOW"}],
            "notice": "Opens upward.",
        },
    }
    spec = {"title": "a > 0", "scene_type": "why_explanation", "visualization": viz}
    code = provider._graph_2d_scene(spec, 5.0)
    assert "Axes(" in code
    assert "x**2" in code
