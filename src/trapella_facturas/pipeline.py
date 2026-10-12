"""Flujo completo: email -> PDF -> lectura -> validación -> Drive -> hoja de control."""

from __future__ import annotations

import logging
from datetime import datetime

from .config import CARPETA_DUPLICADOS, CARPETA_REVISAR
from .duplicados import buscar_duplicado
from .esquema import FILA, INCIDENCIA_PENDIENTE
from .extractor import ErrorExtraccion
from .models import Adjunto, DatosFactura, Email, Estado, Incidencia, Proveedor, Resultado
from .nombres import carpeta_factura, nombre_factura, nombre_pendiente
from .normalizacion import a_decimal, a_fecha
from .pdf import comprobar_pdf
from .validacion import validar

log = logging.getLogger(__name__)

TIPOS_IVA = (4, 10, 21)


def fila_factura(
    datos: DatosFactura,
    proveedor: Proveedor | None,
    estado: Estado,
    incidencias: list[tuple[Incidencia, str]],
    email: Email,
    adjunto: Adjunto,
) -> dict:
    """Convierte la factura leída en una fila de la pestaña Facturas."""
    bases: dict[object, float] = {}
    cuotas: dict[object, float] = {}
    for linea in datos.lineas_iva:
        clave = int(linea.tipo) if linea.tipo in TIPOS_IVA else "otros"
        bases[clave] = round(bases.get(clave, 0) + linea.base, 2)
        cuotas[clave] = round(cuotas.get(clave, 0) + linea.cuota, 2)

    fila = {
        "Estado": estado.value,
        "Fecha factura": a_fecha(datos.fecha_factura),
        "Proveedor": proveedor.nombre if proveedor else datos.proveedor_nombre,
        "CIF": datos.proveedor_cif or (proveedor.cif if proveedor else ""),
        "Nº factura": datos.numero_factura,
        "Vencimiento": a_fecha(datos.fecha_vencimiento),
        "Base otros": bases.get("otros"),
        "IVA otros": cuotas.get("otros"),
        "Base imponible": datos.base_imponible,
        "IVA total": datos.total_iva,
        "Rec. equiv.": datos.recargo_equivalencia,
        "IRPF": datos.retencion_irpf,
        "Total": datos.total,
        "Moneda": datos.moneda,
        "Incidencias": "\n".join(f"{tipo.value}: {detalle}" for tipo, detalle in incidencias),
        "Observaciones": datos.observaciones,
        "Remitente": email.remitente,
        "Asunto": email.asunto,
        "Fecha email": email.fecha,
        "Procesado el": datetime.now().replace(microsecond=0),
        "ID mensaje": email.id,
        "Adjunto original": adjunto.nombre,
    }
    for tipo in TIPOS_IVA:
        fila[f"Base {tipo}%"] = bases.get(tipo)
        fila[f"IVA {tipo}%"] = cuotas.get(tipo)
    return fila


