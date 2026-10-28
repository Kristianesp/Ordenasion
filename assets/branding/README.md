# Identidad de Ordenasion

Assets originales generados con el generador de imágenes integrado ImageGen.
No sustituyen el fondo mesh de la aplicación: el fondo ilustrado se usa sólo
durante el arranque.

- `ordenasion-icon.png`: carpeta azul redondeada con tres paneles alineados,
  orden y silueta O sutil, fondo transparente, Fluent sobrio, sin letras.
- `ordenasion-startup-background.png`: navy con reflejos azul hielo/teal y
  paneles esmerilados sólo en las esquinas; centro vacío para texto e icono.
- `ordenasion-icon.ico`: conversión de formato del PNG mediante Qt, sin cambiar
  el diseño. La aplicación utiliza el PNG como icono de Qt.

El splash lee sólo el tema guardado antes de los imports pesados, aplica una
capa clara/oscura legible y muestra «Preparando Ordenasion…». Se revela la ventana
maximizada y se cierra el splash tras su primera pintura, sin porcentaje ni
espera artificial. Si falla el arranque, se cierra y se comunica el error.
