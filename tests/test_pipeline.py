from conftest import factura

from trapella_facturas.extractor import ErrorExtraccion
from trapella_facturas.models import Adjunto, Incidencia, LineaIVA, Proveedor


def estados(resumen):
    return [r["estado"] for r in resumen["resultados"]]


def test_factura_correcta_se_archiva_y_registra(entorno):
    entorno.llega("m1", factura())
    resumen = entorno.pipeline().ejecutar()

    assert estados(resumen) == ["OK"]
    assert entorno.drive.rutas == ["2026/10-Octubre/Makro/2026-10-03_Makro_FA-2026-0158_170.50.pdf"]
    (fila,) = entorno.sheets.facturas()
    assert fila["Estado"] == "OK"
    assert fila["Proveedor"] == "Makro"
    assert (fila["Base 10%"], fila["IVA 10%"], fila["Base 21%"], fila["IVA 21%"]) == (100, 10, 50, 10.5)
    assert fila["Base 4%"] is None
    assert fila["Total"] == 170.5
    assert entorno.sheets.incidencias() == []
    assert entorno.gmail.etiquetas["m1"] == {"procesada"}


def test_no_se_procesa_dos_veces(entorno):
    entorno.llega("m1", factura())
    entorno.pipeline().ejecutar()
    resumen = entorno.pipeline().ejecutar()

    assert resumen["emails"] == 0
    assert len(entorno.sheets.facturas()) == 1


def test_duplicado_no_crea_fila_y_se_marca(entorno):
    entorno.llega("m1", factura())
    # mismo proveedor (por CIF), mismo número escrito distinto, mismo importe
    entorno.llega("m2", factura(numero_factura="fa 2026-0158", proveedor_nombre="Makro"))
    resumen = entorno.pipeline().ejecutar()

    assert estados(resumen) == ["OK", "DUPLICADO"]
    (fila,) = entorno.sheets.facturas()
    assert "Recibida otra vez" in fila["Posible duplicado"]
    (incidencia,) = entorno.sheets.incidencias()
    assert incidencia["Tipo"] == Incidencia.POSIBLE_DUPLICADO
    assert any(ruta.startswith("_DUPLICADOS/") for ruta in entorno.drive.rutas)
    assert entorno.gmail.etiquetas["m2"] == {"procesada", "incidencia"}


def test_mismo_numero_con_otro_importe_no_es_duplicado(entorno):
    entorno.llega("m1", factura())
    entorno.llega(
        "m2",
        factura(lineas_iva=[LineaIVA(tipo=10, base=200, cuota=20)], base_imponible=200, total_iva=20, total=220),
    )
    assert estados(entorno.pipeline().ejecutar()) == ["OK", "OK"]


def test_incidencias_van_a_revisar_sin_adivinar(entorno):
    entorno.llega("sin-numero", factura(numero_factura=None))
    entorno.llega("no-cuadra", factura(numero_factura="B-1", total=999))
    entorno.llega("dudoso", factura(numero_factura="B-2", importes_fiables=False))
    entorno.llega("desconocido", factura(numero_factura="B-3", proveedor_nombre="Otro SL", proveedor_cif="B11111111"))
    resumen = entorno.pipeline().ejecutar()

    assert estados(resumen) == ["REVISAR"] * 4
    tipos = [r["incidencias"] for r in resumen["resultados"]]
    assert tipos == [
        [Incidencia.FALTA_NUMERO],
        [Incidencia.IMPORTE_DUDOSO],
        [Incidencia.IMPORTE_DUDOSO],
        [Incidencia.PROVEEDOR_NO_RECONOCIDO],
    ]
    assert all(ruta.startswith("_REVISAR/") for ruta in entorno.drive.rutas)
    assert [f["Estado"] for f in entorno.sheets.facturas()] == ["REVISAR"] * 4
    assert len(entorno.sheets.incidencias()) == 4


