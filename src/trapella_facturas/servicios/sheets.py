"""Google Sheets: la hoja de control (Facturas, Incidencias y Proveedores)."""

from __future__ import annotations

import re
from datetime import date, datetime

from ..esquema import (
    FILA,
    HOJA_FACTURAS,
    HOJA_INCIDENCIAS,
    HOJA_PROVEEDORES,
    HOJAS,
    INCIDENCIA_PENDIENTE,
    INCIDENCIA_RESUELTA,
)
from ..models import Proveedor


def _celda(valor: object) -> object:
    """Prepara un valor para escribirlo con USER_ENTERED.

    Números y fechas se dejan interpretar a Sheets. Todo texto lleva apóstrofo
    delante: así '0012' no se convierte en 12 y un asunto de email que empiece
    por '=' no se ejecuta como fórmula.
    """
    if valor is None or valor == "":
        return ""
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return valor
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, date):
        return valor.isoformat()
    return "'" + str(valor)


def _letra(indice: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letras = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def crear_hoja_de_control(servicio, titulo: str) -> str:
    """Crea la hoja de cálculo con sus tres pestañas y devuelve su id."""
    creada = servicio.spreadsheets().create(
        body={
            "properties": {"title": titulo, "locale": "es_ES", "timeZone": "Europe/Madrid"},
            "sheets": [{"properties": {"title": nombre}} for nombre in HOJAS],
        },
        fields="spreadsheetId",
    ).execute()
    return creada["spreadsheetId"]


class SheetsClient:
    def __init__(self, servicio, sheet_id: str):
        self._libro = servicio.spreadsheets()
        self._valores = servicio.spreadsheets().values()
        self._id = sheet_id
        self._cabeceras: dict[str, list[str]] = {}

    # --- estructura -------------------------------------------------------

    def asegurar_estructura(self) -> None:
        """Crea las pestañas y cabeceras que falten. No toca los datos existentes."""
        libro = self._libro.get(spreadsheetId=self._id, fields="sheets.properties").execute()
        ids = {h["properties"]["title"]: h["properties"]["sheetId"] for h in libro["sheets"]}
        faltan = [nombre for nombre in HOJAS if nombre not in ids]
        if faltan:
            resp = self._libro.batchUpdate(
                spreadsheetId=self._id,
                body={"requests": [{"addSheet": {"properties": {"title": n}}} for n in faltan]},
            ).execute()
            for respuesta in resp["replies"]:
                prop = respuesta["addSheet"]["properties"]
                ids[prop["title"]] = prop["sheetId"]

        formato = []
        for nombre, columnas in HOJAS.items():
            if not self._leer_cabecera(nombre):
                self._valores.update(
                    spreadsheetId=self._id,
                    range=f"'{nombre}'!A1",
                    valueInputOption="RAW",
                    body={"values": [columnas]},
                ).execute()
            formato += [
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": ids[nombre], "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "repeatCell": {
                        "range": {"sheetId": ids[nombre], "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                },
            ]
        self._libro.batchUpdate(spreadsheetId=self._id, body={"requests": formato}).execute()
        self._cabeceras.clear()

    def _leer_cabecera(self, hoja: str) -> list[str]:
        filas = self._valores.get(spreadsheetId=self._id, range=f"'{hoja}'!1:1").execute()
        return [str(c).strip() for c in filas.get("values", [[]])[0]]

    def _cabecera(self, hoja: str) -> list[str]:
        if hoja not in self._cabeceras:
            cabecera = self._leer_cabecera(hoja)
            faltan = [c for c in HOJAS[hoja] if c not in cabecera]
            if faltan:
                raise RuntimeError(
                    f"A la pestaña '{hoja}' le faltan las columnas {faltan}. "
                    "Ejecuta: trapella-facturas setup"
                )
            self._cabeceras[hoja] = cabecera
        return self._cabeceras[hoja]

    # --- lectura y escritura genéricas ------------------------------------

    def _leer(self, hoja: str) -> list[dict]:
        cabecera = self._cabecera(hoja)
        resp = self._valores.get(
            spreadsheetId=self._id, range=f"'{hoja}'!A2:ZZ", valueRenderOption="UNFORMATTED_VALUE"
        ).execute()
        filas = []
        for n, valores in enumerate(resp.get("values", []), start=2):
            if any(v != "" for v in valores):
                fila = dict(zip(cabecera, valores))
                filas.append({c: fila.get(c, "") for c in cabecera if c} | {FILA: n})
        return filas

    def _como_lista(self, hoja: str, fila: dict) -> list:
        return [_celda(fila.get(columna)) for columna in self._cabecera(hoja)]

    def _anadir(self, hoja: str, fila: dict) -> int:
        resp = self._valores.append(
            spreadsheetId=self._id,
            range=f"'{hoja}'!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [self._como_lista(hoja, fila)]},
        ).execute()
        return int(re.search(r"!\D+(\d+)", resp["updates"]["updatedRange"]).group(1))

    def _escribir_celda(self, hoja: str, fila: int, columna: str, valor: object) -> None:
        letra = _letra(self._cabecera(hoja).index(columna))
        self._valores.update(
            spreadsheetId=self._id,
            range=f"'{hoja}'!{letra}{fila}",
            valueInputOption="USER_ENTERED",
            body={"values": [[_celda(valor)]]},
        ).execute()

    # --- facturas ----------------------------------------------------------

    def facturas(self) -> list[dict]:
        return self._leer(HOJA_FACTURAS)

    def registrar_factura(self, fila: dict) -> int:
        """Añade una fila y devuelve su número en la hoja."""
        return self._anadir(HOJA_FACTURAS, fila)

    def actualizar_factura(self, fila: dict) -> None:
        self._valores.update(
            spreadsheetId=self._id,
            range=f"'{HOJA_FACTURAS}'!A{fila[FILA]}",
            valueInputOption="USER_ENTERED",
            body={"values": [self._como_lista(HOJA_FACTURAS, fila)]},
        ).execute()

    def anotar_duplicado(self, fila: dict, nota: str) -> None:
        anterior = str(fila.get("Posible duplicado") or "")
        fila["Posible duplicado"] = f"{anterior}\n{nota}".strip()
        self._escribir_celda(HOJA_FACTURAS, fila[FILA], "Posible duplicado", fila["Posible duplicado"])

    # --- incidencias -------------------------------------------------------

    def incidencias(self) -> list[dict]:
        return self._leer(HOJA_INCIDENCIAS)

    def registrar_incidencia(self, fila: dict) -> None:
        self._anadir(HOJA_INCIDENCIAS, {"Estado": INCIDENCIA_PENDIENTE} | fila)

    def resolver_incidencias(self, id_mensaje: str, adjunto: str) -> None:
        for fila in self.incidencias():
            if (
                str(fila["ID mensaje"]) == id_mensaje
                and str(fila["Adjunto"]) == adjunto
                and fila["Estado"] == INCIDENCIA_PENDIENTE
            ):
                self._escribir_celda(HOJA_INCIDENCIAS, fila[FILA], "Estado", INCIDENCIA_RESUELTA)

    # --- proveedores -------------------------------------------------------

    def proveedores(self) -> list[Proveedor]:
        columna_alias = HOJAS[HOJA_PROVEEDORES][2]
        return [
            Proveedor(
                nombre=str(fila["Nombre"]).strip(),
                cif=str(fila["CIF"]).strip(),
                alias=tuple(a.strip() for a in str(fila[columna_alias]).split(";") if a.strip()),
            )
            for fila in self._leer(HOJA_PROVEEDORES)
            if str(fila["Nombre"]).strip()
        ]

    def alta_proveedor(self, proveedor: Proveedor) -> None:
        self._anadir(
            HOJA_PROVEEDORES,
            {
                "Nombre": proveedor.nombre,
                "CIF": proveedor.cif,
                HOJAS[HOJA_PROVEEDORES][2]: "; ".join(proveedor.alias),
            },
        )
