# Experiencia Windows guiada

El flujo de organización es carpeta → análisis → **Revisar y organizar** → confirmación explícita → resultado. El acceso anterior a vista previa utiliza el mismo controlador. La revisión conserva filtros y selección al cancelar; no inicia otro diálogo ni un segundo worker al aceptar. Los conflictos dentro de la selección también se reservan en la vista previa.

Inicio reúne carpeta, rutas recientes, última organización y deshacer según la transacción disponible en esta sesión. Las opciones técnicas de organización y música se muestran bajo demanda. Biblioteca, revisión de duplicados y metadatos tienen accesos separados; la selección de la biblioteca se conserva al cambiar de pestaña.

La apariencia se valida y escribe una sola vez, mediante archivo temporal y reemplazo atómico. Un error conserva tanto la configuración anterior en memoria como el archivo anterior. El acento acepta `#RRGGBB`; el texto sobre el acento elige negro o blanco según contraste. Se conservan las claves y formatos existentes.

Las retiradas conservan el servicio existente: papelera si hay soporte, cuarentena `.quarantine` si falta `send2trash`. La confirmación anuncia ambas posibilidades y el registro comunica el destino utilizado; nunca se promete borrado directo. Los grupos muestran candidatos o coincidencias por hash. Los archivos mayores de 5000 MB usan muestras y requieren revisión; las coincidencias musicales tampoco garantizan archivos idénticos.

Discos distingue ausencia de SMART de una valoración disponible. SMART son indicadores del dispositivo, no una garantía de salud. Actividad prioriza procesos, resultado y deshacer; su registro técnico es desplegable. La cancelación se comunica como solicitada hasta finalizar la tarea.

## Verificación

`tests/test_guided_experience.py` cubre aceptación única y cancelación de la revisión, selección parcial, conflictos del lote, fallo de guardado, validación y contraste de acento, disponibilidad de deshacer, cuarentena y cancelación. La prueba de integración ejecuta `OrganizeWorker.run()` con archivos temporales, conserva un archivo sin seleccionar y un destino existente, y verifica los bytes después de deshacer.

Las pruebas y capturas deben ejecutarse con directorio de trabajo temporal antes de importar los servicios que crean caché o registros. Las capturas Qt con `QT_SCALE_FACTOR=1/1.25/1.5` ayudan a detectar recortes, pero no sustituyen la aceptación interactiva en un escritorio Windows con esos ajustes de escala. No se consideran verificadas las operaciones sobre archivos reales.
