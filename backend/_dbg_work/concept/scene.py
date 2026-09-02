from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = "#0b1220"
        title = Text('Concept card', font_size=40, color=WHITE)
        title.to_edge(UP)
        self.play(FadeIn(title))
        items = []
        group = VGroup()
        for i, line in enumerate(items[:6]):
            t = Text(line, font_size=26, color=YELLOW if i == 0 else WHITE)
            group.add(t)
        if len(group):
            group.arrange(DOWN, aligned_edge=LEFT, buff=0.35)
            group.next_to(title, DOWN, buff=0.6)
            group.set_x(0)
            for t in group:
                self.play(FadeIn(t, shift=UP*0.2), run_time=0.5)
                self.wait(max(0.4, 5.0 / max(2, len(group)+1)))
        else:
            self.wait(5.0)
        self.wait(0.5)