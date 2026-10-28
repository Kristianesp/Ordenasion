# Cambios de Ordenasion

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
