#!/usr/bin/env python3
"""
fusionador.py -- Fusiona deskshare.webm (video) + webcams.webm (audio)
en cada carpeta grabacion_NNN/ generando fusionado_NNN.webm.

Si ffmpeg/ffprobe no estan instalados, los descarga e instala
automaticamente (Windows: gyan.dev, macOS: brew o evermeet.cx,
Linux: apt/pacman/dnf).

Uso:
  python fusionador.py
  python fusionador.py ./organizadas
  python fusionador.py ./organizadas --force
  python fusionador.py ./organizadas --codec aac
"""

import os
import re
import io
import shutil
import stat
import zipfile
import platform
import subprocess
import argparse
import urllib.request
from pathlib import Path


PATRON_CARPETA = re.compile(r'^grabacion_(\d{3})$')
DIR = Path(__file__).parent.resolve()
BIN_DIR = DIR / 'bin'


def _agregar_bin_al_path():
    """Agrega BIN_DIR al PATH del proceso si existe."""
    if BIN_DIR.is_dir():
        os.environ['PATH'] = str(BIN_DIR) + os.pathsep + os.environ.get('PATH', '')


def _descargar_extraer(url, extraer):
    """Descarga un ZIP desde `url` y extrae los archivos listados en `extraer` a BIN_DIR.
    Retorna True si todos se extrajeron correctamente."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    nombre = url.rsplit('/', 1)[-1] or 'ffmpeg.zip'
    print(f"  Descargando {nombre} ...")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception as e:
        print(f"  [ERR] Error de descarga: {e}")
        return False

    ok = True
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for nombre_archivo in extraer:
            # Buscar el archivo ignorando subcarpetas
            coincidencias = [n for n in z.namelist() if n.endswith('/' + nombre_archivo) or n == nombre_archivo]
            if not coincidencias:
                print(f"  [WARN] {nombre_archivo} no encontrado en el ZIP")
                ok = False
                continue
            src = coincidencias[0]
            dst = BIN_DIR / nombre_archivo
            with z.open(src) as origen, open(dst, 'wb') as destino:
                destino.write(origen.read())
            # Marcar como ejecutable en Unix
            st = dst.stat()
            dst.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            print(f"  [OK] {nombre_archivo} -> {dst}")
    _agregar_bin_al_path()
    return ok


def _instalar_ffmpeg_platform():
    """Instala ffmpeg + ffprobe según el SO."""
    so = platform.system()

    if so == 'Windows':
        return _descargar_extraer(
            'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
            ['ffmpeg.exe', 'ffprobe.exe'],
        )
    elif so == 'Darwin':
        # Intentar con Homebrew primero
        try:
            r = subprocess.run(['brew', '--version'], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                print("  Homebrew detectado. Instalando ffmpeg via brew...")
                s = input("  Se ejecutara: brew install ffmpeg  (puede tomar minutos). Continuar? (s/N): ").strip().lower()
                if s == 's':
                    r2 = subprocess.run(['brew', 'install', 'ffmpeg'], timeout=600)
                    if r2.returncode == 0:
                        print("  [OK] ffmpeg + ffprobe instalados via brew")
                        return True
                    else:
                        print("  [WARN] brew install fallo, intentando descarga directa...")
                else:
                    print("  Saltando brew, usando descarga directa...")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print("  Homebrew no disponible, usando descarga directa...")

        ok1 = _descargar_extraer(
            'https://evermeet.cx/ffmpeg/get/zip',
            ['ffmpeg'],
        )
        ok2 = _descargar_extraer(
            'https://evermeet.cx/ffmpeg/ffprobe/get/zip',
            ['ffprobe'],
        )
        return ok1 and ok2
    elif so == 'Linux':
        # Detectar gestor de paquetes
        if shutil.which('apt'):
            cmd = ['sudo', 'apt', 'install', '-y', 'ffmpeg']
        elif shutil.which('pacman'):
            cmd = ['sudo', 'pacman', '-S', '--noconfirm', 'ffmpeg']
        elif shutil.which('dnf'):
            cmd = ['sudo', 'dnf', 'install', '-y', 'ffmpeg']
        else:
            print("  [ERR] No se detecto gestor de paquetes conocido (apt/pacman/dnf).")
            print("  Instala ffmpeg manualmente o descarga el binario estatico.")
            return False

        print(f"  Se ejecutara: {' '.join(cmd)}")
        s = input("  Continuar? (s/N): ").strip().lower()
        if s != 's':
            print("  [ERR] Instalacion cancelada.")
            return False
        r = subprocess.run(cmd, timeout=300)
        if r.returncode == 0:
            print("  [OK] ffmpeg + ffprobe instalados")
            return True
        print("  [ERR] La instalacion fallo. Instala ffmpeg manualmente.")
        return False
    else:
        print(f"  [ERR] SO no soportado: {so}. Instala ffmpeg manualmente.")
        return False


def verificar_ffmpeg():
    """Verifica si ffmpeg esta disponible. Si no, avisa e intenta instalarlo."""
    _agregar_bin_al_path()

    if shutil.which('ffmpeg') and shutil.which('ffprobe'):
        return True

    print("\n  [!] ffmpeg/ffprobe no estan instalados en el sistema.")
    print("      Son necesarios para fusionar el video de deskshare.webm")
    print("      con el audio de webcams.webm en un solo archivo .webm.")
    print("      Sin ffmpeg la fusion no es posible.\n")

    s = input("  Deseas instalar ffmpeg + ffprobe ahora? (s/N): ").strip().lower()
    if s != 's':
        print("\n  [ERR] No se puede continuar sin ffmpeg.")
        print("  Instalalo manualmente desde: https://ffmpeg.org/download.html")
        return False

    return _instalar_ffmpeg_platform()


def buscar_carpetas(base):
    """Retorna lista de (carpeta_path, numero_str) para cada grabacion_NNN/."""
    resultados = []
    base = Path(base)
    if not base.is_dir():
        print(f"[ERR] Directorio no encontrado: {base}")
        return resultados
    for entry in sorted(base.iterdir()):
        if entry.is_dir():
            m = PATRON_CARPETA.match(entry.name)
            if m:
                resultados.append((entry, m.group(1)))
    return resultados


def _detectar_streams(ruta):
    """Usa ffprobe para detectar los tipos de streams en un archivo.
    Retorna dict con listas de codigos de stream {'v': [...], 'a': [...]}."""
    try:
        r = subprocess.run([
            'ffprobe', '-v', 'quiet',
            '-show_entries', 'stream=codec_type,codec_name',
            '-of', 'csv=p=0',
            str(ruta)
        ], capture_output=True, text=True, timeout=30)
        if r.returncode != 0 or not r.stdout.strip():
            return {'v': [], 'a': []}
        streams = {'v': [], 'a': []}
        for linea in r.stdout.strip().split('\n'):
            partes = linea.split(',')
            if len(partes) >= 2:
                codec_type = partes[0].strip()
                codec_name = partes[1].strip()
                if codec_type in streams:
                    streams[codec_type].append(codec_name)
        return streams
    except Exception:
        return {'v': [], 'a': []}


def fusionar(carpeta, num, codec, force):
    """Fusiona deskshare.webm + webcams.webm -> fusionado_NUM.webm.

    Usa mapping fijo con sufijo '?' para que ffmpeg no falle si
    deskshare no tiene video o webcams no tiene audio:
      ffmpeg -map 0:v? -map 1:a? -c:v copy -c:a CODEC

    _detectar_streams se ejecuta solo como informacion visual
    (no condiciona el comando).

    Para resistir cortes inesperados, primero escribe a un archivo
    temporal (_temp.webm) y solo lo renombra a .webm si ffmpeg
    termina exitosamente. Si el programa se cierra a medio fusionar,
    el _temp.webm queda ignorado y al reiniciar se vuelve a fusionar.
    """
    deskshare = carpeta / 'deskshare.webm'
    webcams = carpeta / 'webcams.webm'
    salida = carpeta / f'fusionado_{num}.webm'
    temporal = carpeta / f'fusionado_{num}_temp.webm'

    if not deskshare.is_file():
        print(f"  [SKIP] {carpeta.name}: falta deskshare.webm")
        return False
    if not webcams.is_file():
        print(f"  [SKIP] {carpeta.name}: falta webcams.webm")
        return False

    if salida.is_file() and not force:
        print(f"  [SKIP] {carpeta.name}: {salida.name} ya existe (usa --force)")
        return True

    if temporal.is_file():
        temporal.unlink()

    if deskshare.stat().st_size < 1024:
        print(f"  [SKIP] {carpeta.name}: deskshare.webm vacio ({deskshare.stat().st_size} bytes)")
        return False
    if webcams.stat().st_size < 1024:
        print(f"  [SKIP] {carpeta.name}: webcams.webm vacio ({webcams.stat().st_size} bytes)")
        return False

    # Info de los streams (solo informativo, no condiciona el mapping)
    ds = _detectar_streams(deskshare)
    wc = _detectar_streams(webcams)
    ds_v = ', '.join(ds['v']) if ds['v'] else '(sin video)'
    wc_a = ', '.join(wc['a']) if wc['a'] else '(sin audio)'
    print(f"  [INFO] deskshare: video={ds_v}  |  webcams: audio={wc_a}")

    cmd = [
        'ffmpeg', '-y',
        '-i', str(deskshare),
        '-i', str(webcams),
        '-map', '0:v?',
        '-map', '1:a?',
        '-c:v', 'copy',
        '-c:a', codec,
        str(temporal),
    ]

    print(f"  [FFMPEG] {carpeta.name} -> {salida.name}  (codec audio: {codec})")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            os.replace(temporal, salida)
            print(f"     [OK] {salida}")
            return True
        else:
            err = r.stderr.strip()
            print(f"     [ERR] ffmpeg fallo (codigo {r.returncode})")
            lineas = err.split('\n')
            relevantes = [l for l in lineas if 'error' in l.lower() or 'invalid' in l.lower() or 'unknown' in l.lower()]
            if relevantes:
                for l in relevantes[:5]:
                    print(f"       {l.strip()}")
            else:
                print(f"       {lineas[-1][:200] if lineas else '(sin salida)'}")
            if temporal.is_file():
                temporal.unlink()
            return False
    except Exception as e:
        print(f"     [ERR] Excepcion en ffmpeg: {e}")
        if temporal.is_file():
            temporal.unlink()
        return False


def main():
    ap = argparse.ArgumentParser(
        description="Fusiona deskshare (video) + webcams (audio) "
                    "de cada carpeta grabacion_NNN/")
    ap.add_argument('base', nargs='?', default=None,
                    help='Directorio base con las carpetas grabacion_*')
    ap.add_argument('--force', '-f', action='store_true',
                    help='Re-fusionar aunque fusionado_NNN.webm ya exista')
    ap.add_argument('--codec', default='libopus',
                    help='Codec de audio para la salida (default: libopus)')
    args = ap.parse_args()

    if args.base is None:
        entrada = input("Directorio con las carpetas grabacion_NNN/: ").strip()
        if not entrada:
            entrada = './organizadas'
        args.base = entrada

    if not verificar_ffmpeg():
        return

    carpetas = buscar_carpetas(Path(args.base))
    if not carpetas:
        print(f"[ERR] No se encontraron carpetas grabacion_NNN/ en {args.base}")
        return

    print(f"  Carpetas grabacion_NNN/ encontradas: {len(carpetas)}\n")

    ok = 0
    fail = 0
    for carpeta, num in carpetas:
        try:
            if fusionar(carpeta, num, args.codec, args.force):
                ok += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            print(f"  [ERR] {carpeta.name}: error inesperado: {e}")

    print()
    print(f"  [RESUMEN] {ok} fusionado(s) OK, {fail} fallo(s)")
    print()


if __name__ == '__main__':
    main()
