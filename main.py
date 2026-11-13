import base64
import ipaddress
import json
import os
from urllib.parse import urlencode
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


def ipinfo_lookup(address, token):
    credentials = base64.b64encode(f"{token}:".encode()).decode()
    request = Request(f"https://api.ipinfo.io/lite/{address}",
                      headers={"Authorization": f"Basic {credentials}"})
    with build_opener(NoRedirect()).open(request, timeout=8) as response:
        data = json.loads(response.read(16384))
    return "\n".join((
        f"IP: {address}",
        f"Country: {data.get('country') or 'Unknown'}",
        f"Network: {data.get('asn') or 'Unknown'} · {data.get('as_name') or 'Unknown'}",
        "Data by IPinfo",
    ))


def routing_lookup(address):
    query = urlencode({"resource": str(address)})
    url = f"https://stat.ripe.net/data/network-info/data.json?{query}"
    with build_opener(NoRedirect()).open(url, timeout=8) as response:
        payload = json.loads(response.read(65536))
    if payload.get("status") != "ok":
        raise ValueError("RIPEstat lookup failed.")
    data = payload["data"]
    networks = ", ".join(f"AS{asn}" for asn in data.get("asns", []))
    return "\n".join((f"IP: {address}", f"Prefix: {data.get('prefix') or 'Unavailable'}",
                      f"Announcing ASNs: {networks or 'Unavailable'}", "Data by RIPEstat"))


