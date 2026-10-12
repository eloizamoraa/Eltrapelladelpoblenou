"""Estructura de la hoja de control: pestañas y columnas.

Las filas se manejan como diccionarios {columna: valor}. Cambiar el orden o añadir
columnas al final es seguro; renombrar una existente obliga a renombrarla en la hoja.
"""

from __future__ import annotations

HOJA_FACTURAS = "Facturas"
HOJA_INCIDENCIAS = "Incidencias"
HOJA_PROVEEDORES = "Proveedores"

# Columna interna con el número de fila en la hoja (no se escribe).
FILA = "_fila"

COLUMNAS_FACTURAS = [
    "Estado",
    "Fecha factura",
    "Proveedor",
    "CIF",
    "Nº factura",
    "Vencimiento",
    "Base 4%",
    "IVA 4%",
    "Base 10%",
    "IVA 10%",
    "Base 21%",
    "IVA 21%",
    "Base otros",
    "IVA otros",
    "Base imponible",
    "IVA total",
    "Rec. equiv.",
    "IRPF",
    "Total",
    "Moneda",
    "Archivo",
    "Enlace Drive",
    "Incidencias",
    "Posible duplicado",
    "Observaciones",
    "Remitente",
    "Asunto",
    "Fecha email",
    "Procesado el",
    "ID mensaje",
    "Adjunto original",
    "ID Drive",
]

COLUMNAS_INCIDENCIAS = [
    "Fecha",
    "Estado",
    "Tipo",
    "Detalle",
    "Remitente",
    "Asunto",
    "Adjunto",
    "Enlace Drive",
    "Enlace email",
    "ID mensaje",
]

COLUMNAS_PROVEEDORES = ["Nombre", "CIF", "Alias (separados por ;)"]

INCIDENCIA_PENDIENTE = "Pendiente"
INCIDENCIA_RESUELTA = "Resuelta"

HOJAS = {
    HOJA_FACTURAS: COLUMNAS_FACTURAS,
    HOJA_INCIDENCIAS: COLUMNAS_INCIDENCIAS,
    HOJA_PROVEEDORES: COLUMNAS_PROVEEDORES,
}
