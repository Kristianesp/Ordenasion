# Cambios de Ordenasion

## 4.0.1 — 2026-10-28

1. **El ejecutable vuelve a abrirse siempre:**
   - La ventana se mostraba con opacidad 0 y sólo se hacía visible tras su primera pintura; si Windows no la notificaba, quedaba invisible. Ahora se muestra igualmente a los 2,5 s.
   - La lectura de unidades de Inicio ya no bloquea el arranque: va en segundo plano, así que una unidad de red desconectada o un lector lento no congelan la ventana.
2. **Imagen de carga inmediata:** el `.exe` muestra la pantalla de Ordenasion nada más hacer doble clic, mientras se descomprime.
3. **Versión portable (`_portable.zip`):** no descomprime nada en cada arranque y abre mucho más rápido.
4. **Diagnóstico:**
   - Registro en `%LOCALAPPDATA%\Ordenasion\logs\ordenasion.log`, con cada fase del arranque y su tiempo.
   - Si la ventana no aparece en 20 s, `arranque-bloqueado.txt` guarda dónde se quedó cada hilo.
   - Los fallos graves quedan en `fallo-grave.txt`.
5. **Release verificada en Windows real:** la CI abre los dos formatos como un usuario, con el gestor de discos activo, y falla si la ventana no aparece.
6. **Rutas en formato de Windows:** favoritas, recientes y rutas protegidas se guardan con `\` y se comparan sin distinguir mayúsculas. Quitar una favorita pegada desde el Explorador ya funciona.

## 4.0.0 — 2026-10-28

1. **Organizar, ahora Fluent nativo:** la página deja de envolver la ventana
   antigua (`main_window.py` desaparece). Mantiene todas las funciones y añade
   orden por columna, arrastrar carpetas, política de conflictos en opciones
   avanzadas y diálogos de vista previa, resumen, tareas y reglas con aspecto
   nativo.
2. **Deshacer de verdad:** funciona en la sesión y tras reiniciar. Historial
   persistente en Actividad con «Deshacer» por operación. Nunca sobrescribe un
   origen ocupado, borra las carpetas que creó y no repite lo ya revertido.
3. **Organización más segura:**
   - «Organizar por fecha» ya no falla.
   - Cancelar o terminar con errores se informa como tal.
   - Cargar un perfil no borra las rutas protegidas.
   - Las carpetas de categoría no se reorganizan.
   - Una sola carpeta `VARIOS`.
   - Las reglas personalizadas se respetan.
   - Se ignoran `desktop.ini`, `Thumbs.db` y `~$*`, y no se siguen junctions.
   - La vista previa y la ejecución comparten un único plan.
4. **Duplicados fiables:**
   - «Híbrido», que confirma con hash, es el modo por defecto.
   - Nunca se retiran todas las copias de un grupo.
   - Las carpetas de cuarentena y ocultas se excluyen.
   - Los hardlinks no cuentan como duplicados.
   - Música: ya no agrupa pistas sin etiquetas o ilegibles; compara la duración
     con tolerancia y usa Chromaprint local cuando hace falta.
5. **Duplicados, novedades:**
   - Reglas para elegir qué copia conservar.
   - Sustituir copias por hardlinks.
   - Verificación byte a byte.
   - Imágenes parecidas (dHash).
   - Exportar el plan a CSV.
   - Cancelación real.
6. **Salud SMART correcta:**
   - Cada letra se asocia a su disco físico real.
   - El código de retorno de smartctl se interpreta como máscara de bits, así
     que los discos que fallan ya no salen «sin datos».
   - Temperatura, horas y TB escritos se leen de campos normalizados.
   - Hay salud también para HDD sin TBW y para NVMe.
   - Nada de smartctl en el hilo de la interfaz.
   - Historial con alertas de sectores, atributos críticos y «Reintentar como
     administrador».
7. **Uso del espacio:** tamaño en disco frente a lógico, desglose por extensión,
   CSV, reanálisis de subcarpeta, «Organizar esta carpeta» y un tercio de memoria
   por nodo. Inicio y Discos muestran el mismo porcentaje.
8. **Más rápido:**
   - Construir la ventana tarda ~0,6 s, antes ~1,75 s.
   - Cambiar de tema tarda ~0,2 s, antes ~0,85 s.
   - Música, Duplicados y Discos se cargan al abrirlas.
   - Una sola configuración en memoria.
   - El registro de operaciones es JSONL: 100.000 operaciones en menos de 1 s.
   - La caché de hashes es unas 50 veces más rápida.
9. **Shell:**
   - Los atajos funcionan y F1 muestra la ayuda.
   - Tema «Sistema» que sigue a Windows.
   - Insignia de tareas activas, aviso al terminar y progreso en la barra de
     tareas.
   - Recuerda la última página.
   - «Abrir en el Explorador».
   - Estados vacíos con acción.
   - Nuevas preferencias en Configuración.
10. **Datos y mantenimiento:**
    - Configuración, cachés y registros en `%LOCALAPPDATA%\Ordenasion`, con
      copia automática desde la ubicación antigua.
    - Un solo sistema de temas, sin código muerto (~3.300 líneas menos).
    - Dependencias acotadas.
    - CI con GitHub Actions y 299 tests.

La lógica específica de Windows (mapeo de discos, UAC, tipos de unidad, tamaño en
disco, barra de tareas) está probada con simulaciones; requiere validación en
equipos Windows reales antes de publicar el ejecutable.

## 3.5.0 — 2026-09-27

1. **Inicio operativo:** dashboard con ocupación disponible, último análisis de
   espacio, tareas y resultado de organización. Gráficas basadas en snapshots
   reales; estados vacíos y fallos de actualización explícitos.
2. **Fluent Ocean Frost:** fondo mesh estático, superficies de vidrio adaptadas
   a Qt, controles legibles y diseño adaptable. Tema global claro/oscuro con
   transición breve que conserva página, selección y scroll.
3. **Configuración compacta:** tarjetas con ancho acotado, selector de acento y
   etiquetas visibles. Validación y guardado atómico; los errores de escritura
   se comunican y guardar apariencia respeta el tema global vigente.
4. **Organización guiada:** carpeta → análisis → revisión → resultado. La
   confirmación ejecuta una sola vez, conserva filtros y selección y evita
   organizar un análisis obsoleto tras cambiar la ruta. Conflictos y Deshacer
   usan los servicios existentes y muestran su efecto real.
5. **Discos y uso del espacio:** salud conocida, no disponible o pendiente con
   texto explicativo. Nuevo análisis manual en segundo plano, mapa squarified,
   tabla virtual, navegación, filtro literal y top20. No sigue symlinks/junctions;
   contabiliza errores y resultados parciales. Cancelar conserva el inventario
   anterior y cerrar solicita cancelación cooperativa.
6. **Música progresiva:** biblioteca, búsqueda y reproducción priorizadas;
   duplicados y metadatos separados, diagnóstico/caché bajo demanda. Menús,
   editor, variantes y portadas tienen tema propio claro/oscuro y contraste.
7. **Duplicados y Actividad:** candidatos distinguidos de coincidencias
   confirmadas, copia conservada y destino de retirada explícitos. Acciones
   según selección y estado; progreso y resultados primero, registro técnico
   desplegable y cancelación solicitada sin prometer una parada inmediata.
8. **Arranque e identidad:** icono transparente propio, splash tematizado con
   fuente incluida y revelado tras la primera pintura. Sin porcentaje ni espera
   artificial. El BAT permite arrancar desde el venv y comprobar dependencias.
9. **Distribución Windows:** ejecutable Fluent onefile `Ordenasion_v3.5.0.exe`,
   metadatos PE, branding/fuentes/licencias y smoke opt-in aislado. No incluye
   preferencias, rutas, perfiles ni registros personales del workspace.

La validación usa fixtures temporales y Qt offscreen; la comprobación visual a
100/125/150 % no sustituye la aceptación en otros equipos o drivers de Windows.
