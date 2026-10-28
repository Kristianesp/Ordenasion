# DESIGN.md — Sistema de Diseño Ordenasion

Sistema visual único para toda la aplicación (shell Fluent V2 + páginas legacy).
Fuente de verdad: `src/gui/v2/theme.py` (tokens Python) y `design-tokens.json` (export).

## 1. Principios

1. **Un solo azul.** El acento configurable del usuario es el único color primario.
   Ningún módulo define su propio azul.
2. **Ocean Frost sobrio.** Fondo azul/cian estático → vidrio blanco neutro →
   controles sólidos. Hasta tres capas; bordes y reflejos discretos de 1px.
3. **Semántica sobre decoración.** Verde = éxito, ámbar = aviso, rojo = peligro.
   El color de estado conserva su significado sobre el fondo atmosférico.
4. **Tipografía con escala fija.** Nada de tamaños ad-hoc: siempre la escala
   tipográfica definida abajo.

## 2. Tokens de color

### Modo claro

| Token | Valor | Uso |
|---|---|---|
| `canvas` | `#F3F6FB` | Fondo de ventana |
| `surface` | `#FFFFFF` | Tarjetas, tablas, inputs |
| `surface_alt` | `#E9EFF7` | Cabeceras, filas alternas, chips, nav |
| `stroke` | `#D5DFEA` | Bordes sutiles (1px) |
| `text_primary` | `#1A2430` | Texto principal |
| `text_secondary` | `#40546B` | Texto secundario, placeholders |
| `accent` | `#0F6CBD` | Acción primaria, selección (configurable) |
| `success` | `#0E700E` | Estados positivos |
| `warning` | `#8A5300` | Avisos (legible como texto sobre claro) |
| `danger` | `#C42B1C` | Errores, acciones destructivas |

### Modo oscuro

| Token | Valor | Uso |
|---|---|---|
| `canvas` | `#101827` | Fondo de ventana |
| `surface` | `#182337` | Tarjetas, tablas, inputs |
| `surface_alt` | `#22324A` | Cabeceras, filas alternas, chips, nav |
| `stroke` | `#3A4D66` | Bordes sutiles |
| `text_primary` | `#F5F9FF` | Texto principal |
| `text_secondary` | `#B9C8D9` | Texto secundario |
| `accent` | `#60CDFF` | Acción primaria, selección |
| `success` | `#6CCB5F` | Estados positivos |
| `warning` | `#FFD666` | Avisos (más legible que amarillo puro) |
| `danger` | `#FF99A4` | Errores |

**Regla de estado sobre fondo:** los colores semánticos se usan como *texto*
sobre la superficie del tema (nunca bloques saturados). Para fondos suaves usar
`_rgba(color, 0.12)`.

**Contraste:** objetivo WCAG AA (≥4.5:1) para texto principal y secundario,
comprobado sobre el fondo compuesto y los controles sólidos. Por eso
el `warning` oscuro pasa de `#FCE100` a `#FFD666` y el claro de `#9D5D00` a
`#8A5300`.

## 3. Tipografía

Familia: **Nunito** embebida, luego Segoe UI Variable / Segoe UI / Aptos.

Tamaño base: `interface.font_size` (11 / 13 / 15) × escala de pantalla 0.9–1.1, en **píxeles**.

Escala (px relativos al cuerpo `b`):

| Rol | Tamaño | Peso |
|---|---|---|
| Display (título de página) | `b + 8` | 700 |
| Title (título de tarjeta) | `b + 2` (mín. 14) | 600 |
| Body | `b` | 400–600 |
| Small / métricas etiqueta | `b - 2` (mín. 11) | 600 |
| Caption | `b - 3` (mín. 10) | 400 |

Altura de control: `b + 20` (cómoda) o `b + 16` (compacta). Padding horizontal 12 / 8. Radio 8.

Prohibido: tamaños literales (`28px`, `20px`, `14px`) y `setFixedHeight` de controles fuera de `apply_control_size`.

## 4. Espaciado — escala 4px

Solo estos valores: `4 · 8 · 12 · 16 · 20 · 24 · 32`.

| Contexto | Valor |
|---|---|
| Margen exterior de página | 24–32 |
| Padding interior de tarjeta | 16–20 |
| Espaciado entre tarjetas | 12–16 |
| Gap entre controles | 8–12 |
| Padding compacto (chips/badges) | 4–8 |

Prohibido: márgenes arbitrarios tipo `(9, 7, 9, 7)` o `(2, 8, 2, 8)`.

## 5. Radio de borde — escala

Solo: `4 · 6 · 8 · 12 · 16`.

| Elemento | Radio |
|---|---|
| Progress bar / chip pequeño | 4 |
| Inputs y botones | 8 |
| Tarjetas de vidrio | 16 |
| Superficies de datos heredadas | 12 |

Prohibido: píldoras (15px) salvo badges circulares explícitos; cualquier valor
fuera de la escala.

