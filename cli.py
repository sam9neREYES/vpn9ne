"""vpn9ne - cliente VPN de terminal (Linux, macOS, Windows).

Usa OpenVPN como motor. Mientras esta terminal este abierta y el programa
corriendo, la VPN esta activa. Ctrl+C, cerrar la terminal o terminar el
proceso apaga la VPN.
"""
import argparse
import base64
import csv
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

VERSION = "0.1.0"
API_URL = "https://www.vpngate.net/api/iphone/"  # servidores publicos (VPN Gate)
IS_WIN = os.name == "nt"
MAX_INTENTOS = 5
PRIORIDAD = ["US", "JP", "RU", "KR", "GB", "DE", "CA", "FR", "NL", "SG"]

BANNER = r"""
+--------------------------------------------------+
|                                                  |
|   V P N 9 N E        terminal VPN client         |
|   v{ver:<10}      Linux | macOS | Windows        |
|                                                  |
+--------------------------------------------------+
"""


def user_home():
    if not IS_WIN and os.environ.get("SUDO_USER"):
        try:
            import pwd
            return Path(pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir)
        except Exception:
            pass
    return Path.home()


DATA = user_home() / ".vpn9ne"


# ---------------------------------------------------------------- sistema
def es_admin():
    if IS_WIN:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def asegurar_admin():
    """OpenVPN necesita privilegios para crear la interfaz de red."""
    if es_admin():
        return
    if IS_WIN:
        sys.exit("[!] Abre PowerShell o CMD como Administrador y ejecuta vpn9ne de nuevo.")
    if not shutil.which("sudo"):
        sys.exit("[!] Ejecuta vpn9ne como root.")
    print("[i] Se necesitan permisos de administrador (sudo)...")
    os.execvp("sudo", ["sudo", "-E", sys.executable, "-m", "vpn9ne"] + sys.argv[1:])


def buscar_openvpn():
    exe = shutil.which("openvpn")
    if exe:
        return exe
    candidatos = []
    if IS_WIN:
        candidatos = [r"C:\Program Files\OpenVPN\bin\openvpn.exe",
                      r"C:\Program Files (x86)\OpenVPN\bin\openvpn.exe"]
    elif sys.platform == "darwin":
        candidatos = ["/opt/homebrew/sbin/openvpn", "/usr/local/sbin/openvpn"]
    else:
        candidatos = ["/usr/sbin/openvpn", "/usr/local/sbin/openvpn"]
    for c in candidatos:
        if os.path.exists(c):
            return c
    return None


def ayuda_instalar_openvpn():
    print("[!] OpenVPN no esta instalado. Instalalo asi:")
    if IS_WIN:
        print("    winget install OpenVPN.OpenVPN")
    elif sys.platform == "darwin":
        print("    brew install openvpn")
    else:
        print("    Debian/Ubuntu: sudo apt install openvpn")
        print("    Fedora:        sudo dnf install openvpn")
        print("    Arch:          sudo pacman -S openvpn")


def version_openvpn(exe):
    try:
        out = subprocess.run([exe, "--version"], capture_output=True,
                             text=True, timeout=10).stdout
        m = re.search(r"OpenVPN (\d+)\.(\d+)", out)
        return (int(m.group(1)), int(m.group(2)))
    except Exception:
        return (2, 4)


# ---------------------------------------------------------------- servidores
def descargar_servidores(forzar=False):
    DATA.mkdir(parents=True, exist_ok=True)
    cache = DATA / "cache.json"
    if not forzar and cache.exists() and time.time() - cache.stat().st_mtime < 3600:
        try:
            return json.loads(cache.read_text())
        except Exception:
            pass
    req = urllib.request.Request(API_URL, headers={"User-Agent": "vpn9ne/" + VERSION})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode("utf-8", "ignore")
    lineas = [l for l in raw.splitlines() if l.strip() and not l.startswith("*")]
    if lineas and lineas[0].startswith("#"):
        lineas[0] = lineas[0][1:]
    servidores = []
    for fila in csv.DictReader(lineas):
        try:
            cfg = base64.b64decode(fila["OpenVPN_ConfigData_Base64"]).decode("utf-8", "ignore")
            servidores.append({
                "cc": fila["CountryShort"].upper(),
                "pais": fila["CountryLong"],
                "host": fila["HostName"],
                "ip": fila["IP"],
                "score": int(fila.get("Score") or 0),
                "ping": fila.get("Ping", "?"),
                "config": cfg,
                "origen": "publico",
            })
        except Exception:
            continue
    cache.write_text(json.dumps(servidores))
    return servidores


