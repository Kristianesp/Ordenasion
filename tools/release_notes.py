"""Genera las notas de una release a partir de su sección del CHANGELOG.

Uso:
    python tools/release_notes.py 4.0.0
    python tools/release_notes.py 4.0.0 --out notas.md --exe Ordenasion_v4.0.0.exe --mb 61.2 --sha <sha256>
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRERELEASE_NOTE = (
    "> **Versión de prueba.** La lógica específica de Windows (mapeo de discos, UAC, "
    "tipos de unidad, tamaño en disco, barra de tareas) se valida con esta compilación "
    "antes de marcarla como definitiva."
)
DATA_NOTE = (
    "Tus datos se guardan ahora en `%LOCALAPPDATA%\\Ordenasion`; al abrir la 4.0 se "
    "copian automáticamente desde la ubicación anterior."
)


def section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(version)}\b.*?$(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not match:
        raise SystemExit(f"No hay sección {version} en CHANGELOG.md")
    return match.group(1).strip()


def build_notes(version, exe=None, mb=None, sha=None) -> str:
    parts = [PRERELEASE_NOTE, section(version)]
    if exe:
        parts.append(f"**Archivo:** {exe} · {mb} MB")
    if sha:
        parts.append(f"**SHA-256:** `{sha}`")
    parts.append(DATA_NOTE)
    return "\n\n".join(parts) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--out")
    parser.add_argument("--exe")
    parser.add_argument("--mb")
    parser.add_argument("--sha")
    args = parser.parse_args(argv)
    notes = build_notes(args.version, args.exe, args.mb, args.sha)
    if args.out:
        Path(args.out).write_text(notes, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(notes)


if __name__ == "__main__":
    main()
