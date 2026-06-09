# Recolector de Grabaciones BBB — SENCE

Tres herramientas para extraer, organizar y fusionar grabaciones BigBlueButton de cursos SENCE.

| Herramienta | Propósito |
|-------------|-----------|
| `recolector.py` | Extrae URLs .webm desde la plataforma SENCE vía ClaveÚnica |
| `organizador.py` | Empareja `webcams.webm` y `deskshare.webm` por duración y los organiza en carpetas |
| `fusionador.py` | Combina el video de `deskshare.webm` con el audio de `webcams.webm` en cada carpeta |

---

## 1. Recolector — `recolector.py`

Extrae automáticamente las URLs .webm (video cámara + pantalla compartida) de las grabaciones BigBlueButton de tus cursos SENCE, autenticándose via ClaveÚnica.

### Requisitos

- Python 3.8+
- Navegador: Firefox, Chrome o Edge instalado
- Conexión a Internet
- Credenciales ClaveÚnica (RUT + contraseña)

### Instalación

```bash
git clone https://github.com/gambito700/recolector-WEBM.git o descarga el ZIP
cd "Recolector webm"
python recolector.py --help
```

El script instala Selenium automáticamente si es necesario (vía `pip`).

### Uso básico

```bash
python recolector.py
```

En la primera ejecución un asistente te guiará para configurar navegador, modo ventana/consola y guardar credenciales.

### Flags disponibles

| Flag | Descripción |
|------|-------------|
| `--headless` | Modo solo consola (sin ventana gráfica) |
| `--browser {chrome,firefox,edge}` | Forzar navegador específico |
| `--curso ID` | ID del curso (ej: `--curso 6076`) |
| `--rut RUN` | RUT del usuario |
| `--auto` | Seleccionar primer curso sin preguntar |
| `--url URL` | URL directa del curso (salta descubrimiento) |
| `--no-save-pass` | Ignorar contraseña guardada, pedir cada vez |

### Ejemplos

```bash
# Primera vez con asistente interactivo
python recolector.py

# Solo consola, curso específico, sin guardar password
python recolector.py --headless --curso 6076 --no-save-pass

# Usar Chrome en modo ventana, auto-seleccionar curso
python recolector.py --browser chrome --auto

# Automatización total (sin interacción)
python recolector.py --headless --browser chrome --rut 12345678-9 --curso 6076 --auto
```

### ¿Cómo funciona?

1. **Login**: Ingresa a `auladigital.sence.cl` con RUT + ClaveÚnica
2. **Selección de curso**: Descubre los cursos disponibles desde la página de login
3. **Escaneo**: Busca actividades BigBlueButton en todas las secciones del curso vía JavaScript (una sola carga de página)
4. **Biblioteca de grabaciones**: Identifica la actividad que contiene todas las grabaciones usando un sistema de scoring heurístico (visita candidatas, cuenta grabaciones, elige la de mayor puntaje)
5. **Extracción de RIDs**: Obtiene todos los Recording IDs de la biblioteca (soporta paginación)
6. **Generación de URLs**: Para cada grabación genera:
   - **`webcams.webm`**: Video de la cámara web del presentador (contiene audio)
   - **`deskshare.webm`**: Captura de pantalla compartida

### Salida

```
links_grabacion.txt
```

Contiene las URLs .webm ordenadas alfabéticamente con timestamp y total:

```
# Links .webm extraidos el 2026-06-04 15:38:22
# Total: 332 URLs

https://aulavirtual.sence.cl/presentation/<rid>/video/webcams.webm
https://aulavirtual.sence.cl/presentation/<rid>/deskshare/deskshare.webm
...
```

Puedes descargar los archivos con herramientas como `wget`, `curl`, `ffmpeg` o un gestor de descargas (Motrix, Internet Download Manager, JDownloader, otrxs):

```bash
wget -i links_grabacion.txt
```

### Seguridad

- La contraseña se guarda en texto plano en `credenciales.json` solo si eliges explícitamente hacerlo durante la configuración inicial
- Usa `--no-save-pass` en cada ejecución para evitar que se use una contraseña guardada
- El RUT se guarda sin contraseña por defecto (solo para pre-llenar en la próxima ejecución)

### Solución de problemas

- **"No se encontró navegador"**: Instala Firefox, Chrome o Edge
- **Error de autenticación**: Verifica RUT y contraseña ClaveÚnica
- **No aparecen cursos**: Asegúrate de tener cursos SENCE activos en la plataforma
- **El programa se cuelga**: Usa `--headless` para reducir consumo de recursos