def servidores_locales():
    """Configs propias: ~/.vpn9ne/configs/<CODIGO_PAIS>/*.ovpn"""
    res = []
    base = DATA / "configs"
    if not base.exists():
        return res
    for p in list(base.glob("*/*.ovpn")) + list(base.glob("*/*.conf")):
        try:
            res.append({
                "cc": p.parent.name.upper(), "pais": p.parent.name.upper(),
                "host": p.stem, "ip": "-", "score": 10**12, "ping": "-",
                "config": p.read_text(), "origen": "propio",
            })
        except Exception:
            continue
    return res


def todos_los_servidores(forzar=False):
    locales = servidores_locales()
    try:
        remotos = descargar_servidores(forzar)
    except Exception as e:
        print(f"[!] No pude obtener servidores publicos: {e}")
        remotos = []
    todos = locales + remotos
    todos.sort(key=lambda s: s["score"], reverse=True)
    return todos


def agrupar(servidores):
    paises = {}
    for s in servidores:
        d = paises.setdefault(s["cc"], {"cc": s["cc"], "pais": s["pais"], "n": 0})
        d["n"] += 1
    orden = [paises[c] for c in PRIORIDAD if c in paises]
    resto = sorted((p for c, p in paises.items() if c not in PRIORIDAD),
                   key=lambda p: -p["n"])
    return orden + resto


