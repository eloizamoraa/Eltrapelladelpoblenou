"""Detección de duplicados: mismo proveedor + mismo número + mismo importe."""

from __future__ import annotations

from .normalizacion import a_decimal, norm_cif, norm_nombre, norm_numero


def _mismo_proveedor(fila: dict, nombre: str, cif: str) -> bool:
    cif_fila, cif_nuevo = norm_cif(fila.get("CIF")), norm_cif(cif)
    if cif_fila and cif_nuevo:
        return cif_fila == cif_nuevo
    nombre_nuevo = norm_nombre(nombre)
    return bool(nombre_nuevo) and norm_nombre(fila.get("Proveedor")) == nombre_nuevo


def buscar_duplicado(
    filas: list[dict], *, proveedor: str, cif: str, numero: str | None, total: object
) -> dict | None:
    """Devuelve la fila ya registrada que coincide, o None.

    Sin número o sin total no se puede afirmar que sea un duplicado.
    """
    numero_n, total_d = norm_numero(numero), a_decimal(total)
    if not numero_n or total_d is None:
        return None
    for fila in filas:
        if (
            norm_numero(fila.get("Nº factura")) == numero_n
            and a_decimal(fila.get("Total")) == total_d
            and _mismo_proveedor(fila, proveedor, cif)
        ):
            return fila
    return None