---

## 2. Organizador — `organizador.py`

Una vez descargados los `.webm`, este script empareja cada `webcams.webm` con su `deskshare.webm` correspondiente según la duración del video y los organiza en carpetas `grabacion_001/`, `grabacion_002/`, etc.

### Uso

```bash
# Modo interactivo (pide carpeta de entrada y salida)
python organizador.py

# Modo CLI
python organizador.py ./descargas --out ./organizadas
python organizador.py ./dir1 ./dir2 --copy --tolerancia 10
```

### Flags

| Flag | Default | Descripción |
|------|---------|-------------|
| `DIR` (posicional) | — | Directorio(s) con los .webm (modo interactivo si se omite) |
| `--out DIR` | `./organizadas` | Carpeta donde crear las subcarpetas `grabacion_NNN/` |
| `--copy` | off | Copiar archivos en vez de moverlos |
| `--tolerancia SEG` | `5.0` | Diferencia máxima de duración en segundos entre webcams y deskshare |
| `--sin-progress` | off | Ocultar barra de progreso |

### ¿Cómo funciona?

1. **Escanea** el/los directorios en busca de archivos `.webm`
2. **Clasifica** por nombre: los que contienen `"webcams"` vs `"deskshare"`
3. **Calcula la duración** de cada archivo — primero intenta con `ffprobe` (más preciso); si no está disponible, usa un **parser EBML** propio que lee la estructura binaria del header WebM sin dependencias externas
4. **Empareja** ordenando ambos grupos por duración y apareando por índice (el más corto con el más corto). Si la diferencia supera la tolerancia, marca el par como `[REVISAR]`
5. **Organiza** moviendo (o copiando con `--copy`) cada par a `grabacion_001/webcams.webm` y `grabacion_001/deskshare.webm`

### Ejemplos

```bash
# Interactivo
python organizador.py

# Especificar carpetas
python organizador.py ./mis_webm --out ./resultado

# Copiar en vez de mover, tolerancia ampliada
python organizador.py ./descargas --copy --tolerancia 15
```

---

## 3. Fusionador — `fusionador.py`

Para cada carpeta `grabacion_NNN/` generada por el organizador, fusiona el **video de `deskshare.webm`** con el **audio de `webcams.webm`** en un único archivo `fusionado_NNN.webm`.

### Uso

```bash
# Modo interactivo (pide el directorio base)
python fusionador.py

# Modo CLI
python fusionador.py ./organizadas
python fusionador.py ./organizadas --force
python fusionador.py ./organizadas --codec aac
```

### Flags

| Flag | Default | Descripción |
|------|---------|-------------|
| `BASE` (posicional) | `./organizadas` | Directorio con las carpetas `grabacion_*` (modo interactivo si se omite) |
| `--force` / `-f` | off | Re-fusionar aunque `fusionado_NNN.webm` ya exista |
| `--codec C` | `libopus` | Códec de audio de salida (ej: `aac`, `libmp3lame`) |

### Auto-instalación de ffmpeg

Si `ffmpeg` o `ffprobe` no están instalados, el programa detecta la falta, explica por qué son necesarios y ofrece instalarlos automáticamente:

| SO | Fuente de descarga |
|----|-------------------|
| **Windows** | Descarga ZIP portable desde `gyan.dev`, extrae `ffmpeg.exe` + `ffprobe.exe` a `bin/` en la carpeta del script |
| **macOS** | Intenta `brew install ffmpeg` primero; si no hay Homebrew, descarga binarios estáticos desde `evermeet.cx` |
| **Linux** | Usa el gestor de paquetes del sistema (`apt`, `pacman` o `dnf` vía `sudo`) |

En Windows y macOS (sin brew) los binarios se guardan en `bin/` junto al script y se agregan al `PATH` del proceso, sin modificar el sistema.

### ¿Cómo funciona?

1. Busca subcarpetas que coincidan con `grabacion_NNN/` dentro del directorio base
2. Para cada una, verifica que existan `deskshare.webm` y `webcams.webm`
3. Ejecuta `ffmpeg` con `-map 0:v -map 1:a`: toma la pista de video del primer archivo (deskshare) y la pista de audio del segundo (webcams), las copia sin recodificar video y recodifica el audio al códec elegido
4. Guarda el resultado como `fusionado_NNN.webm` dentro de la misma carpeta

Comando interno:

