"""Basic unit tests for math QC and image helpers (no OpenAI / Docker required)."""

from app.services.quality import QualityControlService
from app.services.image_processing import detect_content_type


def test_quadratic_roots_validate():
    qc = QualityControlService()
    result = qc.validate_algebra_steps(
        "x^2 - 5x + 6 = 0",
        ["(x - 2)(x - 3) = 0", "x = 2 or x = 3"],
    )
    assert result.ok, result.messages


def test_wrong_roots_fail():
    qc = QualityControlService()
    result = qc.validate_algebra_steps(
        "x^2 - 5x + 6 = 0",
        ["x = 1 or x = 6"],
    )
    assert not result.ok


def test_missing_expression_recovers_from_steps():
    qc = QualityControlService()
    result = qc.validate_algebra_steps("", ["T_n = a + (n-1)d", "a = 5 and d = 7"])
    assert result.ok, result.messages
    assert any("Recovered original expression" in m for m in result.messages)


def test_missing_expression_and_steps_soft_pass():
    qc = QualityControlService()
    result = qc.validate_algebra_steps("", [])
    assert result.ok, result.messages
    assert any("Missing original math expression" in m for m in result.messages)


def test_validate_scenes_missing_expr_does_not_abort():
    qc = QualityControlService()
    result = qc.validate_scenes_math(
        [
            {
                "scene_id": "scene_04",
                "scene_type": "algebra_steps",
                "visualization": {
                    "type": "algebra_steps",
                    "math_expression": "",
                    "steps": ["T_n = a + (n-1)d", "a = 5"],
                },
            }
        ]
    )
    assert result.ok, result.messages


def test_detect_png_magic():
    # Minimal PNG header
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert detect_content_type(data, "image/png", "page.png") == "image/png"
