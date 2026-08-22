"use strict";

/**
 * Librería Central — cliente del backend real (FastAPI).
 *
 * IMPORTANTE: este archivo NO se usa todavía. Esta fase del proyecto es
 * "solo frontend, con datos de demostración" — ver js/demoData.js y
 * js/dataSource.js, que es lo que las pantallas consultan hoy. Este módulo
 * queda listo y probado (se construyó y se verificó de punta a punta en la
 * fase anterior) para el día en que conectemos el backend real: en ese
 * momento, dataSource.js es el único archivo que hay que tocar para que las
 * pantallas empiecen a llamar a estas funciones en vez de a los datos demo.
 *
 * Nunca maneja API keys, secrets ni contraseñas — solo habla con este
 * backend propio, nunca directo con WooCommerce ni Mercado Libre.
 */

window.LC = window.LC || {};

(function () {
  const API_BASE_URL = "http://localhost:8000";
  const REPORTE_ENDPOINT = `${API_BASE_URL}/api/productos/reporte`;
  const FETCH_TIMEOUT_MS = 10000;

  async function fetchReporte() {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    try {
      const res = await fetch(REPORTE_ENDPOINT, { signal: controller.signal });
      clearTimeout(timeoutId);

      let body = null;
      let bodyParseFailed = false;
      try {
        body = await res.json();
      } catch (_parseErr) {
        bodyParseFailed = true;
      }

      if (!res.ok) {
        const detail = !bodyParseFailed && body && body.detail ? String(body.detail) : null;
        return { ok: false, error: classifyHttpError(res.status, detail, bodyParseFailed) };
      }
      if (bodyParseFailed || !body) {
        return { ok: false, error: { tipo: "json", mensaje: "El backend respondió, pero el contenido no es un JSON válido." } };
      }
      return { ok: true, data: body };
    } catch (err) {
      clearTimeout(timeoutId);
      if (err && err.name === "AbortError") {
        return { ok: false, error: { tipo: "timeout", mensaje: `El backend no respondió en ${FETCH_TIMEOUT_MS / 1000} segundos.` } };
      }
      return {
        ok: false,
        error: {
          tipo: "red",
          mensaje: "No fue posible conectar con el backend. Verifica que esté corriendo, o que CORS permita este origen.",
        },
      };
    }
  }

  function classifyHttpError(status, detail, bodyParseFailed) {
    if (status === 500) return { tipo: "credenciales", mensaje: detail || "Faltan variables de entorno de WooCommerce en backend/.env." };
    if (status === 502) {
      const esAuth = !!detail && /autenticaci[oó]n/i.test(detail);
      return { tipo: "woocommerce", mensaje: detail || "No se pudo conectar con WooCommerce.", credenciales: esAuth ? "rechazadas" : "sin_conexion" };
    }
    if (status === 404) return { tipo: "endpoint", mensaje: "El endpoint /api/productos/reporte no existe en este backend." };
    return { tipo: "http", mensaje: bodyParseFailed ? `El backend respondió HTTP ${status}.` : detail || `El backend respondió HTTP ${status}.` };
  }

  LC.backendApi = { API_BASE_URL, fetchReporte };
})();
