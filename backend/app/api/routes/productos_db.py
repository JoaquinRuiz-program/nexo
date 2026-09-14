"""
Catálogo respaldado por la base de datos propia (no WooCommerce) — primera
porción vertical de "datos de prueba -> BD -> API -> frontend" (ver decisión
del 22 de agosto de 2026 de no depender todavía del acceso real a
WooCommerce). Hoy la base se llena con app/db/seed_demo.py; el día que exista
un job real de sincronización con WooCommerce, ese job llena las mismas
tablas (Product/ProductVariant) y este endpoint no cambia una línea.

29 de agosto de 2026 — cada endpoint exige sesión válida y filtra/valida
por `store.id` (Depends(get_current_store)). Antes de esto, `GET/PUT
/api/productos/{id}` buscaba la variante SOLO por su ID, sin verificar de
qué tienda era — con una sola tienda en desarrollo era invisible, pero es
exactamente el hueco (IDOR: adivinar/iterar un ID ajeno) que había que
cerrar antes de tener más de un cliente real. `_variante_de_la_tienda`
centraliza ese chequeo: un ID que existe pero es de OTRA tienda responde
404, igual que un ID que no existe — nunca se distingue una cosa de la
otra en la respuesta.
"""

from __future__ import annotations

from datetime import datetime

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_store
from app.config import get_settings
from app.db.models import MarketplaceAccount, MarketplaceListing, Product, ProductImage, ProductVariant, Store
from app.db.session import get_db
from app.domain.image_storage import (
    MAX_IMAGENES_POR_PRODUCTO,
    ImagenInvalida,
    eliminar_archivo_si_es_local,
    guardar_imagen,
)
from app.domain.listing_validation import gtin_checksum_valido
from app.domain.marketplace_stock import set_manual_stock

router = APIRouter(prefix="/api/productos", tags=["productos-bd"])


class MarketplaceStockUpdate(BaseModel):
    # None = dejar de ofrecer el producto por Mercado Libre (no configurado).
    cantidad: int | None = None


class CostoUpdate(BaseModel):
    # None = borrar el costo cargado (vuelve a "sin costo", nunca $0).
    costo: float | None = None


class StockUpdate(BaseModel):
    # None = este producto no gestiona stock (distinto de 0 = sin unidades).
    cantidad: int | None = None


class ImagenUrlCreate(BaseModel):
    url: str


class ImagenesOrdenUpdate(BaseModel):
    orden: list[int]  # ids de ProductImage, en el orden final deseado


class CodigoBarrasUpdate(BaseModel):
    # None = no hay código para cargar en esta llamada — ver
    # confirmarSinCodigo para distinguir "no sabemos todavía" de "el dueño
    # confirmó que este producto no tiene GTIN" (30 de agosto de 2026).
    barcode: str | None = None
    confirmarSinCodigo: bool = False


def _estado_gtin(variante: ProductVariant) -> str:
    """valido | invalido | sin_codigo_confirmado | datos_incompletos — ver
    PUBLICACION_MERCADOLIBRE.md, Caso A/B/C/D. Nunca se usa para bloquear
    nada acá (solo informa) — el bloqueo real vive en /confirmar."""
    if variante.barcode:
        return "valido" if gtin_checksum_valido(variante.barcode) else "invalido"
    if variante.gtin_confirmado_ausente:
        return "sin_codigo_confirmado"
    return "datos_incompletos"


def build_producto_fila(producto: Product, variante: ProductVariant) -> dict:
    return {
        "id": variante.id,
        "sku": variante.variant_sku or "",
        "nombre": f"{producto.name} - {variante.variant_label}" if variante.variant_label else producto.name,
        "categoria": producto.category,
        "tipo": producto.product_type,
        "precio": float(variante.price) if variante.price is not None else None,
        "stockQuantity": variante.stock_quantity,
        "gestionaStock": variante.manage_stock,
        "estadoStock": variante.stock_status,
        # Tope manual de unidades reservadas para Mercado Libre — NO es
        # stock físico (ver app/domain/marketplace_stock.py). None = el
        # dueño todavía no decidió ofrecer este producto por ese canal.
        "marketplaceStock": variante.marketplace_stock,
        "esVariante": producto.product_type == "variable",
        "colorVariante": variante.variant_label,
        "parentId": producto.id,
        "codigoBarras": variante.barcode,
        "estadoGtin": _estado_gtin(variante),
        # 1 de septiembre de 2026 — gestión de imágenes: `position == 0` es
        # la imagen principal (ver ProductImage.position en el modelo,
        # "0 = imagen principal"), acá ya resuelto como `principal` para
        # que el frontend no tenga que conocer esa convención.
        "imagenes": [
            {"id": img.id, "url": img.url, "principal": img.position == 0}
            for img in sorted(producto.images, key=lambda i: i.position)
        ],
    }