def domain_lookup(domain, token):
    opener = build_opener(NoRedirect())
    sections = []
    for kind, number in (("A", 1), ("AAAA", 28), ("MX", 15), ("NS", 2)):
        query = urlencode({"name": domain, "type": kind})
        try:
            with opener.open(f"https://dns.google/resolve?{query}", timeout=4) as response:
                data = json.loads(response.read(65536))
            status = data.get("Status")
            if status == 3:
                sections.append(f"{kind}: domain not found")
                break
            if status != 0:
                sections.append(f"{kind}: DNS error ({status})")
                continue
            records = [record["data"] for record in data.get("Answer", [])
                       if record.get("type") == number and isinstance(record.get("data"), str)]
            sections.append(f"{kind}: " + (", ".join(records[:4]) or "No records"))
        except (OSError, ValueError):
            sections.append(f"{kind}: lookup unavailable")
    result = ["Google Public DNS", *sections]
    if token:
        request = Request(f"https://www.virustotal.com/api/v3/domains/{domain}",
                          headers={"x-apikey": token})
        try:
            with opener.open(request, timeout=5) as response:
                data = json.loads(response.read(524288))
            stats = data["data"]["attributes"]["last_analysis_stats"]
            result.append(f"VirusTotal: {stats['malicious']} malicious · {stats['suspicious']} suspicious")
        except (OSError, ValueError, KeyError, TypeError):
            result.append("VirusTotal: report unavailable. Check your key and quota.")
    return "\n".join(result)


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
        rail = tk.Frame(body, bg=BG, width=64)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        self.search_tab = Button(rail, "⌕", lambda: self.show_page(self.lookup))
        self.search_tab.pack(pady=(11, 5))
        self.settings_tab = Button(rail, "⚙", lambda: self.show_page(self.settings))
        self.settings_tab.pack(side="bottom", pady=10)
        tk.Frame(body, bg="#2a2a2a", width=1).pack(side="left", fill="y")
        pages = tk.Frame(body, bg="#111111")
        pages.pack(fill="both", expand=True)
        self.lookup = tk.Frame(pages, bg="#111111")
        self.settings = tk.Frame(pages, bg="#111111")
        card = tk.Frame(self.settings, bg="#191919", highlightthickness=1,
                        highlightbackground="#303030")
        card.pack(fill="x", padx=34, pady=34)
        tk.Label(card, text="Settings", bg="#191919", fg="white",
                 font=("Segoe UI Semibold", 20)).pack(anchor="w", padx=20, pady=(16, 3))
        tk.Label(card, text="Coming soon", bg="#191919", fg="#aaa",
                 font=("Segoe UI", 11)).pack(anchor="w", padx=20, pady=(0, 17))
        self.page = None
        self.transition = None
        self.build_lookup()
        self.show_page(self.lookup)
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
                self.query_entry.focus_set()
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
        searching = page is self.lookup
        self.search_tab.state(active=searching)
        self.settings_tab.state(active=not searching)
        self.refresh_placeholder()

        def slide(frame):
            offset = round(12 * (1 - frame / 7) ** 3)
            page.place(x=offset, width=-offset, relwidth=1, relheight=1)
            self.transition = self.root.after(16, slide, frame + 1) if frame < 7 else None

        slide(0)
        if searching:
            self.query_entry.focus_set()
        else:
            self.settings_tab.focus_set()

    def build_lookup(self):
        content = tk.Frame(self.lookup, bg="#111111")
        content.pack(fill="both", expand=True, padx=34, pady=(42, 20))
        tk.Label(content, text="OSINT", fg="white", bg="#111111",
                 font=("Segoe UI Semibold", 28)).pack(anchor="w")
        tk.Label(content, text="Inspect public DNS or check identifier formats locally.",
                 fg="#aaa", bg="#111111", font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 20))
        bar = tk.Frame(content, bg=BG, highlightthickness=1, highlightbackground="#3a3a3a")
        bar.pack(fill="x")
        self.query = tk.StringVar()
        self.query_entry = tk.Entry(bar, textvariable=self.query, bg=BG, fg="white",
                                    insertbackground="white", relief="flat", font=("Segoe UI", 13))
        self.query_entry.pack(side="left", fill="both", expand=True, padx=13)
        placeholder = tk.Label(self.query_entry, bg=BG, font=("Segoe UI", 12), cursor="xterm")
        placeholder.bind("<Button-1>", lambda _: self.query_entry.focus_set())
        Button(bar, "Search", self.search_lookup, primary=True).pack(side="right", padx=5, pady=5)
        self.query_entry.bind("<Return>", lambda _: self.search_lookup())
        self.lookup_result = tk.Label(content, text="", fg="#ddd", bg="#111111",
                                      justify="left", anchor="nw", font=("Segoe UI", 11), wraplength=570)
        self.lookup_result.pack(fill="x", pady=18)
        examples = ("Phone number", "Email", "Name", "Discord ID")
        self.placeholder_job = None

        def animate(frame=0):
            self.placeholder_job = None
            if self.query.get() or self.page is not self.lookup:
                return
            phase = frame % 40
            shade = 66 + min(phase, 39-phase, 6) * 15
            placeholder.configure(text=examples[(frame // 40) % len(examples)],
                                  fg=f"#{shade:02x}{shade:02x}{shade:02x}")
            placeholder.place(x=0, rely=.5, anchor="w")
            self.placeholder_job = self.root.after(55, animate, frame+1)

        def refresh_placeholder(*_):
            if self.placeholder_job is not None:
                self.root.after_cancel(self.placeholder_job)
                self.placeholder_job = None
            placeholder.place_forget()
            animate()

        self.refresh_placeholder = refresh_placeholder
        self.query.trace_add("write", refresh_placeholder)
        refresh_placeholder()

    def search_lookup(self):
        value = self.query.get().strip()
        if not value:
            self.lookup_result.configure(text="Enter a domain or identifier.")
            return
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            address = None
        if address is not None:
            self.lookup_request = None
            token = os.environ.get("VOIDCLIENT_IPINFO_TOKEN", "").strip()
            if not address.is_global or address.is_multicast or "%" in value:
                self.lookup_result.configure(text="Enter a public unicast IP address.")
            elif not token:
                self.lookup_result.configure(text="Looking up IP address…")
                self.start_lookup(value, lambda: routing_lookup(address), "RIPEstat lookup failed.")
            else:
                self.lookup_result.configure(text="Looking up IP address…")
                self.start_lookup(value, lambda: ipinfo_lookup(address, token), "IPinfo lookup failed. Check your token and connection.")
            return
        if re.fullmatch(r"[0-9]{17,20}", value) and 0 < int(value) < 2**64:
            from datetime import datetime, timezone
            created = datetime.fromtimestamp(((int(value) >> 22) + 1420070400000) / 1000, timezone.utc)
            result = f"Discord ID format · Embedded timestamp {created:%Y-%m-%d %H:%M UTC}"
        elif re.fullmatch(r"[+][1-9][0-9]{6,14}", re.sub(r"[ ()-]", "", value)):
            result = "International phone number format · Ownership unverified."
        elif re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            result = f"Email format · Domain: {value.rsplit('@', 1)[1]}"
        elif re.fullmatch(r"(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}", value):
            self.lookup_result.configure(text=f"Resolving {value}…")
            token = os.environ.get("VOIDCLIENT_VIRUSTOTAL_KEY", "").strip()
            self.start_lookup(value, lambda: domain_lookup(value, token), "Domain lookup failed.")
            return
        else:
            result = "Name entered. This app checks identifier formats and public domain DNS."
        self.lookup_request = None
        self.lookup_result.configure(text=result)

    def start_lookup(self, value, action, failure):
        results = SimpleQueue()
        request = object()
        self.lookup_request = request

        def worker():
            try:
                results.put(action())
            except (OSError, ValueError, AttributeError, KeyError, TypeError):
                results.put(failure)

        def show_result():
            if self.lookup_request is not request or self.query.get().strip() != value:
                return
            try:
                self.lookup_result.configure(text=results.get_nowait())
            except Empty:
                self.root.after(75, show_result)

        Thread(target=worker, daemon=True).start()
        self.root.after(75, show_result)


if __name__ == "__main__":
    root = tk.Tk()
    VoidClient(root)
    root.mainloop()
