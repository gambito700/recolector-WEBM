# =============================================================================
# recolector.py — Extrae grabaciones BBB de cursos SENCE
# =============================================================================
# Un solo programa auto-contenido que:
#   1. Inicia sesion en SENCE + ClaveUnica
#   2. Lista los cursos del usuario (o usa --curso)
#   3. Descubre la biblioteca de grabaciones (pagina que agrupa todas)
#   4. Extrae los RIDs y genera URLs .webm
#   5. Guarda en links_grabacion.txt
#
# Uso:
#   python recolector.py
#   python recolector.py --curso 6076
#   python recolector.py --auto
#   python recolector.py --rut 12345678-9 --curso 9999 --auto
# =============================================================================

import sys
import os
import shutil
import platform
import time
import subprocess
import importlib
import json
import re
import threading
import itertools
import logging
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.getLogger("selenium").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

SO = platform.system()
DIR = os.path.dirname(os.path.abspath(__file__))
INICIO = time.time()

URL_LOGIN = "https://auladigital.sence.cl/login/index.php"
CRE_FILE = os.path.join(DIR, "credenciales.json")
LINKS_FILE = os.path.join(DIR, "links_grabacion.txt")
LOG_FILE = os.path.join(DIR, "recolector_log.txt")

# =============================================================================
# LOG
# =============================================================================

