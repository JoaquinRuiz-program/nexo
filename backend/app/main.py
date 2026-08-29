"""
Punto de entrada del backend.

24 de agosto de 2026 — pivote de "app de una librería" a plataforma
universal para vendedores de Mercado Libre (Librería Central queda como
primer caso de uso, no como límite de arquitectura): importador de catálogo
desde cualquier Excel/CSV (app/api/routes/catalogo.py), motor de
rentabilidad configurable por canal, selección de qué conviene publicar
(app/api/routes/seleccion.py), lectura de WooCommerce, y OAuth real de
Mercado Libre con importación de sus ventas — sin escribir todavía en
WooCommerce ni en Mercado Libre, y sin autenticación de usuarios del panel.
Ver DATABASE.md para el detalle de cada fase.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    catalogo,
    configuracion,
    costos,
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

# CORS: el frontend (frontend/index.html) se sirve desde un servidor estático
# local en un puerto distinto al de este backend, así que el navegador lo
# trata como un origen distinto y bloquea el fetch() si no se habilita acá.
# Se listan los orígenes EXACTOS que vamos a usar en desarrollo local (el
# mismo servidor estático responde tanto en "localhost" como en "127.0.0.1",
# y los navegadores los tratan como orígenes distintos) — nada de "*"
# (cualquier origen), que sería inseguro y además no funciona junto con
# credenciales.
DEV_FRONTEND_ORIGINS = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_FRONTEND_ORIGINS,
    # GET para consultas; PUT (configurar costos de canal) y POST (subir
    # el archivo de costos) desde que existen esos endpoints — ninguno
    # borra nada, así que no hace falta DELETE.
    allow_methods=["GET", "PUT", "POST"],
    allow_headers=["*"],
)

# Orden importante: productos.router registra /api/productos/reporte antes
# de que productos_db.router registre /api/productos/{variant_id} — así una
# request a /reporte siempre matchea la ruta literal primero.
app.include_router(productos.router)
app.include_router(productos_db.router)
app.include_router(rentabilidad.router)
app.include_router(configuracion.router)
app.include_router(costos.router)
app.include_router(mercadolibre.router)
app.include_router(catalogo.router)
app.include_router(seleccion.router)
app.include_router(publicaciones.router)


@app.on_event("startup")
async def on_startup() -> None:
    print_env_diagnostics(get_settings())


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
