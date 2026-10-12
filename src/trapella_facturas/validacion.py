"""Reglas que deciden si una factura leída es fiable o hay que señalar una incidencia.

Aquí no se adivina nada: si un dato falta o no cuadra, se devuelve la incidencia.
"""

from __future__ import annotations

from decimal import Decimal

from .models import DatosFactura, Incidencia, Proveedor
from .normalizacion import a_decimal, a_fecha, norm_cif, norm_nombre

TOLERANCIA_TOTAL = Decimal("0.02")
TOLERANCIA_CUOTA = Decimal("0.05")  # los redondeos línea a línea desvían algún céntimo


def reconocer_proveedor(
    nombre: str | None, cif: str | None, proveedores: list[Proveedor]
) -> Proveedor | None:
    """Busca primero por CIF; el nombre solo vale si no contradice un CIF conocido."""
    cif_n, nombre_n = norm_cif(cif), norm_nombre(nombre)
    if cif_n:
        for p in proveedores:
            if norm_cif(p.cif) == cif_n:
                return p
    if not nombre_n:
        return None
    for p in proveedores:
        if nombre_n not in {norm_nombre(n) for n in (p.nombre, *p.alias)}:
            continue
        if cif_n and norm_cif(p.cif):
            continue  # mismo nombre, distinto CIF: no es seguro que sea el mismo
        return p
    return None


def comprobar_importes(datos: DatosFactura) -> str | None:
    """Devuelve el motivo por el que el importe no es fiable, o None si cuadra."""
    total = a_decimal(datos.total)
    if total is None:
        return "No se ha podido leer el total."
    if not datos.importes_fiables:
        return "La lectura marca los importes como dudosos."

    extras = (a_decimal(datos.recargo_equivalencia) or 0) - (a_decimal(datos.retencion_irpf) or 0)
    if datos.lineas_iva:
        suma = Decimal(0)
        for linea in datos.lineas_iva:
            base, cuota = a_decimal(linea.base), a_decimal(linea.cuota)
            if base is None or cuota is None:
                return "Hay una línea de IVA incompleta."
            esperada = base * Decimal(str(linea.tipo)) / 100
            if abs(esperada - cuota) > TOLERANCIA_CUOTA:
                return f"La cuota del {linea.tipo:g}% ({cuota}) no corresponde a su base ({base})."
            suma += base + cuota
    else:
        base, iva = a_decimal(datos.base_imponible), a_decimal(datos.total_iva)
        if base is None or iva is None:
            return "No hay desglose de base e IVA para comprobar el total."
        suma = base + iva

    if abs(suma + extras - total) > TOLERANCIA_TOTAL:
        return f"Base + IVA suman {suma + extras}, pero el total leído es {total}."
    return None


def validar(
    datos: DatosFactura, proveedores: list[Proveedor]
) -> tuple[list[tuple[Incidencia, str]], Proveedor | None]:
    """Devuelve las incidencias (tipo, detalle) y el proveedor reconocido, si lo hay."""
    incidencias: list[tuple[Incidencia, str]] = []

    if not (datos.numero_factura or "").strip():
        incidencias.append((Incidencia.FALTA_NUMERO, "No aparece número de factura."))
    if a_fecha(datos.fecha_factura) is None:
        incidencias.append((Incidencia.FALTA_FECHA, "No se ha podido leer la fecha de factura."))

    motivo = comprobar_importes(datos)
    if motivo:
        incidencias.append((Incidencia.IMPORTE_DUDOSO, motivo))

    proveedor = reconocer_proveedor(datos.proveedor_nombre, datos.proveedor_cif, proveedores)
    if proveedor is None:
        leido = f"{datos.proveedor_nombre or 'sin nombre'} ({datos.proveedor_cif or 'sin CIF'})"
        incidencias.append(
            (
                Incidencia.PROVEEDOR_NO_RECONOCIDO,
                f"{leido} no está en la pestaña Proveedores.",
            )
        )
    return incidencias, proveedor