```
ffmpeg -y -i deskshare.webm -i webcams.webm -map 0:v -map 1:a -c:v copy -c:a libopus fusionado_001.webm
```

### Ejemplos

```bash
# Fusionar todo en el directorio por defecto
python fusionador.py

# Especificar carpeta base
python fusionador.py ./resultado

# Forzar refusión y usar AAC
python fusionador.py ./organizadas --force --codec aac
```

---

## 4. Bitácora de desarrollo

### Recolector

#### Login en dos fases (SENCE → ClaveÚnica)

**Problema:** La autenticación requiere dos pasos: primero un formulario Moodle en `auladigital.sence.cl` (RUT + botón), que redirige automáticamente a ClaveÚnica para la segunda contraseña. Los tiempos de redirección varían y los errores pueden aparecer en cualquier fase.

**Solución:** Un bucle de 3 reintentos con `WebDriverWait` por fase. Primero espera que aparezca el selector de cursos (prueba de que el RUT fue aceptado), luego hace clic en el botón de login, espera la URL de ClaveÚnica, ingresa la contraseña, y finalmente espera el retorno a `auladigital`. Tras una pausa de seguridad, verifica si hay elementos de error en la página.

#### Cursos en dos formatos DOM distintos

**Problema:** La plataforma renderiza la lista de cursos en dos formatos diferentes según el estado de sesión o navegador: un `<select id="curso">` con opciones, o una lista de `<li>` con enlaces a `course/view.php`. No se sabe cuál aparecerá.

**Solución:** El `WebDriverWait` usa un predicado con `OR` que espera **cualquiera de los dos** formatos. Luego, flags booleanos (`hay_select` / `hay_lista`) determinan la rama a ejecutar. Cada formato tiene su propia función de selección (`_escojer_curso_select` y `_escojer_curso_li`) que maneja modo interactivo, `--curso ID` y `--auto`.

#### Identificar la biblioteca de grabaciones

**Problema:** Un curso puede tener muchas actividades BigBlueButton (sesiones en vivo, enlaces a grabaciones sueltas, etc.), pero solo una es la página "biblioteca" que agrupa **todas** las grabaciones. No hay una clase CSS o atributo que la distinga.

**Solución:** Sistema de **scoring heurístico**: (1) suma 10 puntos si el nombre contiene "grabacion" o "recording", (2) visita cada candidata, cuenta cuántos botones de reproducción (`data-action="play"`) tiene y suma esa cantidad. La página con mayor puntaje total es declarada biblioteca. Esto asegura que una página llamada "Grabaciones" con 15 recording IDs gane sobre una sin grabaciones.

#### RIDs con paginación

**Problema:** La biblioteca puede tener decenas de grabaciones repartidas en varias páginas con un enlace "Siguiente".

**Solución:** Un bucle `while True` extrae los RIDs de la página actual, luego busca un enlace de paginación con un selector CSS amplio (`a[rel='next']`, `a.pagination-next`, `li.next a`, etc.). Si existe, navega a la siguiente página y repite. Si no, termina.

#### Password con asteriscos en todas las plataformas

**Problema:** `getpass.getpass()` de Python no muestra asteriscos y en Windows puede no suprimir el eco correctamente en IDLE o PowerShell.

**Solución:** Implementación propia con bifurcación de plataforma: en Windows usa `msvcrt.getwch()` para leer caracteres uno a uno sin eco; en Unix usa `tty.setraw()` para poner stdin en modo raw. Ambas versiones imprimen `*` por cada tecla, manejan backspace y Ctrl+C, y restauran el estado original de la terminal al terminar.

#### DOM dinámico que Selenium no captura

**Problema:** La plataforma Moodle renderiza parte del contenido vía JavaScript. `driver.find_elements` puede devolver vacío para elementos que sí existen en la página renderizada.

**Solución:** Patrón de **doble ruta** en todas las funciones de extracción (`listar_cursos_sidebar`, `detectar_modulos`, `detectar_bbb_en_modulo`, `extraer_rids`): primero intenta con los localizadores estándar de Selenium; si no encuentra nada, ejecuta la misma consulta vía `driver.execute_script()` con `querySelectorAll` de JavaScript, que captura elementos generados dinámicamente. Como último recurso, `escanear_curso` tiene un fallback que itera módulo por módulo cargando cada sección por separado.

#### Auto-detección de navegador y drivers