def _variante_de_la_tienda(db: Session, store: Store, variant_id: int) -> ProductVariant:
    """La variante SOLO si es de esta tienda — un ID real pero de otra
    empresa da el mismo 404 que un ID inexistente (nunca 403: no hay que
    confirmarle a quien pregunta que ese ID existe en algún lado)."""
    variante = db.get(ProductVariant, variant_id)
    if variante is None or variante.store_id != store.id:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    return variante


def _estado_publicacion_por_producto(db: Session, store: Store) -> dict[int, str]:
    """6 de septiembre de 2026 — "estado claro de cada producto" (auditoría
    comercial): una sola consulta agregada, nunca una por producto —
    devuelve {product_id: status} de MarketplaceListing (active/paused/
    closed) solo para las publicaciones de ESTA tienda. Un producto sin
    entrada acá nunca se publicó todavía."""
    filas = (
        db.query(MarketplaceListing.product_id, MarketplaceListing.status)
        .join(MarketplaceAccount, MarketplaceListing.account_id == MarketplaceAccount.id)
        .filter(MarketplaceAccount.store_id == store.id)
        .all()
    )
    return {product_id: status for product_id, status in filas}


@router.get("")
def listar_productos(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> list[dict]:
    productos = db.query(Product).filter_by(store_id=store.id).order_by(Product.name).all()
    estado_publicacion = _estado_publicacion_por_producto(db, store)
    filas = []
    for producto in productos:
        for variante in producto.variants:
            fila = build_producto_fila(producto, variante)
            fila["estadoPublicacionMercadoLibre"] = estado_publicacion.get(producto.id)
            filas.append(fila)
    return filas


@router.get("/{variant_id}")
def obtener_producto(variant_id: int, db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    variante = _variante_de_la_tienda(db, store, variant_id)
    return build_producto_fila(variante.product, variante)


class MarketplaceStockLoteUpdate(BaseModel):
    # None = todos los productos de la tienda; una lista = solo esos.
    variantIds: list[int] | None = None
    cantidad: int | None = None


@router.put("/stock-mercadolibre/lote")
def configurar_stock_mercado_libre_en_lote(
    body: MarketplaceStockLoteUpdate,
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    """14 de septiembre de 2026 — reservar unidades para Mercado Libre en
    MUCHOS productos de una sola vez, en vez de uno por uno. Es el dato que
    hoy más frena publicar: sin él, un producto no se puede subir. Con esto
    el dueño fija un stock por defecto (ej. 5) para todo lo seleccionado y
    listo, sin tener que cargarlo producto por producto.

    Mismo criterio de aislamiento que el resto: solo toca variantes de ESTA
    tienda (nunca un variantId de otra empresa, aunque venga en el body).
    `variantIds=None` aplica a todos los productos de la tienda."""
    try:
        valor = set_manual_stock(body.cantidad)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    q = db.query(ProductVariant).filter(ProductVariant.store_id == store.id)
    if body.variantIds is not None:
        if not body.variantIds:
            return {"actualizados": 0}
        q = q.filter(ProductVariant.id.in_(body.variantIds))
    variantes = q.all()
    for v in variantes:
        v.marketplace_stock = valor
    db.commit()
    return {"actualizados": len(variantes)}


@router.put("/{variant_id}/stock-mercadolibre")
def configurar_stock_mercado_libre(
    variant_id: int,
    body: MarketplaceStockUpdate,
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    """El dueño decide manualmente cuántas unidades ofrecer por Mercado
    Libre — 5 -> 10 -> 0 -> None, en cualquier momento. Nunca toca
    stock_quantity (el stock que reporta WooCommerce): son dos números
    completamente separados a propósito (ver domain/marketplace_stock.py)."""
    variante = _variante_de_la_tienda(db, store, variant_id)

    try:
        variante.marketplace_stock = set_manual_stock(body.cantidad)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    db.commit()
    db.refresh(variante)
    return build_producto_fila(variante.product, variante)


@router.put("/{variant_id}/costo")
def configurar_costo(
    variant_id: int, body: CostoUpdate, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    """Cierra el círculo de "Oportunidades": completar el costo de compra de
    UN producto puntual, sin tener que volver a subir todo el catálogo por
    Excel. `cost_price` es el mismo campo que ya lee domain/profitability.py
    — el margen se recalcula solo la próxima vez que se pida (acá no se
    guarda ningún margen, solo el costo real, igual que en la importación)."""
    variante = _variante_de_la_tienda(db, store, variant_id)
    if body.costo is not None and body.costo < 0:
        raise HTTPException(status_code=400, detail="El costo no puede ser negativo.")

    variante.cost_price = body.costo
    db.commit()
    db.refresh(variante)
    return build_producto_fila(variante.product, variante)


@router.put("/{variant_id}/stock")
def configurar_stock(
    variant_id: int, body: StockUpdate, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    """13 de septiembre de 2026 — stock físico editable a mano, mismo criterio
    que `configurar_costo`: la mayoría de los Excel reales traen solo código,
    nombre, costo y precio, así que sin esto el stock quedaba en `None` para
    siempre y no había forma de corregirlo desde la aplicación.

    NO toca `marketplace_stock` (las unidades reservadas para Mercado Libre,
    ver configurar_stock_mercado_libre): son dos números separados a
    propósito. `cantidad=None` significa "este producto no gestiona stock",
    que es distinto de 0 ("gestiona stock y no queda ninguna")."""
    variante = _variante_de_la_tienda(db, store, variant_id)
    if body.cantidad is not None and body.cantidad < 0:
        raise HTTPException(status_code=400, detail="El stock no puede ser negativo.")

    variante.stock_quantity = body.cantidad
    variante.manage_stock = body.cantidad is not None
    variante.stock_status = "instock" if (body.cantidad or 0) > 0 else "outofstock"
    db.commit()
    db.refresh(variante)
    return build_producto_fila(variante.product, variante)


@router.put("/{variant_id}/codigo-barras")
def configurar_codigo_barras(
    variant_id: int, body: CodigoBarrasUpdate, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    """Carga el GTIN real de un producto, o confirma explícitamente que no
    tiene — nunca las dos cosas a la vez. Ver Caso A/B/C/D en
    PUBLICACION_MERCADOLIBRE.md: esto es lo que cierra el Caso D ("Nexo
    todavía no lo sabe") sin que /confirmar tenga que adivinarlo."""
    variante = _variante_de_la_tienda(db, store, variant_id)

    codigo = (body.barcode or "").strip() or None
    if codigo is not None:
        if not gtin_checksum_valido(codigo):
            raise HTTPException(
                status_code=400,
                detail="Ese código no es válido (no pasa el checksum GTIN/EAN) — revisalo antes de guardarlo.",
            )
        variante.barcode = codigo
        variante.gtin_confirmado_ausente = False
    else:
        variante.barcode = None
        variante.gtin_confirmado_ausente = body.confirmarSinCodigo

    db.commit()
    db.refresh(variante)
    return build_producto_fila(variante.product, variante)


# ------------------------------------------------------------------
# Gestión de imágenes (1 de septiembre de 2026, ronda de pulido). Hoy
# Nexo NO tiene almacenamiento real de archivos (ni local ni en la nube,
# ver docstring de ProductImage) — estos tres endpoints son el CRUD real
# que faltaba sobre lo que ya existe (URL + orden), para que el dueño
# pueda agregar/quitar/reordenar imágenes sin volver a subir el Excel.
# Cargar un archivo real desde la computadora sigue sin poder hacerse
# hasta que se elija un proveedor de almacenamiento — decisión de
# arquitectura que no se toma acá.
#
# `position` reasignada siempre de forma contigua (0..N-1) después de
# cualquier cambio: es la única forma de que "position == 0 == imagen
# principal" (ver build_producto_fila) sea siempre verdad, nunca deje un
# hueco si se borra justo la principal.
# ------------------------------------------------------------------


def _reordenar_posiciones(imagenes: list[ProductImage]) -> None:
    for indice, imagen in enumerate(sorted(imagenes, key=lambda i: i.position)):
        imagen.position = indice


@router.post("/{variant_id}/imagenes")
def agregar_imagen(
    variant_id: int, body: ImagenUrlCreate, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    """Agrega una imagen por URL — nunca se descarga ni se valida que la
    URL cargue de verdad (eso lo confirma el propio dueño viendo la
    previsualización en el frontend antes de confirmar; Nexo no tiene
    almacenamiento propio para copiarla). Solo se rechaza lo que no puede
    ser una URL real."""
    variante = _variante_de_la_tienda(db, store, variant_id)
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Falta la URL de la imagen.")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="La URL de la imagen tiene que empezar con http:// o https://.")
    if len(url) > 1000:
        raise HTTPException(status_code=400, detail="Esa URL es demasiado larga.")

    producto = variante.product
    siguiente_posicion = max((img.position for img in producto.images), default=-1) + 1
    db.add(ProductImage(product=producto, url=url, source="manual_upload", position=siguiente_posicion, created_at=datetime.now()))
    db.commit()
    db.refresh(variante)
    return build_producto_fila(variante.product, variante)


@router.post("/{variant_id}/imagenes/upload")
async def subir_imagenes(
    variant_id: int,
    files: list[UploadFile],
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    """Subida real desde el computador (click o drag & drop, ver
    frontend) — a diferencia de agregar_imagen (por URL), acá Nexo sí
    guarda el archivo (ver app/domain/image_storage.py). Valida cada
    archivo de a uno: uno inválido no aborta los demás, se informa cuál
    falló y por qué."""
    variante = _variante_de_la_tienda(db, store, variant_id)
    producto = variante.product
    settings = get_settings()
    uploads_dir = Path(settings.uploads_dir)

    cantidad_actual = len(producto.images)
    guardadas: list[str] = []
    rechazadas: list[dict] = []
    siguiente_posicion = max((img.position for img in producto.images), default=-1) + 1

    for file in files:
        if cantidad_actual + len(guardadas) >= MAX_IMAGENES_POR_PRODUCTO:
            rechazadas.append({"archivo": file.filename, "motivo": f"Este producto ya tiene el máximo de {MAX_IMAGENES_POR_PRODUCTO} imágenes."})
            continue
        contenido = await file.read()
        try:
            ruta_relativa, _nombre = guardar_imagen(contenido, uploads_dir=uploads_dir, store_id=store.id)
        except ImagenInvalida as err:
            rechazadas.append({"archivo": file.filename, "motivo": str(err)})
            continue
        url = f"{settings.backend_public_base_url}/uploads/{ruta_relativa}"
        db.add(ProductImage(product=producto, url=url, source="manual_upload", position=siguiente_posicion, created_at=datetime.now()))
        siguiente_posicion += 1
        guardadas.append(file.filename or "")

    db.commit()
    db.refresh(variante)
    resultado = build_producto_fila(variante.product, variante)
    resultado["subidas"] = {"guardadas": len(guardadas), "rechazadas": rechazadas}
    return resultado


@router.delete("/{variant_id}/imagenes/{image_id}")
def eliminar_imagen(
    variant_id: int, image_id: int, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    variante = _variante_de_la_tienda(db, store, variant_id)
    producto = variante.product
    imagen = next((img for img in producto.images if img.id == image_id), None)
    if imagen is None:
        raise HTTPException(status_code=404, detail="Esa imagen no existe para este producto.")

    settings = get_settings()
    eliminar_archivo_si_es_local(imagen.url, uploads_dir=Path(settings.uploads_dir), backend_public_base_url=settings.backend_public_base_url)
    db.delete(imagen)
    db.flush()
    _reordenar_posiciones([img for img in producto.images if img.id != image_id])
    db.commit()
    db.refresh(variante)
    return build_producto_fila(variante.product, variante)


@router.put("/{variant_id}/imagenes/orden")
def reordenar_imagenes(
    variant_id: int, body: ImagenesOrdenUpdate, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    """`body.orden` tiene que incluir EXACTAMENTE los ids de imágenes que
    ya tiene este producto, ni más ni menos — nunca se asume un orden
    parcial (dejaría posiciones ambiguas)."""
    variante = _variante_de_la_tienda(db, store, variant_id)
    producto = variante.product
    imagenes_por_id = {img.id: img for img in producto.images}
    if set(body.orden) != set(imagenes_por_id.keys()):
        raise HTTPException(status_code=400, detail="El orden enviado no coincide con las imágenes actuales de este producto.")

    for indice, image_id in enumerate(body.orden):
        imagenes_por_id[image_id].position = indice
    db.commit()
    db.refresh(variante)
    return build_producto_fila(variante.product, variante)
