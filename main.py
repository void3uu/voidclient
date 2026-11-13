import json
from queue import Empty, SimpleQueue
from threading import Thread
import re
import tkinter as tk
import winsound
import subprocess
import sys
from updates import check_update, install_update
from pathlib import Path
from tkinter import messagebox, simpledialog
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from chrome import BG, Button

DEMO = '-- VoidClient demo\nprint("Hello, World!")\nwait(2)\nprint("Done.")'
LIMIT = 16384
STORE = Path.home() / ".voidclient-scripts.json"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def import_raw(value):
    value = value.strip()
    wrapper = re.fullmatch(r"""loadstring\(\s*(["'])(https://[^\s"']+)\1\s*\)(?:\(\))?""", value)
    url = wrapper[2] if wrapper else value
    parts = urlsplit(url)
    if (parts.scheme, parts.netloc) != ("https", "raw.githubusercontent.com") or len(parts.path.split("/")) < 5:
        raise ValueError("Use a public GitHub Raw file URL.")
    with build_opener(NoRedirect()).open(url, timeout=5) as response:
        content = response.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise ValueError("The file exceeds 16 KB.")
    return content.decode("utf-8")


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
        root.iconphoto(True, self.icon)
        self.taskbar_refresh_done = False
        root.after_idle(self.show_taskbar_icon)
        self.scripts = {}
        try:
            data = json.loads(STORE.read_text(encoding="utf-8"))
            self.scripts = {name: entry for name, entry in data.items()
                            if isinstance(entry.get("source"), str) and isinstance(entry.get("favorite"), bool)}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            messagebox.showerror("Saved scripts", "The saved scripts file could not be read.")
        window = tk.Frame(root, bg=BG, highlightthickness=1, highlightbackground="#262626")
        self.window = window
        header = tk.Frame(window, bg=BG, height=44)
        header.pack(fill="x")
        header.pack_propagate(False)
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
        body = tk.Frame(window, bg=BG)
        body.pack(fill="both", expand=True)
        nav = tk.Frame(body, bg=BG, width=56)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        self.editor_tab = Button(nav, "</>", self.show_editor)
        self.editor_tab.pack(pady=(8, 9))
        self.library_tab = Button(nav, "☷", self.show_library)
        self.library_tab.pack(pady=(12, 0))
        tk.Frame(body, bg="#333333", width=1).pack(side="left", fill="y")
        self.editor = tk.Frame(body, bg=BG)
        self.library = tk.Frame(body, bg=BG)
        footer = tk.Frame(self.editor, bg=BG)
        footer.pack(side="bottom", fill="x", padx=5, pady=5)
        Button(footer, "Run", self.run, primary=True).pack(side="left")
        Button(footer, "Import", self.load).pack(side="left", padx=5)
        Button(footer, "Save", self.save).pack(side="left")
        self.lines = tk.Text(self.editor, width=5, bg=BG, fg="#77848f", bd=0,
                             font=("Consolas", 10), padx=8, pady=10, state="disabled")
        self.lines.pack(side="left", fill="y")
        self.text = tk.Text(self.editor, bg=BG, fg="#a5d2ff", insertbackground="white",
                            bd=0, font=("Consolas", 10), padx=10, pady=10, wrap="none",
                            undo=True, yscrollcommand=self.sync_lines)
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("keyword", foreground="#55a5ee")
        self.text.tag_configure("string", foreground="#ec9873")
        self.text.tag_configure("comment", foreground="#73818c")
        self.refresh_job = None
        self.text.bind("<<Modified>>", self.schedule_refresh)
        self.replace(DEMO)
        self.show_editor()
        self.check_startup_update()

    def close_app(self):
        if not getattr(self, "installing", False):
            self.root.destroy()

    def check_startup_update(self):
        screen = tk.Frame(self.root, bg=BG)
        screen.pack(fill="both", expand=True)
        exit_button = Button(screen, "×", self.root.destroy)
        exit_button.pack(anchor="ne", padx=5, pady=5)
        content = tk.Frame(screen, bg=BG)
        content.place(relx=0.5, rely=0.5, anchor="center")
        heading = tk.Label(content, text="Checking for updates…", bg=BG, fg="white",
                           font=("Segoe UI", 17, "bold"))
        heading.pack(pady=(0, 14))
        spinner = tk.Canvas(content, width=48, height=48, bg=BG, highlightthickness=0)
        spinner.create_oval(6, 6, 42, 42, outline="#303030", width=3)
        arc = spinner.create_arc(6, 6, 42, 42, start=0, extent=94,
                                 style="arc", outline="white", width=3)
        angle = 0
        animation = None

        def spin():
            nonlocal angle, animation
            angle = (angle - 11) % 360
            spinner.itemconfigure(arc, start=angle)
            animation = self.root.after(20, spin)

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
            heading.configure(text="New Update")

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
                    heading.configure(text="New Update")
                    button.pack()
                    messagebox.showerror("Update failed", error, parent=self.root)

                Thread(target=apply_update, daemon=True).start()
                self.root.after(50, finish)

            button = Button(content, "Install Update", install, primary=True)
            button.configure(width=164, height=44)
            button.pack()

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

    def button(self, parent, label, command, primary=False):
        return tk.Button(parent, text=label, command=command, relief="flat",
                         bg="white" if primary else BG, fg="#111111" if primary else "#eeeeee",
                         activebackground="#363636", activeforeground="white",
                         font=("Segoe UI", 10), padx=12, pady=7, cursor="hand2")

    def sync_lines(self, first, _last):
        self.lines.yview_moveto(first)

    def schedule_refresh(self, _event=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self.refresh_job is not None:
            self.root.after_cancel(self.refresh_job)
        self.refresh_job = self.root.after(65, self.refresh)

    def refresh(self):
        self.refresh_job = None
        source = self.source()
        lines = source[:LIMIT].split("\n")
        self.lines.configure(state="normal")
        self.lines.delete("1.0", "end")
        self.lines.insert("1.0", "\n".join(f"{i:>3}" for i in range(1, len(lines) + 1)))
        self.lines.configure(state="disabled")
        self.sync_lines(self.text.yview()[0], None)
        for tag in ("keyword", "string", "comment"):
            self.text.tag_remove(tag, "1.0", "end")
        for index, line in enumerate(lines, 1):
            if line.lstrip().startswith("--"):
                self.text.tag_add("comment", f"{index}.0", f"{index}.end")
                continue
            for match in re.finditer(r'"(?:[^"\\]|\\.)*"|\b(?:print|wait)\b', line):
                tag = "string" if match[0].startswith('"') else "keyword"
                self.text.tag_add(tag, f"{index}.{match.start()}", f"{index}.{match.end()}")

    def source(self):
        return self.text.get("1.0", "end-1c")

    def replace(self, source):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", source)
        self.text.edit_reset()
        self.text.edit_modified(False)
        if self.refresh_job is not None:
            self.root.after_cancel(self.refresh_job)
        self.refresh()

    def show_editor(self):
        self.editor_tab.state(active=True)
        self.library_tab.state(active=False)
        self.library.pack_forget()
        self.editor.pack(fill="both", expand=True)
        self.text.focus_set()

    def show_library(self):
        self.editor_tab.state(active=False)
        self.library_tab.state(active=True)
        self.editor.pack_forget()
        self.library.pack(fill="both", expand=True)
        for child in self.library.winfo_children():
            child.destroy()
        top = tk.Frame(self.library, bg=BG)
        top.pack(fill="x", padx=20, pady=(18, 12))
        tk.Label(top, text="Saved scripts", bg=BG, fg="white",
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        count = len(self.scripts)
        tk.Label(top, text=f"{count} saved", bg=BG, fg="#9b9b9b",
                 font=("Segoe UI", 10)).pack(side="right")

        actions = tk.Frame(self.library, bg=BG)
        actions.pack(side="bottom", fill="x", padx=16, pady=(4, 12))
        Button(actions, "Editor", self.show_editor).pack(side="left")
        Button(actions, "Import", self.load).pack(side="left", padx=5)

        self.library_list = tk.Listbox(
            self.library, bg="#191919", fg="#e8e8e8", selectbackground="#303030",
            selectforeground="white", font=("Segoe UI", 11), activestyle="none",
            highlightthickness=1, highlightbackground="#303030", relief="flat",
            exportselection=False,
        )
        self.library_list.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        names = sorted(self.scripts, key=lambda name: (not self.scripts[name]["favorite"], name.casefold()))
        for name in names:
            prefix = "★" if self.scripts[name]["favorite"] else "☆"
            self.library_list.insert("end", f"  {prefix}   {name}")

        def selected_action(action):
            selection = self.library_list.curselection()
            if selection:
                action(names[selection[0]])

        if names:
            self.library_list.selection_set(0)
            self.library_list.bind("<Double-Button-1>", lambda _: selected_action(self.open_script))
            self.library_list.bind("<Return>", lambda _: selected_action(self.open_script))
            Button(actions, "Favorite", lambda: selected_action(self.favorite)).pack(side="right")
            Button(actions, "Open", lambda: selected_action(self.open_script), primary=True).pack(side="right", padx=5)
        else:
            self.library_list.insert("end", "  Save a script from the editor to add it here.")
            self.library_list.configure(state="disabled")

    def persist(self, scripts):
        temporary = STORE.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(scripts, ensure_ascii=False), encoding="utf-8")
            temporary.replace(STORE)
        except OSError as error:
            messagebox.showerror("Saved scripts", str(error))
            return False
        self.scripts = scripts
        return True

    def favorite(self, name):
        entry = self.scripts[name]
        if self.persist({**self.scripts, name: {**entry, "favorite": not entry["favorite"]}}):
            self.show_library()

    def open_script(self, name):
        self.replace(self.scripts[name]["source"])
        self.show_editor()

    def save(self):
        name = simpledialog.askstring("Save script", "Script name", parent=self.root)
        if not name or not name.strip():
            return
        name = name.strip()
        existing = self.scripts.get(name)
        if existing and not messagebox.askyesno("Save script", f"Replace {name}?"):
            return
        self.persist({**self.scripts, name: {"source": self.source(),
                                            "favorite": existing["favorite"] if existing else False}})

    def load(self):
        value = simpledialog.askstring("Import from GitHub", "GitHub Raw URL or loadstring command", parent=self.root)
        if not value:
            return
        self.import_script(value)

    def import_script(self, value):
        if getattr(self, "import_pending", False):
            return
        self.import_pending = True
        results = SimpleQueue()

        def download():
            try:
                results.put((import_raw(value), None))
            except Exception as error:
                results.put((None, str(error)))

        def receive():
            try:
                source, error = results.get_nowait()
            except Empty:
                self.root.after(50, receive)
                return
            self.import_pending = False
            if error is not None:
                messagebox.showerror("Import failed", error, parent=self.root)
            else:
                self.replace(source)
                self.show_editor()

        Thread(target=download, daemon=True).start()
        self.root.after(50, receive)

    def run(self):
        source = self.source()
        if source.strip().startswith("loadstring("):
            self.import_script(source.strip())
            return
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
