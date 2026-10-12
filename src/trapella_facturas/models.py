"""Modelos de datos compartidos por todo el proyecto."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Incidencia(StrEnum):
    SIN_ADJUNTO_PDF = "Email sin PDF adjunto"
    PDF_NO_VALIDO = "Archivo no válido / PDF no legible"
    NO_ES_FACTURA = "El PDF no parece una factura"
    ERROR_LECTURA = "No se pudo leer la factura"
    FALTA_NUMERO = "Falta el número de factura"
    FALTA_FECHA = "Falta la fecha de factura"
    IMPORTE_DUDOSO = "Importe no fiable"
    PROVEEDOR_NO_RECONOCIDO = "Proveedor no reconocido"
    POSIBLE_DUPLICADO = "Posible duplicado"


class Estado(StrEnum):
    OK = "OK"
    REVISAR = "REVISAR"
    DUPLICADO = "DUPLICADO"  # no genera fila en Facturas
    INCIDENCIA = "INCIDENCIA"  # no se pudo leer nada: solo va a Incidencias
    OMITIDO = "OMITIDO"  # ya estaba procesado


class LineaIVA(BaseModel):
    tipo: float = Field(description="Tipo de IVA en porcentaje: 4, 10 o 21 (0 si es exento).")
    base: float = Field(description="Base imponible sujeta a este tipo.")
    cuota: float = Field(description="Cuota de IVA de este tipo.")


class DatosFactura(BaseModel):
    """Lo que el modelo lee del PDF. Lo que no aparece en el documento va a null."""

    es_factura: bool = Field(description="false si es un albarán, presupuesto, publicidad u otro documento.")
    legible: bool = Field(description="false si el documento está en blanco, cortado o no se puede leer.")
    proveedor_nombre: str | None = Field(description="Razón social del emisor de la factura.")
    proveedor_cif: str | None = Field(description="CIF/NIF del emisor, sin espacios ni guiones.")
    numero_factura: str | None = Field(description="Número de factura tal cual aparece impreso.")
    fecha_factura: str | None = Field(description="Fecha de emisión en formato AAAA-MM-DD.")
    fecha_vencimiento: str | None = Field(description="Fecha de vencimiento en formato AAAA-MM-DD.")
    lineas_iva: list[LineaIVA] = Field(description="Desglose de IVA, una entrada por tipo impositivo.")
    base_imponible: float | None = Field(description="Base imponible total.")
    total_iva: float | None = Field(description="Suma de todas las cuotas de IVA.")
    recargo_equivalencia: float | None = Field(description="Recargo de equivalencia, si lo hay.")
    retencion_irpf: float | None = Field(description="Retención de IRPF en positivo, si la hay.")
    total: float | None = Field(description="Total a pagar de la factura.")
    moneda: str | None = Field(description="Código ISO de la moneda, p. ej. EUR.")
    importes_fiables: bool = Field(
        description="false si algún importe es ambiguo, está tapado, borroso o hubo que deducirlo."
    )
    observaciones: str | None = Field(description="Dudas o anomalías, en una frase. null si no hay.")


@dataclass(frozen=True)
class Proveedor:
    nombre: str  # nombre canónico: se usa para la carpeta y el nombre de archivo
    cif: str = ""
    alias: tuple[str, ...] = ()


@dataclass
class Adjunto:
    nombre: str
    mime: str
    datos: bytes

    @property
    def es_pdf(self) -> bool:
        return self.mime == "application/pdf" or self.nombre.lower().endswith(".pdf")


@dataclass
class Email:
    id: str
    remitente: str
    asunto: str
    fecha: datetime
    adjuntos: list[Adjunto] = field(default_factory=list)

    @property
    def enlace(self) -> str:
        return f"https://mail.google.com/mail/u/0/#all/{self.id}"


@dataclass
class Resultado:
    """Qué pasó con un adjunto (o con un email sin adjuntos)."""

    id_mensaje: str
    adjunto: str
    estado: Estado
    incidencias: list[str] = field(default_factory=list)
    detalle: str = ""
    archivo: str = ""
    enlace: str = ""

    def como_dict(self) -> dict:
        return {
            "id_mensaje": self.id_mensaje,
            "adjunto": self.adjunto,
            "estado": self.estado.value,
            "incidencias": self.incidencias,
            "detalle": self.detalle,
            "archivo": self.archivo,
            "enlace": self.enlace,
        }
