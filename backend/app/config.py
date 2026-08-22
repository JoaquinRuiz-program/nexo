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

    # Base de datos propia del sistema (NO es WooCommerce ni Mercado Libre —
    # ver app/db/). Por defecto un archivo SQLite local, para no depender de
    # instalar nada en desarrollo/pruebas. En producción se sobreescribe con
    # una URL de PostgreSQL vía la variable de entorno DATABASE_URL.
    database_url: str = "sqlite:///./libreria_central.db"

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
