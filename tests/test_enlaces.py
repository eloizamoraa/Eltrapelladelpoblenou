import httpx2 as httpx
from conftest import descargador, pdf_valido

from trapella_facturas.models import Enlace
from trapella_facturas.servicios.enlaces import candidatos, extraer_enlaces
from trapella_facturas.servicios.gmail import _cuerpo

PDF = {"content-type": "application/pdf"}


def test_extraer_enlaces_de_html_y_texto():
    html = """
        <a href="https://x.example/d/1"><b>Descargar</b> factura</a>
        <a href="https://x.example/d/2"><img alt="Ver factura" src="boton.png"></a>
        <a href="mailto:hola@x.example">Escríbenos</a>
        <a href="https://x.example/d/1">repetido</a>
    """
    texto = "Tu factura está aquí: https://x.example/d/3.\nGracias"
    assert extraer_enlaces(html, texto) == [
        Enlace("https://x.example/d/1", "Descargar factura"),
        Enlace("https://x.example/d/2", "Ver factura"),
        Enlace("https://x.example/d/3", "Tu factura está aquí: https://x.example/d/3."),
    ]


def test_cuerpo_del_mensaje():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/html", "body": {"data": "PGEgaHJlZj0iaHR0cHM6Ly94LmV4YW1wbGUiPng8L2E-"}},
            {"mimeType": "text/html", "filename": "adjunto.html", "body": {"data": "bm8="}},
        ],
    }
    assert _cuerpo(payload, "text/html") == '<a href="https://x.example">x</a>\n'
    assert _cuerpo(payload, "text/plain") == ""


def test_solo_se_abren_los_enlaces_que_parecen_facturas():
    enlaces = [
        Enlace("https://x.example/", "Nuestra web"),
        Enlace("https://x.example/d/1", "Descargar factura"),
        Enlace("https://x.example/baja?unsubscribe=1", "No recibir más facturas"),
        Enlace("https://x.example/f/2026-158.pdf", ""),
        Enlace("https://x.example/logo.png", ""),
    ]
    assert [e.url for e in candidatos(enlaces)] == ["https://x.example/f/2026-158.pdf", "https://x.example/d/1"]


def test_descarga_sigue_redirecciones_y_pone_nombre():
    pdf = pdf_valido()
    web = {
        "https://x.example/factura/1": httpx.Response(302, headers={"location": "https://cdn.example/f?k=1"}),
        "https://cdn.example/f?k=1": httpx.Response(
            200, content=pdf, headers=PDF | {"content-disposition": 'attachment; filename="Fra 158.pdf"'}
        ),
        # sin tipo PDF declarado, pero lo es
        "https://x.example/descargar": httpx.Response(200, content=pdf + b"x"),
    }
    enlaces = [Enlace(url, "") for url in ("https://x.example/factura/1", "https://x.example/descargar")]
    adjuntos, fallos = descargador(web).descargar(enlaces)

    assert fallos == []
    assert [(a.nombre, a.datos, a.es_pdf) for a in adjuntos] == [
        ("Fra 158.pdf", pdf, True),
        ("descargar.pdf", pdf + b"x", True),
    ]


def test_el_mismo_pdf_en_dos_enlaces_solo_cuenta_una_vez():
    respuesta = httpx.Response(200, content=pdf_valido(), headers=PDF)
    web = {"https://x.example/factura/a": respuesta, "https://x.example/factura/b": respuesta}
    adjuntos, _ = descargador(web).descargar([Enlace(url, "") for url in web])
    assert len(adjuntos) == 1


def test_enlaces_que_no_dan_un_pdf():
    web = {
        "https://x.example/factura/login": httpx.Response(
            200, content=b"<html>Inicia sesion</html>", headers={"content-type": "text/html; charset=utf-8"}
        ),
        "https://x.example/factura/error": httpx.Response(500),
    }
    adjuntos, fallos = descargador(web).descargar([Enlace(url, "") for url in web])

    assert adjuntos == []
    assert "no devuelve un PDF sino text/html" in fallos[0]
    assert "responde 500" in fallos[1]


def test_no_se_alcanza_la_red_local():
    web = {
        "https://x.example/factura.pdf": httpx.Response(200, content=pdf_valido(), headers=PDF),
        "https://x.example/factura/salto": httpx.Response(302, headers={"location": "http://192.168.1.1/factura.pdf"}),
    }
    # el dominio del enlace resuelve a una IP privada
    adjuntos, fallos = descargador(web, ip="10.0.0.5").descargar([Enlace("https://x.example/factura.pdf", "")])
    assert adjuntos == [] and "dirección interna" in fallos[0]

    # un servidor público redirige a una IP privada
    def resolver(host, puerto):
        return [(0, 0, 0, "", ("192.168.1.1" if host == "192.168.1.1" else "93.184.216.34", 0))]

    d = descargador(web)
    d._resolver = resolver
    adjuntos, fallos = d.descargar([Enlace("https://x.example/factura/salto", "")])
    assert adjuntos == [] and "dirección interna" in fallos[0]

    adjuntos, fallos = d.descargar([Enlace("http://localhost:8080/factura.pdf", "")])
    d._resolver = lambda host, puerto: [(0, 0, 0, "", ("127.0.0.1", 0))]
    adjuntos, fallos = d.descargar([Enlace("http://localhost:8080/factura.pdf", "")])
    assert adjuntos == [] and "dirección interna" in fallos[0]
