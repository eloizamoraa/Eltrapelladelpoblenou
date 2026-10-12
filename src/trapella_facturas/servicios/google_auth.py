"""Autorización OAuth con Google, compartida por Gmail, Drive y Sheets."""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ..config import Settings

# drive.file solo da acceso a lo que crea esta aplicación (la carpeta y la hoja de
# `setup`), no al resto del Drive de la cuenta.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]


class SinAutorizar(RuntimeError):
    pass


def credenciales(settings: Settings, *, interactivo: bool = False) -> Credentials:
    creds = None
    if settings.token_path.exists():
        creds = Credentials.from_authorized_user_file(str(settings.token_path), SCOPES)
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif interactivo:
        if not settings.credentials_path.exists():
            raise SinAutorizar(
                f"Falta {settings.credentials_path}. Descarga el cliente OAuth de tipo "
                "'App de escritorio' desde Google Cloud Console (ver README)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(settings.credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)
    else:
        raise SinAutorizar("No hay sesión de Google. Ejecuta primero: trapella-facturas auth")

    settings.token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def servicio(nombre: str, version: str, creds: Credentials):
    return build(nombre, version, credentials=creds, cache_discovery=False)
