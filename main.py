import json
import winsound
import ctypes
from ctypes import wintypes
from queue import Empty, SimpleQueue
from threading import Thread
import re
import tkinter as tk
import subprocess
import sys
from pathlib import Path
from tkinter import messagebox



import base64
import hashlib
import os
import tempfile
from time import time_ns
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

BG = "#151515"


class Button(tk.Canvas):
    def __init__(self, parent, label, command, primary=False):
        self.label, self.command, self.primary = label, command, primary
        self.hover = self.pressed = self.active = False
        self.last_draw = None
        self.fill = None
        self.animation = None
        icon = label in ("×", "−", "</>", "☷", "⌕", "⚙")
        super().__init__(parent, width=38 if icon else max(86, len(label) * 8 + 22), height=39, bg=BG,
                         highlightthickness=0, takefocus=True, cursor="hand2")
        for event, callback in (
            ("<Configure>", self.draw), ("<FocusIn>", self.draw), ("<FocusOut>", self.draw),
            ("<Enter>", lambda _: self.state(hover=True)),
            ("<Leave>", lambda _: self.state(hover=False)),
            ("<ButtonPress-1>", lambda _: self.press()),
            ("<ButtonRelease-1>", self.release),
            ("<Return>", self.activate), ("<space>", self.activate),
            ("<Destroy>", self.cancel_animation),
        ):
            self.bind(event, callback)

    def state(self, **changes):
        for key, value in changes.items():
            setattr(self, key, value)
        self.draw()

    def activate(self, _event=None):
        if str(self.cget("state")) != "disabled":
            self.command()
        return "break"

    def cancel_animation(self, _event=None):
        if self.animation is not None:
            self.after_cancel(self.animation)
            self.animation = None

    def fade(self, start, end, step=1):
        weight = 1 - (1 - step / 6) ** 2
        self.fill = "#" + "".join(f"{round(a + (b - a) * weight):02x}" for a, b in zip(start, end))
        self.itemconfigure("surface", fill=self.fill)
        self.animation = self.after(15, self.fade, start, end, step + 1) if step < 6 else None

    def press(self):
        self.focus_set()
        self.state(pressed=True)

    def release(self, event):
        invoke = self.pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self.state(pressed=False)
        if invoke:
            self.activate()

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
        icon = label in ("×", "−", "</>", "☷", "⌕", "⚙")
        fill = "#c9c9c9" if self.pressed else "#eeeeee" if self.hover else "#ffffff"
        ink = "#131313" if self.primary else "#888888"
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
        self.cancel_animation()
        previous = self.fill or fill
        border = "#a4a4a4" if focused else "#373737" if self.active or not icon else BG
        rounded(self, 0, 0, w, h, 8, border)
        rounded(self, 1, 1, w - 1, h - 1, 7, previous, tags="surface")
        if previous != fill:
            channels = lambda color: tuple(value // 257 for value in self.winfo_rgb(color))
            self.fade(channels(previous), channels(fill))
        else:
            self.fill = fill
        if self.active and icon:
            self.create_line(3, y - 5, 3, y + 5, fill="#d6d6d6", width=2, capstyle="round")

        def line(*coords):
            points = [value + (x if i % 2 == 0 else y) for i, value in enumerate(coords)]
            self.create_line(*points, fill=ink, width=2, capstyle="round", joinstyle="round")

        if label == "×":
            line(-5, -5, 5, 5)
            line(-5, 5, 5, -5)
        elif label == "−":
            line(-6, 0, 6, 0)
        elif label == "⚙":
            self.create_text(x, y, text=label, fill=ink, font=("Segoe UI Symbol", 15))
        elif label == "⌕":
            self.create_oval(x-8, y-8, x+3, y+3, outline=ink, width=2)
            line(2, 2, 8, 8)
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
            self.create_text(x + 11, y, text="Run", fill=ink, font=("Segoe UI Semibold", 10))
        else:
            self.create_text(x, y, text=label, fill=ink, font=("Segoe UI Semibold", 10))


def rounded(canvas, x, y, right, bottom, r, fill, tags=()):
    canvas.create_polygon(x+r,y, right-r,y, right,y, right,y+r, right,bottom-r,
                          right,bottom, right-r,bottom, x+r,bottom, x,bottom, x,bottom-r,
                          x,y+r, x,y, fill=fill, smooth=True, splinesteps=16, tags=tags)
BUILD = 12
REPOSITORY = "void3uu/voidclient"


def check_update():
    if getattr(sys, "frozen", False):
        return packaged_release()
    return newer_source()


def newer_source():
    url = f"https://raw.githubusercontent.com/{REPOSITORY}/main/main.py?check={time_ns()}"
    data = fetch(url)
    versions = re.findall(rb"^BUILD = ([0-9]{1,9})\r?$", data, re.MULTILINE)
    if len(versions) == 1 and int(versions[0]) > BUILD:
        return data
    return None


def install_update():
    if getattr(sys, "frozen", False):
        install_packaged_update()
        return
    data = newer_source()
    if not data:
        raise ValueError("A newer source build is unavailable.")
    target = Path(__file__).resolve()
    compile(data, str(target), "exec")
    with tempfile.TemporaryDirectory(dir=target.parent) as directory:
        staged = Path(directory) / target.name
        staged.write_bytes(data)
        staged.replace(target)


def packaged_release():
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
                      headers={"User-Agent": "VoidClient", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=8) as response:
        release = json.loads(response.read(262145))
    tag = re.fullmatch(r"voidclient-(\d{1,9})", release.get("tag_name", ""))
    if not tag or int(tag[1]) <= BUILD:
        return None
    for asset in release.get("assets", []):
        digest = asset.get("digest") or ""
        size = asset.get("size", 0)
        if (asset.get("name") == "voidclient.exe"
                and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                and 0 < size <= 80 * 1024 * 1024):
            url = f"https://github.com/{REPOSITORY}/releases/download/{tag[0]}/voidclient.exe"
            return url, digest[7:], size
    return None


def install_packaged_update():
    release = packaged_release()
    if not release:
        raise ValueError("No newer packaged build is available.")
    url, digest, size = release
    target = Path(sys.executable).resolve()
    fd, staged = tempfile.mkstemp(prefix="voidclient-update-", suffix=".exe", dir=target.parent)
    try:
        checksum = hashlib.sha256()
        with os.fdopen(fd, "wb") as output, urlopen(url, timeout=15) as response:
            remaining = size
            while remaining:
                chunk = response.read(min(remaining, 65536))
                if not chunk:
                    break
                output.write(chunk)
                checksum.update(chunk)
                remaining -= len(chunk)
            if remaining or response.read(1) or checksum.hexdigest() != digest:
                raise ValueError("The update download did not match the release checksum.")

        environment = dict(os.environ, VOIDCLIENT_TARGET=str(target), VOIDCLIENT_STAGE=staged,
                           PYINSTALLER_RESET_ENVIRONMENT="1")
        shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        subprocess.Popen(
            [str(shell), "-NoProfile", "-NonInteractive", "-Command", """
$target = $env:VOIDCLIENT_TARGET
$stage = $env:VOIDCLIENT_STAGE
$backup = $stage + '.bak'
$replaced = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    try {
        [IO.File]::Replace($stage, $target, $backup)
        $replaced = $true
        break
    } catch [IO.IOException] {
        Start-Sleep -Milliseconds 250
    }
}
if ($replaced) {
    try {
        Start-Process -FilePath $target -ErrorAction Stop
        [IO.File]::Delete($backup)
    } catch {
        if ([IO.File]::Exists($backup)) {
            [IO.File]::Replace($backup, $target, $null)
            Start-Process -FilePath $target
        }
    }
} else {
    [IO.File]::Delete($stage)
}
"""], env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        Path(staged).unlink(missing_ok=True)
        raise


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(url, payload=None):
    request = Request(url, data=json.dumps(payload).encode() if payload else None,
                      headers={"Content-Type": "application/json", "User-Agent": "VoidClient"})
    with build_opener(NoRedirect()).open(request, timeout=8) as response:
        data = response.read(1048577)
    if len(data) > 1048576:
        raise ValueError("Roblox response exceeded the size limit.")
    return data


def player_activity():
    directory = Path(os.environ["LOCALAPPDATA"]) / "Roblox" / "logs"
    files = list(directory.glob("*_Player_*.log"))
    if not files:
        return None, None, None
    newest = max(files, key=lambda path: path.stat().st_ctime_ns)
    with newest.open("rb") as log:
        length = log.seek(0, 2)
        log.seek(max(0, length - 2 * 1024 * 1024))
        lines = log.read(2 * 1024 * 1024).decode("utf-8", errors="replace").splitlines()
    user = place = job = None
    for line in lines:
        if "[FLog::GameJoinLoadTime] Report game_join_loadtime:" in line:
            match = re.search(r"\buserid:([1-9][0-9]{0,18})\b", line)
            if match:
                user = int(match[1])
        if "[FLog::" in line:
            joined = re.search(r"Joining game '([0-9a-fA-F-]{36})' place ([1-9][0-9]{0,18})\b", line)
            if joined:
                job, place = joined.groups()
            elif "Time to disconnect replication data" in line or "leaveUGCGameInternal" in line:
                place = job = None
    return user, place, job



LIMIT = 16384

def parse(source):
    if len(source.encode()) > LIMIT:
        raise ValueError("Scripts must be 16 KB or smaller.")
    steps = []
    total = 0
    for number, line in enumerate(source.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        if line == "sound_button()":
            steps.append(None)
            continue
        match = re.fullmatch(r'print\(("(?:[^"\\]|\\.)*")\)', line)
        if match:
            steps.append(json.loads(match[1]))
            continue
        match = re.fullmatch(r"wait\((\d{1,2}(?:\.\d{1,3})?)\)", line)
        if match:
            delay = round(float(match[1]) * 1000)
            total += delay
            if total <= 30000:
                steps.append(delay)
                continue
        raise ValueError(f'Line {number}: use print("text"), sound_button(), or wait(seconds), with at most 30 seconds of total waits.')
    return steps


def roblox_window():
    user32 = ctypes.windll.user32
    foreground = user32.GetForegroundWindow
    foreground.restype = wintypes.HWND
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    candidates = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        title = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, title, len(title))
        if user32.IsWindowVisible(hwnd) and title.value == "Roblox":
            candidates.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return (candidates[0] if candidates else None), foreground()


class VoidClient:
    def __init__(self, root):
        self.root = root
        root.title("voidclient")
        root.geometry("793x491")
        root.overrideredirect(True)
        root.bind("<Map>", self.restore_chrome)
        root.bind("<Alt-F4>", lambda _: self.close_app())
        root.minsize(570, 360)
        root.configure(bg="#0e0e10")
        self.icon = tk.PhotoImage(width=32, height=32)
        self.icon.put("#151515", to=(0, 0, 32, 32))
        for i in range(9):
            self.icon.put("#ffffff", to=(7+i, 7+i, 10+i, 10+i))
            self.icon.put("#ffffff", to=(23-i, 7+i, 26-i, 10+i))
        for rect in ((7, 7, 15, 10), (7, 7, 10, 15), (18, 7, 26, 10),
                     (23, 7, 26, 15), (15, 15, 18, 26)):
            self.icon.put("#ffffff", to=rect)
        icon_path = Path(__file__).with_name("duck.ico")
        if icon_path.is_file():
            root.iconbitmap(default=str(icon_path))
        else:
            root.iconphoto(True, self.icon)
        self.taskbar_refresh_done = False
        root.after_idle(self.show_taskbar_icon)
        window = tk.Frame(root, bg=BG, highlightthickness=1, highlightbackground="#262626")
        self.window = window
        header = tk.Frame(window, bg=BG, height=44)
        header.pack(fill="x")
        header.pack_propagate(False)
        duck_path = Path(__file__).with_name("duck-title.png")
        if duck_path.is_file():
            self.duck_logo = tk.PhotoImage(file=str(duck_path))
            logo = tk.Label(header, image=self.duck_logo, bg=BG, bd=0)
            logo.pack(side="left", padx=(14, 7))
        else:
            logo = tk.Canvas(header, width=26, height=26, bg=BG, highlightthickness=0)
            logo.pack(side="left", padx=(14, 5))
            logo.create_line(13, 22, 13, 13, 6, 6, fill="white", width=2)
            logo.create_line(6, 11, 6, 6, 11, 6, fill="white", width=2)
            logo.create_line(15, 11, 20, 6, 20, 11, fill="white", width=2)
            logo.create_line(15, 6, 20, 6, fill="white", width=2)
        title = tk.Label(header, text="voidclient", bg=BG, fg="white", font=("Segoe UI", 10, "bold"))
        title.pack(side="left")
        for target in (header, title, logo):
            target.bind("<ButtonPress-1>", self.start_drag)
            target.bind("<B1-Motion>", self.drag)
        Button(header, "×", root.destroy).pack(side="right", padx=(0, 3))
        Button(header, "−", self.minimize).pack(side="right")
        tk.Frame(window, bg="#333333", height=1).pack(fill="x")
        body = tk.Frame(window, bg="#111111")
        body.pack(fill="both", expand=True)
        rail = tk.Frame(body, bg=BG, width=132)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        self.roblox_tab = Button(rail, "Executor", lambda: self.show_page(self.roblox))
        self.roblox_tab.pack(pady=(11, 5))
        self.attach_tab = Button(rail, "Attach Stuff", lambda: self.show_page(self.attach))
        self.attach_tab.pack(side="bottom", pady=10)
        tk.Frame(body, bg="#2a2a2a", width=1).pack(side="left", fill="y")
        pages = tk.Frame(body, bg="#111111")
        pages.pack(fill="both", expand=True)
        self.roblox = tk.Frame(pages, bg="#111111")
        self.attach = tk.Frame(pages, bg="#111111")
        self.page = None
        self.transition = None
        self.last_server = None
        self.build_companion()
        self.show_page(self.roblox)
        self.check_startup_update()

    def close_app(self):
        if not getattr(self, "installing", False):
            self.root.destroy()

    def check_startup_update(self):
        screen = tk.Frame(self.root, bg=BG)
        screen.pack(fill="both", expand=True)
        exit_button = Button(screen, "×", self.close_app)
        exit_button.pack(anchor="ne", padx=5, pady=5)
        content = tk.Frame(screen, bg=BG)
        content.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(content, text="voidclient", bg=BG, fg="white",
                 font=("Segoe UI", 25, "bold")).pack(pady=(0, 18))
        heading = tk.Label(content, text="Checking for updates…", bg=BG, fg="#bcbcbc",
                           font=("Segoe UI", 11))
        heading.pack(side="bottom", pady=(12, 0))
        spinner = tk.Canvas(content, width=56, height=56, bg=BG, highlightthickness=0)
        spinner.create_oval(7, 7, 49, 49, outline="#303030", width=3)
        arc = spinner.create_arc(7, 7, 49, 49, start=0, extent=108,
                                 style="arc", outline="white", width=3)
        angle = 0
        animation = None

        def spin():
            nonlocal angle, animation
            angle = (angle - 7) % 360
            spinner.itemconfigure(arc, start=angle)
            animation = self.root.after(16, spin)

        def show_spinner():
            spinner.pack(pady=5)
            spin()

        def hide_spinner():
            self.root.after_cancel(animation)
            spinner.pack_forget()

        show_spinner()
        result = SimpleQueue()

        def worker():
            try:
                result.put(check_update())
            except (OSError, ValueError, AttributeError):
                result.put(None)

        def show_result():
            try:
                url = result.get_nowait()
            except Empty:
                self.root.after(50, show_result)
                return
            hide_spinner()
            if not url:
                screen.destroy()
                self.window.pack(fill="both", expand=True)
                self.text.focus_set()
                return
            def install():
                self.installing = True
                button.pack_forget()
                exit_button.configure(state="disabled")
                heading.configure(text="Installing update…")
                show_spinner()
                installed = SimpleQueue()

                def apply_update():
                    try:
                        install_update()
                        installed.put(None)
                    except Exception as error:
                        installed.put(str(error))

                def finish():
                    try:
                        error = installed.get_nowait()
                    except Empty:
                        self.root.after(50, finish)
                        return
                    self.installing = False
                    hide_spinner()
                    if error is None:
                        if getattr(sys, "frozen", False):
                            self.root.destroy()
                            return
                        try:
                            subprocess.Popen([sys.executable, str(Path(__file__).resolve())])
                        except OSError as restart_error:
                            heading.configure(text="Update installed")
                            exit_button.configure(state="normal")
                            messagebox.showerror("Restart VoidClient", str(restart_error), parent=self.root)
                            return
                        self.root.destroy()
                        return
                    exit_button.configure(state="normal")
                    heading.configure(text="Update failed")
                    button.pack(pady=(10, 0))
                    messagebox.showerror("Update failed", error, parent=self.root)

                Thread(target=apply_update, daemon=True).start()
                self.root.after(50, finish)

            button = Button(content, "Retry Update", install, primary=True)
            button.configure(width=152, height=42)
            install()

        Thread(target=worker, daemon=True).start()
        self.root.after(550, show_result)

    def start_drag(self, event):
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag(self, event):
        x, y = self.drag_offset
        self.root.geometry(f"+{event.x_root - x}+{event.y_root - y}")

    def show_taskbar_icon(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32")
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
        hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
        if hwnd:
            style = user32.GetWindowLongW(hwnd, -20)
            updated = (style | 0x40000) & ~0x80
            if style != updated:
                user32.SetWindowLongW(hwnd, -20, updated)
                if not self.taskbar_refresh_done:
                    self.taskbar_refresh_done = True
                    self.root.withdraw()
                    self.root.deiconify()

    def minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()

    def restore_chrome(self, event):
        if (event.widget is self.root and self.root.state() == "normal"
                and not self.root.overrideredirect()):
            self.root.overrideredirect(True)
            self.root.after_idle(self.show_taskbar_icon)

    def show_page(self, page):
        if page is self.page:
            return
        if self.transition is not None:
            self.root.after_cancel(self.transition)
        if self.page is not None:
            self.page.place_forget()
        self.page = page
        searching = page is self.roblox
        self.roblox_tab.state(active=searching)
        self.attach_tab.state(active=not searching)

        def slide(frame):
            offset = round(12 * (1 - frame / 7) ** 3)
            page.place(x=offset, width=-offset, relwidth=1, relheight=1)
            self.transition = self.root.after(16, slide, frame + 1) if frame < 7 else None

        slide(0)
        if searching:
            self.text.focus_set()
        else:
            self.attach_tab.focus_set()

    def build_companion(self):
        panel = tk.Frame(self.roblox, bg="#111111")
        panel.pack(fill="both", expand=True, padx=20, pady=17)
        tk.Label(panel, text="Script Workspace", bg="#111111", fg="white",
                 font=("Segoe UI Semibold", 20)).pack(anchor="w")
        shell = tk.Frame(panel, bg="#141517", highlightbackground="#303237", highlightthickness=1)
        shell.pack(fill="both", expand=True, pady=(13, 10))
        tab = tk.Frame(shell, bg="#1e2024")
        tab.pack(fill="x")
        tk.Label(tab, text="script.lua", bg="#1e2024", fg="#dedfe3",
                 font=("Segoe UI Semibold", 10)).pack(side="left", padx=13, pady=7)
        tk.Label(tab, text="Local runner", bg="#1e2024", fg="#aeb4c0").pack(side="right", padx=12)
        gutter = tk.Canvas(shell, bg="#18191c", width=42, highlightthickness=0)
        gutter.pack(side="left", fill="y")
        self.text = tk.Text(shell, bg="#141517", fg="#c8dafa", insertbackground="white",
                            selectbackground="#284065", relief="flat", font=("Consolas", 11),
                            undo=True, padx=12, pady=10, wrap="none")
        self.text.pack(fill="both", expand=True)

        def draw_lines(*_):
            gutter.delete("all")
            index = self.text.index("@0,0")
            while info := self.text.dlineinfo(index):
                gutter.create_text(33, info[1] + info[3]/2, anchor="e",
                                   text=index.split(".")[0], fill="#8c919e", font=("Consolas", 10))
                following = self.text.index(f"{index}+1line linestart")
                if self.text.compare(following, "<=", index):
                    break
                index = following

        def edited(_):
            if self.text.edit_modified():
                self.text.edit_modified(False)
                draw_lines()

        self.text.configure(yscrollcommand=draw_lines)
        self.text.bind("<Configure>", draw_lines)
        self.text.bind("<<Modified>>", edited)
        self.text.bind("<Control-Return>", lambda _: (self.run(), "break")[1])
        self.text.insert("1.0", 'print("Hello from VoidClient")')
        footer = tk.Frame(panel, bg="#111111")
        footer.pack(fill="x")
        Button(footer, "Execute", self.run, primary=True).pack(side="left")
        Button(footer, "Link Roblox", self.attach_from_editor).pack(side="left", padx=8)
        tk.Label(footer, text="Ctrl+Enter to execute", bg="#111111", fg="#a0a0a0").pack(side="right")
        self.attach_job = None
        Button(self.attach, "Attach Roblox", self.attach_roblox, primary=True).pack(anchor="w", padx=26, pady=20)
        self.attach_status = tk.Label(self.attach, bg="#111111", fg="#ddd", text="Detached")
        self.attach_status.pack(anchor="w", padx=26)
        self.profile_id = None
        self.avatar = tk.Label(self.attach, bg="#111111")
        self.avatar.pack(anchor="w", padx=26, pady=(12, 0))
        self.profile_status = tk.Label(self.attach, bg="#111111", fg="#ddd")
        self.profile_status.pack(anchor="w", padx=26)
        self.next_profile_check = 0

    def attach_from_editor(self):
        self.show_page(self.attach)
        self.attach_roblox()

    def attach_roblox(self):
        if self.attach_job is None:
            self.track_roblox()

    def track_roblox(self):
        game, foreground = roblox_window()
        self.root.attributes("-topmost", bool(game and game == foreground))
        self.attach_status.configure(text="Roblox Player linked" if game else "Waiting for Roblox Player…")
        if not game:
            self.profile_id = None
            self.avatar.configure(image="")
            self.profile_status.configure(text="")
        elif time_ns() >= self.next_profile_check:
            self.next_profile_check = time_ns() + 5_000_000_000
            self.background(self.profile_status, self.linked_profile, self.show_profile)
        self.attach_job = self.root.after(350, self.track_roblox)

    def linked_profile(self):
        user, _, _ = player_activity()
        if user is None or user == self.profile_id:
            return user, None, None
        profile = json.loads(fetch(f"https://users.roblox.com/v1/users/{user}"))
        image = None
        try:
            query = urlencode({"userIds": user, "size": "60x60", "format": "Png"})
            thumbnails = json.loads(fetch(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?{query}"))
            for item in thumbnails["data"]:
                url = item.get("imageUrl") or ""
                parts = urlsplit(url)
                if parts.scheme == "https" and parts.netloc == "tr.rbxcdn.com":
                    image = fetch(url)
                    break
        except (OSError, ValueError, KeyError):
            pass
        return user, profile, image

    def show_profile(self, result):
        user, profile, image = result
        if not roblox_window()[0]:
            return
        if user is None:
            self.profile_status.configure(text="Join a game in Roblox to detect your profile.")
        elif profile:
            self.profile_id = user
            self.profile_status.configure(text=f"@{profile['name']}  ·  Linked user ID: {user}")
            try:
                self.avatar.image = tk.PhotoImage(data=base64.b64encode(image)) if image else None
            except tk.TclError:
                self.avatar.image = None
            self.avatar.configure(image=self.avatar.image or "")


    def background(self, status, work, done):
        if getattr(status, "busy", False):
            return
        status.busy = True
        results = SimpleQueue()

        def worker():
            try:
                results.put((work(), None))
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
                results.put((None, str(error)))

        def poll():
            try:
                data, error = results.get_nowait()
            except Empty:
                self.root.after(60, poll)
                return
            status.busy = False
            if error:
                status.configure(text=error[:90])
            else:
                done(data)

        Thread(target=worker, daemon=True).start()
        self.root.after(60, poll)

    def source(self):
        return self.text.get("1.0", "end-1c")

    def run(self):
        source = self.source()
        existing = getattr(self, "run_console", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        console = tk.Toplevel(self.root)
        self.run_console = console
        console.title("voidclient · Run")
        console.geometry(f"520x245+{self.root.winfo_x() + 80}+{self.root.winfo_y() + 90}")
        console.overrideredirect(True)
        console.configure(bg=BG)
        console.transient(self.root)
        frame = tk.Frame(console, bg=BG, highlightthickness=1, highlightbackground="#343434")
        frame.pack(fill="both", expand=True)
        header = tk.Frame(frame, bg=BG, height=44)
        header.pack(fill="x")
        header.pack_propagate(False)
        title = tk.Label(header, text="voidclient  /  Output", bg=BG, fg="white",
                         font=("Segoe UI", 10, "bold"))
        title.pack(side="left", padx=18)
        tk.Frame(frame, bg="#343434", height=1).pack(fill="x")
        footer = tk.Frame(frame, bg=BG)
        footer.pack(side="bottom", fill="x", padx=5, pady=5)
        output = tk.Text(frame, bg=BG, fg="#ddd", bd=0, padx=17, pady=12,
                         font=("Consolas", 10), state="disabled", wrap="word")
        timer = None
        console_lines = 0

        def write(line):
            nonlocal console_lines
            console_lines += 1
            if console_lines > 251:
                return
            if console_lines == 251:
                line = "[Output limit reached]"
            output.configure(state="normal")
            output.insert("end", line + "\n")
            output.see("end")
            output.configure(state="disabled")

        def close(_event=None):
            if timer is not None:
                console.after_cancel(timer)
            console.destroy()

        Button(header, "×", close).pack(side="right", padx=(0, 3))

        def begin_drag(event):
            console.drag_offset = (event.x_root - console.winfo_x(), event.y_root - console.winfo_y())

        def drag(event):
            x, y = console.drag_offset
            console.geometry(f"+{event.x_root - x}+{event.y_root - y}")

        for target in (header, title):
            target.bind("<ButtonPress-1>", begin_drag)
            target.bind("<B1-Motion>", drag)

        console.protocol("WM_DELETE_WINDOW", close)
        console.bind("<Alt-F4>", close)
        console.bind("<Escape>", close)
        console.update_idletasks()
        console.focus_set()

        def play_sound():
            try:
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except RuntimeError as error:
                write(f"Sound unavailable: {error}")

        sound_button = Button(footer, "Test Sound", play_sound)
        output.pack(fill="both", expand=True)

        def advance():
            nonlocal timer
            timer = None
            for _ in range(32):
                try:
                    step = next(steps)
                except StopIteration:
                    write("[Finished]")
                    return
                if step is None:
                    sound_button.pack(side="left")
                    continue
                if isinstance(step, int):
                    if step:
                        timer = console.after(step, advance)
                        return
                    continue
                write(step)
            timer = console.after(10, advance)

        try:
            steps = iter(parse(source))
        except ValueError as error:
            write(str(error))
            return
        advance()


if __name__ == "__main__":
    root = tk.Tk()
    VoidClient(root)
    root.mainloop()