def ui(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def log(nivel, msg):
    t = int(time.time() - INICIO)
    linea = f"[{datetime.now().strftime('%H:%M:%S')}][{nivel}][{t}s] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(linea + "\n")

def log_sep(titulo=""):
    sep = "=" * 72
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{sep}\n")
        if titulo:
            f.write(f"  {titulo}\n")
        f.write(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{sep}\n")

# =============================================================================
# SPINNER — Indicador de carga animado
# =============================================================================

class Spinner:
    def __init__(self, msg="Cargando"):
        self.msg = msg
        self._stop = False
        self._thread = None

    def __enter__(self):
        self._stop = False
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop = True
        if self._thread:
            self._thread.join(0.5)
        sys.stdout.write("\r" + " " * (len(self.msg) + 10) + "\r")
        sys.stdout.flush()

    def _spin(self):
        for c in itertools.cycle(['|', '/', '-', '\\']):
            if self._stop:
                break
            sys.stdout.write(f"\r  [{c}] {self.msg}...")
            sys.stdout.flush()
            time.sleep(0.1)

# =============================================================================
# CREDENCIALES
# =============================================================================

def cargar_creds():
    if os.path.exists(CRE_FILE):
        try:
            with open(CRE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def guardar_creds(**kwargs):
    try:
        creds = cargar_creds()
        creds.update(kwargs)
        creds["guardado_en"] = datetime.now().isoformat()
        with open(CRE_FILE, "w", encoding="utf-8") as f:
            json.dump(creds, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        ui(f"[ERR] No se pudo guardar credencial: {e}")
        return False

def pedir_creds():
    creds = cargar_creds()
    saved = creds.get("rut", "")
    if saved:
        r = input(f"  RUN [{saved}]: ").strip()
        rut = r if r else saved
    else:
        rut = input("  RUN: ").strip()
    return rut

# =============================================================================
# NAVEGADOR
# =============================================================================

NAV_CONFIG = {
    "firefox": {
        "cmds_linux": ["firefox", "firefox-esr"],
        "driver": "geckodriver",
        "win_paths": [
            r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
            r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
        ],
        "mac_path": "/Applications/Firefox.app",
    },
    "chrome": {
        "cmds_linux": ["google-chrome", "chromium", "chromium-browser"],
        "driver": "chromedriver",
        "win_paths": [
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        ],
        "mac_path": "/Applications/Google Chrome.app",
    },
    "edge": {
        "cmds_linux": ["microsoft-edge"],
        "driver": "msedgedriver",
        "win_paths": [
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        ],
        "mac_path": "/Applications/Microsoft Edge.app",
    },
}

def detectar_navegador():
    for nom, cfg in NAV_CONFIG.items():
        if SO == "Windows":
            for p in cfg["win_paths"]:
                r = os.path.expandvars(p)
                if os.path.exists(r):
                    return nom, r
        elif SO == "Darwin":
            if os.path.exists(cfg["mac_path"]):
                return nom, cfg["mac_path"]
        else:
            for cmd in cfg["cmds_linux"]:
                r = shutil.which(cmd)
                if r:
                    return nom, r
    return None, None

def detectar_driver(navegador):
    dc = NAV_CONFIG[navegador]["driver"]
    r = shutil.which(dc)
    if not r and SO == "Windows":
        local = os.path.join(DIR, dc + ".exe")
        if os.path.exists(local):
            return local
    return r

def instalar_selenium():
    try:
        import selenium
        return True
    except ImportError:
        pass
    ui("[...] Instalando selenium...")
    fl = ["--break-system-packages"] if SO == "Linux" else []
    r = subprocess.run([sys.executable, "-m", "pip", "install", "selenium", "-q"] + fl,
                       capture_output=True, text=True)
    if r.returncode == 0:
        ui("[OK] selenium instalado")
        return True
    ui(f"[ERR] selenium fallo: {r.stderr.strip()[:100]}")
    return False

def instalar_pip():
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, check=True)
    except Exception:
        ui("[...] Instalando pip...")
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "-q"], capture_output=True)

def preparar(navegador):
    ui("[...] Revisando dependencias...")
    instalar_pip()
    instalar_selenium()
    dp = detectar_driver(navegador)
    if not dp:
        try:
            import selenium
            v = [int(x) for x in selenium.__version__.split(".") if x.isdigit()]
            if len(v) >= 2 and (v[0] > 4 or (v[0] == 4 and v[1] >= 6)):
                ui("[OK] Driver via Selenium Manager")
                return
        except Exception:
            pass
    ui("[OK] Dependencias listas")

# =============================================================================
# PEDIR CONTRASENA
# =============================================================================

def pedir_pass(usar_guardada=True):
    if usar_guardada:
        creds = cargar_creds()
        saved = creds.get("password")
        if saved:
            return saved
    print("  Password: ", end="", flush=True)
    pwd = ""
    if SO == "Windows":
        import msvcrt
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                print()
                break
            elif ch == "\x03":
                raise KeyboardInterrupt
            elif ch in ("\x7f", "\x08"):
                if pwd:
                    pwd = pwd[:-1]
                    print("\b \b", end="", flush=True)
            else:
                pwd += ch
                print("*", end="", flush=True)
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch in ("\r", "\n"):
                    print()
                    break
                elif ch in ("\x7f", "\x08"):
                    if pwd:
                        pwd = pwd[:-1]
                        print("\b \b", end="", flush=True)
                elif ch == "\x03":
                    raise KeyboardInterrupt
                else:
                    pwd += ch
                    print("*", end="", flush=True)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return pwd

# =============================================================================
# CONFIGURACION INICIAL
# =============================================================================

def detectar_navegadores_disponibles():
    disponibles = []
    for nom in ["firefox", "chrome", "edge"]:
        cfg = NAV_CONFIG.get(nom)
        if not cfg:
            continue
        if SO == "Windows":
            for p in cfg["win_paths"]:
                if os.path.exists(os.path.expandvars(p)):
                    disponibles.append(nom)
                    break
        elif SO == "Darwin":
            if os.path.exists(cfg["mac_path"]):
                disponibles.append(nom)
        else:
            for cmd in cfg["cmds_linux"]:
                if shutil.which(cmd):
                    disponibles.append(nom)
                    break
    return disponibles

def configurar_primera_vez():
    print("\n" + "=" * 50)
    print("  CONFIGURACION INICIAL")
    print("  (solo la primera vez)")
    print("=" * 50)

    disponibles = detectar_navegadores_disponibles()
    if not disponibles:
        disponibles = list(NAV_CONFIG.keys())

    print("\n  Navegadores disponibles:")
    for i, nom in enumerate(disponibles, 1):
        print(f"    {i}. {nom.capitalize()}")

    while True:
        s = input(f"  \u00bfCual usar? (1-{len(disponibles)}): ").strip()
        try:
            browser = disponibles[int(s) - 1]
            break
        except (ValueError, IndexError):
            pass
    guardar_creds(browser=browser)
    ui(f"[OK] Navegador: {browser}")

    s = input("  \u00bfModo solo consola (sin ventana)? (s/N): ").strip().lower()
    headless = s == "s"
    guardar_creds(headless=headless)
    if headless:
        ui("[OK] Modo: solo consola")
    else:
        ui("[OK] Modo: ventana grafica")

    print("\n" + "-" * 50)
    print("  [ADVERTENCIA] La contrasena se guardara en texto plano")
    print("  en 'credenciales.json'. Cualquier persona con acceso")
    print("  a tu PC podra leerla.")
    print("-" * 50)
    s = input("  \u00bfGuardar contrasena igual? (s/N): ").strip().lower()
    if s == "s":
        pwd = pedir_pass(usar_guardada=False)
        guardar_creds(password=pwd)
        ui("[OK] Contrasena guardada")

    print("  [OK] Configuracion guardada en credenciales.json\n")

def mostrar_comandos():
    print("")
    print("  " + "-" * 50)
    print("  COMANDOS DISPONIBLES:")
    print("    --headless       Modo solo consola (sin ventana)")
    print("    --browser CHROME Navegador: chrome, firefox, edge")
    print("    --no-save-pass   Ignorar password guardado")
    print("    --curso ID       ID del curso (ej: 6076)")
    print("    --rut RUN        RUN del usuario")
    print("    --url URL        URL directo del curso")
    print("    --auto           Seleccionar primer curso")
    print("  " + "-" * 50)
    print("")

# =============================================================================
# IMPORTAR SELENIUM
# =============================================================================

def imp_sel(navegador):
    wd = importlib.import_module("selenium.webdriver")
    mb = f"selenium.webdriver.{navegador}"
    Opt = importlib.import_module(f"{mb}.options").Options
    Svc = importlib.import_module(f"{mb}.service").Service
    Drv = getattr(wd, navegador.capitalize())
    By = importlib.import_module("selenium.webdriver.common.by").By
    Wt = importlib.import_module("selenium.webdriver.support.ui").WebDriverWait
    Sl = importlib.import_module("selenium.webdriver.support.ui").Select
    EC = importlib.import_module("selenium.webdriver.support.expected_conditions")
    return Drv, Opt, Svc, By, Wt, Sl, EC

# =============================================================================
# INICIAR DRIVER
# =============================================================================

def iniciar_driver(navegador, headless, Drv, Opt, Svc):
    dp = detectar_driver(navegador)
    op = Opt()
    op.page_load_strategy = "eager"
    if navegador == "firefox":
        if headless:
            op.add_argument("-headless")
        op.set_preference("browser.tabs.remote.autostart", False)
    else:
        if headless:
            op.add_argument("--headless=new")
        op.add_argument("--no-sandbox")
        op.add_argument("--disable-dev-shm-usage")
        op.add_experimental_option("excludeSwitches", ["enable-logging"])
    sv = Svc(executable_path=dp if dp else None, log_output=os.devnull)
    dr = Drv(options=op, service=sv)
    dr.implicitly_wait(5)
    dr.set_page_load_timeout(30)
    return dr

# =============================================================================
# LOGIN
# =============================================================================

def login(driver, rut, password, sm, auto=False, curso_id=None):
    """Autenticacion en dos fases: SENCE (RUT) + ClaveUnica (password).
       Retorna (True, curso_url) si ok, (False, None) si falla."""
    Drv, Opt, Svc, By, Wt, Sl, EC = sm
    # Bucle de reintentos: la pagina puede tardar o fallar intermitentemente
    for intento in range(1, 4):
        try:
            t0 = time.time()
            log("INFO", f"login_intento={intento}")
            ui(f"[{intento}/3] Iniciando sesion...")
            driver.get(URL_LOGIN)
            # Fase 1: Esperar el campo RUT en la pagina de SENCE
            Wt(driver, 20).until(EC.presence_of_element_located((By.ID, "rut")))
            log("DBG", f"login_pagina_cargada url={driver.current_url[:80]}")
            driver.find_element(By.ID, "rut").send_keys(rut)
            driver.find_element(By.TAG_NAME, "body").click()

            # La plataforma renderiza cursos en 2 formatos DOM distintos:
            # - <select id="curso"> (dropdown clasico)
            # - <li data-key> con enlaces (lista moderna)
            # Esperamos cualquiera de los dos
            try:
                Wt(driver, 20).until(lambda d: (
                    len(d.find_elements(By.CSS_SELECTOR, "select#curso")) > 0 or
                    len(d.find_elements(By.CSS_SELECTOR, "li[data-key] a[href*='course/view.php']")) > 0
                ))
                log("DBG", "cursos_encontrados_en_login")
            except Exception:
                log("WARN", f"cursos_no_aparecen url={driver.current_url[:80]} titulo={driver.title[:80]}")
                raise

            # Detectar que formato aparecio
            hay_select = len(driver.find_elements(By.CSS_SELECTOR, "select#curso")) > 0
            hay_lista = len(driver.find_elements(By.CSS_SELECTOR, "li[data-key] a[href*='course/view.php']")) > 0
            log("DBG", f"hay_select={hay_select} hay_lista={hay_lista}")

            curso_url = None
            if hay_select:
                log("INFO", "cursos=formato_select")
                sel = Sl(driver.find_element(By.ID, "curso"))
                opts = [o for o in sel.options if o.text.strip()]
                elegida = _escojer_curso_select(opts, auto, curso_id, intento)
                sel.select_by_value(elegida.get_attribute("value"))
                curso_id_sel = elegida.get_attribute("value")
                curso_url = f"https://auladigital.sence.cl/course/view.php?id={curso_id_sel}"
                log("DBG", f"curso_seleccionado_select id={curso_id_sel} url={curso_url}")
                ui(f"  Curso: {elegida.text.strip()[:55]}")
                # Hacemos clic en el boton de login, lo que activa la redireccion a ClaveUnica
                driver.find_element(By.ID, "btnLogin").click()
            elif hay_lista:
                log("INFO", "cursos=formato_lista_li")
                enlaces = driver.find_elements(By.CSS_SELECTOR, "li[data-key] a[href*='course/view.php']")
                elegida = _escojer_curso_li(enlaces, auto, curso_id, intento)
                curso_url = elegida.get_attribute("href")
                log("DBG", f"curso_seleccionado_li url={curso_url}")
                ui(f"  Curso: {elegida.text.strip()[:55]}")
                # En formato lista, navegamos directamente a la URL del curso
                driver.get(curso_url)
            else:
                raise Exception("No se detecto lista de cursos")

            log("DBG", f"post_curso url={driver.current_url[:80]} titulo={driver.title[:80]}")
            # Fase 2: Autenticacion ClaveUnica (gobierno de Chile)
            Wt(driver, 30).until(EC.url_contains("claveunica.gob.cl"))
            Wt(driver, 30).until(EC.visibility_of_element_located((By.ID, "uname")))
            driver.find_element(By.ID, "uname").send_keys(rut)
            driver.find_element(By.ID, "pword").send_keys(password)
            driver.find_element(By.ID, "login-submit").click()
            ui("[...] Validando retorno...")
            # ClaveUnica redirige de vuelta a auladigital.sence.cl
            Wt(driver, 30).until(EC.url_contains("auladigital"))
            log("DBG", f"claveunica_redirect_ok url={driver.current_url[:100]} titulo={driver.title[:80]}")
            time.sleep(3)
            log("DBG", f"post_sleep url={driver.current_url[:100]} titulo={driver.title[:80]}")
            # Verificar si hay mensajes de error visibles
            try:
                err = driver.find_element(By.CSS_SELECTOR, ".alert-danger, .alert-error, .error, #error-message")
                ui(f"[ERR] {err.text.strip()}")
                log("ERR", f"auth_fail {err.text.strip()}")
                return False, None
            except Exception:
                pass
            log("OK", f"login_ok duracion={time.time()-t0:.1f}s curso_url={curso_url}")
            ui("[OK] Sesion iniciada.")
            return True, curso_url
        except Exception as e:
            log("WARN", f"login_intento={intento} error={type(e).__name__} {e}")
            ui(f"[WARN] Intento {intento} fallido: {type(e).__name__}")
            if intento == 3:
                ui(f"[ERR] Login fallido tras 3 intentos")
                return False, None
            time.sleep(5)
    return False, None

def _escojer_curso_select(opts, auto, curso_id, intento):
    """Selecciona curso desde un <select> HTML.
    Prioridad: --curso ID > --auto/reintento > input interactivo."""
    if curso_id:
        for o in opts:
            if o.get_attribute("value") == str(curso_id):
                return o
        ui(f"[WARN] Curso {curso_id} no encontrado, usando primero")
    if auto or intento > 1:
        return opts[0]
    print("\n  Cursos:")
    for i, o in enumerate(opts, 1):
        print(f"  {i}. {o.text.strip()}")
    s = input("  Selecciona: ").strip()
    try:
        return opts[int(s) - 1]
    except Exception:
        return opts[0]

def _escojer_curso_li(enlaces, auto, curso_id, intento):
    """Selecciona curso desde lista de <li> con enlaces.
    Prioridad: --curso ID por substring > --auto/reintento > input interactivo."""
    datos = [(e.get_attribute("href"), e.text.strip()) for e in enlaces]
    if curso_id:
        for e in enlaces:
            if str(curso_id) in (e.get_attribute("href") or ""):
                return e
        ui(f"[WARN] Curso {curso_id} no encontrado, usando primero")
    if auto or intento > 1:
        return enlaces[0]
    print("\n  Cursos:")
    for i, (url, nom) in enumerate(datos, 1):
        print(f"  {i}. {nom}")
    s = input("  Selecciona: ").strip()
    try:
        return enlaces[int(s) - 1]
    except Exception:
        return enlaces[0]

# =============================================================================
# CURSOS DEL SIDEBAR (post-login)
# =============================================================================

def listar_cursos_sidebar(driver, By, Wt, EC):
    cursos = []
    try:
        items = driver.find_elements(By.CSS_SELECTOR, "li[data-key] a[href*='course/view.php']")
        for a in items:
            try:
                href = a.get_attribute("href") or ""
                m = re.search(r"id=(\d+)", href)
                cid = m.group(1) if m else ""
                txt = a.text.strip()
                if cid and txt:
                    cursos.append({"id": cid, "nombre": txt, "url": href})
            except Exception:
                continue
    except Exception as e:
        log("WARN", f"sidebar_cursos error={e}")
    if not cursos:
        try:
            js = driver.execute_script("""
                return Array.from(document.querySelectorAll('li[data-key] a[href*="course/view.php"]')).map(function(a) {
                    var m = a.href.match(/id=(\\d+)/);
                    return {id: m ? m[1] : '', nombre: a.textContent.trim(), url: a.href};
                });
            """) or []
            cursos = js
        except Exception:
            pass
    if not cursos:
        log("WARN", f"sidebar_cursos=vacio titulo={driver.title[:80]}")
        try:
            log("WARN", f"sidebar_html={driver.execute_script('return document.body.innerHTML.slice(0,500)')}")
        except Exception:
            pass
    return cursos

# =============================================================================
# MODULOS Y ACTIVIDADES BBB
# =============================================================================

def detectar_modulos(driver, By):
    """Detecta los modulos/secciones del curso en la pagina actual."""
    mods = []
    try:
        secs = driver.find_elements(By.CSS_SELECTOR, "li.section.main")
        for s in secs:
            try:
                sid = s.get_attribute("id") or ""
                m = re.search(r"section-(\d+)", sid)
                num = int(m.group(1)) if m else 0
                lbl = s.get_attribute("aria-label") or ""
                if not lbl:
                    for a in s.find_elements(By.TAG_NAME, "a"):
                        t = a.text.strip()
                        if t and len(t) > 3:
                            lbl = t
                            break
                mods.append({"id": num, "nombre": lbl.strip()})
            except Exception:
                continue
    except Exception:
        pass
    if not mods:
        try:
            js = driver.execute_script("""
                return Array.from(document.querySelectorAll('li.section.main')).map(function(s) {
                    var id = s.id || '';
                    var m = id.match(/section-(\\d+)/);
                    var num = m ? parseInt(m[1]) : 0;
                    var lbl = s.getAttribute('aria-label') || '';
                    if (!lbl) {
                        var a = s.querySelector('a');
                        if (a) lbl = a.textContent.trim();
                    }
                    return {id: num, nombre: lbl, url: ''};
                });
            """) or []
            mods = js
        except Exception:
            pass
    return mods

def detectar_bbb_en_modulo(driver, By):
    acts = []
    try:
        enlaces = driver.find_elements(By.CSS_SELECTOR, "a[href*='mod/bigbluebuttonbn/view.php?id=']")
        for a in enlaces:
            try:
                href = a.get_attribute("href") or ""
                m = re.search(r"id=(\d+)", href)
                cid = m.group(1) if m else ""
                nom = a.text.strip()
                acts.append({"id": cid, "nombre": nom, "url": href})
            except Exception:
                continue
    except Exception:
        pass
    if not acts:
        try:
            js = driver.execute_script("""
                return Array.from(document.querySelectorAll('a[href*="mod/bigbluebuttonbn/view.php?id="]')).map(function(a) {
                    var m = a.href.match(/id=(\\d+)/);
                    var cid = m ? m[1] : '';
                    return {id: cid, nombre: a.textContent.trim(), url: a.href};
                });
            """) or []
            acts = js
        except Exception:
            pass
    return acts

# =============================================================================
# EXTRACCION DE RIDS
# =============================================================================

def extraer_rids(driver, By):
    """Extrae los Recording IDs (RID) de los botones de reproduccion en la pagina actual."""
    rids = []
    try:
        enlaces = driver.find_elements(By.CSS_SELECTOR, "a[data-action='play']")
        for a in enlaces:
            try:
                dh = a.get_attribute("data-href") or ""
                m = re.search(r'rid=([a-f0-9]{40}-\d+)', dh)
                if m:
                    rids.append({"rid": m.group(1), "nombre": a.text.strip() or "", "data_href": dh})
            except Exception:
                continue
    except Exception:
        pass
    if not rids:
        try:
            js = driver.execute_script("""
                return Array.from(document.querySelectorAll('a[data-action="play"]')).map(function(a) {
                    var dh = a.getAttribute('data-href') || '';
                    var m = dh.match(/rid=([a-f0-9]{40}-\\d+)/);
                    return {rid: m ? m[1] : '', nombre: a.textContent.trim(), data_href: dh};
                });
            """) or []
            rids = [r for r in js if r.get("rid")]
        except Exception:
            pass
    return rids

def gen_urls(rid):
    return {
        "playback": f"https://aulavirtual.sence.cl/playback/presentation/2.3/{rid}",
        "webcams": f"https://aulavirtual.sence.cl/presentation/{rid}/video/webcams.webm",
        "deskshare": f"https://aulavirtual.sence.cl/presentation/{rid}/deskshare/deskshare.webm",
        "metadata": f"https://aulavirtual.sence.cl/presentation/{rid}/metadata.xml",
    }

# =============================================================================
# ESCANEO DEL CURSO
# =============================================================================

def escanear_curso(driver, curso_url, sm):
    By, Wt, EC = sm[3], sm[4], sm[6]
    ui("[...] Escaneando estructura del curso...")
    driver.get(curso_url)
    log("DBG", f"escanear_get url={driver.current_url[:100]} titulo={driver.title[:80]}")
    time.sleep(3)

    modulos = detectar_modulos(driver, By)
    ui(f"  Modulos detectados: {len(modulos)}")
    log("INFO", f"modulos={len(modulos)} curso={curso_url}")
    if not modulos:
        log("WARN", f"sin_modulos url={driver.current_url[:100]} titulo={driver.title[:80]}")
        try:
            log("WARN", f"body_inicio={driver.find_element(By.TAG_NAME, 'body').get_attribute('innerHTML')[:500]}")
        except Exception:
            pass

    todas_bbb = []
    try:
        js_todas = driver.execute_script("""
            return Array.from(document.querySelectorAll('li.section.main')).map(function(s) {
                var m = s.id.match(/section-(\\d+)/);
                var sid = m ? parseInt(m[1]) : 0;
                var nom = s.getAttribute('aria-label') || '';
                if (!nom) {
                    var a = s.querySelector('a');
                    if (a) nom = a.textContent.trim();
                }
                var bbb = Array.from(s.querySelectorAll('a[href*="mod/bigbluebuttonbn/view.php?id="]')).map(function(a) {
                    var mm = a.href.match(/id=(\\d+)/);
                    return {
                        id: mm ? mm[1] : '',
                        nombre: a.textContent.trim(),
                        url: a.href,
                        modulo_id: sid,
                        modulo_nombre: nom
                    };
                });
                return bbb;
            });
        """) or []
        for sect_bbb in js_todas:
            for b in sect_bbb:
                todas_bbb.append(b)
        ui(f"  Actividades BBB: {len(todas_bbb)}")
        log("INFO", f"actividades_bbb={len(todas_bbb)}")
    except Exception as e:
        log("WARN", f"js_extraer_bbb_fallback exc={type(e).__name__} {e}")
        ui("[WARN] Usando metodo modulo por modulo (lento)...")
        for i, mod in enumerate(modulos):
            sep = "&" if "?" in curso_url else "?"
            url_mod = f"{curso_url}{sep}section={mod['id']}" if mod["id"] is not None else curso_url
            ui(f"  Modulo {i+1}/{len(modulos)}: {mod['nombre'][:40]}")
            try:
                driver.get(url_mod)
                time.sleep(2)
                acts = detectar_bbb_en_modulo(driver, By)
                for a in acts:
                    a["modulo_id"] = mod["id"]
                    a["modulo_nombre"] = mod["nombre"]
                    todas_bbb.append(a)
            except Exception as e2:
                log("WARN", f"modulo_error id={mod['id']} nom={mod['nombre'][:30]} exc={type(e2).__name__} {e2}")
                ui(f"  [WARN] Modulo {mod['id']}: {type(e2).__name__}")
        ui(f"  Actividades BBB: {len(todas_bbb)}")
        log("INFO", f"actividades_bbb={len(todas_bbb)}")

    ui(f"  Actividades BBB: {len(todas_bbb)}")
    log("INFO", f"actividades_bbb={len(todas_bbb)}")

    if not todas_bbb:
        ui("[WARN] No hay actividades BBB en este curso")
        log("WARN", "sin_actividades_bbb")
        return []

    log("DBG", f"inicio_identificacion_biblioteca total_candidatas={len(todas_bbb)}")

    # De todas las actividades BBB del curso, solo una es la "biblioteca"
    # que contiene TODAS las grabaciones. No hay un marcador CSS que la
    # identifique, asi que usamos un sistema de scoring heuristico:
    #   - +10 pts si el nombre contiene "grabacion" o "recording"
    #   - +N pts donde N = cantidad de botones de reproduccion en esa pagina
    # La pagina con mayor puntaje total es la biblioteca.
    candidatas_nombre = [b for b in todas_bbb if "grabacion" in b.get("nombre", "").lower() or "recording" in b.get("nombre", "").lower()]
    candidatas_a_visitar = candidatas_nombre if candidatas_nombre else todas_bbb[:10]
    ui(f"  Evaluando {len(candidatas_a_visitar)} candidatas (de {len(todas_bbb)} total)")

    candidatas = []
    for i, bbb in enumerate(candidatas_a_visitar):
        nm = bbb.get("nombre", "").lower()
        pts = 10 if ("grabacion" in nm or "recording" in nm) else 0
        try:
            log("DBG", f"candidata_{i} nom={bbb['nombre'][:40]}")
            driver.get(bbb["url"])
            time.sleep(2)
            rids = extraer_rids(driver, By)
            pts += len(rids)
            ui(f"    {bbb['nombre'][:45]:45s} id={bbb['id']:6s}  plays={len(rids):2d}  pts={pts}")
            log("INFO", f"candidata id={bbb['id']} nom={bbb['nombre'][:40]} rids={len(rids)} pts={pts}")
        except Exception as e:
            ui(f"    {bbb['nombre'][:45]:45s} id={bbb['id']:6s}  ERROR: {e}")
            log("WARN", f"candidata_err id={bbb['id']} {e}")
            pts = 0

        candidatas.append({
            "id": bbb["id"],
            "nombre": bbb["nombre"],
            "url": bbb["url"],
            "modulo_id": bbb["modulo_id"],
            "total_grabaciones": pts if pts <= 10 else pts - 10,
            "puntaje": pts,
        })

    candidatas.sort(key=lambda x: x["puntaje"], reverse=True)

    if not candidatas or candidatas[0]["puntaje"] <= 0:
        ui("[WARN] No se identifico una biblioteca de grabaciones")
        return []

    mejor = candidatas[0]
    log("INFO", f"biblioteca=id={mejor['id']} nom={mejor['nombre']} rids={mejor['total_grabaciones']}")

    ui(f"\n  >>> Biblioteca: {mejor['nombre']} ({mejor['total_grabaciones']} grabaciones)")
    ui(f"      URL: {mejor['url']}")

    # Extraer todos los RIDs de la biblioteca
    ui("[...] Extrayendo grabaciones de la biblioteca...")
    driver.get(mejor["url"])
    log("DBG", f"biblioteca_loaded url={driver.current_url[:100]} titulo={driver.title[:80]}")
    time.sleep(3)

    # La biblioteca puede tener multiples paginas (paginacion)
    rids_totales = []
    pagina = 1

    while True:
        rids = extraer_rids(driver, By)
        log("DBG", f"pagina_{pagina}_rids_encontrados={len(rids)}")
        rids_totales.extend(rids)
        ui(f"  Pagina {pagina}: {len(rids)} grabaciones")
        log("INFO", f"pagina={pagina} rids={len(rids)} total={len(rids_totales)}")

        # La pagina de la biblioteca puede tener paginacion con "Siguiente"
        try:
            sig = driver.find_element(By.CSS_SELECTOR, "a[rel='next'], a:has(>span[aria-label='Pagina siguiente']), a.pagination-next, li.next a")
            driver.get(sig.get_attribute("href"))
            time.sleep(2)
            pagina += 1
        except Exception:
            break

    webm_urls = []
    for r in rids_totales:
        u = gen_urls(r["rid"])
        webm_urls.append(u["webcams"])
        webm_urls.append(u["deskshare"])
        log("INFO", f"webm rid={r['rid']} nom={r['nombre'][:40]}")

    ui(f"  Total grabaciones: {len(rids_totales)}")
    ui(f"  Total URLs .webm: {len(webm_urls)}")

    return webm_urls

# =============================================================================
# GUARDAR LINKS
# =============================================================================

def guardar_links(links):
    """Guarda las URLs .webm en links_grabacion.txt.
    Ordena alfabeticamente, elimina duplicados y escribe
    encabezado con timestamp y total."""
    webm = sorted(set(l for l in links if l.endswith(".webm")))
    try:
        with open(LINKS_FILE, "w", encoding="utf-8") as f:
            f.write(f"# Links .webm extraidos el {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total: {len(webm)} URLs\n\n")
            for l in webm:
                f.write(l + "\n")
        ui(f"[OK] {len(webm)} URLs .webm guardadas en {LINKS_FILE}")
        log("OK", f"guardados total={len(webm)}")
        return True
    except Exception as e:
        ui(f"[ERR] No se pudo guardar: {e}")
        return False

# =============================================================================
# MAIN
# =============================================================================

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Recolector de grabaciones BBB — SENCE")
    ap.add_argument("--curso", help="ID del curso (ej: 6076)")
    ap.add_argument("--rut", help="RUN del usuario")
    ap.add_argument("--auto", action="store_true", help="Seleccionar primer curso sin preguntar")
    ap.add_argument("--headless", action="store_true", help="Sin ventana grafica (solo consola)")
    ap.add_argument("--url", help="URL directo (salta descubrimiento)")
    ap.add_argument("--browser", choices=["chrome", "firefox", "edge"], help="Navegador: chrome, firefox, edge")
    ap.add_argument("--no-save-pass", action="store_true", help="Ignorar password guardado")
    args = ap.parse_args()

    log_sep("RECOLECTOR INICIADO")
    print(f"\n  RECOLECTOR — Extraccion de grabaciones BBB")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("  " + "-" * 50)

    # --- Cargar configuracion guardada ---
    creds = cargar_creds()

    # --- Si es primera vez, ejecutar asistente ---
    if not creds.get("browser") or creds.get("headless") is None:
        configurar_primera_vez()
        creds = cargar_creds()
        mostrar_comandos()

    # --- Determinar navegador: CLI > config > auto-detect ---
    nav = args.browser or creds.get("browser")
    if nav and nav not in NAV_CONFIG:
        ui(f"[WARN] Navegador '{nav}' no reconocido, detectando...")
        nav = None
    if not nav:
        nav, _ = detectar_navegador()
    if not nav:
        ui("[ERR] No se encontro navegador (Chrome/Firefox/Edge)")
        log("ERR", "no_browser")
        return
    ui(f"Navegador: {nav}")
    log("INFO", f"browser={nav}")

    # --- Determinar headless: CLI > config > default False ---
    headless = creds.get("headless", False)
    if args.headless:
        headless = True
    if headless:
        ui("Modo: solo consola")
    else:
        ui("Modo: ventana grafica")
    log("INFO", f"headless={headless}")

    # --- Credenciales: CLI > config > pedir ---
    rut_arg = args.rut or creds.get("rut") or pedir_creds()
    password = creds.get("password") if not args.no_save_pass else None
    if not password:
        password = pedir_pass(usar_guardada=False)

    # --- Preparar dependencias ---
    with Spinner("Revisando dependencias"):
        preparar(nav)

    Drv, Opt, Svc, By, Wt, Sl, EC = imp_sel(nav)
    sm = (Drv, Opt, Svc, By, Wt, Sl, EC)
    driver = iniciar_driver(nav, headless, Drv, Opt, Svc)

    curso_id = None
    try:
        # --- Login ---
        ok, curso_url_del_login = login(driver, rut_arg, password, sm, auto=args.auto, curso_id=args.curso)
        log("DBG", f"login_retorno ok={ok} curso_url_del_login={curso_url_del_login}")
        if not ok:
            ui("[ERR] No se pudo iniciar sesion")
            return

        # Guardar config persistente tras login exitoso
        if not creds.get("rut") and not args.rut:
            guardar_creds(rut=rut_arg)
        if not creds.get("password") and not args.no_save_pass:
            if input("  Guardar contrasena para proxima vez? (s/N): ").strip().lower() == "s":
                guardar_creds(password=password)

        # --- Determinar curso objetivo ---
        log("DBG", f"determinando_curso args.curso={args.curso} args.url={args.url} curso_url_del_login={curso_url_del_login}")
        curso_url = None
        if args.curso:
            curso_url = f"https://auladigital.sence.cl/course/view.php?id={args.curso}"
            curso_id = args.curso
            ui(f"Curso objetivo: {args.curso}")
        elif args.url:
            curso_url = args.url
            m = re.search(r"id=(\d+)", args.url)
            if m:
                curso_id = m.group(1)
        elif curso_url_del_login:
            curso_url = curso_url_del_login
            m = re.search(r"id=(\d+)", curso_url)
            if m:
                curso_id = m.group(1)
            ui(f"Curso: {driver.title}")
            log("DBG", f"usando_url_del_login curso_url={curso_url}")
        else:
            saved_id = creds.get("ultimo_curso_id")
            ui("[...] Buscando cursos...")
            cursos = listar_cursos_sidebar(driver, By, Wt, EC)
            if not cursos:
                ui("[ERR] No se encontraron cursos en el sidebar")
                log("ERR", "no_cursos_sidebar")
                return

            ui(f"  Cursos disponibles: {len(cursos)}")
            for i, c in enumerate(cursos, 1):
                ui(f"  {i}. {c['nombre']} (id={c['id']})")

            elegido = None
            if args.auto or len(cursos) == 1:
                elegido = cursos[0]
            else:
                if saved_id:
                    for i, c in enumerate(cursos, 1):
                        if c["id"] == str(saved_id):
                            print(f"  Curso anterior [{i}]: {c['nombre'][:40]}")
                            break
                s = input("  Selecciona curso: ").strip()
                try:
                    elegido = cursos[int(s) - 1]
                except Exception:
                    elegido = cursos[0]

            curso_url = elegido["url"]
            curso_id = elegido.get("id")
            ui(f"Curso elegido: {elegido['nombre']}")

        log("INFO", f"curso_url={curso_url}")

        # --- Escanear ---
        with Spinner("Escaneando curso"):
            webm = escanear_curso(driver, curso_url, sm)

        # --- Guardar ultimo curso usado ---
        if curso_id:
            guardar_creds(ultimo_curso_id=int(curso_id))

        # --- Guardar links ---
        if webm:
            guardar_links(webm)
        else:
            ui("[WARN] No se encontraron grabaciones .webm")

        log("OK", f"recoleccion_completa total_webm={len(webm)}")

    except KeyboardInterrupt:
        ui("\n[!] Interrupcion del usuario")
        log("INFO", "interrupted")
    except Exception as e:
        log("ERR", f"fatal {e}")
        ui(f"[ERR] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            if 'driver' in locals():
                driver.quit()
                log("INFO", "browser=closed")
        except Exception:
            pass
        ui("[OK] Recolector finalizado.")

if __name__ == "__main__":
    main()