## 6. Componentes canónicos

- **PageHeader**: título jerárquico + subtítulo + acciones a la derecha, sin caja adicional.
- **GlassCard / SurfaceCard**: vidrio blanco neutro con contorno 1px y reflejo superior.
- **MetricCard**: valor + etiqueta + detalle sobre vidrio; sin franjas saturadas.
- **ActionBar**: fila de acciones con gap 10.
- **Botón primario**: relleno accent sólido, texto negro o blanco según contraste, radio 8, sin sombra de color.
- **Botón secundario**: `surface_alt` + stroke, mismo radio/altura.
- **Botón destructivo**: relleno danger, reservado para borrar/eliminar.

Estados obligatorios: hover (superficie + borde accent), pressed (superficie o
variación de luminosidad del accent sin mover el control), focus (borde de alto
contraste 2px en botones, accent en campos), disabled (`text_secondary`, sin borde
accent). Los scrollbars usan estilo overlay fino con pulgar `stroke` →
`text_secondary` en hover.

## 7. Iconografía

Un solo sistema: **FluentIcon** (vectorial) en botones, navegación y tarjetas.
Los emojis dentro de contenido HTML se permiten únicamente cuando acompañan
datos (identificación rápida de métricas), nunca como iconografía de UI.

## 8. Anti-slop (reglas duras)

1. Un único fondo mesh azul/cian estático, suave y cacheado por tamaño/tema.
   Sin animación continua, halos ni fondos competidores por pantalla.
2. Un único azul primario; prohibido introducir nuevos hex azules fuera de tokens.
3. Sin sombras de color saturadas; elevación implícita por capa + stroke.
4. Vidrio limitado a navegación y tarjetas; campos, tablas y CTA sólidos.
   En Qt se compone un fondo previamente suavizado con superficies translúcidas:
   no es blur nativo, no usa Win32, `backdrop-filter` ni difumina widgets/texto.
5. Sin `setStyleSheet` inline con colores hardcodeados en módulos de features;
   consumir tokens vía `_get_analysis_colors()` o QSS centralizado.

## 9. Migración de paletas huérfanas

Estas paletas quedan **deprecadas** y deben consumir tokens:

- `src/gui/modern_components.py` (`COLORS` Material)
- `src/gui/duplicates_dashboard.py` (`_get_theme_colors` Tailwind)
- `src/gui/notification_manager.py` (`_get_type_colors`)
- `src/gui/splash_screen.py` (gradiente)
- `src/gui/music_duplicates_presenters.py` (badges)

## 10. Ocean Frost: composición Qt

`OceanBackdrop` dibuja tres gradientes radiales amplios y guarda el resultado por
tamaño/tema/DPR. `GlassCard` conserva las señales Fluent y pinta únicamente el
fondo, el contorno y el reflejo; el contenido se dibuja después con nitidez.
Las páginas/scroll areas son transparentes para compartir la misma atmósfera.

| Tema | Vidrio blanco | Borde blanco | Reflejo blanco |
|---|---|---|---|
| Claro | 184/255 | 224/255 | 242/255 |
| Oscuro | 16/255 | 34/255 | 62/255 |

El fondo frío tiene tokens propios y no cambia el acento elegido por el usuario.
No hay dependencias nuevas ni temporizadores de repintado continuo.

## 11. Configuración compacta y tema global

Configuración limita el contenido a 1120px lógicos centrados. Texto/espacio y
acento forman dos columnas; por debajo de 880px útiles se apilan. Los selectores
se acotan a 320px y las acciones mantienen su ancho natural. La muestra de color
acompaña al valor hexadecimal, sin sustituir su etiqueta visible.

El botón sol/luna de la barra superior es el único selector de modo visual.
Su área mide 36×36px, admite teclado y anuncia el tema actual y el destino. Si el
modo anterior era Sistema, el cambio parte del tema efectivo y guarda Claro u
Oscuro explícitamente. Un fallo de guardado conserva el tema y muestra un error.

Tras guardar, una captura en memoria del contenido anterior se desvanece durante
280ms sobre la nueva superficie. No difumina texto ni intercepta entrada; conserva
página y scroll. La doble pulsación se bloquea durante la transición y el overlay
se elimina al terminar, redimensionar o cerrar. No existe animación continua.
Guardar texto/acento/densidad conserva el modo global vigente.
El modal de organización conserva sus demás opciones; aplicar fuente desde él
refresca Fluent y respeta el modo global, sin reinstalar la paleta antigua.

## 12. Discos: uso del espacio

Discos abre **Unidades y salud**. El selector **Uso del espacio** conserva su
inventario al cambiar de vista y sólo analiza al pulsar Analizar. Lee nombres y
`st_size` de archivos regulares (incluidos ocultos); no abre su contenido ni
modifica archivos. Los totales son bytes lógicos por ruta, sin deduplicar enlaces
duros; la ocupación y espacio libre de la unidad se presentan por separado.

