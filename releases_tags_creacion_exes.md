# Compilación y release de Ordenasion 3.5.0

## 1. Entorno y paquete

Usa Python 3.12 x64 y el venv del proyecto. Instala las dependencias de aplicación
más las herramientas de build, separadas de las de runtime:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
New-Item -ItemType Directory -Force artifacts/release-v3.5.0 | Out-Null
.\venv\Scripts\python.exe -m pip freeze > artifacts/release-v3.5.0/build-environment.txt
$buildOriginalPath = $env:PATH
$buildPythonBase = & .\venv\Scripts\python.exe -c "import sys; print(sys.base_prefix)"
$env:PATH = "$PWD\venv\Scripts;$buildPythonBase;$env:WINDIR\System32;$env:WINDIR"
.\venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath artifacts/release-v3.5.0/dist --workpath artifacts/release-v3.5.0/build OrganizadorAlpha_OPTIMIZED.spec
$env:PATH = $buildOriginalPath
```

La spec utiliza `main_fluent.py` para conservar la interfaz actual, splash y tema.
Produce un único `Ordenasion_v3.5.0.exe`, con icono/versión PE, QtMultimedia,
branding, Nunito/OFL, tokens y binarios auxiliares disponibles en `bin/`.
Los hooks de Qt reúnen los recursos necesarios; no se usa `collect_all()` ni se
agregan WebEngine, Charts, ciencia de datos o frameworks no utilizados.
El PATH acotado evita recoger DLL de otras herramientas instaladas. ICU y UCRT
se resuelven desde Windows; no se empaquetan copias ajenas al sistema.

No empaquetes `app_config.json`, `organization_profiles.json`, categorías locales,
bases de datos, logs, capturas ni datos personales. Los defaults están en el código.
Los archivos locales existentes se conservan y están ignorados por Git. Antes de
publicar revisa el índice explícito; evita `git add .` y no publiques `artifacts/`.

No hay límite arbitrario de 50 MB: registra tamaño real, SHA-256 y librerías Qt
incluidas. El archivo de entorno permite reproducir las versiones instaladas.
No borres builds anteriores: esta versión usa su directorio propio.

## 2. Smoke seguro del código y del EXE

El modo opt-in cambia primero a una carpeta temporal y bloquea análisis de discos,
organización automática, búsquedas online y escritura de metadatos. Construye la
ventana real, comprueba assets/QtMultimedia/splash/primera pintura y cierre.
Los errores devuelven código distinto de cero y quedan en JSON/log, sin MessageBox.

```powershell
$env:ORDENASION_SMOKE = '1'
$env:ORDENASION_SMOKE_REPORT = (Join-Path $PWD 'artifacts/release-v3.5.0/smoke-exe.json')
$env:QT_QPA_PLATFORM = 'offscreen'
$buildProcess = Start-Process -FilePath 'artifacts/release-v3.5.0/dist/Ordenasion_v3.5.0.exe' -WindowStyle Hidden -Wait -PassThru
$buildProcess.ExitCode
Get-Content $env:ORDENASION_SMOKE_REPORT
Remove-Item Env:ORDENASION_SMOKE, Env:ORDENASION_SMOKE_REPORT, Env:QT_QPA_PLATFORM
```

Para comprobar código usa el mismo entorno con
`.\venv\Scripts\python.exe main_fluent.py`. `ORDENASION_SMOKE_CAPTURE` permite
capturar la primera ventana dentro de la carpeta de QA. Un watchdog de seguridad
marca fallo si Qt no termina la pintura; no añade duración al arranque normal.
No ejecutes el EXE normal sobre las carpetas del usuario durante estas pruebas.

## 3. Revisión y publicación

Antes de publicar: pruebas focales vigentes, smoke empaquetado con exit0, archivo
JSON `status=ok`, versión PE correcta, assets presentes, ausencia de datos privados
en el archivo PyInstaller y `git diff --check`. Registra tamaño y SHA-256.

Commit, push, tag `v3.5.0` y GitHub Release requieren la autorización de publicación.
Haz stage de archivos revisados y deja fuera la configuración local. Adjunta sólo
`Ordenasion_v3.5.0.exe`, con las novedades numeradas de `CHANGELOG.md`; comprueba
posteriormente el asset remoto, versión, tamaño y hash. La compilación local no
confirma que el release esté publicado.
