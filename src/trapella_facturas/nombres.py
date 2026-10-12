"""Nombre del archivo y carpeta de destino en Drive."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import PurePath

from .normalizacion import sin_acentos

MESES = [
    "01-Enero", "02-Febrero", "03-Marzo", "04-Abril", "05-Mayo", "06-Junio",
    "07-Julio", "08-Agosto", "09-Septiembre", "10-Octubre", "11-Noviembre", "12-Diciembre",
]  # fmt: skip


def slug(texto: str) -> str:
    """Deja solo letras, números y guiones: 'FA 2026/0158' -> 'FA-2026-0158'."""
    return re.sub(r"[^A-Za-z0-9]+", "-", sin_acentos(texto)).strip("-")


def nombre_factura(fecha: date, proveedor: str, numero: str, total: Decimal) -> str:
    """FECHA_PROVEEDOR_NUMFACTURA_IMPORTE.pdf"""
    return f"{fecha:%Y-%m-%d}_{slug(proveedor)}_{slug(numero)}_{total:.2f}.pdf"


def carpeta_factura(fecha: date, proveedor: str) -> list[str]:
    """año -> mes -> proveedor, según la fecha de la factura."""
    return [f"{fecha:%Y}", MESES[fecha.month - 1], proveedor.strip()]


def nombre_pendiente(fecha_email: date, nombre_original: str) -> str:
    """Nombre para lo que va a _REVISAR o _DUPLICADOS: se conserva el original."""
    ruta = PurePath(nombre_original or "adjunto")
    return f"{fecha_email:%Y-%m-%d}_{slug(ruta.stem) or 'adjunto'}{ruta.suffix.lower()}"
