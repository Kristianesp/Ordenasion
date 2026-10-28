# Guía de compilación del ejecutable — Ordenasion 4.0.0

Esta guía explica cómo se genera `Ordenasion_v4.0.0.exe` y qué hay que vigilar
para que el ejecutable siga siendo pequeño, arranque bien y no se lleve datos
personales. El procedimiento paso a paso de una release (comandos exactos,
smoke del EXE y publicación) está en
[`releases_tags_creacion_exes.md`](releases_tags_creacion_exes.md).

---

## 1. Resumen

| Elemento | Valor |
|---|---|
| Punto de entrada | `main_fluent.py` (el único; `main.py` y `main_optimized.py` ya no existen) |
| Spec de PyInstaller | `OrganizadorAlpha_OPTIMIZED.spec` (la única) |
| Resultado | Un único archivo `Ordenasion_v4.0.0.exe` (onefile, sin consola) |
| Nombre y versión | Salen de `src/utils/version.py` (`EXECUTABLE_NAME`, `APP_VERSION`) |
| Metadatos PE | `packaging/windows_version_info.txt` |
| Herramientas de build | `requirements-build.txt` (PyInstaller y hooks fijados) |
| Python | 3.12 o 3.13 x64 con el `venv` del proyecto |

No hay scripts `.bat` de compilación: se llama a PyInstaller directamente.
`arrancar_ordenasion.bat` sólo sirve para ejecutar la app desde el código.

---

## 2. Compilar

```powershell
py -3 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt

# Probar antes desde el código
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe main_fluent.py

# Compilar
.\venv\Scripts\python.exe -m PyInstaller --clean --noconfirm OrganizadorAlpha_OPTIMIZED.spec
```

El ejecutable queda en `dist\Ordenasion_v4.0.0.exe`. Para una release usa los
directorios propios por versión (`--distpath`/`--workpath`) y el `PATH` acotado
que se describen en `releases_tags_creacion_exes.md`.

---

## 3. Qué incluye la spec y por qué

- **Datos:** `assets/branding`, `assets/fonts` (Nunito + OFL), `design-tokens.json`
  y `LICENSE`.
- **Binarios opcionales:** `bin/smartctl.exe` (salud SMART) y `bin/fpcalc.exe`
  (Chromaprint para música) sólo si existen en `bin/`. Sin ellos la app funciona
  y explica qué falta.
- **Imports ocultos:** módulos Qt usados (incluido `QtMultimedia`), `psutil`,
  `wmi`, `mutagen` y las páginas y diálogos que se cargan bajo demanda
  (`lazy_gui_modules`). Música, Duplicados y Discos se construyen la primera vez
  que se abren, así que PyInstaller no los ve al analizar el arranque: **si añades
  una página o diálogo que se importa dentro de una función, añádelo a
  `lazy_gui_modules`.**
- **Exclusiones:** `matplotlib`, `numpy`, `reportlab`, `schedule`, `torch`,
  WebEngine, Charts y `pytest`.
- **DLL del sistema:** se quitan `ucrtbase.dll` y las ICU que PyInstaller pueda
  encontrar en el `PATH`; Qt usa las de Windows.

**Nunca se empaquetan datos del usuario.** La configuración, los perfiles, las
cachés (`hash_cache.db`, `media_index.db`, `smart_history.db`) y los registros de
operaciones viven en `%LOCALAPPDATA%\Ordenasion` (ver `src/utils/paths.py`), no
en la carpeta del proyecto. La primera vez que arranca la 4.0, la app copia los
archivos que encuentre junto al ejecutable o en el directorio de trabajo
(versiones ≤ 3.5) a esa carpeta.

---

## 4. Lecciones aprendidas (siguen vigentes)

1. **No usar `collect_all()`.** En la 3.0 metía PyTorch, matplotlib y numpy y el
   ejecutable llegó a 3 GB. Los hooks oficiales de Qt reúnen lo necesario.
2. **`ApplicationState` no hereda de `QObject`.** Con PyInstaller, un singleton que
   hereda de `QObject` se bloqueaba en `QObject.__init__()`. Las señales van en un
   `_SignalEmitter` interno creado bajo demanda (`src/core/application_state.py`).
3. **Nada de `print()` con emojis.** En el EXE sin consola la codificación cp1252
   rompía la salida. Todo pasa por `src/utils/logger.py` (UTF-8, seguro sin
   consola); `ORDENASION_DEBUG=1` muestra los mensajes de depuración.
4. **Cerrar la ventana antes de que Python termine.** `main_fluent.main()` llama a
   `dispose_window()` al salir; sin eso, la limpieza de PyQt podía terminar en un
   fallo de segmentación con la tabla Fluent.
5. **Subprocesos sin ventana.** Todas las llamadas a `smartctl` usan
   `CREATE_NO_WINDOW` y UTF-8; en un EXE `--noconsole` cualquier otra cosa hace
   parpadear una consola.

---

## 5. Comprobaciones después de compilar

- [ ] `dist\Ordenasion_v4.0.0.exe` existe; anota tamaño y SHA-256 (no hay un
      límite fijo, pero un salto grande indica una dependencia nueva).
- [ ] Propiedades del archivo → Detalles: versión 4.0.0 e icono correctos.
- [ ] El smoke aislado (`ORDENASION_SMOKE=1`) termina con código 0 y el JSON
      dice `status=ok` (comandos en `releases_tags_creacion_exes.md`).
- [ ] Al abrirlo normalmente: splash, ventana Fluent, todas las páginas abren,
      se detectan los discos y Configuración guarda en `%LOCALAPPDATA%\Ordenasion`.
- [ ] Con permisos de usuario normal, Discos ofrece «Reintentar como
      administrador» si smartctl lo necesita.

---

## 6. Problemas habituales

| Síntoma | Causa probable | Solución |
|---|---|---|
| `ModuleNotFoundError` sólo en el EXE | Módulo importado dentro de una función | Añadirlo a `lazy_gui_modules` / `hiddenimports` |
| El EXE no muestra ventana | Error antes de la primera pintura | Ejecutar el smoke y revisar su JSON; compilar temporalmente con `console=True` |
| Ejecutable de cientos de MB | Dependencia pesada nueva o `collect_all()` | Revisar `build\*\warn-*.txt` y la lista de exclusiones |
| La salud SMART sale como no disponible | Falta `bin\smartctl.exe` o hacen falta permisos | Copiar smartctl en `bin\` (ver `INSTRUCCIONES_SMARTCTL.md`) o usar «Reintentar como administrador» |
| Fallo al cerrar la app | Ventana destruida después de Python | Mantener la llamada a `dispose_window()` en `main_fluent.py` |

---

## Historial

- **4.0.0 (2026-10):** spec y guía actualizadas a la página Organizar nativa
  (sin `main_window.py`), páginas bajo demanda, datos de usuario en
  `%LOCALAPPDATA%` y salida ordenada con `dispose_window()`.
- **3.5.0 (2026-09):** entrada única `main_fluent.py`, EXE onefile Fluent con
  metadatos PE y smoke aislado.
- **3.0.2 (2025-11):** tamaño de 3 GB → 38 MB quitando `collect_all()`, bloqueo de
  `QObject.__init__()` y errores de Unicode resueltos.
