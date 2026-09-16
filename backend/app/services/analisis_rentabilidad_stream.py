"""
Análisis de rentabilidad EN VIVO, con progreso producto a producto (16 de
septiembre de 2026, pedido del dueño: al subir el Excel, Nexo debe intentar
solo obtener el costo de envío real de Mercado Libre para CADA producto
antes de decidir si conviene — sin pedirle peso ni medidas al dueño — y la
pantalla no debe parecer congelada mientras tanto).

Este módulo NO agrega ningún mecanismo nuevo de comisión ni de envío: solo
orquesta, con progreso, los mismos servicios que ya corren al importar el
catálogo y al apretar "Actualizar comisiones y envíos" (POST
/api/mercadolibre/comisiones/recalcular):

  1. services/ml_comisiones.py::actualizar_comisiones_reales — categoría,
     comisión real y, para lo que todavía NO está publicado, el envío
     ESTIMADO de Mercado Libre (medidas por defecto de la categoría +
     GET /users/{id}/shipping_options/free?dimensions=...&item_price=...).
  2. services/ml_shipping_sync.py::sincronizar_costos_envio_de_la_cuenta —
     el envío REAL de lo que ya está publicado, por item_id
     (GET /users/{id}/shipping_options/free?item_id=...).
  3. domain/catalog_selection.py::classify_product — la MISMA regla de
     Oportunidades y "¿Conviene?" (nunca una nueva) para clasificar cada
     producto al terminar.

Ninguna de las tres corre dos veces por casualidad: este módulo solo les
agrega progreso (a través del parámetro opcional `on_avance` que ya aceptan)
y después lee lo que quedó guardado — no reimplementa ninguna consulta a
Mercado Libre por su cuenta ni inventa un costo.

Por qué secuencial y no en paralelo: `db` es una Session de SQLAlchemy
síncrona, no segura para dos tareas tocándola al mismo tiempo. La comisión/
envío estimado corre primero y despues el envío real, cada uno como una sola
tarea de asyncio a la vez; mientras esa tarea corre (y espera red), este
generador solo lee una cola en memoria para emitir progreso — nunca toca la
sesión en paralelo.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Coroutine

from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError
from app.db.models import ChannelCostSettings, MarketplaceAccount, Store
from app.db.models.channel_costs import umbrales_minimos
from app.domain.catalog_selection import SelectionCriteria, select, summarize_selection
from app.services.ml_comisiones import _tiendas_en_curso, actualizar_comisiones_reales
from app.services.ml_shipping_sync import sincronizar_costos_envio_de_la_cuenta

logger = logging.getLogger(__name__)

# Si no hay ningún avance real en este lapso, igual se manda un latido: así
# el navegador/proxy nunca ve la conexión como colgada durante una consulta
# lenta a Mercado Libre.
LATIDO_SEGUNDOS = 2.0

# Tope esperando a que termine una corrida ya en curso de otra parte (ver
# más abajo): pasado esto se deja de esperar y se pasa a clasificar con lo
# que ya esté guardado, en vez de colgar el stream para siempre si esa otra
# corrida quedó pegada.
ESPERA_MAXIMA_SEGUNDOS = 600.0


async def _correr_fase(queue: asyncio.Queue, corrutina: Coroutine, etiqueta: str) -> AsyncGenerator[dict, None]:
    """Corre `corrutina` (ya con su propio `on_avance=queue.put_nowait`) como
    una tarea y va vaciando `queue` mientras tanto, para no bloquear el
    stream durante toda la llamada. Nunca deja que un error de Mercado Libre
    rompa el análisis completo: lo reporta como aviso y sigue."""
    tarea = asyncio.create_task(corrutina)
    while not tarea.done():
        try:
            yield await asyncio.wait_for(queue.get(), timeout=LATIDO_SEGUNDOS)
        except asyncio.TimeoutError:
            yield {"tipo": "latido"}
    while not queue.empty():
        yield queue.get_nowait()
    try:
        await tarea
    except MercadoLibreAuthError:
        yield {
            "tipo": "aviso",
            "mensaje": f"Mercado Libre rechazó la consulta de {etiqueta} — revisa el permiso 'Publicación y sincronización' en developers.mercadolibre.cl.",
        }
    except Exception as err:  # noqa: BLE001 — nunca rompe el stream; el detalle queda en el log
        logger.error("Análisis de rentabilidad en vivo: falló la consulta de %s: %s", etiqueta, err)
        yield {"tipo": "aviso", "mensaje": f"No pudimos completar la consulta de {etiqueta} con Mercado Libre en este momento."}


async def analizar_catalogo_stream(db: Session, store: Store, settings) -> AsyncGenerator[dict, None]:
    """Generador de eventos (uno por línea NDJSON, ver
    routes/mercadolibre.py::analizar_rentabilidad_stream). Nunca inventa un
    costo: si Mercado Libre no puede resolver el envío de un producto, ese
    producto termina en "sin_datos" (Faltan datos), igual que en
    Oportunidades — ver domain/catalog_selection.py."""
    # Import diferido: mismo motivo que en ml_comisiones.py/ml_shipping_sync.py
    # (routes.mercadolibre importa estos servicios, así que importar al
    # revés arriba del archivo sería un ciclo).
    from app.api.routes.mercadolibre import _build_ml_config, _get_valid_access_token
    from app.api.routes.rentabilidad import build_profitability_rows

    account = db.query(MarketplaceAccount).filter_by(store_id=store.id, marketplace="mercadolibre").first()
    if account is None or account.status != "connected":
        yield {"tipo": "error", "mensaje": "Conecta Mercado Libre en Integraciones para analizar el envío y la rentabilidad con datos reales."}
        return

    cfg = _build_ml_config(settings)
    if not cfg.is_configured() or not settings.token_encryption_key:
        yield {"tipo": "error", "mensaje": "Mercado Libre no está configurado en el servidor."}
        return

    yield {"tipo": "inicio"}
    db.rollback()  # mismo motivo que el resto del archivo: nunca leer con una transacción vieja abierta

    if store.id in _tiendas_en_curso:
        # Ya hay una corrida en curso para esta empresa — casi siempre el
        # disparo automático que corre solo al importar el catálogo
        # (services/ml_comisiones.py::actualizar_comisiones_en_segundo_plano,
        # sin cambios). En vez de fallar (y arriesgar mostrar "Faltan datos"
        # mientras esa corrida sigue completando datos), se espera a que
        # termine: mismo guardia, nunca dos corridas pisándose para la misma
        # empresa, pero acá sí con progreso visible.
        espera_maxima = 0.0
        while store.id in _tiendas_en_curso and espera_maxima < ESPERA_MAXIMA_SEGUNDOS:
            yield {"tipo": "consultando_ml", "hecho": None}
            await asyncio.sleep(LATIDO_SEGUNDOS)
            espera_maxima += LATIDO_SEGUNDOS
    else:
        try:
            access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
        except Exception:  # noqa: BLE001 — igual que recalcular_comisiones: el detalle queda en el log
            yield {"tipo": "error", "mensaje": "El token de Mercado Libre venció y no se pudo renovar. Hay que reconectar la cuenta."}
            return

        _tiendas_en_curso.add(store.id)
        queue: asyncio.Queue = asyncio.Queue()
        hecho = 0

        def avanzar() -> None:
            nonlocal hecho
            hecho += 1
            queue.put_nowait({"tipo": "consultando_ml", "hecho": hecho})

        adapter = MercadoLibreAdapter(cfg)
        try:
            # Fase 1 — categoría, comisión real y envío ESTIMADO de lo que
            # todavía no está publicado (actualizar_comisiones_reales, sin
            # cambios).
            async for evento in _correr_fase(
                queue,
                actualizar_comisiones_reales(
                    db, store.id, adapter, access_token, account.external_account_site_id or "MLC",
                    account.external_account_id, on_avance=avanzar,
                ),
                "comisiones",
            ):
                yield evento

            # Fase 2 — envío REAL de lo que YA está publicado, por item_id
            # (sincronizar_costos_envio_de_la_cuenta, sin cambios). Corre
            # aunque la fase 1 haya fallado: son consultas independientes.
            async for evento in _correr_fase(
                queue,
                sincronizar_costos_envio_de_la_cuenta(db, account, settings, on_avance=avanzar),
                "envío real de tus publicaciones",
            ):
                yield evento
        finally:
            _tiendas_en_curso.discard(store.id)
            await adapter.aclose()

    # Fase 3 — con todo lo que Mercado Libre pudo resolver ya guardado, se
    # clasifica cada producto con la MISMA regla de Oportunidades (nunca se
    # recalcula un margen acá: build_profitability_rows + classify_product,
    # sin cambios). Todo lectura, sin más llamadas a Mercado Libre.
    filas, _ml_configurado = build_profitability_rows(db, store)
    config_ml = db.query(ChannelCostSettings).filter_by(store_id=store.id, channel="mercadolibre").first()
    margen_minimo_pct, ganancia_minima_clp = umbrales_minimos(config_ml)
    criterios = SelectionCriteria(
        channel="mercadolibre", require_marketplace_stock=False,
        min_margin_pct=margen_minimo_pct, ganancia_minima_clp=ganancia_minima_clp,
    )
    clasificadas = select(filas, criterios)

    total = len(clasificadas)
    for indice, fila in enumerate(clasificadas, start=1):
        yield {
            "tipo": "producto",
            "indice": indice,
            "total": total,
            "nombre": fila["nombre"],
            "sku": fila.get("sku"),
            "comisionObtenida": fila.get("comisionMlFuente") is not None,
            "envioObtenido": fila.get("envioMlResuelto") is True,
            "envioMlFuente": fila.get("envioMlFuente"),
            "clasificacion": fila["clasificacion"],
        }

    resumen = summarize_selection(clasificadas)
    yield {
        "tipo": "resumen",
        "total": total,
        "conviene": resumen["rentables"],
        "noConviene": resumen["margenBajo"] + resumen["noRentables"],
        "faltanDatos": resumen["sinDatos"],
    }
