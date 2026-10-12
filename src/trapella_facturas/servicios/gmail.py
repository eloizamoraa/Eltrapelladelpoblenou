"""Gmail: localizar los emails pendientes, leer sus adjuntos y etiquetarlos."""

from __future__ import annotations

import base64
from datetime import datetime

from ..config import ETIQUETA_INCIDENCIA, ETIQUETA_PROCESADA
from ..models import Adjunto, Email, nombres_unicos
from .enlaces import extraer_enlaces


class GmailClient:
    def __init__(self, servicio, query: str):
        self._mensajes = servicio.users().messages()
        self._etiquetas_api = servicio.users().labels()
        self._query = query
        self._etiquetas: dict[str, str] = {}

    def asegurar_etiquetas(self) -> dict[str, str]:
        """Crea las etiquetas si no existen y devuelve {nombre: id}."""
        if not self._etiquetas:
            existentes = self._etiquetas_api.list(userId="me").execute().get("labels", [])
            ids = {e["name"]: e["id"] for e in existentes}
            for nombre in (ETIQUETA_PROCESADA, ETIQUETA_INCIDENCIA):
                if nombre not in ids:
                    creada = self._etiquetas_api.create(userId="me", body={"name": nombre}).execute()
                    ids[nombre] = creada["id"]
                self._etiquetas[nombre] = ids[nombre]
        return self._etiquetas

    def buscar_pendientes(self, maximo: int = 25) -> list[str]:
        """IDs de los emails dirigidos al buzón que aún no llevan la etiqueta de procesado."""
        ids: list[str] = []
        token = None
        while len(ids) < maximo:
            resp = self._mensajes.list(
                userId="me", q=self._query, maxResults=min(100, maximo - len(ids)), pageToken=token
            ).execute()
            ids += [m["id"] for m in resp.get("messages", [])]
            token = resp.get("nextPageToken")
            if not token:
                break
        # Gmail devuelve primero lo más nuevo; se procesa por orden de llegada.
        return ids[:maximo][::-1]

    def leer_mensaje(self, id_mensaje: str) -> Email:
        msg = self._mensajes.get(userId="me", id=id_mensaje, format="full").execute()
        cabeceras = {c["name"].lower(): c["value"] for c in msg["payload"].get("headers", [])}
        email = Email(
            id=id_mensaje,
            remitente=cabeceras.get("from", ""),
            asunto=cabeceras.get("subject", ""),
            fecha=datetime.fromtimestamp(int(msg["internalDate"]) / 1000),
        )
        self._recoger_adjuntos(id_mensaje, msg["payload"], email.adjuntos)
        nombres_unicos(email.adjuntos)
        email.enlaces = extraer_enlaces(
            _cuerpo(msg["payload"], "text/html"), _cuerpo(msg["payload"], "text/plain")
        )
        return email

    def _recoger_adjuntos(self, id_mensaje: str, parte: dict, destino: list[Adjunto]) -> None:
        for sub in parte.get("parts", []):
            self._recoger_adjuntos(id_mensaje, sub, destino)
        if not parte.get("filename"):
            return
        cuerpo = parte.get("body", {})
        datos = cuerpo.get("data")
        if datos is None and cuerpo.get("attachmentId"):
            datos = (
                self._mensajes.attachments()
                .get(userId="me", messageId=id_mensaje, id=cuerpo["attachmentId"])
                .execute()["data"]
            )
        destino.append(
            Adjunto(
                nombre=parte["filename"],
                mime=parte.get("mimeType", ""),
                datos=base64.urlsafe_b64decode(datos or ""),
            )
        )

    def marcar(self, id_mensaje: str, *, incidencia: bool) -> None:
        etiquetas = self.asegurar_etiquetas()
        poner = [etiquetas[ETIQUETA_PROCESADA]]
        if incidencia:
            poner.append(etiquetas[ETIQUETA_INCIDENCIA])
        self._mensajes.modify(userId="me", id=id_mensaje, body={"addLabelIds": poner}).execute()

    def desmarcar(self, id_mensaje: str) -> None:
        etiquetas = self.asegurar_etiquetas()
        self._mensajes.modify(
            userId="me", id=id_mensaje, body={"removeLabelIds": list(etiquetas.values())}
        ).execute()


def _cuerpo(parte: dict, mime: str) -> str:
    """Texto de las partes del mensaje de ese tipo que no son adjuntos."""
    texto = "".join(_cuerpo(sub, mime) for sub in parte.get("parts", []))
    datos = parte.get("body", {}).get("data")
    if datos and parte.get("mimeType") == mime and not parte.get("filename"):
        texto += base64.urlsafe_b64decode(datos).decode("utf-8", errors="replace") + "\n"
    return texto