El motor usa `os.scandir` iterativo y no sigue symlinks/junctions. Otros puntos de
reanálisis, como placeholders cloud accesibles, se cuentan por su metadata sin
leer contenido. Las entradas denegadas, desaparecidas y errores quedan con texto
en la tabla; el total parcial se conserva. Un origen ilegible produce un error.

Mapa squarified propio (`QPainter`) y tabla virtual (`QAbstractTableModel`) muestran
los hijos de la carpeta actual, por tamaño descendente. El mapa limita bloques y
agrupa áreas pequeñas; la tabla conserva todas las entradas. Seleccionar sincroniza
ambas vistas; Intro/doble clic entra sólo en carpetas, Retroceso/Subir vuelve al
padre. Migas y rutas se recortan con tooltip completo. Filtrar usa texto literal,
sin regex, en nombre/extensión de la carpeta actual. Top20 archivos/carpetas usa
índices globales del inventario; las carpetas de ese listado pueden solaparse.

Mapa y tabla forman columnas con al menos 980px útiles; debajo se apilan dentro
de la página desplazable. Abrir ubicación abre una carpeta, nunca el archivo;
Copiar ruta conserva la ruta exacta. Un fallo al abrir se comunica sin descartar
el inventario.

Un único worker prepara tamaños, hijos ordenados y top20 fuera del hilo GUI.
El indicador indeterminado aparece sólo mientras se analiza; el progreso incluye
ruta actual y bytes Python sin truncar, como máximo cada 200ms. Las lecturas
incompletas se anuncian como **Completado parcialmente**. Cancelar descarta el
análisis nuevo y conserva el anterior; los run IDs
descartan señales antiguas. Cerrar solicita cancelación y difiere el cierre hasta
`finished`, sin bloquear la GUI ni terminar el hilo por la fuerza.

## 13. Inicio: dashboard de snapshots

Inicio centra el contenido hasta 1440px. Cuatro métricas compactas muestran
ocupación/libre de la unidad elegida, tamaño y cantidades del último análisis de
espacio, tareas activas y archivos movidos en la última organización. Las métricas
forman cuatro columnas con 980px útiles y dos por debajo; las gráficas pasan de
dos columnas a una por debajo de 850px. Los accesos son botones compactos.

El donut usa exclusivamente el último snapshot de `DiskViewer` y muestra su hora
de actualización; un fallo conserva los datos y lo anuncia. No inicia consultas,
SMART ni sondeos. Ocupado y libre llevan valores y texto accesible; una diferencia
frente al total se etiqueta **Sin desglose**, sin atribuirla a reservas. Sin datos,
se muestra un estado vacío y un acceso a Unidades y salud.

**Qué ocupa espacio** usa los cinco hijos directos mayores de la raíz del último
análisis, incluidos archivos, y agrupa el resto. Las barras suman exactamente el
total lógico y no cuentan de nuevo carpetas anidadas. Un análisis parcial lo indica
con texto, incluso cuando no hay tamaños disponibles. Su acción abre el inventario
existente en Uso del espacio; no analiza automáticamente.

Actividad muestra estados reales del registro y añade el análisis de espacio
mientras su worker siga activo, incluida la cancelación pendiente. Resultado y
Deshacer dependen del estado del controlador. Las rutas recientes están acotadas,
la selección se conserva al actualizar snapshots o cambiar de tema y el selector
de organización sigue requiriendo una carpeta válida y revisión posterior.

## 14. Identidad y arranque

El icono propio usa una carpeta azul con tres documentos y transparencia. Qt lo
aplica a QApplication y a la ventana; se incluye PNG e ICO. El fondo ilustrado
navy se reserva para el splash y conserva el mesh estático de las páginas.
Los prompts y la procedencia ImageGen están en `assets/branding/README.md`.

El entrypoint muestra un splash ligero de 560×340 antes de los imports pesados.
Lee el modo guardado sin escribir configuración; system sigue el esquema de Qt.
Carga la fuente Nunito incluida antes de dibujar y aplica overlay claro/oscuro
con texto legible. «Preparando Ordenasion…» no representa un porcentaje ni una
animación que pueda congelarse durante la construcción síncrona de widgets.

La ventana ya lleva su paleta antes de maximizar y permanece con opacity 0 bajo
el splash hasta su primera pintura. En la siguiente vuelta del event loop se
revela y el splash se cierra, sin duración artificial. El cierre anticipado o un
error limpian el splash; un fallo muestra un mensaje y devuelve estado de error.
El splash heredado conserva su comportamiento para los otros entrypoints.

Los menús y diálogos musicales tienen superficie Fluent propia, también fuera
del shell. El helper asigna un nombre estable si falta, aplica campos/tablas y
estados de foco/deshabilitado, y los menús persistentes resuelven el tema de su
padre actual al abrir. Las variantes cargadas usan texto y superficie de tokens,
sin combinar fondos claros con etiquetas blancas. No cambian las acciones ni
la escritura de metadatos.
