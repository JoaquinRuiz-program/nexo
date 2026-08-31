"""
Punto de entrada del backend.

24 de agosto de 2026 — pivote de "app de una librería" a plataforma
universal para vendedores de Mercado Libre (Librería Central queda como
primer caso de uso, no como límite de arquitectura): importador de catálogo
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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    auth,
    catalogo,
    configuracion,
    costos,
    dashboard,
    mercadolibre,
    productos,
    productos_db,
    publicaciones,
    rentabilidad,
    seleccion,
)
from app.config import get_settings, print_env_diagnostics

app = FastAPI(
    title="Backend de catálogo y rentabilidad para Mercado Libre",
    description="Importa cualquier catálogo (Excel/CSV), calcula rentabilidad y decide qué conviene publicar en Mercado Libre. Librería Central es el primer caso de uso, no un límite de arquitectura.",
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
    # GET para consultas; PUT (configurar costos de canal) y POST (subir
    # el archivo de costos) desde que existen esos endpoints — ninguno
    # borra nada, así que no hace falta DELETE.
    allow_methods=["GET", "PUT", "POST"],
    allow_headers=["*"],
    # 29 de agosto de 2026 — autenticación real por cookie de sesión
    # (app/api/deps.py): sin esto, el navegador nunca manda la cookie en un
    # fetch() entre orígenes distintos (frontend:5500 -> backend:8000), sin
    # importar que sea HttpOnly/SameSite=Lax. Es justo por esto que
    # allow_origins NUNCA puede ser "*" (el spec de CORS lo prohíbe junto
    # con credenciales) — ya listamos orígenes exactos arriba.
    allow_credentials=True,
)

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
app.include_router(catalogo.router)
app.include_router(seleccion.router)
app.include_router(publicaciones.router)
app.include_router(dashboard.router)
app.include_router(admin.router)


@app.on_event("startup")
async def on_startup() -> None:
    print_env_diagnostics(get_settings())


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
