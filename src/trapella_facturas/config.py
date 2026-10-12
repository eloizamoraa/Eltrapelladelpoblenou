"""Configuración: todo sale del archivo .env (ver .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ETIQUETA_PROCESADA = "facturas-procesada"
ETIQUETA_INCIDENCIA = "facturas-incidencia"

CARPETA_REVISAR = "_REVISAR"
CARPETA_DUPLICADOS = "_DUPLICADOS"


def directorio_base() -> Path:
    """Carpeta del proyecto: donde viven .env, credentials.json y token.json."""
    if os.environ.get("TRAPELLA_HOME"):
        return Path(os.environ["TRAPELLA_HOME"])
    if (Path.cwd() / ".env").exists():
        return Path.cwd()
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    base: Path
    buzon: str
    gmail_query: str
    drive_root_id: str
    sheet_id: str
    empresa_nombre: str
    empresa_cif: str
    modelo: str
    intervalo_segundos: int

    @property
    def env_path(self) -> Path:
        return self.base / ".env"

    @property
    def credentials_path(self) -> Path:
        return self.base / "credentials.json"

    @property
    def token_path(self) -> Path:
        return self.base / "token.json"

    @property
    def log_path(self) -> Path:
        return self.base / "logs" / "trapella-facturas.log"


def cargar_settings() -> Settings:
    base = directorio_base()
    load_dotenv(base / ".env", override=True)
    buzon = os.environ.get("BUZON_FACTURAS", "facturas@eltrapelladelpoblenou.com")
    # {a b} en Gmail es un OR: cubre tanto buzón propio como alias o grupo.
    query = os.environ.get("GMAIL_QUERY") or f"{{to:{buzon} deliveredto:{buzon}}}"
    return Settings(
        base=base,
        buzon=buzon,
        gmail_query=f"{query} -label:{ETIQUETA_PROCESADA}",
        drive_root_id=os.environ.get("DRIVE_ROOT_FOLDER_ID", "").strip(),
        sheet_id=os.environ.get("SHEET_ID", "").strip(),
        empresa_nombre=os.environ.get("EMPRESA_NOMBRE", "El Trapella del Poblenou"),
        empresa_cif=os.environ.get("EMPRESA_CIF", "").strip(),
        modelo=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
        intervalo_segundos=int(os.environ.get("INTERVALO_SEGUNDOS", "600")),
    )
