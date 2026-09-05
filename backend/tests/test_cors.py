"""CORS del backend (app/main.py) — 1 de septiembre de 2026, hallazgo
real en vivo: se agregó un endpoint DELETE real (eliminar imagen de
producto) pero `allow_methods` seguía sin incluir "DELETE" (el comentario
del código decía "ninguno borra nada" — ya no es cierto). El navegador
bloqueaba el preflight OPTIONS y el fetch nunca salía, aunque el backend
en sí funcionara perfecto — un bug que curl/TestClient sin este test
específico nunca detectan (no hacen el preflight real de un navegador).

Prueba directa contra la app real (sin dependency_override de DB — CORS
es un concern de middleware, nunca toca la base)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# Mismo origen de desarrollo que main.py usa como fallback
# (_DEV_FRONTEND_ORIGINS) cuando CORS_ALLOWED_ORIGINS no está seteado.
ORIGEN_FRONTEND_DEV = "http://localhost:5500"


def test_preflight_delete_esta_permitido():
    """Si esto vuelve a fallar, algún endpoint DELETE real (o uno nuevo)
    quedó sin reflejarse en allow_methods -- el fetch del navegador nunca
    llega a salir, sin importar que el endpoint en sí funcione bien."""
    res = client.options(
        "/api/productos/1/imagenes/1",
        headers={"Origin": ORIGEN_FRONTEND_DEV, "Access-Control-Request-Method": "DELETE"},
    )
    assert res.status_code == 200
    metodos_permitidos = res.headers.get("access-control-allow-methods", "")
    assert "DELETE" in metodos_permitidos


def test_preflight_get_put_post_siguen_permitidos():
    for metodo in ("GET", "PUT", "POST"):
        res = client.options(
            "/api/productos/1",
            headers={"Origin": ORIGEN_FRONTEND_DEV, "Access-Control-Request-Method": metodo},
        )
        assert res.status_code == 200
        assert metodo in res.headers.get("access-control-allow-methods", "")


def test_preflight_desde_un_origen_no_permitido_se_rechaza():
    """Nunca "*" -- solo los orígenes explícitos de main.py. Un origen
    cualquiera no debe recibir Access-Control-Allow-Origin."""
    res = client.options(
        "/api/productos/1",
        headers={"Origin": "https://sitio-cualquiera.com", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in res.headers.keys()}
