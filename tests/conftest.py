"""Dobles en memoria de Gmail, Drive, Sheets y el extractor para probar el pipeline."""

from __future__ import annotations

import io
from datetime import datetime

import pytest
from pypdf import PdfWriter

from trapella_facturas.esquema import FILA, INCIDENCIA_PENDIENTE, INCIDENCIA_RESUELTA
from trapella_facturas.models import Adjunto, DatosFactura, Email, LineaIVA, Proveedor
from trapella_facturas.pipeline import Pipeline


def pdf_valido(marca: str = "") -> bytes:
    """Un PDF real de una página. `marca` lo hace distinto para el extractor falso."""
    escritor = PdfWriter()
    escritor.add_blank_page(width=200, height=200)
    escritor.add_metadata({"/Title": marca})
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


def factura(**cambios) -> DatosFactura:
    """Factura correcta de Makro: 100 al 10% + 50 al 21% = 170,50."""
    datos = dict(
        es_factura=True,
        legible=True,
        proveedor_nombre="MAKRO AUTOSERVICIO MAYORISTA S.A.U.",
        proveedor_cif="A28647451",
        numero_factura="FA-2026/0158",
        fecha_factura="2026-10-03",
        fecha_vencimiento="2026-11-02",
        lineas_iva=[LineaIVA(tipo=10, base=100, cuota=10), LineaIVA(tipo=21, base=50, cuota=10.5)],
        base_imponible=150,
        total_iva=20.5,
        recargo_equivalencia=None,
        retencion_irpf=None,
        total=170.5,
        moneda="EUR",
        importes_fiables=True,
        observaciones=None,
    )
    return DatosFactura(**(datos | cambios))


class GmailFalso:
    def __init__(self):
        self.emails: dict[str, Email] = {}
        self.etiquetas: dict[str, set[str]] = {}

    def anadir(self, id_mensaje: str, *adjuntos: Adjunto) -> None:
        self.emails[id_mensaje] = Email(
            id=id_mensaje,
            remitente="proveedor@example.com",
            asunto=f"Factura {id_mensaje}",
            fecha=datetime(2026, 10, 5, 9, 30),
            adjuntos=list(adjuntos),
        )

    def buscar_pendientes(self, maximo=25):
        return [i for i in self.emails if "procesada" not in self.etiquetas.get(i, set())][:maximo]

    def leer_mensaje(self, id_mensaje):
        return self.emails[id_mensaje]

    def marcar(self, id_mensaje, *, incidencia):
        self.etiquetas[id_mensaje] = {"procesada"} | ({"incidencia"} if incidencia else set())

    def desmarcar(self, id_mensaje):
        self.etiquetas.pop(id_mensaje, None)


class DriveFalso:
    def __init__(self):
        self.archivos: dict[str, str] = {}  # id -> ruta completa

    def asegurar_ruta(self, partes):
        return "/".join(partes)

    def subir(self, nombre, datos, mime, carpeta):
        id_archivo = f"drive-{len(self.archivos) + 1}"
        self.archivos[id_archivo] = f"{carpeta}/{nombre}"
        return id_archivo, f"https://drive.example/{id_archivo}"

    def mover(self, id_archivo, carpeta, nombre=None):
        self.archivos[id_archivo] = f"{carpeta}/{nombre}"
        return f"https://drive.example/{id_archivo}"

    @property
    def rutas(self) -> list[str]:
        return sorted(self.archivos.values())


class SheetsFalso:
    def __init__(self, proveedores):
        self._proveedores = list(proveedores)
        self._facturas: list[dict] = []
        self._incidencias: list[dict] = []

    def proveedores(self):
        return list(self._proveedores)

    def alta_proveedor(self, proveedor):
        self._proveedores.append(proveedor)

    def facturas(self):
        return [dict(f) for f in self._facturas]

    def incidencias(self):
        return [dict(f) for f in self._incidencias]

    def registrar_factura(self, fila):
        self._facturas.append({k: v for k, v in fila.items() if k != FILA} | {FILA: len(self._facturas) + 2})
        return self._facturas[-1][FILA]

    def actualizar_factura(self, fila):
        self._facturas[fila[FILA] - 2] = dict(fila)

    def anotar_duplicado(self, fila, nota):
        self._facturas[fila[FILA] - 2]["Posible duplicado"] = nota

    def registrar_incidencia(self, fila):
        self._incidencias.append({"Estado": INCIDENCIA_PENDIENTE} | fila | {FILA: len(self._incidencias) + 2})

    def resolver_incidencias(self, id_mensaje, adjunto):
        for fila in self._incidencias:
            if fila["ID mensaje"] == id_mensaje and fila["Adjunto"] == adjunto:
                fila["Estado"] = INCIDENCIA_RESUELTA


class ExtractorFalso:
    """Devuelve la lectura preparada para cada PDF (por contenido)."""

    def __init__(self):
        self.lecturas: dict[bytes, object] = {}
        self.llamadas = 0

    def extraer(self, pdf):
        self.llamadas += 1
        lectura = self.lecturas[pdf]
        if isinstance(lectura, Exception):
            raise lectura
        return lectura


class Entorno:
    def __init__(self):
        self.gmail = GmailFalso()
        self.drive = DriveFalso()
        self.sheets = SheetsFalso([Proveedor("Makro", "A28647451", ("Makro Autoservicio Mayorista",))])
        self.extractor = ExtractorFalso()

    def pipeline(self, **opciones) -> Pipeline:
        return Pipeline(
            gmail=self.gmail, drive=self.drive, sheets=self.sheets, extractor=self.extractor, **opciones
        )

    def llega(self, id_mensaje: str, lectura, nombre: str = "factura.pdf") -> None:
        """Simula un email con un PDF cuya lectura será `lectura`."""
        pdf = pdf_valido(id_mensaje + nombre)
        self.extractor.lecturas[pdf] = lectura
        self.gmail.anadir(id_mensaje, Adjunto(nombre, "application/pdf", pdf))


@pytest.fixture
def entorno() -> Entorno:
    return Entorno()
