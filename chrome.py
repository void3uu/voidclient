import tkinter as tk

BG = "#151515"


class Button(tk.Canvas):
    def __init__(self, parent, label, command, primary=False):
        self.label, self.command, self.primary = label, command, primary
        self.hover = self.pressed = self.active = False
        self.last_draw = None
        icon = label in ("×", "−", "</>", "☷")
        super().__init__(parent, width=36 if icon else 83, height=39, bg=BG,
                         highlightthickness=0, takefocus=True, cursor="hand2")
        for event, callback in (
            ("<Configure>", self.draw), ("<FocusIn>", self.draw), ("<FocusOut>", self.draw),
            ("<Enter>", lambda _: self.state(hover=True)),
            ("<Leave>", lambda _: self.state(hover=False)),
            ("<ButtonPress-1>", lambda _: self.press()),
            ("<ButtonRelease-1>", self.release),
            ("<Return>", lambda _: command()), ("<space>", lambda _: command()),
        ):
            self.bind(event, callback)

    def state(self, **changes):
        for key, value in changes.items():
            setattr(self, key, value)
        self.draw()

    def press(self):
        self.focus_set()
        self.state(pressed=True)

    def release(self, event):
        invoke = self.pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self.state(pressed=False)
        if invoke:
            self.command()

    def draw(self, _event=None):
        w, h = self.winfo_width(), self.winfo_height()
        focused = self.focus_get() is self
        appearance = (w, h, focused, self.active, self.hover, self.pressed)
        if appearance == self.last_draw or min(w, h) < 3:
            return
        self.last_draw = appearance
        self.delete("all")
        x, y = w / 2, h / 2
        label = self.label
        icon = label in ("×", "−", "</>", "☷")
        fill = "#c9c9c9" if self.pressed else "#eeeeee" if self.hover else "#ffffff"
        ink = "#131313" if self.primary else "#565656"
        if self.hover or self.active or not icon:
            ink = "#f0f0f0" if not self.primary else ink
        if not self.primary:
            fill = "#1b1b1b" if not icon else BG
            if self.active or self.hover:
                fill = "#303030" if self.hover else "#242424"
            if self.pressed:
                fill = "#333333"
            if label == "×" and self.hover:
                fill = "#a52d36"
        if fill != BG:
            rounded(self, 1, 1, w - 1, h - 1, 6, fill)
        if focused:
            self.create_rectangle(2, 2, w - 2, h - 2, outline="#888888")

        def line(*coords):
            points = [value + (x if i % 2 == 0 else y) for i, value in enumerate(coords)]
            self.create_line(*points, fill=ink, width=2, capstyle="round", joinstyle="round")

        if label == "×":
            line(-5, -5, 5, 5)
            line(-5, 5, 5, -5)
        elif label == "−":
            line(-6, 0, 6, 0)
        elif label == "</>":
            line(-5, -4, -9, 0, -5, 4)
            line(5, -4, 9, 0, 5, 4)
            line(2, -6, -2, 6)
        elif label == "☷":
            for dy in (-5, 0, 5):
                line(-8, dy, -7, dy)
                line(-3, dy, 8, dy)
        elif label == "Run":
            self.create_polygon(x - 24, y - 6, x - 24, y + 6, x - 13, y,
                                fill="", outline=ink, width=1.5)
            self.create_text(x + 11, y, text="Run", fill=ink, font=("Segoe UI", 10, "bold"))
        else:
            self.create_text(x, y, text=label, fill=ink, font=("Segoe UI", 10))


def rounded(canvas, x, y, right, bottom, r, fill, tags=()):
    canvas.create_polygon(x+r,y, right-r,y, right,y, right,y+r, right,bottom-r,
                          right,bottom, right-r,bottom, x+r,bottom, x,bottom, x,bottom-r,
                          x,y+r, x,y, fill=fill, smooth=True, splinesteps=16, tags=tags)
