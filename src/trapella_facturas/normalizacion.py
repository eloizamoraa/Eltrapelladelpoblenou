"""Normalización de textos para poder comparar proveedores, CIF y números de factura."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

_FORMAS_JURIDICAS = re.compile(r"\b(S\s?L\s?U|S\s?L\s?L|S\s?A\s?U|S\s?C\s?P|S\s?L|S\s?A|S\s?C|C\s?B)\b")


def sin_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def norm_cif(cif: object) -> str:
    limpio = re.sub(r"[^A-Z0-9]", "", sin_acentos(str(cif or "")).upper())
    # ES + 9 caracteres es el NIF-IVA intracomunitario del mismo CIF.
    return limpio[2:] if limpio.startswith("ES") and len(limpio) == 11 else limpio


def norm_nombre(nombre: object) -> str:
    """'Frutas Pérez, S.L.' -> 'FRUTASPEREZ'."""
    texto = re.sub(r"[^A-Z0-9 ]", " ", sin_acentos(str(nombre or "")).upper().replace(".", ""))
    texto = _FORMAS_JURIDICAS.sub(" ", texto)
    return re.sub(r"\s+", "", texto)


def norm_numero(numero: object) -> str:
    """'FA-2026/0158' -> 'FA20260158'. Acepta números que Sheets devuelve como float."""
    if isinstance(numero, float) and numero.is_integer():
        numero = int(numero)
    return re.sub(r"[^A-Z0-9]", "", sin_acentos(str(numero or "")).upper())


def a_decimal(valor: object) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except ArithmeticError:
        return None


def a_fecha(valor: object) -> date | None:
    """Acepta AAAA-MM-DD o el número de serie con el que Sheets devuelve las fechas."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)) and valor > 0:
        return date(1899, 12, 30) + timedelta(days=int(valor))
    try:
        return date.fromisoformat(str(valor or "").strip()[:10])
    except ValueError:
        return None
