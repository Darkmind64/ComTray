"""ComTray — icône de zone de notification listant les ports COM (USB)."""
import ctypes, json, os, queue, shutil, subprocess, sys, tempfile, threading, time, traceback
import urllib.request, uuid, webbrowser, winreg
from ctypes import wintypes as wt

APP = "ComTray"
VERSION = "1.1.0"
REPO = "Darkmind64/ComTray"
CFG_DIR = os.path.join(os.environ.get("APPDATA", "."), APP)
DEV_FILE = os.path.join(CFG_DIR, "devices.json")
OLD_ALIAS = os.path.join(CFG_DIR, "aliases.json")
SET_FILE = os.path.join(CFG_DIR, "settings.json")
LOG_FILE = os.path.join(CFG_DIR, "history.log")
ERR_FILE = os.path.join(CFG_DIR, "error.log")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOWIN = 0x08000000
DEFAULT_BAUD = 115200
BAUDS = [300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400,
         250000, 460800, 921600, 1000000, 2000000]
COLORS = {"Bleu": ("#3fa9f5", "🔵"), "Vert": ("#4caf50", "🟢"), "Rouge": ("#f44336", "🔴"),
          "Orange": ("#ff9800", "🟠"), "Jaune": ("#ffd600", "🟡"), "Violet": ("#ab47bc", "🟣"),
          "Marron": ("#8d6e63", "🟤"), "Blanc": ("#e0e0e0", "⚪")}
DEFAULTS = {"notify_add": True, "notify_rem": True, "show_non_usb": False,
            "monitor": "primary", "terminal": "", "check_updates": True}
COM_GUID = "86E0D1E0-8089-11D0-9CE4-08003E301F73"

os.makedirs(CFG_DIR, exist_ok=True)


def log_error():
    try:
        with open(ERR_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + traceback.format_exc() + "\n")
    except Exception:
        pass


