"""Google Drive: carpetas año/mes/proveedor y subida de los PDF."""

from __future__ import annotations

import io

from googleapiclient.http import MediaIoBaseUpload

MIME_CARPETA = "application/vnd.google-apps.folder"


class DriveClient:
    def __init__(self, servicio, raiz_id: str = ""):
        self._archivos = servicio.files()
        self._raiz = raiz_id
        self._cache: dict[tuple[str, str], str] = {}

    def crear_carpeta(self, nombre: str, padre: str | None = None) -> str:
        cuerpo = {"name": nombre, "mimeType": MIME_CARPETA}
        if padre:
            cuerpo["parents"] = [padre]
        return self._archivos.create(body=cuerpo, fields="id", supportsAllDrives=True).execute()["id"]

    def _asegurar_carpeta(self, nombre: str, padre: str) -> str:
        clave = (padre, nombre)
        if clave not in self._cache:
            escapado = nombre.replace("\\", "\\\\").replace("'", "\\'")
            encontradas = self._archivos.list(
                q=(
                    f"name = '{escapado}' and '{padre}' in parents "
                    f"and mimeType = '{MIME_CARPETA}' and trashed = false"
                ),
                fields="files(id)",
                pageSize=1,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute().get("files", [])
            self._cache[clave] = encontradas[0]["id"] if encontradas else self.crear_carpeta(nombre, padre)
        return self._cache[clave]

    def asegurar_ruta(self, partes: list[str]) -> str:
        """Crea (si hace falta) la ruta de carpetas bajo la raíz y devuelve el id de la última."""
        carpeta = self._raiz
        for parte in partes:
            carpeta = self._asegurar_carpeta(parte, carpeta)
        return carpeta

    def subir(self, nombre: str, datos: bytes, mime: str, carpeta: str) -> tuple[str, str]:
        """Sube un archivo y devuelve (id, enlace)."""
        media = MediaIoBaseUpload(io.BytesIO(datos), mimetype=mime or "application/octet-stream")
        creado = self._archivos.create(
            body={"name": nombre, "parents": [carpeta]},
            media_body=media,
            fields="id, webViewLink",
            supportsAllDrives=True,
        ).execute()
        return creado["id"], creado["webViewLink"]

    def mover(self, id_archivo: str, carpeta: str, nombre: str | None = None) -> str:
        """Mueve (y opcionalmente renombra) un archivo ya subido. Devuelve su enlace."""
        actual = self._archivos.get(fileId=id_archivo, fields="parents", supportsAllDrives=True).execute()
        movido = self._archivos.update(
            fileId=id_archivo,
            body={"name": nombre} if nombre else {},
            addParents=carpeta,
            removeParents=",".join(actual.get("parents", [])),
            fields="id, webViewLink",
            supportsAllDrives=True,
        ).execute()
        return movido["webViewLink"]
