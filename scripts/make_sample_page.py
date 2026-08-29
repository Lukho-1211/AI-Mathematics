"""Generate a sample textbook-style page for the quadratic acceptance test."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample_data" / "quadratic_page.png"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("arial.ttf", 56)
        body_font = ImageFont.truetype("arial.ttf", 40)
        eq_font = ImageFont.truetype("arial.ttf", 48)
    except OSError:
        title_font = ImageFont.load_default()
        body_font = title_font
        eq_font = title_font

    draw.rectangle((60, 60, 1140, 1540), outline="#222222", width=3)
    draw.text((100, 120), "Quadratic equations", fill="#111111", font=title_font)
    draw.text((100, 220), "Chapter 4  ·  Section 4.1", fill="#555555", font=body_font)
    draw.text(
        (100, 320),
        "A quadratic equation is an equation that can be written",
        fill="#222222",
        font=body_font,
    )
    draw.text((100, 380), "in the form  ax² + bx + c = 0,  where a ≠ 0.", fill="#222222", font=body_font)
    draw.text((100, 500), "Example 1 — Solve by factorisation", fill="#111111", font=body_font)
    draw.text((100, 600), "Solve:", fill="#222222", font=body_font)
    draw.text((180, 700), "x² − 5x + 6 = 0", fill="#000000", font=eq_font)
    draw.text((100, 860), "Find two numbers that multiply to 6 and add to −5.", fill="#333333", font=body_font)
    draw.text((100, 980), "Notes", fill="#111111", font=body_font)
    draw.text((100, 1060), "• Always check solutions in the original equation.", fill="#333333", font=body_font)
    draw.text((100, 1130), "• Common mistake: incorrect factor pairs.", fill="#333333", font=body_font)

    img.save(OUT, "PNG")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