def test_email_sin_pdf(entorno):
    entorno.gmail.anadir("m1", Adjunto("logo.png", "image/png", b"png"))
    resumen = entorno.pipeline().ejecutar()

    assert resumen["resultados"][0]["incidencias"] == [Incidencia.SIN_ADJUNTO_PDF]
    assert "logo.png" in resumen["resultados"][0]["detalle"]
    assert entorno.sheets.facturas() == []
    assert entorno.extractor.llamadas == 0


def test_pdf_no_valido_no_llega_al_extractor(entorno):
    entorno.gmail.anadir("m1", Adjunto("factura.pdf", "application/pdf", b"esto no es un pdf"))
    resumen = entorno.pipeline().ejecutar()

    assert resumen["resultados"][0]["incidencias"] == [Incidencia.PDF_NO_VALIDO]
    assert entorno.extractor.llamadas == 0
    assert entorno.drive.rutas == ["_REVISAR/2026-10-05_factura.pdf"]
    assert len(entorno.sheets.incidencias()) == 1


def test_documento_ilegible_o_que_no_es_factura(entorno):
    entorno.llega("m1", factura(legible=False))
    entorno.llega("m2", factura(es_factura=False, observaciones="Es un albarán."))
    entorno.llega("m3", ErrorExtraccion("La lectura quedó incompleta."))
    resumen = entorno.pipeline().ejecutar()

    assert [r["incidencias"] for r in resumen["resultados"]] == [
        [Incidencia.PDF_NO_VALIDO],
        [Incidencia.NO_ES_FACTURA],
        [Incidencia.ERROR_LECTURA],
    ]
    assert entorno.sheets.facturas() == []


def test_error_transitorio_deja_el_email_para_reintentar(entorno):
    entorno.llega("m1", ConnectionError("sin red"))
    resumen = entorno.pipeline().ejecutar()

    assert resumen["errores"][0]["id_mensaje"] == "m1"
    assert "m1" not in entorno.gmail.etiquetas
    assert entorno.sheets.incidencias() == []


def test_reprocesar_tras_alta_de_proveedor(entorno):
    entorno.llega("m1", factura(proveedor_nombre="Frutas Pérez, S.L.", proveedor_cif="B22222222"))
    entorno.pipeline().ejecutar()
    assert entorno.drive.rutas == ["_REVISAR/2026-10-05_factura.pdf"]

    entorno.sheets.alta_proveedor(Proveedor("Frutas Perez", "B22222222"))
    (resultado,) = entorno.pipeline().reprocesar("m1")

    assert resultado.estado == "OK"
    # el archivo se mueve y renombra; no se sube otra vez ni se crea otra fila
    assert entorno.drive.rutas == [
        "2026/10-Octubre/Frutas Perez/2026-10-03_Frutas-Perez_FA-2026-0158_170.50.pdf"
    ]
    (fila,) = entorno.sheets.facturas()
    assert (fila["Estado"], fila["Incidencias"]) == ("OK", "")
    assert entorno.sheets.incidencias()[0]["Estado"] == "Resuelta"
    assert entorno.gmail.etiquetas["m1"] == {"procesada"}


def test_dry_run_no_escribe_nada(entorno):
    entorno.llega("m1", factura())
    resumen = entorno.pipeline(dry_run=True).ejecutar()

    assert estados(resumen) == ["OK"]
    assert resumen["resultados"][0]["archivo"].endswith("Makro/2026-10-03_Makro_FA-2026-0158_170.50.pdf")
    assert entorno.drive.rutas == []
    assert entorno.sheets.facturas() == []
    assert entorno.gmail.etiquetas == {}


def test_varios_pdf_en_un_email(entorno):
    entorno.llega("m1", factura())
    pdf_a = entorno.gmail.emails["m1"].adjuntos[0]
    entorno.llega("m1", factura(numero_factura="FA-2026/0159"), nombre="otra.pdf")
    entorno.gmail.emails["m1"].adjuntos.insert(0, pdf_a)

    assert estados(entorno.pipeline().ejecutar()) == ["OK", "OK"]
    assert len(entorno.sheets.facturas()) == 2
