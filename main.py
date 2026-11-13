import json
import os
import base64
import ctypes
from ctypes import wintypes
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from queue import Empty, SimpleQueue
from threading import Thread
import re
import tkinter as tk
import subprocess
import sys
from updates import check_update, install_update
from pathlib import Path
from tkinter import messagebox

from chrome import BG, Button

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


def place_id(value):
    if re.fullmatch(r"[1-9][0-9]{0,18}", value):
        return value
    url = urlsplit(value)
    match = re.match(r"/games/([1-9][0-9]{0,18})(?:/|$)", url.path)
    if url.scheme == "https" and url.netloc.lower() in ("roblox.com", "www.roblox.com") and match:
        return match[1]
    raise ValueError("Enter a Roblox experience URL or place ID.")


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
        self.roblox_tab = Button(rail, "Roblox Stuff", lambda: self.show_page(self.roblox))
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
                self.experience.focus_set()
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
            self.experience.focus_set()
        else:
            self.attach_tab.focus_set()

    def build_companion(self):
        content = tk.Frame(self.roblox, bg="#111111")
        content.pack(fill="both", expand=True, padx=26, pady=20)
        tk.Label(content, text="Roblox Stuff", bg="#111111", fg="white",
                 font=("Segoe UI Semibold", 23)).pack(anchor="w")
        def field(parent, label, button, action):
            tk.Label(parent, text=label, bg="#111111", fg="#aaa").pack(anchor="w", pady=(5, 2))
            row = tk.Frame(parent, bg="#111111")
            row.pack(fill="x")
            entry = tk.Entry(row, bg="#222222", fg="white", insertbackground="white",
                             relief="flat", font=("Segoe UI", 11))
            entry.pack(side="left", fill="both", expand=True, padx=(0, 8))
            entry.bind("<Return>", lambda _: action())
            Button(row, button, action, primary=True).pack(side="right")
            return entry

        self.experience = field(content, "Experience link or place ID", "Server Hop", self.server_hop)
        self.server_list = tk.Listbox(content, height=4, bg="#1b1b1b", fg="white",
                                      selectbackground="#383838", relief="flat", exportselection=False)
        self.server_list.pack(fill="both", expand=True, pady=8)
        footer = tk.Frame(content, bg="#111111")
        footer.pack(fill="x")
        self.server_status = tk.Label(footer, bg="#111111", fg="#aaa", text="")
        self.server_status.pack(side="left")
        Button(footer, "Join Selected", self.join_server).pack(side="right")
        self.server_list.bind("<Double-Button-1>", lambda _: self.join_server())
        self.servers = []
        self.attached = tk.BooleanVar()
        tk.Label(self.attach, text="Attach Stuff", bg="#111111", fg="white",
                 font=("Segoe UI Semibold", 23)).pack(anchor="w", padx=26, pady=(22, 12))
        attach_form = tk.Frame(self.attach, bg="#111111")
        attach_form.pack(fill="x", padx=26)
        self.username = field(attach_form, "Your Roblox username", "Attach Roblox", self.attach_roblox)
        profile = tk.Frame(self.attach, bg="#111111")
        profile.pack(fill="x", padx=26, pady=8)
        self.avatar = tk.Label(profile, bg="#111111")
        self.avatar.pack(side="left", padx=(0, 10))
        self.profile_status = tk.Label(profile, text="Load your public profile", bg="#111111", fg="#ddd")
        self.profile_status.pack(side="left")

        self.attach_status = tk.Label(self.attach, bg="#111111", fg="#aaa", text="Detached")
        self.attach_status.pack(anchor="w", padx=26, pady=12)
        self.attach_job = None
        self.profile_id = None
        self.current_game = None
        self.presence_status = tk.Label(self.roblox, bg="#111111", fg="#aaa")
        self.presence_status.pack(anchor="w", padx=26, pady=(0, 8))
        self.attached.set(True)
        self.track_roblox()
        self.refresh_presence()

    def refresh_presence(self):
        user_id = self.profile_id
        if user_id is not None and self.game_window:
            def work():
                data = json.loads(fetch("https://presence.roblox.com/v1/presence/users",
                                        {"userIds": [user_id]}))
                return next(iter(data["userPresences"]), {})

            def done(presence):
                if self.profile_id != user_id or not self.game_window:
                    return
                place = presence.get("placeId")
                self.current_game = str(place) if presence.get("userPresenceType") == 2 and isinstance(place, int) and place > 0 else None
                title = presence.get("lastLocation") or f"Place {place}"
                self.presence_status.configure(text=f"Current game: {title}" if self.current_game else
                                               "Current game unavailable. Enter a place ID or link.")
                if self.current_game:
                    self.experience.delete(0, "end")
                    self.experience.insert(0, self.current_game)

            self.background(self.presence_status, work, done)
        self.root.after(15000, self.refresh_presence)

    def attach_roblox(self):
        self.load_profile()

    def server_hop(self):
        self.load_servers(hop=True)

    def track_roblox(self):
        if self.attach_job is not None:
            self.root.after_cancel(self.attach_job)
            self.attach_job = None
        if not self.attached.get():
            self.root.attributes("-topmost", False)
            self.attach_status.configure(text="Detached")
            return
        game, foreground = roblox_window()
        self.game_window = game
        self.root.attributes("-topmost", bool(game and (
            game == foreground or self.root.focus_displayof() is not None)))
        self.attach_status.configure(text="Roblox window linked" if game else "Waiting for Roblox…")
        self.attach_job = self.root.after(350, self.track_roblox)

    def background(self, status, work, done):
        if getattr(status, "busy", False):
            return
        status.busy = True
        status.configure(text="Loading…")
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

    def load_profile(self):
        name = self.username.get().strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{1,20}", name):
            self.profile_status.configure(text="Enter a Roblox username.")
            return

        def work():
            profiles = json.loads(fetch("https://users.roblox.com/v1/usernames/users",
                                        {"usernames": [name], "excludeBannedUsers": True}))["data"]
            if not profiles:
                raise ValueError("Username not found.")
            profile = profiles[0]
            try:
                query = urlencode({"userIds": int(profile["id"]), "size": "60x60", "format": "Png"})
                thumbnails = json.loads(fetch(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?{query}"))
                for item in thumbnails["data"]:
                    url = item.get("imageUrl") or ""
                    parts = urlsplit(url)
                    if parts.scheme == "https" and re.fullmatch(r"tr\.rbxcdn\.com", parts.netloc):
                        return profile, fetch(url)
            except (OSError, ValueError, KeyError):
                pass
            return profile, None

        def done(result):
            profile, image = result
            self.profile_id = int(profile["id"])
            self.avatar.image = None
            try:
                if image:
                    self.avatar.image = tk.PhotoImage(data=base64.b64encode(image), format="png")
            except tk.TclError:
                pass
            self.avatar.configure(image=self.avatar.image or "")
            self.profile_status.configure(text=f"{profile['displayName']}  ·  @{profile['name']}")

        self.background(self.profile_status, work, done)

    def load_servers(self, hop=False):
        try:
            place = place_id(self.experience.get().strip())
        except ValueError as error:
            self.server_status.configure(text=str(error))
            return

        def work():
            url = f"https://games.roblox.com/v1/games/{place}/servers/Public?excludeFullGames=true&limit=25"
            return json.loads(fetch(url))["data"]

        def done(data):
            self.servers = [(place, item["id"]) for item in data
                            if re.fullmatch(r"[a-fA-F0-9-]{36}", item.get("id", ""))
                            and isinstance(item.get("playing"), int)
                            and isinstance(item.get("maxPlayers"), int)
                            and item["playing"] < item["maxPlayers"]]
            self.server_list.delete(0, "end")
            for index, (listed_place, server) in enumerate(self.servers, 1):
                item = next(item for item in data if item["id"] == server)
                self.server_list.insert("end", f"Server {index}   ·   {item['playing']}/{item['maxPlayers']} players")
                if (listed_place, server) != self.last_server and not self.server_list.curselection():
                    self.server_list.selection_set(index - 1)
            self.server_status.configure(text=f"{len(self.servers)} public servers found")
            if hop:
                if self.server_list.curselection():
                    self.join_server()
                else:
                    self.server_status.configure(text="No different public server available.")

        self.background(self.server_status, work, done)

    def join_server(self):
        selection = self.server_list.curselection()
        if not selection:
            self.server_status.configure(text="Select a public server first.")
            return
        place, server = self.servers[selection[0]]
        try:
            os.startfile(f"roblox://placeId={place}&gameInstanceId={server}")
        except OSError:
            self.server_status.configure(text="Could not open Roblox. Check that Roblox is installed.")
            return
        self.last_server = (place, server)
        self.server_status.configure(text="Join requested in Roblox.")


if __name__ == "__main__":
    root = tk.Tk()
    VoidClient(root)
    root.mainloop()
