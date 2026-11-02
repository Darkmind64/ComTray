"""ComTray — icône de zone de notification listant les ports COM (USB)."""
import ctypes, json, os, queue, sys, subprocess, threading, time, winreg
import pystray
from PIL import Image, ImageDraw, ImageFont
from serial.tools import list_ports

APP = "ComTray"
POLL = 1.0
CFG_DIR = os.path.join(os.environ.get("APPDATA", "."), APP)
ALIAS_FILE = os.path.join(CFG_DIR, "aliases.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
os.makedirs(CFG_DIR, exist_ok=True)

try:
    with open(ALIAS_FILE, encoding="utf-8") as f:
        aliases = json.load(f)
except Exception:
    aliases = {}

ports = {}
icon = None
lock = threading.Lock()
uiq = queue.Queue()


# ---------- UI (thread Tk unique : popups + dialogues) ----------
def work_area():
    class R(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
    r = R()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
    return r.r, r.b


def ui_thread():
    import tkinter as tk
    root = tk.Tk(); root.withdraw()
    root.ui_popups = []

    def relayout():
        right, bottom = work_area()
        y = bottom - 10
        for w in reversed(root.ui_popups):
            y -= w.winfo_height()
            w.geometry(f"+{right - w.winfo_width() - 10}+{y}")
            y -= 8

    def close(w):
        if w in root.ui_popups:
            root.ui_popups.remove(w)
            w.destroy()
            relayout()

    def show(title, msg, color, ms):
        bg = "#1f1f1f"
        w = tk.Toplevel(root); w.overrideredirect(True)
        w.attributes("-topmost", True); w.attributes("-alpha", 0.96)
        f = tk.Frame(w, bg=bg, highlightthickness=2, highlightbackground=color); f.pack(fill="both")
        tk.Label(f, text=title, fg=color, bg=bg, font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(f, text=msg, fg="white", bg=bg, font=("Segoe UI", 10), justify="left", anchor="w").pack(fill="x", padx=14, pady=(4, 12))
        w.update_idletasks()
        w.geometry(f"{max(w.winfo_reqwidth(), 320)}x{w.winfo_reqheight()}")
        w.update_idletasks()
        for c in [w, f] + f.winfo_children():
            c.bind("<Button-1>", lambda e, w=w: close(w))
        root.ui_popups.append(w)
        relayout()
        w.after(ms, lambda: close(w))

    root.ui_show = show

    def poll():
        while not uiq.empty():
            try:
                uiq.get_nowait()(root)
            except Exception:
                pass
        root.after(150, poll)

    poll()
    root.mainloop()


def popup(title, msg, color="#3fa9f5", ms=6000):
    uiq.put(lambda root: root.ui_show(title, msg, color, ms))


# ---------- ports ----------
def pkey(p):
    if p.vid is None:
        return p.hwid
    return f"{p.vid:04X}:{p.pid:04X}:{p.serial_number or ''}"


def label(p):
    a = aliases.get(pkey(p)) or aliases.get(pkey(p).rsplit(":", 1)[0])
    if a:
        return a
    return (p.description or "").replace(f"({p.device})", "").strip() or "Inconnu"


def com_num(d):
    n = "".join(c for c in d if c.isdigit())
    return int(n) if n else 0


def sorted_ports():
    return [ports[d] for d in sorted(ports, key=com_num)]


def details(p):
    out = []
    if p.vid is not None:
        out.append(f"VID:PID  {p.vid:04X}:{p.pid:04X}")
    if p.serial_number:
        out.append(f"N° série  {p.serial_number}")
    if p.manufacturer:
        out.append(f"Fabricant  {p.manufacturer}")
    if p.description:
        out.append(p.description)
    if p.location:
        out.append(f"Emplacement  {p.location}")
    return out


# ---------- icône ----------
def make_image(n):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 62, 62), 12, fill=(0, 120, 215) if n else (110, 110, 110))
    try:
        font = ImageFont.truetype("arialbd.ttf", 40 if n < 10 else 30)
    except Exception:
        font = ImageFont.load_default()
    t = str(n)
    b = d.textbbox((0, 0), t, font=font)
    d.text(((64 - (b[2] - b[0])) / 2 - b[0], (64 - (b[3] - b[1])) / 2 - b[1]), t, font=font, fill="white")
    return img


def tooltip():
    if not ports:
        return "Aucun port COM"
    s = "\n".join(f"{p.device}: {label(p)[:24]}" for p in sorted_ports())
    return s if len(s) <= 127 else s[:124] + "..."


# ---------- actions ----------
def act(f, *a):
    return lambda: f(*a)


def save_aliases():
    with open(ALIAS_FILE, "w", encoding="utf-8") as f:
        json.dump(aliases, f, ensure_ascii=False, indent=2)


def rename(p):
    def run(root):
        from tkinter import simpledialog
        root.attributes("-topmost", True)
        k = pkey(p)
        v = simpledialog.askstring(
            APP, f"Nom pour {p.device}\n{p.description}\n(vide = supprimer)",
            initialvalue=aliases.get(k, ""), parent=root)
        if v is None:
            return
        if v.strip():
            aliases[k] = v.strip()
        else:
            aliases.pop(k, None)
        save_aliases()
        threading.Thread(target=refresh, kwargs={"force": True}, daemon=True).start()
    uiq.put(run)


def copy(text):
    subprocess.run("clip", input=text.encode("utf-16"), creationflags=0x08000000)


def show_list():
    if not ports:
        popup("Ports COM", "Aucun port COM connecté", "#9e9e9e")
    else:
        popup("Ports COM", "\n".join(f"{p.device}  —  {label(p)}" for p in sorted_ports()), ms=10000)


def devmgmt():
    subprocess.Popen("devmgmt.msc", shell=True)


def autostart_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw}" "{os.path.abspath(__file__)}"'


