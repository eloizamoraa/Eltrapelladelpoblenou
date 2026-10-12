"""Línea de comandos: trapella-facturas <comando>."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from .app import configurar_logging, construir_pipeline, preparar_entorno
from .config import cargar_settings
from .servicios.google_auth import SinAutorizar, credenciales

log = logging.getLogger(__name__)


def _imprimir(datos: object) -> None:
    print(json.dumps(datos, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trapella-facturas", description="Procesa las facturas que llegan por email."
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("auth", help="Autoriza el acceso a la cuenta de Google (abre el navegador).")
    sub.add_parser("setup", help="Crea la carpeta de Drive, la hoja de control y las etiquetas.")
    run = sub.add_parser("run", help="Procesa los emails pendientes una vez.")
    watch = sub.add_parser("watch", help="Se queda en marcha y procesa cada cierto tiempo.")
    for p in (run, watch):
        p.add_argument("--max", type=int, default=25, help="Máximo de emails por pasada.")
    run.add_argument("--dry-run", action="store_true", help="Lee y valida, pero no escribe nada.")
    watch.add_argument("--intervalo", type=int, help="Segundos entre pasadas.")
    rep = sub.add_parser("reprocesar", help="Vuelve a procesar un email por su ID de mensaje.")
    rep.add_argument("id_mensaje")
    args = parser.parse_args(argv)

    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8")
    settings = cargar_settings()
    configurar_logging(settings)

    try:
        if args.comando == "auth":
            credenciales(settings, interactivo=True)
            print(f"Autorizado. Sesión guardada en {settings.token_path}")
        elif args.comando == "setup":
            enlaces = preparar_entorno(settings)
            print(f"Carpeta de facturas: {enlaces['carpeta']}")
            print(f"Hoja de control:     {enlaces['hoja']}")
            print("Siguiente paso: rellena la pestaña Proveedores de la hoja.")
        elif args.comando == "run":
            _imprimir(construir_pipeline(settings, dry_run=args.dry_run).ejecutar(args.max))
        elif args.comando == "reprocesar":
            resultados = construir_pipeline(settings).reprocesar(args.id_mensaje)
            _imprimir([r.como_dict() for r in resultados])
        elif args.comando == "watch":
            intervalo = args.intervalo or settings.intervalo_segundos
            log.info("Vigilando %s cada %s s. Ctrl+C para parar.", settings.buzon, intervalo)
            while True:
                try:
                    resumen = construir_pipeline(settings).ejecutar(args.max)
                    log.info(
                        "Pasada: %s emails, %s errores", resumen["emails"], len(resumen["errores"])
                    )
                except SinAutorizar:
                    raise
                except Exception:  # una caída de red no debe parar la vigilancia
                    log.exception("La pasada ha fallado; se reintentará")
                time.sleep(intervalo)
    except (SinAutorizar, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
