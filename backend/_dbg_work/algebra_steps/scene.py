from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = "#0b1220"
        title = Text('Factor', font_size=36, color=WHITE)
        title.to_edge(UP)
        self.play(Write(title))
        exprs = ['a^2 - b^2', '(a+b)(a-b)']
        prev = None
        for i, e in enumerate(exprs):
            try:
                mob = MathTex(e, font_size=42, color=YELLOW if i == len(exprs)-1 else WHITE)
            except Exception:
                mob = Text(e, font_size=28, color=WHITE)
            mob.move_to(ORIGIN)
            if prev is None:
                self.play(Write(mob))
            else:
                self.play(TransformMatchingTex(prev, mob) if isinstance(prev, MathTex) and isinstance(mob, MathTex) else ReplacementTransform(prev, mob))
            wait_t = max(0.8, 5.0 / max(1, len(exprs)))
            self.wait(wait_t)
            prev = mob
        self.wait(0.5)
