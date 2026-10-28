"""Genera las notas de una release a partir de su sección del CHANGELOG.

Uso:
    python tools/release_notes.py 4.0.1
    python tools/release_notes.py 4.0.1 --out notas.md --exe Ordenasion_v4.0.1.exe --mb 54 --sha <sha256> \\
        --portable Ordenasion_v4.0.1_portable.zip --portable-mb 70 --portable-sha <sha256>
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
LOGS_NOTE = (
    "Si la aplicación no se abre, el registro está en `%LOCALAPPDATA%\\Ordenasion\\logs`: "
    "`ordenasion.log` y, si el arranque se quedó bloqueado, `arranque-bloqueado.txt`."
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


def build_notes(version, exe=None, mb=None, sha=None, portable=None, portable_mb=None,
                portable_sha=None) -> str:
    parts = [PRERELEASE_NOTE, section(version)]
    downloads = []
    if exe:
        downloads.append(f"- **{exe}** ({mb} MB): un solo archivo. Al abrirlo se descomprime "
                         "en una carpeta temporal, así que tarda unos segundos en cada arranque "
                         "(más la primera vez, mientras Windows Defender lo analiza).")
    if portable:
        downloads.append(f"- **{portable}** ({portable_mb} MB): versión portable. Descomprímela en "
                         "una carpeta y abre el `.exe` de dentro: arranca mucho más rápido.")
    if downloads:
        parts.append("### Descargas\n\n" + "\n".join(downloads))
    hashes = [f"- `{sha}`  {exe}" if sha and exe else None,
              f"- `{portable_sha}`  {portable}" if portable_sha and portable else None]
    hashes = [line for line in hashes if line]
    if hashes:
        parts.append("**SHA-256:**\n\n" + "\n".join(hashes))
    parts.append(LOGS_NOTE)
    parts.append(DATA_NOTE)
    return "\n\n".join(parts) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--out")
    parser.add_argument("--exe")
    parser.add_argument("--mb")
    parser.add_argument("--sha")
    parser.add_argument("--portable")
    parser.add_argument("--portable-mb")
    parser.add_argument("--portable-sha")
    args = parser.parse_args(argv)
    notes = build_notes(args.version, args.exe, args.mb, args.sha,
                        args.portable, args.portable_mb, args.portable_sha)
    if args.out:
        Path(args.out).write_text(notes, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(notes)


if __name__ == "__main__":
    main()