class Pipeline:
    """Orquesta el procesado. Recibe los clientes ya construidos (ver app.py)."""

    def __init__(self, *, gmail, drive, sheets, extractor, dry_run: bool = False):
        self.gmail = gmail
        self.drive = drive
        self.sheets = sheets
        self.extractor = extractor
        self.dry_run = dry_run
        self.proveedores: list[Proveedor] = []
        self.filas: list[dict] = []
        self.pendientes: set[tuple[str, str]] = set()

    def _cargar_estado(self) -> None:
        self.proveedores = self.sheets.proveedores()
        self.filas = self.sheets.facturas()
        self.pendientes = {
            (str(f["ID mensaje"]), str(f["Adjunto"]))
            for f in self.sheets.incidencias()
            if f["Estado"] == INCIDENCIA_PENDIENTE
        }

    # --- entradas ----------------------------------------------------------

    def ejecutar(self, max_emails: int = 25) -> dict:
        """Procesa los emails pendientes del buzón y devuelve un resumen."""
        self._cargar_estado()
        resultados: list[Resultado] = []
        errores: list[dict] = []
        ids = self.gmail.buscar_pendientes(max_emails)
        for id_mensaje in ids:
            try:
                resultados += self.procesar_email(id_mensaje)
            except Exception as error:  # el email queda sin etiquetar y se reintenta
                log.exception("Error procesando el email %s; se reintentará", id_mensaje)
                errores.append({"id_mensaje": id_mensaje, "error": str(error)})
        return {
            "emails": len(ids),
            "simulacion": self.dry_run,
            "resultados": [r.como_dict() for r in resultados],
            "errores": errores,
        }

    def reprocesar(self, id_mensaje: str) -> list[Resultado]:
        """Vuelve a pasar un email, p. ej. tras dar de alta a su proveedor."""
        self._cargar_estado()
        if not self.dry_run:
            self.gmail.desmarcar(id_mensaje)
        return self.procesar_email(id_mensaje)

    def procesar_email(self, id_mensaje: str) -> list[Resultado]:
        email = self.gmail.leer_mensaje(id_mensaje)
        pdfs = [a for a in email.adjuntos if a.es_pdf]
        if pdfs:
            resultados = [self._procesar_adjunto(email, adjunto) for adjunto in pdfs]
        else:
            recibidos = ", ".join(a.nombre for a in email.adjuntos) or "ninguno"
            resultados = [
                self._solo_incidencia(
                    email, None, Incidencia.SIN_ADJUNTO_PDF, f"Adjuntos recibidos: {recibidos}."
                )
            ]
        for r in resultados:
            log.info("%s | %s | %s %s", email.asunto, r.adjunto or "-", r.estado.value, r.detalle)
        if not self.dry_run:
            hay_incidencia = any(r.estado not in (Estado.OK, Estado.OMITIDO) for r in resultados)
            self.gmail.marcar(id_mensaje, incidencia=hay_incidencia)
        return resultados

    # --- un adjunto --------------------------------------------------------

    def _procesar_adjunto(self, email: Email, adjunto: Adjunto) -> Resultado:
        clave = (email.id, adjunto.nombre)
        previa = next(
            (
                f
                for f in self.filas
                if str(f.get("ID mensaje")) == email.id
                and str(f.get("Adjunto original")) == adjunto.nombre
            ),
            None,
        )
        if previa and previa["Estado"] == Estado.OK:
            return Resultado(*clave, Estado.OMITIDO, detalle="Ya estaba registrada.")
        if previa is None and clave in self.pendientes:
            return Resultado(*clave, Estado.INCIDENCIA, detalle="Incidencia ya registrada y pendiente.")

        motivo = comprobar_pdf(adjunto.datos)
        if motivo:
            return self._solo_incidencia(email, adjunto, Incidencia.PDF_NO_VALIDO, motivo)
        try:
            datos = self.extractor.extraer(adjunto.datos)
        except ErrorExtraccion as error:
            return self._solo_incidencia(email, adjunto, Incidencia.ERROR_LECTURA, str(error))
        if not datos.legible:
            detalle = datos.observaciones or "El contenido del PDF no se puede leer."
            return self._solo_incidencia(email, adjunto, Incidencia.PDF_NO_VALIDO, detalle)
        if not datos.es_factura:
            detalle = datos.observaciones or "El documento no es una factura."
            return self._solo_incidencia(email, adjunto, Incidencia.NO_ES_FACTURA, detalle)

        incidencias, proveedor = validar(datos, self.proveedores)

        duplicada = buscar_duplicado(
            [f for f in self.filas if f is not previa],
            proveedor=proveedor.nombre if proveedor else (datos.proveedor_nombre or ""),
            cif=datos.proveedor_cif or (proveedor.cif if proveedor else ""),
            numero=datos.numero_factura,
            total=datos.total,
        )
        if duplicada:
            detalle = (
                f"Coincide con la fila {duplicada[FILA]} de Facturas: {duplicada['Proveedor']}, "
                f"nº {duplicada['Nº factura']}, total {duplicada['Total']}."
            )
            if previa is None:
                return self._duplicado(email, adjunto, duplicada, detalle)
            incidencias.append((Incidencia.POSIBLE_DUPLICADO, detalle))

        if incidencias:
            estado = Estado.REVISAR
            ruta = [CARPETA_REVISAR]
            archivo = nombre_pendiente(email.fecha, adjunto.nombre)
        else:
            estado = Estado.OK
            fecha = a_fecha(datos.fecha_factura)
            ruta = carpeta_factura(fecha, proveedor.nombre)
            archivo = nombre_factura(fecha, proveedor.nombre, datos.numero_factura, a_decimal(datos.total))

        resultado = Resultado(
            *clave,
            estado,
            incidencias=[tipo.value for tipo, _ in incidencias],
            detalle=" ".join(detalle for _, detalle in incidencias),
            archivo="/".join([*ruta, archivo]),
        )
        if self.dry_run:
            return resultado

        carpeta = self.drive.asegurar_ruta(ruta)
        if previa and previa.get("ID Drive"):
            id_drive = str(previa["ID Drive"])
            resultado.enlace = self.drive.mover(id_drive, carpeta, archivo)
        else:
            id_drive, resultado.enlace = self.drive.subir(archivo, adjunto.datos, "application/pdf", carpeta)

        fila = fila_factura(datos, proveedor, estado, incidencias, email, adjunto)
        fila |= {"Archivo": archivo, "Enlace Drive": resultado.enlace, "ID Drive": id_drive}
        if previa:
            fila |= {FILA: previa[FILA], "Posible duplicado": previa.get("Posible duplicado", "")}
            self.sheets.actualizar_factura(fila)
            self.filas[self.filas.index(previa)] = fila
        else:
            fila[FILA] = self.sheets.registrar_factura(fila)
            self.filas.append(fila)

        if incidencias:
            self._registrar_incidencia(email, resultado)
        elif clave in self.pendientes:
            self.sheets.resolver_incidencias(*clave)
            self.pendientes.discard(clave)
        return resultado

    # --- casos que no generan fila en Facturas -----------------------------

    def _duplicado(self, email: Email, adjunto: Adjunto, existente: dict, detalle: str) -> Resultado:
        resultado = Resultado(
            email.id, adjunto.nombre, Estado.DUPLICADO, [Incidencia.POSIBLE_DUPLICADO.value], detalle
        )
        if self.dry_run:
            return resultado
        self._guardar_pendiente(email, adjunto, resultado, CARPETA_DUPLICADOS)
        self.sheets.anotar_duplicado(
            existente,
            f"Recibida otra vez el {email.fecha:%Y-%m-%d} de {email.remitente}: {resultado.enlace}",
        )
        self._registrar_incidencia(email, resultado)
        return resultado

    def _solo_incidencia(
        self, email: Email, adjunto: Adjunto | None, tipo: Incidencia, detalle: str
    ) -> Resultado:
        nombre = adjunto.nombre if adjunto else ""
        resultado = Resultado(email.id, nombre, Estado.INCIDENCIA, [tipo.value], detalle)
        if self.dry_run or (email.id, nombre) in self.pendientes:
            return resultado
        if adjunto and adjunto.datos:
            self._guardar_pendiente(email, adjunto, resultado, CARPETA_REVISAR)
        self._registrar_incidencia(email, resultado)
        return resultado

    def _guardar_pendiente(self, email: Email, adjunto: Adjunto, resultado: Resultado, carpeta: str) -> None:
        """Sube el adjunto tal cual llegó, para que quien revise lo tenga a mano."""
        nombre = nombre_pendiente(email.fecha, adjunto.nombre)
        resultado.archivo = f"{carpeta}/{nombre}"
        _, resultado.enlace = self.drive.subir(
            nombre, adjunto.datos, adjunto.mime, self.drive.asegurar_ruta([carpeta])
        )

    def _registrar_incidencia(self, email: Email, resultado: Resultado) -> None:
        clave = (email.id, resultado.adjunto)
        if clave in self.pendientes:
            return
        self.sheets.registrar_incidencia(
            {
                "Fecha": datetime.now().replace(microsecond=0),
                "Tipo": "\n".join(resultado.incidencias),
                "Detalle": resultado.detalle,
                "Remitente": email.remitente,
                "Asunto": email.asunto,
                "Adjunto": resultado.adjunto,
                "Enlace Drive": resultado.enlace,
                "Enlace email": email.enlace,
                "ID mensaje": email.id,
            }
        )
        self.pendientes.add(clave)
