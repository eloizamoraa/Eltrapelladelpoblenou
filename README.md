# Trapella Facturas

Procesa solas las facturas que llegan a `facturas@eltrapelladelpoblenou.com`: detecta el
email, lee el PDF adjunto, lo guarda renombrado en Google Drive y lo registra en una hoja
de control. Lo que no se puede registrar con seguridad no se adivina: queda señalado como
incidencia para que lo revise una persona.

## Qué hace con cada email

```
Gmail ──► ¿trae PDF,  ──► ¿PDF válido? ──► Claude lee los datos ──► validación ──► ¿duplicado?
          adjunto o en        │no                                      │                │
          un enlace?          │                                        │                │
              │no             │                                        │                │
              ▼               ▼                                        ▼                ▼
          incidencia      incidencia                          OK  o  REVISAR        DUPLICADO
```

| Resultado | Dónde queda el PDF | Hoja de control |
|---|---|---|
| **OK** | `2026/10-Octubre/Makro/2026-10-03_Makro_FA-2026-0158_170.50.pdf` | Fila nueva en **Facturas** |
| **REVISAR** (falta el número o la fecha, el importe no cuadra, proveedor no reconocido) | `_REVISAR/`, con su nombre original | Fila en **Facturas** con estado `REVISAR` + fila en **Incidencias** |
| **DUPLICADO** (mismo proveedor + número + importe) | `_DUPLICADOS/` | Sin fila nueva: se anota en la columna *Posible duplicado* de la factura original + fila en **Incidencias** |
| **INCIDENCIA** (sin PDF, PDF dañado o protegido, no es una factura) | `_REVISAR/` si había archivo | Solo fila en **Incidencias** |

En Gmail, cada email tratado recibe la etiqueta `facturas-procesada`, y además
`facturas-incidencia` si algo quedó pendiente. Si falla la red o una API, el email no se
etiqueta y se reintenta en la siguiente pasada.

**Facturas en un enlace.** Si el email no trae ningún PDF adjunto, se abren los enlaces del
mensaje que parecen llevar a una factura (por su texto o su dirección: "Descargar factura",
`.../invoice/123`, `...pdf`; como mucho 5 por email) y los que devuelven un PDF se tratan
igual que un adjunto. Nunca se abren enlaces de baja ni direcciones de la red local. Si
ningún enlace da un PDF, la incidencia *Email sin PDF adjunto* dice qué enlaces se probaron
y por qué fallaron; si fue un fallo pasajero, basta con `trapella-facturas reprocesar`.

**El importe se considera fiable** solo si se lee el total y además cuadra con el desglose
(bases + cuotas de IVA + recargo − IRPF, con 2 céntimos de margen) y cada cuota corresponde
a su base.

**Un proveedor está reconocido** si aparece en la pestaña **Proveedores** de la hoja, por CIF
o por nombre/alias. El nombre de esa pestaña es el que se usa para carpetas y archivos, así
que conviene que sea corto ("Makro", no "Makro Autoservicio Mayorista S.A.U.").

## Puesta en marcha