def jload(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# =====================================================================
#  Recherche du processus qui occupe un port (exécuté en sous-processus)
# =====================================================================
def iter_port_users(device, skip):
    import msvcrt
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    k32.OpenProcess.restype = wt.HANDLE
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.DuplicateHandle.argtypes = [wt.HANDLE, wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.HANDLE),
                                    wt.DWORD, wt.BOOL, wt.DWORD]
    k32.GetFileType.argtypes = [wt.HANDLE]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
                                               ctypes.POINTER(ctypes.c_ulong)]
    ntdll.NtQuerySystemInformation.restype = ctypes.c_ulong
    ntdll.NtQueryObject.argtypes = [wt.HANDLE, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
                                    ctypes.POINTER(ctypes.c_ulong)]
    ntdll.NtQueryObject.restype = ctypes.c_ulong

    tb = ctypes.create_unicode_buffer(512)
    if not k32.QueryDosDeviceW(device, tb, 512):
        return
    target = tb.value.lower()

    class ENTRY(ctypes.Structure):
        _fields_ = [("Object", ctypes.c_void_p), ("Pid", ctypes.c_size_t), ("Handle", ctypes.c_size_t),
                    ("Access", wt.ULONG), ("Bt", wt.USHORT), ("Type", wt.USHORT),
                    ("Attr", wt.ULONG), ("Res", wt.ULONG)]

    ref = open(sys.executable, "rb")
    myh, mypid = msvcrt.get_osfhandle(ref.fileno()), os.getpid()
    size = 1 << 22
    while True:
        buf = ctypes.create_string_buffer(size)
        rl = ctypes.c_ulong()
        st = ntdll.NtQuerySystemInformation(64, buf, size, ctypes.byref(rl))
        if st == 0:
            break
        if st == 0xC0000004:
            size = max(size * 2, rl.value + 0x100000)
            continue
        return
    n = ctypes.c_size_t.from_buffer(buf).value
    entries = (ENTRY * n).from_buffer(buf, ctypes.sizeof(ctypes.c_size_t) * 2)
    ftype = next((e.Type for e in entries if e.Pid == mypid and e.Handle == myh), None)
    if ftype is None:
        return
    cand = sorted((e.Pid, e.Handle) for e in entries
                  if e.Type == ftype and e.Pid not in skip and e.Pid != mypid and e.Pid > 4)
    del entries, buf
    cur = k32.GetCurrentProcess()
    nb = ctypes.create_string_buffer(8192)
    lastpid, hproc, found = None, None, False
    for pid, h in cand:
        if pid != lastpid:
            if hproc:
                k32.CloseHandle(hproc)
            lastpid, found = pid, False
            yield "scan", str(pid)
            hproc = k32.OpenProcess(0x40, False, pid)
        if not hproc or found:
            continue
        dup = wt.HANDLE()
        if not k32.DuplicateHandle(hproc, h, cur, ctypes.byref(dup), 0, False, 2):
            continue
        try:
            if k32.GetFileType(dup) != 2:
                continue
            if ntdll.NtQueryObject(dup, 1, nb, 8192, ctypes.byref(rl)) != 0:
                continue
            ln = ctypes.c_ushort.from_buffer(nb, 0).value
            ptr = ctypes.c_void_p.from_buffer(nb, 8).value
            if ptr and ctypes.wstring_at(ptr, ln // 2).lower() == target:
                found = True
                ph = k32.OpenProcess(0x1000, False, pid)
                name = "?"
                if ph:
                    b = ctypes.create_unicode_buffer(1024)
                    sz = wt.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(ph, 0, b, ctypes.byref(sz)):
                        name = os.path.basename(b.value)
                    k32.CloseHandle(ph)
                yield "hit", f"{pid}\t{name}"
        finally:
            k32.CloseHandle(dup)


def find_port_child(device, out, skip):
    skip = {int(x) for x in skip.split(",") if x}
    with open(out, "w", encoding="utf-8") as f:
        try:
            for kind, val in iter_port_users(device, skip):
                f.write(f"{kind}\t{val}\n")
                f.flush()
        except Exception:
            f.write("error\t" + traceback.format_exc().replace("\n", " | ") + "\n")
        f.write("done\n")


if __name__ == "__main__" and len(sys.argv) > 3 and sys.argv[1] == "--find-port":
    find_port_child(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
    sys.exit(0)


# =====================================================================
#  Application
# =====================================================================
import pystray
from PIL import Image, ImageDraw, ImageFont
from serial.tools import list_ports

settings = {**DEFAULTS, **jload(SET_FILE, {})}
devices = jload(DEV_FILE, None)
if devices is None:
    devices = {k: {"name": v} for k, v in jload(OLD_ALIAS, {}).items() if isinstance(v, str) and v}
    jsave(DEV_FILE, devices)

ports = {}
icon = None
lock = threading.Lock()
uiq = queue.Queue()
devevt = threading.Event()
running = True
history = []
update = {"tag": None, "url": None, "data": None}


def save_settings():
    jsave(SET_FILE, settings)


def save_devices():
    jsave(DEV_FILE, devices)


# ---------- appareils (1, 4, 5) ----------
def pkey(p):
    if p.vid is None:
        return p.hwid
    base = f"{p.vid:04X}:{p.pid:04X}"
    return f"{base}:{p.serial_number}" if p.serial_number else f"{base}@{p.location or '?'}"


def legacy_key(p):
    return f"{p.vid:04X}:{p.pid:04X}:" if p.vid is not None and not p.serial_number else None


def dev(p, create=False):
    k = pkey(p)
    if k in devices:
        return devices[k]
    lk = legacy_key(p)
    if lk and lk in devices:
        if not create:
            return devices[lk]
        devices[k] = dict(devices[lk])
        return devices[k]
    if create:
        devices[k] = {}
        return devices[k]
    return {}


def set_dev(p, field, value):
    d = dev(p, create=True)
    if value in (None, ""):
        d.pop(field, None)
    else:
        d[field] = value
    if not d:
        devices.pop(pkey(p), None)
    save_devices()
    changed()


def label(p):
    n = dev(p).get("name")
    if n:
        return n
    return (p.description or "").replace(f"({p.device})", "").strip() or "Inconnu"


def color(p):
    return COLORS.get(dev(p).get("color"))


def baud(p):
    return dev(p).get("baud", DEFAULT_BAUD)


def com_num(d):
    n = "".join(c for c in d if c.isdigit())
    return int(n) if n else 0


def sorted_ports():
    return [ports[d] for d in sorted(ports, key=com_num)]


def details(p):
    out = []
    if p.vid is not None:
        out.append(f"VID:PID  {p.vid:04X}:{p.pid:04X}")
    out.append(f"N° série  {p.serial_number}" if p.serial_number else "N° série  (aucun — identifié par le port USB)")
    if p.manufacturer:
        out.append(f"Fabricant  {p.manufacturer}")
    if p.description:
        out.append(p.description)
    if p.location:
        out.append(f"Port USB  {p.location}")
    out.append(f"Vitesse  {baud(p)} bauds")
    return out


def scan():
    return {p.device: p for p in list_ports.comports() if settings["show_non_usb"] or p.vid is not None}


# ---------- historique (7) ----------
def load_history():
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
        if len(lines) > 5000:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(lines[-2000:]) + "\n")
        history.extend(lines[-50:])
    except Exception:
        pass


def log_event(kind, p):
    line = f"{time.strftime('%d/%m %H:%M:%S')}  {kind}  {p.device}  {label(p)}"
    history.append(line)
    del history[:-50]
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d')} {line}  [{pkey(p)}]\n")
    except Exception:
        pass


# ---------- écrans (9) ----------
def monitors():
    u32 = ctypes.windll.user32
    res = []

    class MI(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    PROC = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
    u32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.c_void_p]

    def cb(h, dc, r, l):
        mi = MI()
        mi.cbSize = ctypes.sizeof(MI)
        u32.GetMonitorInfoW(h, ctypes.byref(mi))
        m, w = mi.rcMonitor, mi.rcWork
        res.append({"mon": (m.left, m.top, m.right, m.bottom), "work": (w.left, w.top, w.right, w.bottom),
                    "primary": bool(mi.dwFlags & 1)})
        return 1

    u32.EnumDisplayMonitors(None, None, PROC(cb), 0)
    return res


def target_area():
    ms = monitors() or [{"mon": (0, 0, 1920, 1080), "work": (0, 0, 1920, 1040), "primary": True}]
    sel = settings["monitor"]
    if sel == "mouse":
        pt = wt.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        for m in ms:
            l, t, r, b = m["mon"]
            if l <= pt.x < r and t <= pt.y < b:
                return m["work"]
    elif isinstance(sel, int) and 0 <= sel < len(ms):
        return ms[sel]["work"]
    return next((m["work"] for m in ms if m["primary"]), ms[0]["work"])


# ---------- UI Tk (popups + dialogues) ----------
def ui_thread():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.ui_popups = []
    root.ui_area = None

    def relayout():
        if not root.ui_popups:
            root.ui_area = None
            return
        if root.ui_area is None:
            root.ui_area = target_area()
        l, t, r, b = root.ui_area
        y = b - 10
        for w in reversed(root.ui_popups):
            y -= w.winfo_height()
            w.geometry(f"+{r - w.winfo_width() - 10}+{y}")
            y -= 8

    def close(w):
        if w in root.ui_popups:
            root.ui_popups.remove(w)
            w.destroy()
            relayout()

    def show(title, msg, tcolor, ms, border):
        bg = "#1f1f1f"
        w = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.96)
        f = tk.Frame(w, bg=bg, highlightthickness=3, highlightbackground=border or tcolor)
        f.pack(fill="both")
        tk.Label(f, text=title, fg=tcolor, bg=bg, font=("Segoe UI", 11, "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(10, 0))
        tk.Label(f, text=msg, fg="white", bg=bg, font=("Segoe UI", 10), justify="left", anchor="w").pack(
            fill="x", padx=14, pady=(4, 12))
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
                log_error()
        root.after(150, poll)

    poll()
    root.mainloop()


def popup(title, msg, tcolor="#3fa9f5", ms=6000, border=None):
    uiq.put(lambda root: root.ui_show(title, msg, tcolor, ms, border))


def in_thread(f, *a):
    threading.Thread(target=f, args=a, daemon=True).start()


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


def changed():
    if icon:
        icon.icon = make_image(len(ports))
        icon.title = tooltip()
        icon.update_menu()


# ---------- actions ----------
def act(f, *a):
    return lambda: f(*a)


def rename(p):
    def run(root):
        from tkinter import simpledialog
        root.attributes("-topmost", True)
        v = simpledialog.askstring(APP, f"Nom pour {p.device}\n{p.description}\n(vide = supprimer)",
                                   initialvalue=dev(p).get("name", ""), parent=root)
        if v is not None:
            set_dev(p, "name", v.strip())
    uiq.put(run)


def copy(text):
    subprocess.run("clip", input=text.encode("utf-16"), creationflags=NOWIN)


def show_list():
    if not ports:
        popup("Ports COM", "Aucun port COM connecté", "#9e9e9e")
    else:
        popup("Ports COM", "\n".join(f"{(color(p) or ('', ''))[1]} {p.device}  —  {label(p)}  ({baud(p)})".strip()
                                     for p in sorted_ports()), ms=10000)


def devmgmt():
    subprocess.Popen("devmgmt.msc", shell=True)


# ---------- terminal (3) ----------
TERM_PATHS = [r"PuTTY\putty.exe", r"teraterm5\ttermpro.exe", r"teraterm\ttermpro.exe", r"KiTTY\kitty.exe"]


def find_terminal():
    t = settings["terminal"]
    if t and os.path.exists(t):
        return t
    for exe in ("putty.exe", "kitty.exe", "ttermpro.exe"):
        w = shutil.which(exe)
        if w:
            return w
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        for rel in TERM_PATHS:
            if base and os.path.exists(os.path.join(base, rel)):
                return os.path.join(base, rel)
    return None


def open_terminal(p):
    exe = find_terminal()
    if not exe:
        popup("Terminal introuvable", "Installe PuTTY ou Tera Term,\nou Options > Terminal > Choisir…", "#ff9800")
        return
    n, b = os.path.basename(exe).lower(), baud(p)
    if "putty" in n or "kitty" in n:
        args = [exe, "-serial", p.device, "-sercfg", f"{b},8,n,1,N"]
    elif "ttermpro" in n:
        args = [exe, f"/C={com_num(p.device)}", f"/BAUD={b}"]
    else:
        args = [exe, p.device, str(b)]
    try:
        subprocess.Popen(args)
    except Exception as e:
        popup("Terminal", f"Échec du lancement :\n{e}", "#f44336")


def choose_terminal():
    def run(root):
        from tkinter import filedialog
        root.attributes("-topmost", True)
        f = filedialog.askopenfilename(parent=root, title="Choisir le terminal série",
                                       filetypes=[("Programmes", "*.exe")])
        if f:
            settings["terminal"] = os.path.normpath(f)
            save_settings()
            changed()
    uiq.put(run)


def auto_terminal():
    settings["terminal"] = ""
    save_settings()
    changed()


# ---------- port occupé (6) ----------
def child_cmd():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--find-port"]
    return [sys.executable, os.path.abspath(__file__), "--find-port"]


def port_users(device):
    hits, skip = {}, []
    out = os.path.join(tempfile.gettempdir(), f"comtray_find_{os.getpid()}.txt")
    for _ in range(30):
        open(out, "w").close()
        proc = subprocess.Popen(child_cmd() + [device, out, ",".join(map(str, skip))], creationflags=NOWIN)
        t0, seen, last, started, done = time.time(), 0, None, False, False
        while True:
            time.sleep(0.1)
            try:
                with open(out, encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except Exception:
                lines = []
            for ln in lines[seen:]:
                parts = ln.split("\t")
                if parts[0] == "scan":
                    last, started, t0 = int(parts[1]), True, time.time()
                elif parts[0] == "hit":
                    hits[int(parts[1])] = parts[2]
                elif parts[0] == "done":
                    done = True
            seen = len(lines)
            if done or proc.poll() is not None:
                break
            if time.time() - t0 > (2.0 if started else 20.0):
                proc.kill()
                break
        if done or last is None:
            break
        skip.append(last)
    try:
        os.remove(out)
    except Exception:
        pass
    return hits


def who_uses(p):
    def run():
        popup(p.device, "Recherche du programme qui utilise le port…", "#9e9e9e", 2500)
        hits = port_users(p.device)
        if not hits:
            popup(p.device, "Aucun programme ne semble utiliser ce port.\n"
                            "(un programme lancé en administrateur n'est pas visible)", "#4caf50", 7000)
        for pid, name in hits.items():
            uiq.put(lambda root, pid=pid, name=name: confirm_kill(root, p, pid, name))
    in_thread(run)


def confirm_kill(root, p, pid, name):
    from tkinter import messagebox
    root.attributes("-topmost", True)
    if messagebox.askyesno(APP, f"{p.device} est utilisé par :\n\n{name}  (PID {pid})\n\n"
                                f"Terminer ce programme pour libérer le port ?", icon="warning", parent=root):
        r = subprocess.run(["taskkill", "/F", "/PID", str(pid)], creationflags=NOWIN, capture_output=True)
        if r.returncode == 0:
            popup(p.device, f"{name} terminé — port libéré", "#4caf50")
        else:
            popup(p.device, f"Impossible de terminer {name}\n(droits administrateur nécessaires ?)", "#f44336")


# ---------- démarrage auto ----------
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
    changed()


def toggle(name, silent_refresh=False):
    settings[name] = not settings[name]
    save_settings()
    if silent_refresh:
        in_thread(refresh, True, True)
    else:
        changed()


def set_monitor(v):
    settings["monitor"] = v
    save_settings()
    changed()
    popup("Popups", "Les popups s'afficheront ici", ms=2500)


# ---------- mises à jour (11) ----------
def vtuple(s):
    return tuple(int(x) for x in s.lstrip("vV").split(".") if x.isdigit())


def fetch_latest():
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"User-Agent": APP, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def check_update(manual=False):
    try:
        data = fetch_latest()
        tag = data.get("tag_name", "")
        if vtuple(tag) > vtuple(VERSION):
            new = tag != update["tag"]
            update.update(tag=tag, url=data.get("html_url"), data=data)
            changed()
            if new or manual:
                popup("Mise à jour disponible", f"ComTray {tag} est disponible\nMenu > Installer la mise à jour",
                      "#ffd600", 12000)
        elif manual:
            popup("Mise à jour", f"ComTray {VERSION} est à jour", "#4caf50")
    except Exception:
        if manual:
            popup("Mise à jour", "Vérification impossible (pas de connexion ?)", "#f44336")


def update_loop():
    time.sleep(15)
    while running:
        if settings["check_updates"]:
            check_update()
        for _ in range(6 * 3600):
            if not running:
                return
            time.sleep(1)


def installed():
    base = os.path.normcase(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", APP))
    return getattr(sys, "frozen", False) and os.path.normcase(sys.executable).startswith(base)


def do_update():
    def run():
        page = update["url"] or f"https://github.com/{REPO}/releases/latest"
        if not installed():
            webbrowser.open(page)
            return
        try:
            asset = next(a for a in update["data"]["assets"]
                         if a["name"].lower().endswith(".exe") and "setup" in a["name"].lower())
            popup("Mise à jour", f"Téléchargement de {asset['name']}…", "#ffd600", 4000)
            path = os.path.join(tempfile.gettempdir(), asset["name"])
            urllib.request.urlretrieve(asset["browser_download_url"], path)
            subprocess.Popen([path])
        except Exception:
            log_error()
            webbrowser.open(page)
    in_thread(run)


# ---------- menu ----------
def port_menu(p):
    items = [pystray.MenuItem(l, None, enabled=False) for l in details(p)]
    bauds = sorted(set(BAUDS + [baud(p)]))
    items += [
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Ouvrir un terminal ({baud(p)} bauds)", act(open_terminal, p)),
        pystray.MenuItem("Renommer…", act(rename, p)),
        pystray.MenuItem("Vitesse", pystray.Menu(*[
            pystray.MenuItem(str(b), act(set_dev, p, "baud", None if b == DEFAULT_BAUD else b),
                             checked=lambda i, b=b: baud(p) == b, radio=True) for b in bauds])),
        pystray.MenuItem("Couleur", pystray.Menu(
            pystray.MenuItem("Aucune", act(set_dev, p, "color", None),
                             checked=lambda i: not dev(p).get("color"), radio=True),
            *[pystray.MenuItem(f"{e} {n}", act(set_dev, p, "color", n),
                               checked=lambda i, n=n: dev(p).get("color") == n, radio=True)
              for n, (_, e) in COLORS.items()])),
        pystray.MenuItem("Qui utilise ce port ?", act(who_uses, p)),
        pystray.MenuItem(f"Copier « {p.device} »", act(copy, p.device)),
    ]
    return pystray.Menu(*items)


def monitor_menu():
    items = [pystray.MenuItem("Écran principal", act(set_monitor, "primary"),
                              checked=lambda i: settings["monitor"] == "primary", radio=True),
             pystray.MenuItem("Écran de la souris", act(set_monitor, "mouse"),
                              checked=lambda i: settings["monitor"] == "mouse", radio=True)]
    for i, m in enumerate(monitors()):
        l, t, r, b = m["mon"]
        items.append(pystray.MenuItem(f"Écran {i + 1} — {r - l}×{b - t}" + (" (principal)" if m["primary"] else ""),
                                      act(set_monitor, i), checked=lambda it, i=i: settings["monitor"] == i,
                                      radio=True))
    return pystray.Menu(*items)


def terminal_menu():
    cur = find_terminal()
    return pystray.Menu(
        pystray.MenuItem(f"Actuel : {os.path.basename(cur) if cur else 'aucun trouvé'}", None, enabled=False),
        pystray.MenuItem("Détection automatique", auto_terminal, checked=lambda i: not settings["terminal"],
                         radio=True),
        pystray.MenuItem("Choisir…", choose_terminal, checked=lambda i: bool(settings["terminal"]), radio=True))


def history_menu():
    items = [pystray.MenuItem(h, None, enabled=False) for h in reversed(history[-15:])] or \
            [pystray.MenuItem("(vide)", None, enabled=False)]
    items += [pystray.Menu.SEPARATOR,
              pystray.MenuItem("Ouvrir le journal complet", act(os.startfile, LOG_FILE) if os.path.exists(LOG_FILE)
                               else None, enabled=os.path.exists(LOG_FILE))]
    return pystray.Menu(*items)


def menu_items():
    if update["tag"]:
        yield pystray.MenuItem(f"⬆ Installer la mise à jour {update['tag']}", do_update)
        yield pystray.Menu.SEPARATOR
    if not ports:
        yield pystray.MenuItem("Aucun port COM", None, enabled=False)
    for p in sorted_ports():
        c = color(p)
        yield pystray.MenuItem(f"{c[1] + '  ' if c else ''}{p.device}  —  {label(p)}", port_menu(p))
    yield pystray.Menu.SEPARATOR
    yield pystray.MenuItem("Afficher la liste", show_list, default=True)
    yield pystray.MenuItem("Historique", history_menu())
    yield pystray.MenuItem("Gestionnaire de périphériques", devmgmt)
    yield pystray.MenuItem("Options", pystray.Menu(
        pystray.MenuItem("Notifier les connexions", act(toggle, "notify_add"),
                         checked=lambda i: settings["notify_add"]),
        pystray.MenuItem("Notifier les déconnexions", act(toggle, "notify_rem"),
                         checked=lambda i: settings["notify_rem"]),
        pystray.MenuItem("Afficher les ports non USB", act(toggle, "show_non_usb", True),
                         checked=lambda i: settings["show_non_usb"]),
        pystray.MenuItem("Écran des popups", monitor_menu()),
        pystray.MenuItem("Terminal série", terminal_menu()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Vérifier les mises à jour automatiquement", act(toggle, "check_updates"),
                         checked=lambda i: settings["check_updates"]),
        pystray.MenuItem("Vérifier maintenant", act(in_thread, check_update, True)),
        pystray.MenuItem("Lancer au démarrage", toggle_autostart, checked=autostart_on),
        pystray.MenuItem("Ouvrir le dossier de configuration", act(os.startfile, CFG_DIR)),
    ))
    yield pystray.MenuItem(f"Quitter  (v{VERSION})", quit_app)


def quit_app():
    global running
    running = False
    devevt.set()
    icon.stop()


# ---------- détection (2) ----------
def devchange_thread():
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    u32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    u32.DefWindowProcW.restype = ctypes.c_ssize_t
    u32.CreateWindowExW.restype = wt.HWND
    u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    u32.RegisterDeviceNotificationW.restype = ctypes.c_void_p
    u32.RegisterDeviceNotificationW.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]
    k32.GetModuleHandleW.restype = wt.HMODULE

    def proc(h, m, w, l):
        if m == 0x0219:
            devevt.set()
        return u32.DefWindowProcW(h, m, w, l)

    wp = WNDPROC(proc)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR)]

    class DBI(ctypes.Structure):
        _fields_ = [("size", wt.DWORD), ("type", wt.DWORD), ("res", wt.DWORD),
                    ("guid", ctypes.c_byte * 16), ("name", ctypes.c_wchar * 1)]

    wc = WNDCLASSW()
    wc.lpfnWndProc = wp
    wc.hInstance = k32.GetModuleHandleW(None)
    wc.lpszClassName = "ComTrayDevWatch"
    u32.RegisterClassW(ctypes.byref(wc))
    hwnd = u32.CreateWindowExW(0, wc.lpszClassName, APP, 0, 0, 0, 0, 0, None, None, wc.hInstance, None)
    f = DBI()
    f.size, f.type = ctypes.sizeof(DBI), 5
    ctypes.memmove(f.guid, uuid.UUID(COM_GUID).bytes_le, 16)
    u32.RegisterDeviceNotificationW(hwnd, ctypes.byref(f), 0)
    msg = wt.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        u32.TranslateMessage(ctypes.byref(msg))
        u32.DispatchMessageW(ctypes.byref(msg))


def refresh(force=False, silent=False):
    global ports
    with lock:
        new = scan()
        added = [new[d] for d in new if d not in ports]
        removed = [ports[d] for d in ports if d not in new]
        if not (force or added or removed):
            return
        ports = new
        changed()
        if silent:
            return
        for p in added:
            log_event("+", p)
            if settings["notify_add"]:
                c = color(p)
                popup("Connecté", f"{p.device}  —  {label(p)}", "#4caf50", border=c[0] if c else None)
        for p in removed:
            log_event("−", p)
            if settings["notify_rem"]:
                c = color(p)
                popup("Déconnecté", f"{p.device}  —  {label(p)}", "#f44336", border=c[0] if c else None)


def loop(ic):
    ic.visible = True
    refresh(force=True, silent=True)
    in_thread(devchange_thread)
    in_thread(update_loop)
    while running:
        fired = devevt.wait(3.0)
        if not running:
            break
        try:
            if fired:
                devevt.clear()
                time.sleep(0.3)
                refresh()
                time.sleep(1.2)
            refresh()
        except Exception:
            log_error()


if __name__ == "__main__":
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = k32.CreateMutexW(None, False, "Local\\ComTraySingleInstance")
    if ctypes.get_last_error() == 183:
        sys.exit(0)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    if not os.path.exists(DEV_FILE):
        save_devices()
    load_history()
    in_thread(ui_thread)
    icon = pystray.Icon(APP, make_image(0), APP, pystray.Menu(menu_items))
    icon.run(setup=loop)
