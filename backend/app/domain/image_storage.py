"""
Subida real de imágenes de producto desde el computador — 5 de septiembre
de 2026.

Decisión de arquitectura (evaluada antes de implementar, per pedido
explícito): almacenamiento en DISCO LOCAL, servido por FastAPI
(`StaticFiles`, ver app/main.py) — no un proveedor externo (S3, Cloudinary,
etc.). Motivos: (1) cero cuentas/credenciales nuevas que crear ni pagar
para poder probar el flujo completo hoy, (2) Nexo ya sabe servir HTTPS
público el día que se despliega de verdad (ver DEPLOY.md) — un disco
persistente ahí resuelve exactamente lo mismo que un bucket, sin acoplar
el proyecto a un proveedor específico, (3) el volumen esperado (fotos de
producto de PyMEs) está lejos de la escala en la que un disco local deja
de alcanzar. Si el día de mañana hace falta escalar a múltiples
instancias del backend, migrar a un bucket es un cambio acotado a este
único archivo (todo lo demás ya trabaja con "una URL", nunca con la ruta
física) — no una reescritura.

Nunca se confía en la extensión del archivo ni en el Content-Type que
manda el navegador (los dos son texto que cualquiera puede falsificar):
Pillow abre los bytes de verdad y sólo si decodifica una imagen real se
guarda algo.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# jpg/jpeg/png/webp — mismos formatos que Mercado Libre acepta para
# imágenes de publicación (gif/bmp no están soportados por ML).
FORMATOS_PERMITIDOS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
TAMANO_MAXIMO_BYTES = 5 * 1024 * 1024  # 5 MB por archivo
MAX_IMAGENES_POR_PRODUCTO = 8


class ImagenInvalida(Exception):
    """Nunca expone detalles internos (ruta en disco, traceback de
    Pillow) — el mensaje ya es el texto final para el dueño."""


MENSAJE_REQUISITOS = f"La imagen debe ser JPG, PNG o WEBP y pesar menos de {TAMANO_MAXIMO_BYTES // (1024 * 1024)} MB."


def _validar_bytes_de_imagen(contenido: bytes) -> str:
    # 6 de septiembre de 2026 — auditoría comercial: un solo mensaje
    # simple ("qué tiene que hacer el dueño"), nunca un detalle técnico
    # (tamaño exacto en bytes, nombre del formato que Pillow detectó) —
    # ver domain/ml_error_messages.py, mismo criterio ya aplicado a los
    # errores de Mercado Libre.
    if not contenido or len(contenido) > TAMANO_MAXIMO_BYTES:
        raise ImagenInvalida(MENSAJE_REQUISITOS)
    try:
        with Image.open(io.BytesIO(contenido)) as img:
            img.verify()  # detecta corrupción sin cargar el archivo completo en memoria dos veces
        # Pillow exige reabrir después de verify() (deja el objeto inutilizable) —
        # ver documentación de Image.verify().
        with Image.open(io.BytesIO(contenido)) as img2:
            formato = img2.format
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImagenInvalida("No pudimos abrir ese archivo como imagen — prueba con otro.") from None
    if formato not in FORMATOS_PERMITIDOS:
        raise ImagenInvalida(MENSAJE_REQUISITOS)
    return formato


def guardar_imagen(contenido: bytes, *, uploads_dir: Path, store_id: int) -> tuple[str, str]:
    """Valida y guarda un archivo ya leído en memoria. Devuelve
    (ruta_relativa_para_url, nombre_de_archivo) — nunca el nombre original
    del archivo subido (evita colisiones y cualquier caracter/ruta
    maliciosa en el nombre)."""
    formato = _validar_bytes_de_imagen(contenido)
    extension = FORMATOS_PERMITIDOS[formato]
    nombre_archivo = f"{uuid.uuid4().hex}{extension}"

    carpeta_tienda = uploads_dir / "product_images" / str(store_id)
    carpeta_tienda.mkdir(parents=True, exist_ok=True)
    destino = carpeta_tienda / nombre_archivo
    destino.write_bytes(contenido)

    ruta_relativa = f"product_images/{store_id}/{nombre_archivo}"
    return ruta_relativa, nombre_archivo


CONTENT_TYPE_POR_EXTENSION = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def ruta_local_de_imagen(url: str, *, uploads_dir: Path, backend_public_base_url: str) -> Path | None:
    """Archivo físico de una imagen que Nexo guardó, o None si la URL es
    externa (ej. un CDN de terceros) o apunta fuera de uploads_dir."""
    prefijo = f"{backend_public_base_url}/uploads/"
    if not url.startswith(prefijo):
        return None
    ruta_relativa = url[len(prefijo):]
    # Nunca sigue ".." fuera de uploads_dir, aunque `ruta_relativa` viniera
    # manipulada — resuelve y verifica que el resultado siga adentro.
    destino = (uploads_dir / ruta_relativa).resolve()
    if uploads_dir.resolve() not in destino.parents:
        return None
    return destino


def eliminar_archivo_si_es_local(url: str, *, uploads_dir: Path, backend_public_base_url: str) -> None:
    """Borra el archivo físico cuando la imagen eliminada es una que Nexo
    guardó (nunca toca nada si la URL es externa, ej. una cargada por URL
    de un CDN de terceros — no hay ningún archivo propio que borrar)."""
    destino = ruta_local_de_imagen(url, uploads_dir=uploads_dir, backend_public_base_url=backend_public_base_url)
    if destino is not None:
        destino.unlink(missing_ok=True)
