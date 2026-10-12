"""Servidor MCP: permite a Claude (Code, Desktop...) operar y consultar el sistema.

Arranque:  trapella-facturas-mcp   (transporte stdio; ver .mcp.json)
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .app import configurar_logging, construir_pipeline, construir_sheets
from .config import cargar_settings
from .esquema import FILA, INCIDENCIA_PENDIENTE
from .models import Estado, Proveedor
from .normalizacion import a_decimal, a_fecha, norm_nombre
from .validacion import reconocer_proveedor

mcp = MCPServer(
    "trapella-facturas",
    instructions=(
        "Facturas de proveedores de El Trapella del Poblenou. Las facturas llegan por email, "
        "se archivan en Google Drive y se registran en una hoja de control. Las que no se "
        "pueden registrar con seguridad quedan como incidencias pendientes de revisión humana."
    ),
)


def _presentable(fila: dict) -> dict:
    """Fila de la hoja lista para devolver: sin vacíos y con las fechas legibles."""
    salida = {}
    for columna, valor in fila.items():
        if valor == "" or columna == FILA:
            continue
        if columna in ("Fecha factura", "Vencimiento", "Fecha email", "Procesado el", "Fecha"):
            valor = str(a_fecha(valor) or valor)
        salida[columna] = valor
    return salida | {"fila": fila[FILA]}


@mcp.tool()
def procesar_bandeja(max_emails: int = 25, simulacion: bool = False) -> dict:
    """Procesa los emails de facturas pendientes: lee cada PDF, lo archiva en Drive y lo
    registra en la hoja. Con simulacion=True solo informa de lo que haría, sin escribir nada.
    """
    return construir_pipeline(dry_run=simulacion).ejecutar(max_emails)


@mcp.tool()
def reprocesar_email(id_mensaje: str) -> list[dict]:
    """Vuelve a procesar un email ya tratado. Úsalo después de resolver la causa de una
    incidencia (p. ej. tras dar de alta al proveedor). El ID de mensaje está en la hoja.
    """
    return [r.como_dict() for r in construir_pipeline().reprocesar(id_mensaje)]


@mcp.tool()
def listar_incidencias(solo_pendientes: bool = True) -> list[dict]:
    """Incidencias registradas: facturas sin número, importes dudosos, proveedores no
    reconocidos, PDF no válidos y posibles duplicados.
    """
    filas = construir_sheets().incidencias()
    if solo_pendientes:
        filas = [f for f in filas if f["Estado"] == INCIDENCIA_PENDIENTE]
    return [_presentable(f) for f in filas]


@mcp.tool()
def buscar_facturas(
    proveedor: str = "",
    desde: str = "",
    hasta: str = "",
    estado: str = "",
    limite: int = 50,
) -> list[dict]:
    """Busca en la hoja de control. `proveedor` admite parte del nombre; `desde` y `hasta`
    son fechas de factura AAAA-MM-DD; `estado` es OK o REVISAR. Devuelve las más recientes.
    """
    f_desde, f_hasta = a_fecha(desde), a_fecha(hasta)
    encontradas = []
    for fila in construir_sheets().facturas():
        fecha = a_fecha(fila["Fecha factura"])
        if proveedor and norm_nombre(proveedor) not in norm_nombre(fila["Proveedor"]):
            continue
        if estado and fila["Estado"] != estado.upper():
            continue
        if (f_desde or f_hasta) and fecha is None:
            continue
        if (f_desde and fecha < f_desde) or (f_hasta and fecha > f_hasta):
            continue
        encontradas.append(_presentable(fila))
    return encontradas[-limite:][::-1]


@mcp.tool()
def resumen_iva(anio: int, mes: int = 0) -> dict:
    """Totales de base e IVA por tipo (4, 10, 21 y otros) de las facturas en estado OK de
    un año, o de un mes concreto si se indica `mes` (1-12). Las facturas en REVISAR no se
    suman; se informa de cuántas hay.
    """
    columnas = [
        "Base 4%", "IVA 4%", "Base 10%", "IVA 10%", "Base 21%", "IVA 21%",
        "Base otros", "IVA otros", "Base imponible", "IVA total", "IRPF", "Total",
    ]  # fmt: skip
    totales = dict.fromkeys(columnas, a_decimal(0))
    facturas = en_revision = 0
    for fila in construir_sheets().facturas():
        fecha = a_fecha(fila["Fecha factura"])
        en_periodo = fecha and fecha.year == anio and (not mes or fecha.month == mes)
        if fila["Estado"] != Estado.OK:
            # sin fecha legible no se sabe el periodo: se cuenta para no ocultarla
            en_revision += 1 if (fecha is None or en_periodo) else 0
            continue
        if not en_periodo:
            continue
        facturas += 1
        for columna in columnas:
            totales[columna] += a_decimal(fila[columna]) or 0
    return {
        "periodo": f"{anio}-{mes:02d}" if mes else str(anio),
        "facturas_sumadas": facturas,
        "facturas_en_revision_sin_sumar": en_revision,
        "totales": {columna: float(valor) for columna, valor in totales.items()},
    }


@mcp.tool()
def listar_proveedores() -> list[dict]:
    """Proveedores dados de alta. Solo las facturas de estos proveedores se archivan solas."""
    return [
        {"nombre": p.nombre, "cif": p.cif, "alias": list(p.alias)}
        for p in construir_sheets().proveedores()
    ]


@mcp.tool()
def alta_proveedor(nombre: str, cif: str = "", alias: list[str] | None = None) -> str:
    """Da de alta un proveedor. `nombre` es el nombre corto que se usará en carpetas y
    archivos; `alias` son otras formas en que aparece en las facturas (razón social, etc.).
    """
    sheets = construir_sheets()
    existente = reconocer_proveedor(nombre, cif, sheets.proveedores())
    if existente:
        return f"Ya existe: {existente.nombre} ({existente.cif or 'sin CIF'}). No se ha añadido."
    sheets.alta_proveedor(Proveedor(nombre.strip(), cif.strip(), tuple(alias or ())))
    return f"Proveedor {nombre} añadido."


def main() -> None:
    configurar_logging(cargar_settings())
    mcp.run("stdio")


if __name__ == "__main__":
    main()
