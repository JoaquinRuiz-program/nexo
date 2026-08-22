"""
Punto de entrada de la app real de Librería Central (backend).

Fase actual: solo lectura de WooCommerce, reutilizando el adaptador y el
análisis ya probados en scripts/woocommerce-audit/. Nada de esto escribe en
WooCommerce, ni implementa Mercado Libre, pedidos o autenticación todavía —
eso es el resto del roadmap ya acordado (ver
arquitectura-fase0-decisiones.md, sección 7.10).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import productos
from app.config import get_settings, print_env_diagnostics

app = FastAPI(
    title="Librería Central — Backend",
    description="Backend real del proyecto. Fase actual: lectura de WooCommerce.",
    version="0.1.0",
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
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(productos.router)


@app.on_event("startup")
async def on_startup() -> None:
    print_env_diagnostics(get_settings())


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
