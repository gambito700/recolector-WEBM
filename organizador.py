#!/usr/bin/env python3
"""
organizador.py -- Empareja webcams.webm y deskshare.webm por duracion
y los organiza en carpetas.

Extrae la duracion de cada archivo usando ffprobe (si disponible)
o un parser EBML integrado (sin dependencias). Empareja webcams con
deskshare ordenando por duracion, y crea carpetas grabacion_001/...
con cada par.

Uso:
  python organizador.py                           # directorio actual
  python organizador.py ./descargas               # directorio especifico
  python organizador.py ./dir1 ./dir2             # multiples directorios
  python organizador.py --copy                    # copiar en vez de mover
  python organizador.py --tolerancia 10            # tolerancia en segundos
"""

import os
import sys
import shutil
import struct
import subprocess
import argparse
from pathlib import Path


# =============================================================================
# EBML / WebM duration parser (sin dependencias externas)
# =============================================================================
# El formato WebM usa EBML (Extensible Binary Meta Language). La duracion
# esta en Segment > Info > Duration, con TimecodeScale como factor de escala.
# Este parser recorre la estructura binaria para extraer ambos valores.

# Identificadores de elementos EBML (Matroska/WebM):
#   EBML header      -> Segment -> Info -> Duration (+ TimecodeScale)
EID_EBML = b'\x1a\x45\xdf\xa3'       # Cabecera del archivo EBML
EID_SEGMENT = b'\x18\x53\x80\x67'    # Segmento principal (contiene todo)
EID_INFO = b'\x15\x49\xa9\x66'       # Informacion del segmento
EID_TIMECODE_SCALE = b'\x2a\xd7\xb1' # Escala de tiempo (nanosegundos por tick)
EID_DURATION = b'\x44\x89'           # Duracion (en ticks, multiplicar por TimecodeScale)


def _vint(data, offset):
    """Lee un VINT (Variable Length Integer) desde data[offset].
    Retorna (valor, bytes_consumidos)."""
    b = data[offset]
    length = 1
    mask = 0x80
    while mask > 0 and not (b & mask):
        mask >>= 1
        length += 1
    if mask == 0 or length > 8:
        raise ValueError("VINT invalido")
    val = b & (mask - 1)
    for i in range(1, length):
        val = (val << 8) | data[offset + i]
    return val, length


def _eid(data, offset):
    """Lee un Element ID de EBML como bytes crudos.
    Retorna (id_bytes, bytes_consumidos)."""
    b = data[offset]
    length = 1
    mask = 0x80
    while mask > 0 and not (b & mask):
        mask >>= 1
        length += 1
    if mask == 0 or length > 4:
        raise ValueError("EID invalido")
    return data[offset:offset + length], length


def duracion_ebml(ruta, max_leer=262144):
    """Extrae la duracion de un .webm leyendo su header EBML.
    Sin dependencias externas.
    Retorna segundos, o None si no se pudo determinar."""
    try:
        with open(ruta, 'rb') as f:
            data = f.read(max_leer)
    except Exception:
        return None

    if len(data) < 50:
        return None

    tc_scale = 1_000_000
    duration = None
    offset = 0

    try:
        while offset < len(data):
            eid, c = _eid(data, offset)
            offset += c
            size, c = _vint(data, offset)
            offset += c

            if eid == EID_SEGMENT:
                max_vint = (1 << (7 * c)) - 1
                end = len(data) if size >= max_vint else offset + size
                end = min(end, len(data))

                while offset < end:
                    ceid, c = _eid(data, offset)
                    offset += c
                    csize, c = _vint(data, offset)
                    offset += c

                    if ceid == EID_INFO:
                        info_end = offset + csize
                        info_end = min(info_end, len(data))

                        while offset < info_end:
                            ieid, c = _eid(data, offset)
                            offset += c
                            isize, c = _vint(data, offset)
                            offset += c
                            raw_end = offset + isize

                            if ieid == EID_TIMECODE_SCALE:
                                raw = data[offset:raw_end]
                                if raw:
                                    tc_scale = int.from_bytes(raw, 'big')
                            elif ieid == EID_DURATION:
                                raw = data[offset:raw_end]
                                if isize == 4 and len(raw) >= 4:
                                    duration = struct.unpack('>f', raw)[0]
                                elif isize == 8 and len(raw) >= 8:
                                    duration = struct.unpack('>d', raw)[0]

                            offset = raw_end
                    else:
                        offset += csize
            else:
                offset += size
    except Exception:
        pass

    if duration is not None:
        return duration * tc_scale / 1_000_000_000
    return None


