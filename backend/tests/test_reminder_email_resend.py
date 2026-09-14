"""
Correo real de los recordatorios de vencimiento por Resend (14 de septiembre
de 2026) — contra respx, nunca la API real.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import Settings
from app.domain.reminder_email import EnviadorPorLog, EnviadorResend, enviador_desde_settings


@respx.mock
def test_resend_manda_el_mail_con_remitente_destinatario_y_texto():
    ruta = respx.post("https://api.resend.com/emails").mock(return_value=httpx.Response(200, json={"id": "49a3999c"}))

    EnviadorResend("re_prueba", "Nexo <noreply@nexo.cl>").enviar(para="duena@empresa.cl", asunto="Tu plan venció", cuerpo="Hola")

    request = ruta.calls[0].request
    assert request.headers["Authorization"] == "Bearer re_prueba"
    assert json.loads(request.content) == {
        "from": "Nexo <noreply@nexo.cl>", "to": ["duena@empresa.cl"], "subject": "Tu plan venció", "text": "Hola",
    }


@respx.mock
def test_resend_rechazado_levanta_sin_exponer_la_clave():
    """El ciclo de vida atrapa el error: un mail rechazado nunca se da por enviado."""
    respx.post("https://api.resend.com/emails").mock(return_value=httpx.Response(422, json={"message": "The domain is not verified"}))

    with pytest.raises(RuntimeError) as info:
        EnviadorResend("re_secreta_123", "Nexo <noreply@nexo.cl>").enviar(para="a@b.cl", asunto="x", cuerpo="y")
    assert "422" in str(info.value)
    assert "re_secreta_123" not in str(info.value)


def test_sin_resend_configurado_los_mails_van_al_log():
    assert isinstance(enviador_desde_settings(Settings(resend_api_key="", email_from="")), EnviadorPorLog)
    assert isinstance(enviador_desde_settings(Settings(resend_api_key="re_x", email_from="")), EnviadorPorLog)
    assert isinstance(enviador_desde_settings(Settings(resend_api_key="re_x", email_from="Nexo <noreply@nexo.cl>")), EnviadorResend)