Necesitas Python 3.11 o superior. Desde la carpeta del proyecto, en PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
Copy-Item .env.example .env
```

### 1. Clave de Claude

Crea una clave en <https://console.anthropic.com> y ponla en `.env` como `ANTHROPIC_API_KEY`.

### 2. Acceso a Google

1. En [Google Cloud Console](https://console.cloud.google.com) crea un proyecto y activa
   tres APIs: **Gmail API**, **Google Drive API** y **Google Sheets API**.
2. En *Pantalla de consentimiento de OAuth*, elige tipo **Interno** (si la cuenta es de
   Google Workspace).
3. En *Credenciales* → *Crear credenciales* → *ID de cliente de OAuth* → **App de
   escritorio**. Descarga el JSON y guárdalo en esta carpeta como `credentials.json`.
4. Autoriza, iniciando sesión **con la cuenta que recibe las facturas**:

```powershell
.\.venv\Scripts\trapella-facturas auth
```

### 3. Crear la carpeta y la hoja

```powershell
.\.venv\Scripts\trapella-facturas setup
```

Crea en Drive la carpeta *Facturas El Trapella* y, dentro, la hoja *Control de facturas*
con sus tres pestañas; guarda sus identificadores en `.env` y muestra los enlaces. Puedes
mover la carpeta a donde quieras dentro de Drive.

### 4. Dar de alta a los proveedores

Rellena la pestaña **Proveedores**: nombre corto, CIF y, si hace falta, otros nombres con
los que aparece en sus facturas (separados por `;`). Hasta que un proveedor no esté ahí,
sus facturas irán a `REVISAR`.

### 5. Probar y dejarlo funcionando

```powershell
.\.venv\Scripts\trapella-facturas run --dry-run   # lee y valida, no escribe nada
.\.venv\Scripts\trapella-facturas run             # procesa de verdad
.\scripts\registrar_tarea.ps1 -Minutos 10         # tarea de Windows cada 10 minutos
```

Como alternativa a la tarea programada, `trapella-facturas watch` se queda en marcha en
una ventana. El registro de actividad está en `logs/`.

## Resolver incidencias

Filtra **Incidencias** por estado `Pendiente`. Cada fila enlaza al email y al PDF.

- **Proveedor no reconocido**: añádelo a **Proveedores** y vuelve a pasar el email con
  `trapella-facturas reprocesar <ID mensaje>`. La fila pasa a `OK`, el PDF se mueve a su
  carpeta con el nombre definitivo y la incidencia se marca `Resuelta`.
- **Falta un dato o el importe no cuadra**: corrige la fila en **Facturas** a mano, cambia
  su estado a `OK` y mueve el PDF desde `_REVISAR`. Marca la incidencia como `Resuelta`.
- **Posible duplicado**: compara los dos PDF. Si de verdad era un duplicado, basta con
  marcar la incidencia como `Resuelta`.

## Usarlo desde Claude (servidor MCP)

El proyecto incluye un servidor MCP para manejar el sistema conversando. Al abrir esta
carpeta con Claude Code se detecta solo (`.mcp.json`). Para Claude Desktop, añade en su
configuración la ruta completa a `.venv\Scripts\trapella-facturas-mcp.exe`.

| Herramienta | Para qué |
|---|---|
| `procesar_bandeja` | Procesar ya los emails pendientes (o simularlo) |
| `listar_incidencias` | Ver qué hay pendiente de revisar |
| `buscar_facturas` | Buscar por proveedor, fechas o estado |
| `resumen_iva` | Totales de base e IVA por tipo de un mes o un año |
| `listar_proveedores` / `alta_proveedor` | Consultar y dar de alta proveedores |
| `reprocesar_email` | Volver a pasar un email tras resolver su incidencia |

Ejemplos: *"¿Qué incidencias hay pendientes?"*, *"Da de alta a Frutas Pérez con CIF
B12345678 y reprocesa su factura"*, *"¿Cuánto IVA soportado llevamos en octubre?"*.

## Estructura del código

```
src/trapella_facturas/
├── cli.py            Comandos: auth, setup, run, watch, reprocesar
├── mcp_server.py     Servidor MCP
├── app.py            Montaje: construye clientes y pipeline desde .env
├── pipeline.py       El flujo completo, paso a paso
├── extractor.py      Lectura del PDF con Claude (salida estructurada)
├── validacion.py     Reglas de incidencias y reconocimiento de proveedores
├── duplicados.py     Detección de duplicados
├── nombres.py        Nombre de archivo y ruta de carpetas
├── normalizacion.py  Comparación de CIF, nombres, números y fechas
├── pdf.py            Comprobación previa del adjunto
├── esquema.py        Pestañas y columnas de la hoja
├── models.py         Tipos de datos
├── config.py         Lectura del .env
└── servicios/        Clientes de Gmail, Drive, Sheets y OAuth de Google; descarga de enlaces
tests/                Pruebas con dobles en memoria (no tocan Google ni Claude)
```

Pruebas: `.\.venv\Scripts\python -m pytest`

## Límites actuales

- Solo se tratan facturas en **PDF**, adjunto o en un enlace de descarga directa. Una
  factura en foto (JPG), o un enlace que pide iniciar sesión o lleva a una página (portal
  del proveedor, Google Drive, Dropbox, WeTransfer), queda como incidencia *Email sin PDF
  adjunto*.
- La comprobación de correo es periódica (cada 10 minutos por defecto), no instantánea.
- Cada PDF leído es una llamada de pago a la API de Claude.
- `credentials.json`, `token.json` y `.env` dan acceso al buzón y a la clave de la API:
  no los compartas ni los subas a ningún repositorio (ya están en `.gitignore`).