# ---------------------------------------------------------------- conexion
def _pdeathsig():
    """Linux: si vpn9ne muere, el kernel mata a openvpn."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)
    except Exception:
        pass


def detener(proc):
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def ip_publica():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=8) as r:
            return r.read().decode().strip()
    except Exception:
        return "?"


def conectar(servidor, exe, ver):
    """Devuelve 'ok' si conecto y luego el usuario salio, 'fallo' si no pudo conectar."""
    tmp = Path(tempfile.mkdtemp(prefix="vpn9ne_"))
    cfg = tmp / "conexion.ovpn"
    cfg.write_text(servidor["config"])
    cmd = [exe, "--config", str(cfg), "--verb", "3",
           "--connect-timeout", "10", "--connect-retry-max", "2"]
    if ver >= (2, 5):
        cmd += ["--data-ciphers", "AES-256-GCM:AES-128-GCM:AES-128-CBC",
                "--data-ciphers-fallback", "AES-128-CBC"]
    resolv = "/etc/openvpn/update-resolv-conf"
    if sys.platform.startswith("linux") and os.path.exists(resolv):
        cmd += ["--script-security", "2", "--up", resolv, "--down", resolv]

    kw = {}
    if IS_WIN:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    elif sys.platform.startswith("linux"):
        kw["preexec_fn"] = _pdeathsig

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, **kw)
    conectado = threading.Event()
    cola = deque(maxlen=15)

    def leer():
        for linea in proc.stdout:
            cola.append(linea.rstrip())
            if "Initialization Sequence Completed" in linea:
                conectado.set()

    threading.Thread(target=leer, daemon=True).start()

    print(f"[*] Conectando a {servidor['pais']} ({servidor['host']} / {servidor['ip']}) ...")
    resultado = "fallo"
    try:
        limite = time.time() + 35
        while not conectado.is_set() and proc.poll() is None and time.time() < limite:
            time.sleep(0.3)
        if not conectado.is_set():
            print("[x] No se pudo establecer el tunel con este servidor.")
            if cola:
                print("    ultima salida:", cola[-1])
            return "fallo"

        t0 = time.time()
        print(f"[+] CONECTADO a {servidor['pais']}. IP publica: {ip_publica()}")
        print("    Ctrl+C para desconectar. Cerrar la terminal tambien apaga la VPN.\n")
        resultado = "ok"
        while proc.poll() is None:
            m, s = divmod(int(time.time() - t0), 60)
            h, m = divmod(m, 60)
            print(f"\r    [{servidor['cc']}] activo {h:02d}:{m:02d}:{s:02d}", end="", flush=True)
            time.sleep(1)
        print("\n[!] El tunel se cerro.")
        return resultado
    except KeyboardInterrupt:
        print("\n[*] Desconectando...")
        return "ok"
    finally:
        detener(proc)
        shutil.rmtree(tmp, ignore_errors=True)
        print("[-] VPN desconectada.")


def conectar_pais(cc, servidores, exe, ver):
    cc = cc.upper()
    candidatos = [s for s in servidores if s["cc"] == cc][:MAX_INTENTOS]
    if not candidatos:
        print(f"[x] No hay servidores para '{cc}'. Usa 'vpn9ne list'.")
        return
    for s in candidatos:
        if conectar(s, exe, ver) == "ok":
            return
        print("[i] Probando el siguiente servidor...\n")
    print("[x] Ningun servidor respondio. Intenta mas tarde o con otro pais.")


# ---------------------------------------------------------------- interfaz
def menu(exe, ver):
    print(BANNER.format(ver=VERSION))
    servidores = todos_los_servidores()
    while True:
        paises = agrupar(servidores)
        if not paises:
            print("[x] Sin servidores disponibles (revisa tu internet).")
            return
        print("  Destinos disponibles:\n")
        for i, p in enumerate(paises, 1):
            print(f"   {i:>2}) {p['cc']}  {p['pais']:<28} {p['n']} servidor(es)")
        print("\n   r) refrescar lista     q) salir")
        op = input("\n  vpn9ne> ").strip().lower()
        if op in ("q", "quit", "exit"):
            return
        if op == "r":
            servidores = todos_los_servidores(forzar=True)
            continue
        if op.isdigit() and 1 <= int(op) <= len(paises):
            conectar_pais(paises[int(op) - 1]["cc"], servidores, exe, ver)
            print()
        else:
            print("  Opcion no valida.")


def main():
    # Convierte cierre de terminal / kill en salida limpia (apaga la VPN)
    def _salir(*_):
        raise KeyboardInterrupt
    for nombre in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, nombre):
            try:
                signal.signal(getattr(signal, nombre), _salir)
            except Exception:
                pass

    ap = argparse.ArgumentParser(prog="vpn9ne", description="VPN de terminal")
    ap.add_argument("--version", action="version", version=f"vpn9ne {VERSION}")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("connect", help="conectar a un pais (ej. US, JP, RU)")
    c.add_argument("pais")
    sub.add_parser("list", help="listar paises disponibles")
    sub.add_parser("refresh", help="actualizar la lista de servidores")
    sub.add_parser("doctor", help="verificar requisitos")
    a = ap.parse_args()

    if a.cmd == "list":
        for p in agrupar(todos_los_servidores()):
            print(f"{p['cc']}  {p['pais']:<28} {p['n']}")
        return
    if a.cmd == "refresh":
        print(f"[+] {len(todos_los_servidores(forzar=True))} servidores en total.")
        return

    exe = buscar_openvpn()
    if a.cmd == "doctor":
        print("Sistema   :", sys.platform)
        print("Python    :", sys.version.split()[0])
        print("OpenVPN   :", exe or "NO ENCONTRADO")
        print("Admin/root:", "si" if es_admin() else "no")
        if not exe:
            ayuda_instalar_openvpn()
        return
    if not exe:
        ayuda_instalar_openvpn()
        sys.exit(1)

    asegurar_admin()
    ver = version_openvpn(exe)
    try:
        if a.cmd == "connect":
            print(BANNER.format(ver=VERSION))
            conectar_pais(a.pais, todos_los_servidores(), exe, ver)
        else:
            menu(exe, ver)
    except (KeyboardInterrupt, EOFError):
        print("\nHasta luego.")


if __name__ == "__main__":
    main()
