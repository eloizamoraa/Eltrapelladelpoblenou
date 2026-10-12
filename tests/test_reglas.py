from datetime import date
from decimal import Decimal

import pytest
from conftest import factura, pdf_valido

from trapella_facturas.duplicados import buscar_duplicado
from trapella_facturas.models import Adjunto, LineaIVA, Proveedor, nombres_unicos
from trapella_facturas.nombres import carpeta_factura, nombre_factura, nombre_pendiente
from trapella_facturas.normalizacion import a_fecha, norm_cif, norm_nombre, norm_numero
from trapella_facturas.pdf import comprobar_pdf
from trapella_facturas.servicios.sheets import _celda, _letra
from trapella_facturas.validacion import comprobar_importes, reconocer_proveedor

PROVEEDORES = [
    Proveedor("Makro", "A28647451", ("Makro Autoservicio Mayorista",)),
    Proveedor("Panadería Rosa", "", ()),
]


def test_normalizacion():
    assert norm_cif("ES-A28.647.451") == "A28647451"
    assert norm_nombre("Frutas Pérez, S.L.") == norm_nombre("FRUTAS PEREZ SL") == "FRUTASPEREZ"
    assert norm_numero("FA-2026/0158") == norm_numero("fa 2026 0158") == "FA20260158"
    assert norm_numero(12345.0) == "12345"
    assert a_fecha("2026-10-03") == date(2026, 10, 3)
    assert a_fecha(46298) == date(2026, 10, 3)  # número de serie de Sheets
    assert a_fecha("03/10/2026") is None


def test_reconocer_proveedor():
    assert reconocer_proveedor("Lo que sea", "a-28647451", PROVEEDORES).nombre == "Makro"
    assert reconocer_proveedor("MAKRO AUTOSERVICIO MAYORISTA S.A.U.", None, PROVEEDORES).nombre == "Makro"
    assert reconocer_proveedor("Panaderia Rosa", "B99999999", PROVEEDORES).nombre == "Panadería Rosa"
    # mismo nombre pero un CIF distinto al registrado: no se da por bueno
    assert reconocer_proveedor("Makro", "B00000000", PROVEEDORES) is None
    assert reconocer_proveedor(None, None, PROVEEDORES) is None


@pytest.mark.parametrize(
    "cambios, cuadra",
    [
        ({}, True),
        ({"total": 170.51}, True),  # un céntimo de redondeo
        ({"total": 171.0}, False),
        ({"total": None}, False),
        ({"importes_fiables": False}, False),
        ({"lineas_iva": [LineaIVA(tipo=10, base=100, cuota=21)], "total": 121}, False),
        ({"lineas_iva": []}, True),  # sin desglose por tipos, pero base + IVA = total
        ({"lineas_iva": [], "base_imponible": None}, False),
        ({"retencion_irpf": 15, "total": 155.5}, True),
        ({"recargo_equivalencia": 1.4, "total": 171.9}, True),
    ],
)
def test_comprobar_importes(cambios, cuadra):
    assert (comprobar_importes(factura(**cambios)) is None) == cuadra


def test_nombres_y_carpetas():
    assert (
        nombre_factura(date(2026, 3, 9), "Frutas Pérez", "A/2026 0012", Decimal("1234.5"))
        == "2026-03-09_Frutas-Perez_A-2026-0012_1234.50.pdf"
    )
    assert carpeta_factura(date(2026, 3, 9), "Frutas Pérez") == ["2026", "03-Marzo", "Frutas Pérez"]
    assert nombre_pendiente(date(2026, 3, 9), "Fra. nº 12.PDF") == "2026-03-09_Fra-no-12.pdf"


def test_buscar_duplicado():
    filas = [{"Proveedor": "Makro", "CIF": "A28647451", "Nº factura": "FA-2026/0158", "Total": 170.5}]
    igual = dict(proveedor="Makro", cif="A28647451", numero="FA 2026 0158", total=170.50)
    assert buscar_duplicado(filas, **igual) is filas[0]
    assert buscar_duplicado(filas, **(igual | {"total": 170.4})) is None
    assert buscar_duplicado(filas, **(igual | {"cif": "B00000000"})) is None
    assert buscar_duplicado(filas, **(igual | {"cif": ""})) is filas[0]  # sin CIF: por nombre
    assert buscar_duplicado(filas, **(igual | {"numero": None})) is None


def test_comprobar_pdf():
    assert comprobar_pdf(pdf_valido()) is None
    assert comprobar_pdf(b"") is not None
    assert comprobar_pdf(b"PK\x03\x04 un zip renombrado") is not None
    assert comprobar_pdf(b"%PDF-1.7 truncado") is not None


def test_celdas_de_la_hoja():
    assert _celda("0012") == "'0012"
    assert _celda("=IMPORTXML(...)") == "'=IMPORTXML(...)"
    assert _celda(170.5) == 170.5
    assert _celda(date(2026, 10, 3)) == "2026-10-03"
    assert _celda(None) == ""
    assert [_letra(i) for i in (0, 25, 26, 31)] == ["A", "Z", "AA", "AF"]


def test_adjuntos_con_el_mismo_nombre():
    adjuntos = [Adjunto("factura.pdf", "application/pdf", b"") for _ in range(3)]
    nombres_unicos(adjuntos)
    assert [a.nombre for a in adjuntos] == ["factura.pdf", "factura (2).pdf", "factura (3).pdf"]
