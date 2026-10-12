"""Enlaces de descarga: cuando la factura no viene adjunta sino en un enlace del email."""

from __future__ import annotations

import ipaddress
import re
import socket
from email.message import Message
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import httpx2 as httpx

from ..models import Adjunto, Enlace, nombres_unicos
from ..pdf import TAMANO_MAXIMO

MAX_ENLACES = 5  # por email
MAX_REDIRECCIONES = 5
TIEMPO_MAXIMO = 20  # segundos

# Solo se abren los enlaces que parecen llevar a una factura (por su texto o su URL)...
PALABRAS_FACTURA = ("factura", "invoice", "pdf", "descar", "download", "recibo", "rebut", "receipt", "document")
# ...y nunca los que tienen efecto al abrirlos.
PALABRAS_EXCLUIDAS = ("unsubscribe", "optout", "opt-out", "darse de baja", "donar-se de baixa", "cancelar suscrip")

_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


class ErrorEnlace(Exception):
    """El enlace no se puede o no se debe descargar. El mensaje va a la incidencia."""


class _LectorEnlaces(HTMLParser):
    def __init__(self):
        super().__init__()
        self.enlaces: list[Enlace] = []
        self._url: str | None = None
        self._texto: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._cerrar()
            self._url = dict(attrs).get("href")
        elif tag == "img" and self._url:  # botones hechos con una imagen
            self._texto.append(dict(attrs).get("alt") or "")

    def handle_endtag(self, tag):
        if tag == "a":
            self._cerrar()

    def handle_data(self, data):
        if self._url:
            self._texto.append(data)

    def _cerrar(self):
        if self._url:
            self.enlaces.append(Enlace(self._url.strip(), " ".join(" ".join(self._texto).split())))
        self._url, self._texto = None, []


def extraer_enlaces(html: str, texto: str) -> list[Enlace]:
    """Enlaces http(s) del cuerpo del email, sin repetir y en orden de aparición."""
    lector = _LectorEnlaces()
    lector.feed(html)
    lector.close()
    lector._cerrar()
    encontrados = lector.enlaces
    # En texto plano no hay "texto del enlace": se usa la línea en la que aparece.
    for linea in texto.splitlines():
        encontrados += [Enlace(url.rstrip(".,;:"), linea.strip()) for url in _URL.findall(linea)]

    unicos: dict[str, Enlace] = {}
    for enlace in encontrados:
        if enlace.url.lower().startswith(("http://", "https://")):
            unicos.setdefault(enlace.url, enlace)
    return list(unicos.values())


def candidatos(enlaces: list[Enlace]) -> list[Enlace]:
    """Los enlaces que merece la pena abrir, primero los que apuntan a un .pdf."""
    elegidos = []
    for enlace in enlaces:
        pista = f"{enlace.url} {enlace.texto}".lower()
        if any(p in pista for p in PALABRAS_FACTURA) and not any(p in pista for p in PALABRAS_EXCLUIDAS):
            elegidos.append(enlace)
    elegidos.sort(key=lambda e: not urlsplit(e.url).path.lower().endswith(".pdf"))
    return elegidos[:MAX_ENLACES]


class DescargadorEnlaces:
    def __init__(self, *, transport=None, resolver=socket.getaddrinfo):
        self._http = httpx.Client(
            transport=transport,
            timeout=TIEMPO_MAXIMO,
            follow_redirects=False,  # se siguen a mano para comprobar cada salto
            headers={"User-Agent": "trapella-facturas"},
        )
        self._resolver = resolver

    def descargar(self, enlaces: list[Enlace]) -> tuple[list[Adjunto], list[str]]:
        """Devuelve los PDF conseguidos y, de los enlaces que fallaron, por qué."""
        adjuntos: list[Adjunto] = []
        fallos: list[str] = []
        for enlace in candidatos(enlaces):
            try:
                datos, cabeceras = self._bajar(enlace.url)
            except ErrorEnlace as error:
                fallos.append(f"{_corta(enlace.url)} ({error})")
            except (httpx.HTTPError, httpx.InvalidURL) as error:
                fallos.append(f"{_corta(enlace.url)} (no se pudo descargar: {error})")
            else:
                # el botón y el enlace de texto suelen llevar al mismo archivo
                if not any(a.datos == datos for a in adjuntos):
                    adjuntos.append(Adjunto(_nombre(enlace.url, cabeceras), "application/pdf", datos))
        nombres_unicos(adjuntos)
        return adjuntos, fallos

    def _bajar(self, url: str) -> tuple[bytes, httpx.Headers]:
        for _ in range(MAX_REDIRECCIONES + 1):
            self._exigir_destino_publico(url)
            with self._http.stream("GET", url) as resp:
                if resp.next_request is not None:
                    url = str(resp.next_request.url)
                    continue
                if resp.status_code >= 400:
                    raise ErrorEnlace(f"el servidor responde {resp.status_code}")
                tipo = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                datos = bytearray()
                for trozo in resp.iter_bytes():
                    datos += trozo
                    if len(datos) > TAMANO_MAXIMO:
                        raise ErrorEnlace(f"pesa más de {TAMANO_MAXIMO // 1_048_576} MB")
                    if "pdf" not in tipo and len(datos) >= 1024 and b"%PDF-" not in datos[:1024]:
                        break
                if "pdf" not in tipo and b"%PDF-" not in datos[:1024]:
                    raise ErrorEnlace(f"no devuelve un PDF sino {tipo or 'otro tipo de archivo'}")
                return bytes(datos), resp.headers
        raise ErrorEnlace("demasiadas redirecciones")

    def _exigir_destino_publico(self, url: str) -> None:
        """El enlace lo escribe quien envía el email: no debe alcanzar la red local."""
        try:
            partes = urlsplit(url)
            host = partes.hostname
        except ValueError:
            raise ErrorEnlace("la dirección no es válida") from None
        if partes.scheme not in ("http", "https") or not host:
            raise ErrorEnlace("la dirección no es válida")
        try:
            direcciones = {info[4][0] for info in self._resolver(host, None)}
        except OSError:
            raise ErrorEnlace("no se encuentra el servidor") from None
        if not direcciones or not all(ipaddress.ip_address(d.split("%")[0]).is_global for d in direcciones):
            raise ErrorEnlace("apunta a una dirección interna")


def _nombre(url: str, cabeceras: httpx.Headers) -> str:
    """Nombre del archivo: el que diga el servidor o, si no, el final de la URL."""
    disposicion = Message()
    disposicion["content-disposition"] = cabeceras.get("content-disposition", "attachment")
    nombre = disposicion.get_filename() or unquote(urlsplit(url).path.rstrip("/"))
    nombre = PurePosixPath(str(nombre).replace("\\", "/")).name or "factura"
    return nombre if nombre.lower().endswith(".pdf") else f"{nombre}.pdf"


def _corta(url: str, largo: int = 100) -> str:
    return url if len(url) <= largo else f"{url[:largo]}…"
