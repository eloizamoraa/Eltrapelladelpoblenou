"""Montaje de la aplicación: construye los clientes y el pipeline a partir del .env.

Lo usan tanto la línea de comandos (cli.py) como el servidor MCP (mcp_server.py).
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from dotenv import set_key

from .config import Settings, cargar_settings
from .extractor import ExtractorFacturas
from .pipeline import Pipeline
from .servicios.drive import DriveClient
from .servicios.gmail import GmailClient
from .servicios.google_auth import credenciales, servicio
from .servicios.sheets import SheetsClient, crear_hoja_de_control

NOMBRE_CARPETA_RAIZ = "Facturas El Trapella"
NOMBRE_HOJA = "Control de facturas - El Trapella"


def configurar_logging(settings: Settings) -> None:
    """Consola (stderr, para no interferir con el protocolo MCP en stdout) y archivo."""
    settings.log_path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            RotatingFileHandler(settings.log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
        ],
    )
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _exigir_configuracion(settings: Settings) -> None:
    if not settings.drive_root_id or not settings.sheet_id:
        raise RuntimeError(
            "Faltan DRIVE_ROOT_FOLDER_ID o SHEET_ID en .env. Ejecuta: trapella-facturas setup"
        )


def construir_sheets(settings: Settings | None = None) -> SheetsClient:
    settings = settings or cargar_settings()
    _exigir_configuracion(settings)
    return SheetsClient(servicio("sheets", "v4", credenciales(settings)), settings.sheet_id)


def construir_pipeline(settings: Settings | None = None, *, dry_run: bool = False) -> Pipeline:
    settings = settings or cargar_settings()
    _exigir_configuracion(settings)
    creds = credenciales(settings)
    return Pipeline(
        gmail=GmailClient(servicio("gmail", "v1", creds), settings.gmail_query),
        drive=DriveClient(servicio("drive", "v3", creds), settings.drive_root_id),
        sheets=SheetsClient(servicio("sheets", "v4", creds), settings.sheet_id),
        extractor=ExtractorFacturas(settings),
        dry_run=dry_run,
    )


def preparar_entorno(settings: Settings) -> dict[str, str]:
    """Crea lo que falte en Google (carpeta, hoja, pestañas, etiquetas) y lo anota en .env."""
    creds = credenciales(settings, interactivo=True)
    drive_api, sheets_api = servicio("drive", "v3", creds), servicio("sheets", "v4", creds)
    drive = DriveClient(drive_api)

    raiz = settings.drive_root_id
    if not raiz:
        raiz = drive.crear_carpeta(NOMBRE_CARPETA_RAIZ)
        set_key(settings.env_path, "DRIVE_ROOT_FOLDER_ID", raiz)

    hoja = settings.sheet_id
    if not hoja:
        hoja = crear_hoja_de_control(sheets_api, NOMBRE_HOJA)
        drive.mover(hoja, raiz)
        set_key(settings.env_path, "SHEET_ID", hoja)

    SheetsClient(sheets_api, hoja).asegurar_estructura()
    GmailClient(servicio("gmail", "v1", creds), settings.gmail_query).asegurar_etiquetas()
    return {
        "carpeta": f"https://drive.google.com/drive/folders/{raiz}",
        "hoja": f"https://docs.google.com/spreadsheets/d/{hoja}",
    }
