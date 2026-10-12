"""Lectura de la factura con Claude: PDF de entrada, DatosFactura de salida."""

from __future__ import annotations

import base64

import anthropic
from pydantic import ValidationError

from .config import Settings
from .models import DatosFactura

INSTRUCCIONES = """\
Lees facturas de proveedores recibidas por {empresa}{cif_empresa}, un restaurante de \
Barcelona, para registrarlas en contabilidad. Las facturas pueden estar en castellano \
o en catalán y a veces son escaneos o fotos.

{empresa} es siempre el cliente (destinatario). El proveedor es quien emite la factura: \
nunca devuelvas los datos de {empresa} como proveedor.

Lo que se registre aquí acaba en la contabilidad, así que un dato inventado es peor que \
un dato vacío. Copia cada dato tal como aparece impreso; si un dato no aparece o no se \
lee con claridad, devuélvelo como null y explica la duda en `observaciones`. No calcules \
importes que no estén escritos en el documento, y no deduzcas la fecha de vencimiento a \
partir de las condiciones de pago: solo va si aparece como fecha.

Marca `importes_fiables` como false si algún importe está borroso, tapado, corregido a \
mano o es ambiguo (por ejemplo, varios totales distintos). Los importes van como números \
con punto decimal, sin símbolo de moneda; en las facturas rectificativas, en negativo.

En `lineas_iva` va una entrada por cada tipo de IVA del cuadro de impuestos de la \
factura (habitualmente 4, 10 y 21), no una por cada producto."""


class ErrorExtraccion(Exception):
    """La factura no se ha podido leer; el motivo acaba como incidencia."""


class ExtractorFacturas:
    def __init__(self, settings: Settings, cliente: anthropic.Anthropic | None = None):
        self._cliente = cliente or anthropic.Anthropic()
        self._modelo = settings.modelo
        self._instrucciones = INSTRUCCIONES.format(
            empresa=settings.empresa_nombre,
            cif_empresa=f" (CIF {settings.empresa_cif})" if settings.empresa_cif else "",
        )

    def extraer(self, pdf: bytes) -> DatosFactura:
        """Los errores transitorios (red, límite de peticiones, 5xx) se propagan para
        que el email se reintente en la siguiente pasada."""
        try:
            respuesta = self._cliente.beta.messages.parse(
                model=self._modelo,
                max_tokens=16000,
                system=self._instrucciones,
                # Si un filtro de seguridad rechaza la petición, la sirve otro modelo.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": base64.standard_b64encode(pdf).decode("ascii"),
                                },
                            },
                            {"type": "text", "text": "Extrae los datos de esta factura."},
                        ],
                    }
                ],
                output_format=DatosFactura,
            )
        except anthropic.BadRequestError as error:
            raise ErrorExtraccion(f"La API no ha aceptado el documento: {error.message}") from error
        except ValidationError as error:
            raise ErrorExtraccion("La lectura devolvió datos con un formato inesperado.") from error

        if respuesta.stop_reason == "refusal":
            raise ErrorExtraccion("El modelo ha rechazado leer este documento.")
        if respuesta.stop_reason == "max_tokens" or respuesta.parsed_output is None:
            raise ErrorExtraccion("La lectura quedó incompleta.")
        return respuesta.parsed_output
