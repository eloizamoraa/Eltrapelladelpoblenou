"""Comprobación previa del adjunto: ¿es un PDF que se puede abrir?"""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PyPdfError

TAMANO_MAXIMO = 20 * 1024 * 1024  # la API admite 32 MB por petición, ya en base64


def comprobar_pdf(datos: bytes) -> str | None:
    """Devuelve el motivo por el que el archivo no es válido, o None si lo es."""
    if not datos:
        return "El adjunto está vacío."
    if b"%PDF-" not in datos[:1024]:
        return "El archivo no es un PDF aunque lo parezca por el nombre."
    if len(datos) > TAMANO_MAXIMO:
        return f"El PDF pesa {len(datos) / 1_048_576:.0f} MB, demasiado para leerlo."
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            return "El PDF está protegido con contraseña."
        if len(lector.pages) == 0:
            return "El PDF no tiene páginas."
    except (PyPdfError, ValueError, OSError) as error:
        return f"El PDF está dañado y no se puede abrir ({error})."
    return None