**Problema:** El programa debe funcionar en Windows, macOS y Linux sin exigir al usuario descargar WebDrivers manualmente. Además, Selenium 4.6+ incorpora Selenium Manager que gestiona los drivers automáticamente.

**Solución:** `NAV_CONFIG` mapea rutas de instalación típicas por plataforma para Firefox, Chrome y Edge. `detectar_navegador` prueba cada uno en orden. `detectar_driver` busca el driver binario, con fallback a una copia local en Windows. `preparar` verifica la versión de Selenium: si es >= 4.6, salta toda la detección de drivers porque Selenium Manager lo maneja.

---

### Organizador

#### Obtener duración del video sin ffprobe

**Problema:** Para emparejar webcams y deskshare por duración se necesita conocer la duración de cada video. ffprobe es la herramienta estándar pero no siempre está instalada. Se necesitaba un método alternativo sin dependencias externas.

**Solución:** Se implementó un **parser EBML** integrado (~70 líneas) que lee la estructura binaria del archivo WebM. El formato WebM usa EBML (Extensible Binary Meta Language), donde la duración está en `Segment > Info > Duration`, con `TimecodeScale` como factor de escala. El parser recorre los Element ID y VINT (Variable Length Integers) para localizar y extraer ambos valores, calculando la duración en segundos. Si ffprobe está disponible se usa primero por ser más preciso; si no, cae al parser EBML.

#### Emparejar sin identificador común

**Problema:** Los archivos `webcams.webm` y `deskshare.webm` descargados no comparten ningún identificador en el nombre (RID, timestamp, etc.) que permita emparejarlos directamente.

**Solución:** Se ordenan **ambos grupos por duración** y se emparejan por índice: el webcam más corto con el deskshare más corto, el segundo más corto con el segundo más corto, etc. Esto asume que grabaciones de la misma sesión tienen duraciones similares.

#### Diferencias de duración entre pares

**Problema:** No siempre coinciden exactamente: un webcam puede durar unos segundos más o menos que su deskshare correspondiente por diferencias en el inicio/fin de la grabación.

**Solución:** Se calcula la diferencia absoluta y se compara contra una **tolerancia configurable** (default 5 segundos). Los pares que superan la tolerancia se marcan como `[REVISAR]` en la salida, permitiendo al usuario inspeccionarlos manualmente sin interrumpir el flujo automatizado.

---

### Fusionador

#### Combinar video de un archivo con audio de otro

**Problema:** `deskshare.webm` contiene la pantalla compartida (video + audio ambiental) y `webcams.webm` contiene la cámara del presentador (video + audio del micrófono). Se necesita el **video del deskshare** pero el **audio del webcams** (el micrófono del presentador).

**Solución:** ffmpeg con **mapeo selectivo de streams**: `-map 0:v` selecciona la pista de video del primer archivo (deskshare), `-map 1:a` selecciona la pista de audio del segundo (webcams). El video se copia sin recodificar (`-c:v copy`) para mantener calidad y velocidad; el audio se recodifica al códec elegido (default `libopus`).

#### Procesar múltiples carpetas

**Problema:** El organizador puede generar decenas de carpetas `grabacion_NNN/` y se necesita procesarlas todas automáticamente.

**Solución:** El programa lista las subcarpetas del directorio base, filtra con una expresión regular (`^grabacion_(\d{3})$`) para identificar las carpetas válidas, extrae el número de 3 dígitos del nombre, y procesa cada una en orden. Si `fusionado_NNN.webm` ya existe, lo salta a menos que se use `--force`.

---

## Flujo completo

```bash
# 1. Extraer URLs desde SENCE
python recolector.py --headless --auto

# 2. Descargar los .webm (con wget, curl, etc.)
wget -i links_grabacion.txt

# 3. Organizar por duración en carpetas
python organizador.py

# 4. Fusionar cada par en un solo video
python fusionador.py
```

---

## Archivos del proyecto

| Archivo | Propósito |
|---------|-----------|
| `recolector.py` | Extrae URLs .webm desde SENCE vía ClaveÚnica |
| `organizador.py` | Empareja y organiza webcams/deskshare por duración |
| `fusionador.py` | Fusiona deskshare (video) + webcams (audio) en cada carpeta |
| `requirements.txt` | Dependencia: `selenium>=4.6` |
| `credenciales.json` | Configuración guardada (RUT, navegador, preferencias, contraseña opcional) |
| `links_grabacion.txt` | URLs .webm extraídas |
| `recolector_log.txt` | Log de ejecución (debug) |
| `README.md` | Este archivo |