def autostart_on(_=None):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
        return True
    except OSError:
        return False


def toggle_autostart():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if autostart_on():
            winreg.DeleteValue(k, APP)
        else:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, autostart_cmd())


notify_on = {"add": True, "rem": True}


def toggle_notify(kind):
    notify_on[kind] = not notify_on[kind]


# ---------- menu ----------
def port_items():
    if not ports:
        yield pystray.MenuItem("Aucun port COM", None, enabled=False)
        return
    for p in sorted_ports():
        sub = [pystray.MenuItem(l, None, enabled=False) for l in details(p)]
        sub += [pystray.Menu.SEPARATOR,
                pystray.MenuItem("Renommer…", act(rename, p)),
                pystray.MenuItem(f"Copier « {p.device} »", act(copy, p.device))]
        yield pystray.MenuItem(f"{p.device}  —  {label(p)}", pystray.Menu(*sub))


def menu_items():
    yield from port_items()
    yield pystray.Menu.SEPARATOR
    yield pystray.MenuItem("Afficher la liste", show_list, default=True)
    yield pystray.MenuItem("Gestionnaire de périphériques", devmgmt)
    yield pystray.MenuItem("Options", pystray.Menu(
        pystray.MenuItem("Notifier les connexions", act(toggle_notify, "add"),
                         checked=lambda i: notify_on["add"]),
        pystray.MenuItem("Notifier les déconnexions", act(toggle_notify, "rem"),
                         checked=lambda i: notify_on["rem"]),
        pystray.MenuItem("Lancer au démarrage", toggle_autostart, checked=autostart_on),
        pystray.MenuItem("Ouvrir aliases.json", act(os.startfile, ALIAS_FILE)),
    ))
    yield pystray.MenuItem("Quitter", lambda: icon.stop())


# ---------- boucle ----------
def refresh(force=False, silent=False):
    global ports
    with lock:
        new = {p.device: p for p in list_ports.comports()}
        added = [new[d] for d in new if d not in ports]
        removed = [ports[d] for d in ports if d not in new]
        if not (force or added or removed):
            return
        ports = new
        icon.icon = make_image(len(ports))
        icon.title = tooltip()
        icon.update_menu()
        if silent:
            return
        if notify_on["add"] and added:
            popup("Connecté", "\n".join(f"{p.device}  —  {label(p)}" for p in added), "#4caf50")
        if notify_on["rem"] and removed:
            popup("Déconnecté", "\n".join(f"{p.device}  —  {label(p)}" for p in removed), "#f44336")


def loop(ic):
    ic.visible = True
    refresh(force=True, silent=True)
    while ic.visible:
        time.sleep(POLL)
        try:
            refresh()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    if not os.path.exists(ALIAS_FILE):
        save_aliases()
    threading.Thread(target=ui_thread, daemon=True).start()
    icon = pystray.Icon(APP, make_image(0), "ComTray", pystray.Menu(menu_items))
    icon.run(setup=loop)
