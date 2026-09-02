from manim import *
import numpy as np

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = "#0b1220"
        title = Text('Quadratic graph', font_size=32, color=WHITE).to_edge(UP)
        notice = Text('Notice how the graph changes.', font_size=20, color=YELLOW)
        notice.next_to(title, DOWN, buff=0.25)
        if notice.width > 12:
            notice.scale_to_fit_width(12)
        axes = Axes(
            x_range=[-5.0, 5.0, 1],
            y_range=[-5.0, 5.0, 1],
            x_length=9,
            y_length=5.2,
            tips=False,
            axis_config={"color": GREY_B, "include_numbers": False},
        )
        axes.next_to(notice, DOWN, buff=0.35)
        self.play(FadeIn(title), FadeIn(notice), Create(axes), run_time=0.8)

        series = [{'expr': 'x**2 - 5*x + 6', 'label': 'curve', 'color': 'YELLOW'}]
        graphs = []
        labels = VGroup()
        for i, s in enumerate(series):
            expr = s["expr"]
            color = globals().get(s["color"], YELLOW)
            def _fn(x, e=expr):
                return float(eval(e, {"__builtins__": {}}, {"x": x, "np": np}))
            try:
                g = axes.plot(_fn, color=color, stroke_width=4)
            except Exception:
                continue
            lab = Text(s["label"], font_size=18, color=color)
            graphs.append(g)
            labels.add(lab)
            # Ghost previous overlays at lower opacity
            for prev in graphs[:-1]:
                prev.set_stroke(opacity=0.35)
            self.play(Create(g), run_time=0.7)
            self.wait(0.625)

        if len(labels):
            labels.arrange(RIGHT, buff=0.4)
            labels.next_to(axes, DOWN, buff=0.2)
            self.play(FadeIn(labels), run_time=0.4)

        # Parameter sweep: animate successive values of the family
        sweep_family = ''
        sweep_param = 'a'
        sweep_values = []
        if sweep_family and sweep_values:
            def make_fn(val):
                def _fn(x, v=val, fam=sweep_family, p=sweep_param):
                    env = {"x": x, "np": np, p: v}
                    return float(eval(fam, {"__builtins__": {}}, env))
                return _fn
            param_label = Text(f"{sweep_param} = {sweep_values[0]:g}", font_size=22, color=ORANGE)
            param_label.to_corner(UR).shift(LEFT * 0.3 + DOWN * 0.8)
            self.play(FadeIn(param_label))
            active = None
            for vi, val in enumerate(sweep_values):
                try:
                    g = axes.plot(make_fn(val), color=ORANGE, stroke_width=5)
                except Exception:
                    continue
                new_lab = Text(f"{sweep_param} = {val:g}", font_size=22, color=ORANGE)
                new_lab.move_to(param_label)
                if active is None:
                    self.play(Create(g), Transform(param_label, new_lab), run_time=0.7)
                else:
                    self.play(
                        ReplacementTransform(active, g),
                        Transform(param_label, new_lab),
                        run_time=0.8,
                    )
                active = g
                self.wait(1.25)

        # Highlights (vertex / intercepts)
        highlights = []
        for h in highlights:
            try:
                dot = Dot(axes.coords_to_point(h["point"][0], h["point"][1]), color=WHITE)
                lab = Text(h["label"], font_size=18, color=WHITE).next_to(dot, UP, buff=0.15)
                self.play(FadeIn(dot), FadeIn(lab), run_time=0.4)
            except Exception:
                pass

        self.wait(0.6)