# =============================================================================
# Wrapper ffprobe (mas preciso, si esta disponible)
# =============================================================================

def duracion_ffprobe(ruta):
    """Obtiene duracion usando ffprobe. Retorna segundos o None."""
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries',
             'format=duration', '-of', 'csv=p=0', str(ruta)],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return None


def obtener_duracion(ruta):
    """Obtiene duracion: intenta ffprobe, fallback a parser EBML."""
    d = duracion_ffprobe(ruta)
    if d is not None:
        return d
    return duracion_ebml(ruta)


# =============================================================================
# Clasificacion y matching
# =============================================================================

def clasificar(archivos):
    """Clasifica .webm en webcams, deskshare y otros segun su nombre."""
    webcams = []
    deskshare = []
    otros = []

    for r in archivos:
        nom = r.name.lower()
        # Los archivos de BigBlueButton siguen la convencion:
        #   webcams.webm   -> camara del presentador
        #   deskshare.webm -> pantalla compartida
        if 'webcams' in nom:
            webcams.append(r)
        elif 'deskshare' in nom:
            deskshare.append(r)
        else:
            otros.append(r)

    return webcams, deskshare, otros


def emparejar(webcams, deskshare, tolerancia=5):
    """Empareja por duracion. Retorna (pares, huerfanos_w, huerfanos_d)."""
    pares = []
    huerf_w = []
    huerf_d = []

    def _durar(lista, huerfanos):
        res = []
        for r in lista:
            d = obtener_duracion(r)
            if d is not None:
                res.append((r, d))
            else:
                huerfanos.append((r, "dur_desconocida"))
        return res

    w_dur = _durar(webcams, huerf_w)
    d_dur = _durar(deskshare, huerf_d)

    w_dur.sort(key=lambda x: x[1])
    d_dur.sort(key=lambda x: x[1])

    n = min(len(w_dur), len(d_dur))
    for i in range(n):
        rw, dw = w_dur[i]
        rd, dd = d_dur[i]
        diff = abs(dw - dd)
        pares.append({
            'webcams': rw, 'deskshare': rd,
            'dur_w': dw, 'dur_d': dd,
            'diferencia': diff, 'revisar': diff > tolerancia,
        })

    for r, d in w_dur[n:]:
        huerf_w.append((r, f"dur={d:.1f}s"))
    for r, d in d_dur[n:]:
        huerf_d.append((r, f"dur={d:.1f}s"))

    return pares, huerf_w, huerf_d


# =============================================================================
# Organizacion en carpetas
# =============================================================================

