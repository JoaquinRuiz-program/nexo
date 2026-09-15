"""
Punto de entrada del backend.

24 de agosto de 2026 — pivote de "app de una librería" a plataforma
universal para vendedores de Mercado Libre (Nexo es el producto, cualquier
rubro es un caso de uso válido, nunca un límite de arquitectura): importador
de catálogo
desde cualquier Excel/CSV (app/api/routes/catalogo.py), motor de
rentabilidad configurable por canal, selección de qué conviene publicar
(app/api/routes/seleccion.py), lectura de WooCommerce, y OAuth real de
Mercado Libre con importación de sus ventas — sin escribir todavía en
WooCommerce ni en Mercado Libre.

29 de agosto de 2026 — autenticación real de usuarios (app/api/routes/auth.py,
app/api/deps.py): cada request a un endpoint de negocio pasa a resolver
"de qué empresa es esto" desde la sesión (cookie HttpOnly), nunca desde "la
primera tienda que exista". Ver DATABASE.md para el detalle de cada fase.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    admin,
    auth,
    catalogo,
    configuracion,
    costos,
    dashboard,
    facturas_ml,
    google_sheets,
    mercadolibre,
    pagos,
    productos,
    productos_db,
    publicaciones,
    rentabilidad,
    seleccion,
    soporte,
    suscripcion,
)
from app.config import get_settings, print_env_diagnostics

app = FastAPI(
    title="Nexo — catálogo y rentabilidad para Mercado Libre",
    description="Importa cualquier catálogo (Excel/CSV), calcula rentabilidad y decide qué conviene publicar en Mercado Libre. Sirve a cualquier rubro, no a un cliente específico.",
    version="0.2.0",
)

# CORS: el frontend (frontend/index.html) se sirve desde un origen distinto
# al de este backend (puerto propio en dev, dominio propio en producción),
# así que el navegador lo trata como un origen distinto y bloquea el
# fetch() si no se habilita acá — nada de "*" (cualquier origen), que sería
# inseguro y además no funciona junto con credenciales.
#
# 30 de agosto de 2026 — antes esta lista estaba fija en código (solo
# localhost:5500) — eso bloquea TODO en producción hasta que alguien tocara
# este archivo y redesplegara. Ahora sale de settings.cors_allowed_origins
# (variable de entorno CORS_ALLOWED_ORIGINS, coma-separada); vacío usa los
# orígenes de desarrollo local como fallback, para no romper nada hoy.
_settings_cors = get_settings()
_DEV_FRONTEND_ORIGINS = ["http://localhost:5500", "http://127.0.0.1:5500"]
_frontend_origins = (
    [o.strip() for o in _settings_cors.cors_allowed_origins.split(",") if o.strip()]
    if _settings_cors.cors_allowed_origins
    else _DEV_FRONTEND_ORIGINS
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    # GET para consultas; PUT/POST para las escrituras de siempre.
    # DELETE agregado el 1 de septiembre de 2026 (eliminar una imagen de
    # producto, app/api/routes/productos_db.py) — hallazgo real en vivo:
    # sin este método en la lista, el navegador bloquea el preflight
    # OPTIONS y el fetch nunca sale, aunque el backend en sí funcione bien.
    allow_methods=["GET", "PUT", "POST", "DELETE"],
    allow_headers=["*"],
    # 29 de agosto de 2026 — autenticación real por cookie de sesión
    # (app/api/deps.py): sin esto, el navegador nunca manda la cookie en un
    # fetch() entre orígenes distintos (frontend:5500 -> backend:8000), sin
    # importar que sea HttpOnly/SameSite=Lax. Es justo por esto que
    # allow_origins NUNCA puede ser "*" (el spec de CORS lo prohíbe junto
    # con credenciales) — ya listamos orígenes exactos arriba.
    allow_credentials=True,
)

# 13 de septiembre de 2026 — cabeceras de seguridad. Antes de esto el
# backend solo tenía el middleware de CORS: cualquier sitio podía meter
# Nexo en un <iframe> y montarle botones falsos encima (clickjacking), y
# nada le decía al navegador que forzara HTTPS en las visitas siguientes.
#
# `Strict-Transport-Security` va SOLO cuando la aplicación se sabe detrás
# de HTTPS (settings.session_cookie_secure, la misma señal que ya gobierna
# la cookie `Secure`): mandarlo desde el http://localhost de desarrollo
# haría que el navegador se niegue después a abrir localhost por HTTP, y es
# molesto de revertir.
#
# La CSP es la más restrictiva posible (`default-src 'none'`) porque este
# servicio devuelve JSON y archivos subidos, nunca páginas HTML: el
# frontend se sirve aparte (ver DEPLOY.md) y tiene sus propias necesidades
# —Tailwind y Google Fonts— que no aplican acá.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "cross-origin",
}


@app.middleware("http")
async def agregar_cabeceras_de_seguridad(request, call_next):  # noqa: ANN001, ANN201
    respuesta = await call_next(request)
    for nombre, valor in _SECURITY_HEADERS.items():
        respuesta.headers.setdefault(nombre, valor)
    if get_settings().session_cookie_secure:
        respuesta.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return respuesta


# Orden importante: productos.router registra /api/productos/reporte antes
# de que productos_db.router registre /api/productos/{variant_id} — así una
# request a /reporte siempre matchea la ruta literal primero.
app.include_router(auth.router)
app.include_router(productos.router)
app.include_router(productos_db.router)
app.include_router(rentabilidad.router)
app.include_router(configuracion.router)
app.include_router(costos.router)
app.include_router(mercadolibre.router)
app.include_router(facturas_ml.router)
app.include_router(google_sheets.router)
app.include_router(catalogo.router)
app.include_router(seleccion.router)
app.include_router(publicaciones.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(suscripcion.router)
app.include_router(pagos.router)
app.include_router(soporte.router)

# 5 de septiembre de 2026 — imágenes de producto subidas desde el
# computador (ver app/domain/image_storage.py): se sirven como archivos
# estáticos, la misma carpeta que usa productos_db.py para guardarlas
# (`Settings.uploads_dir`). Se crea si no existe todavía (primer arranque).
_uploads_dir = Path(get_settings().uploads_dir)
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")


@app.on_event("startup")
async def on_startup() -> None:
    # 6 de septiembre de 2026 — release candidate: esto es SOLO un
    # diagnóstico para los logs. Si falla (por ejemplo, una consola que no
    # puede codificar un carácter), no debe impedir que la aplicación
    # arranque: FastAPI aborta el proceso entero si un handler de startup
    # lanza una excepción. Pasó de verdad al probar el arranque en una
    # configuración de producción (sin .env).
    try:
        print_env_diagnostics(get_settings())
    except Exception as err:  # noqa: BLE001 - nunca debe tumbar el arranque
        print(f"AVISO: no se pudo imprimir el diagnostico de configuracion: {err!r}")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
