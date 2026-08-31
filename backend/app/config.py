"""
Configuración del backend — carga variables de entorno.

Aplica la misma lección aprendida al depurar el 401 persistente en
scripts/woocommerce-audit/ (ver auditCatalog.ts): por defecto, la mayoría de
las librerías de carga de .env (incluyendo pydantic-settings) hacen que una
variable de entorno YA presente en el proceso (una variable de shell suelta,
un perfil de PowerShell, etc.) GANE por sobre el valor del archivo .env del
proyecto — exactamente al revés de lo que se necesita para que "el .env de
este proyecto siempre manda, sin depender de qué haya quedado en la
terminal". Por eso, aquí se invierte explícitamente esa prioridad
(ver `settings_customise_sources` más abajo), igual que se hizo con
`override: true` en el lado de Node/dotenv.

La ruta del .env se resuelve siempre relativa a ESTE archivo (no al
directorio desde el que se invoque `uvicorn`), por la misma razón que en
auditCatalog.ts: para que no importe desde qué carpeta se ejecute el comando.
"""

from pathlib import Path
from typing import Optional, Tuple, Type

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# backend/app/config.py -> backend/.env (dos niveles arriba de este archivo)
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    woocommerce_url: str = ""
    woocommerce_consumer_key: str = ""
    woocommerce_consumer_secret: str = ""
    # Igual que en el adaptador TypeScript: por defecto se decide solo según
    # el esquema de la URL. Se puede forzar con "query" o "basic" si hace
    # falta (mismo caso conocido de Nginx/PHP-FPM descartando la cabecera
    # Authorization en http/https locales).
    woocommerce_auth_method: Optional[str] = None
    # 30 de agosto de 2026 — hallazgo de security-engineer: estas
    # credenciales son GLOBALES (una sola tienda WooCommerce para todo el
    # backend), pero GET /api/productos/reporte no estaba scopeado por
    # tienda — cualquier empresa autenticada veía el mismo catálogo. Hasta
    # que WooCommerce se integre de verdad por tienda (fuera de esta
    # ronda), el endpoint queda restringido a ESTA tienda puntual — nunca
    # hardcodeado por nombre en el código, siempre configurable/removible
    # acá. None = deshabilitado para todas las tiendas.
    woocommerce_legacy_store_id: Optional[int] = None

    # Base de datos propia del sistema (NO es WooCommerce ni Mercado Libre —
    # ver app/db/). Por defecto un archivo SQLite local, para no depender de
    # instalar nada en desarrollo/pruebas. En producción se sobreescribe con
    # una URL de PostgreSQL vía la variable de entorno DATABASE_URL.
    database_url: str = "sqlite:///./libreria_central.db"

    # OAuth de Mercado Libre (app/adapters/mercadolibre.py) — se generan
    # registrando una aplicación en https://developers.mercadolibre.cl (o el
    # sitio del país que corresponda), NO se inventan acá. Vacíos por
    # defecto: sin esto, /api/mercadolibre/conectar devuelve un error claro
    # diciendo exactamente qué falta, nunca intenta adivinar un valor.
    #
    # 29 de agosto de 2026 — corregido contra la documentación oficial
    # vigente de Mercado Libre: la Redirect URI exige HTTPS SIEMPRE, incluso
    # para registrarla en el DevCenter — "en localhost alcanza con HTTP" (lo
    # que decía antes este comentario) ya no es así. Ver backend/README.md,
    # sección "Mercado Libre real", para cómo probarlo en desarrollo con un
    # túnel HTTPS (ngrok o similar).
    mercadolibre_client_id: str = ""
    mercadolibre_client_secret: str = ""
    # URL de este backend que Mercado Libre debe llamar después del login
    # (tiene que coincidir EXACTO con la registrada en el DevCenter de ML,
    # HTTPS obligatorio).
    mercadolibre_redirect_uri: str = ""
    # Dominio de autorización — depende del país del vendedor (Chile por
    # default, ya que la tienda real es lalibreriaonlineoficial.cl). Cambiar
    # solo si la cuenta de Mercado Libre es de otro país.
    mercadolibre_auth_domain: str = "auth.mercadolibre.cl"

    # URL del frontend (frontend/index.html) — a dónde redirige
    # /api/mercadolibre/callback después de procesar la autorización (con
    # ?ml=conectado o ?ml=error&razon=..., antes del "#", para que sea un
    # query string real y no se mezcle con el router de hash del frontend).
    # Cambiar si el dueño abre Nexo desde otro host/puerto.
    frontend_base_url: str = "http://localhost:5500"

    # Clave con la que se cifran (NUNCA se guardan en texto plano) los
    # access_token/refresh_token de Mercado Libre en la base de datos — ver
    # app/domain/token_crypto.py. Se genera una vez con:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # y se guarda en .env — nunca en el código, nunca en Git.
    token_encryption_key: str = ""

    # Sesión de usuario real (29 de agosto de 2026 — ver app/api/deps.py y
    # app/api/routes/auth.py). Cookie HttpOnly, nunca localStorage (mismo
    # criterio ya aplicado a los tokens de Mercado Libre). `secure=False`
    # por defecto porque en desarrollo local el backend corre en HTTP
    # (http://localhost:8000) — un navegador nunca manda una cookie
    # "Secure" a un origen sin HTTPS. En producción SIEMPRE hay que poner
    # esto en True (backend real detrás de HTTPS) — ver DATABASE.md.
    session_cookie_secure: bool = False
    session_ttl_hours: int = 24  # sesión normal ("Recordarme" desmarcado)
    session_ttl_hours_recordarme: int = 24 * 30  # "Recordarme" marcado

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # dotenv_settings ANTES que env_settings: el .env de este proyecto
        # gana sobre cualquier variable de entorno suelta del proceso/shell.
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)


def mask_secret(value: str, visible_edge: int = 4) -> str:
    """Muestra largo + primeros/últimos caracteres — nunca el secreto completo."""
    if not value:
        return "(no definida)"
    if len(value) <= visible_edge * 2:
        return "*" * len(value)
    return f"{value[:visible_edge]}{'*' * (len(value) - visible_edge * 2)}{value[-visible_edge:]} ({len(value)} caracteres)"


def get_settings() -> Settings:
    return Settings()


def print_env_diagnostics(settings: Settings) -> None:
    if ENV_PATH.exists():
        print(f".env cargado desde: {ENV_PATH}")
    else:
        print(f"⚠ No se encontró .env en {ENV_PATH}. Usando solo variables de entorno del proceso, si hay alguna.")
    print(f"  WOOCOMMERCE_URL={settings.woocommerce_url or '(no definida)'}")
    print(f"  WOOCOMMERCE_CONSUMER_KEY={mask_secret(settings.woocommerce_consumer_key)}")
    print(f"  WOOCOMMERCE_CONSUMER_SECRET={mask_secret(settings.woocommerce_consumer_secret)}")
    print(f"  MERCADOLIBRE_CLIENT_ID={settings.mercadolibre_client_id or '(no definida)'}")
    print(f"  MERCADOLIBRE_CLIENT_SECRET={mask_secret(settings.mercadolibre_client_secret)}")
    print(f"  MERCADOLIBRE_REDIRECT_URI={settings.mercadolibre_redirect_uri or '(no definida)'}")
    print(f"  FRONTEND_BASE_URL={settings.frontend_base_url}")
    print(f"  TOKEN_ENCRYPTION_KEY={mask_secret(settings.token_encryption_key)}")