def organizar(pares, out_dir, mover=True):
    """Crea carpetas grabacion_NNN/ con cada par."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, par in enumerate(pares, 1):
        carpeta = out_dir / f"grabacion_{i:03d}"
        carpeta.mkdir(exist_ok=True)

        for clave in ('webcams', 'deskshare'):
            src = par[clave]
            dst = carpeta / f"{clave}.webm"

            if mover:
                shutil.move(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))

        par['carpeta'] = carpeta

    return pares


def resumir_metodo_duracion(archivos):
    """Cuenta cuantos usaron ffprobe vs ebml (solo para info)."""
    total = len(archivos)
    ffprobe = 0
    ebml = 0
    fallo = 0
    for r in archivos:
        if duracion_ffprobe(r) is not None:
            ffprobe += 1
        elif duracion_ebml(r) is not None:
            ebml += 1
        else:
            fallo += 1
    return total, ffprobe, ebml, fallo


# =============================================================================
# CLI
# =============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="Organizador de grabaciones BBB -- "
                    "Empareja webcams y deskshare por duracion")
    ap.add_argument('dirs', nargs='*', default=[],
                    metavar='DIR',
                    help='Directorios con los .webm (default: actual)')
    ap.add_argument('--out', default=None,
                    help='Directorio de salida (default: ./organizadas)')
    ap.add_argument('--copy', action='store_true',
                    help='Copiar archivos en vez de mover')
    ap.add_argument('--tolerancia', type=float, default=5.0,
                    help='Diferencia maxima de duracion en segundos (default: 5)')
    ap.add_argument('--sin-progress', action='store_true',
                    help='Ocultar barra de progreso')
    args = ap.parse_args()

    if not args.dirs and args.out is None:
        entrada = input("Carpeta de entrada (donde buscar los .webm): ").strip()
        if not entrada:
            entrada = '.'
        salida = input("Carpeta de salida (donde guardar resultados): ").strip()
        if not salida:
            salida = './organizadas'
        args.dirs = [entrada]
        args.out = salida
    elif not args.dirs:
        args.dirs = ['.']
    elif args.out is None:
        args.out = './organizadas'

    out_dir = Path(args.out)

    archivos = []
    for d in args.dirs:
        dp = Path(d)
        if not dp.is_dir():
            print(f"[WARN] Directorio no encontrado, ignorado: {dp}")
            continue
        encontrados = sorted(dp.rglob('*.webm'))
        archivos.extend(encontrados)
        print(f"  {dp}  ->  {len(encontrados)} .webm")

    if not archivos:
        print("[ERR] No hay archivos .webm en los directorios especificados")
        return

    print(f"\n  Archivos .webm encontrados: {len(archivos)}")

    webcams, deskshare, otros = clasificar(archivos)
    print(f"  Webcams: {len(webcams)}")
    print(f"  Deskshare: {len(deskshare)}")
    if otros:
        print(f"  Otros (ignorados): {len(otros)}")

    if not webcams or not deskshare:
        print("[ERR] Se necesitan archivos webcams y deskshare")
        return

    # Resumen metodo de duracion
    print("\n  Calculando duraciones...")
    total_w, fp_w, ebml_w, fail_w = resumir_metodo_duracion(webcams)
    total_d, fp_d, ebml_d, fail_d = resumir_metodo_duracion(deskshare)
    n_fp = fp_w + fp_d
    n_ebml = ebml_w + ebml_d
    n_fail = fail_w + fail_d
    if n_fp:
        print(f"  ffprobe: {n_fp} archivos")
    if n_ebml:
        print(f"  parser EBML: {n_ebml} archivos")
    if n_fail:
        print(f"  [WARN] {n_fail} archivos sin duracion detectable")

    # Emparejar
    pares, huerf_w, huerf_d = emparejar(webcams, deskshare, args.tolerancia)

    print(f"\n  {'=' * 50}")
    print(f"  RESULTADOS")
    print(f"  {'=' * 50}")
    print(f"  Pares formados:     {len(pares)}")
    print(f"  Webcams huerfanas:  {len(huerf_w)}")
    print(f"  Deskshare huerfanos:{len(huerf_d)}")

    if pares:
        print(f"\n  {f'Pares ({len(pares)})':-^48}")
        for par in pares:
            rev = "  [REVISAR]" if par['revisar'] else ""
            print(f"    {par['dur_w']:7.1f}s  <->  {par['dur_d']:7.1f}s  "
                  f"(diff={par['diferencia']:.1f}s){rev}")

    if huerf_w:
        print(f"\n  Webcams sin pareja ({len(huerf_w)}):")
        for r, info in huerf_w:
            print(f"    {r.name}  ({info})")

    if huerf_d:
        print(f"\n  Deskshare sin pareja ({len(huerf_d)}):")
        for r, info in huerf_d:
            print(f"    {r.name}  ({info})")

    if not pares:
        print("[WARN] No se pudieron formar pares")
        return

    # Organizar
    accion = "Copiando" if args.copy else "Moviendo"
    print(f"\n  {accion} pares a: {out_dir}")
    organizar(pares, out_dir, mover=not args.copy)

    print(f"\n  [OK] {len(pares)} pares organizados en {out_dir}")
    if args.copy:
        print("  (archivos copiados, originales intactos)")
    else:
        print("  (archivos movidos)")

    n_rev = sum(1 for p in pares if p['revisar'])
    if n_rev:
        print(f"\n  [AVISO] {n_rev} par(es) tienen diferencia "
              f"mayor a {args.tolerancia}s -- revisa manualmente")

    print()


if __name__ == '__main__':
    main()
