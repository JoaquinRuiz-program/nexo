"use strict";

/**
 * Librería Central — cliente del backend real (FastAPI).
 *
 * 24 de agosto de 2026: este archivo empieza a usarse de verdad — antes
 * solo `fetchReporte()` existía, sin usar. `js/importFlow.js` fue el primer
 * consumidor real: sube un catálogo, lo analiza, calcula rentabilidad,
 * arma la selección y prepara publicaciones — todo contra el backend real,
 * cuando está disponible.
 *
 * 29 de agosto de 2026: `js/dataSource.js` también consume este archivo
 * ahora (dashboard/productos) — sigue siendo el único lugar que hace
 * fetch() de verdad; dataSource.js decide cuándo usarlo y cuándo caer a
 * Demo Mode.
 *
 * Nunca maneja API keys, secrets ni contraseñas — solo habla con este
 * backend propio, nunca directo con WooCommerce ni Mercado Libre.
 */

window.LC = window.LC || {};

(function () {
  const API_BASE_URL = "http://localhost:8000";
  const FETCH_TIMEOUT_MS = 10000;
  // Analizar/confirmar un catálogo grande puede tardar más que una consulta
  // normal (lee y valida cada fila) — timeout más generoso solo para eso.
  const UPLOAD_TIMEOUT_MS = 30000;

  // Mensajes de respaldo cuando el servidor no manda un "detail" propio —
  // en lenguaje simple, sin códigos HTTP ni palabras técnicas: quien lee
  // esto es el dueño del negocio, no alguien que sepa qué es un 500.
  // Cuando SÍ hay un "detail" (lo redacta el propio backend, ver
  // app/api/routes/), se usa tal cual — ya está pensado para explicar qué
  // falta y cómo resolverlo.
  function classifyHttpError(status, detail, bodyParseFailed) {
    if (status === 500) return { tipo: "servidor", mensaje: detail || "Hubo un problema procesando esto. Intenta de nuevo en un momento." };
    if (status === 502) {
      const esAuth = !!detail && /autenticaci[oó]n/i.test(detail);
      return { tipo: "integracion", mensaje: detail || "No pudimos conectar con Mercado Libre en este momento. Intenta de nuevo más tarde.", credenciales: esAuth ? "rechazadas" : "sin_conexion" };
    }
    if (status === 404) return { tipo: "endpoint", mensaje: detail || "No encontramos lo que buscábamos." };
    if (status === 400) return { tipo: "datos", mensaje: detail || "Algo en los datos ingresados no es válido. Revísalos e intenta de nuevo." };
    return { tipo: "http", mensaje: detail || "Ocurrió un problema inesperado. Intenta de nuevo." };
  }

  // Punto único de fetch — cualquier función de acá abajo pasa por esto,
  // así el manejo de timeout/red/HTTP/JSON no se repite 6 veces.
  async function request(path, { method = "GET", body, isFormData = false, timeoutMs = FETCH_TIMEOUT_MS } = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const opts = { method, signal: controller.signal };
    if (body !== undefined) {
      if (isFormData) {
        opts.body = body; // FormData: el navegador arma el Content-Type con el boundary solo.
      } else {
        opts.headers = { "Content-Type": "application/json" };
        opts.body = JSON.stringify(body);
      }
    }

    try {
      const res = await fetch(`${API_BASE_URL}${path}`, opts);
      clearTimeout(timeoutId);

      let responseBody = null;
      let bodyParseFailed = false;
      try {
        responseBody = await res.json();
      } catch (_parseErr) {
        bodyParseFailed = true;
      }

      if (!res.ok) {
        const detail = !bodyParseFailed && responseBody && responseBody.detail ? String(responseBody.detail) : null;
        return { ok: false, error: classifyHttpError(res.status, detail, bodyParseFailed) };
      }
      if (bodyParseFailed || responseBody === null) {
        return { ok: false, error: { tipo: "json", mensaje: "Ocurrió un problema inesperado leyendo la respuesta. Intenta de nuevo." } };
      }
      return { ok: true, data: responseBody };
    } catch (err) {
      clearTimeout(timeoutId);
      if (err && err.name === "AbortError") {
        return { ok: false, error: { tipo: "timeout", mensaje: "El servidor está tardando más de lo normal. Intenta de nuevo en un momento." } };
      }
      return {
        ok: false,
        error: { tipo: "red", mensaje: "No pudimos conectar con el servidor. Verifica tu conexión e intenta de nuevo." },
      };
    }
  }

  async function fetchReporte() {
    return request("/api/productos/reporte");
  }

  async function fetchDashboardResumen() {
    return request("/api/dashboard/resumen");
  }

  async function fetchProductos() {
    return request("/api/productos");
  }

  async function fetchProductoDetalle(id) {
    return request(`/api/productos/${id}`);
  }

  // Cierra el flujo de Oportunidades: completar el costo de UN producto
  // puntual sin volver a subir el catálogo entero (PUT /api/productos/:id/costo).
  async function actualizarCostoProducto(id, costo) {
    return request(`/api/productos/${id}/costo`, { method: "PUT", body: { costo } });
  }

  async function fetchMercadoLibreEstado() {
    return request("/api/mercadolibre/estado");
  }

  // Chequeo rápido y silencioso — usado por importFlow.js para decidir si
  // mostrar el flujo real o el de demostración. Nunca lanza un error, ni
  // muestra un toast: es solo una pregunta de "¿estás ahí?".
  async function checkHealth() {
    const resultado = await request("/api/health", { timeoutMs: 2500 });
    return resultado.ok;
  }

  async function analizarCatalogo(file) {
    const form = new FormData();
    form.append("file", file);
    return request("/api/catalogo/importar/analizar", { method: "POST", body: form, isFormData: true, timeoutMs: UPLOAD_TIMEOUT_MS });
  }

  async function confirmarImportacion(file, mapeo, omitirErrores = true) {
    const form = new FormData();
    form.append("file", file);
    form.append("mapeo", JSON.stringify(mapeo));
    form.append("omitir_errores", omitirErrores ? "true" : "false");
    return request("/api/catalogo/importar/confirmar", { method: "POST", body: form, isFormData: true, timeoutMs: UPLOAD_TIMEOUT_MS });
  }

  async function obtenerSeleccion(opts = {}) {
    const params = new URLSearchParams();
    if (opts.canal) params.set("canal", opts.canal);
    if (opts.margenMinimoClp != null) params.set("margen_minimo_clp", opts.margenMinimoClp);
    if (opts.margenMinimoPct != null) params.set("margen_minimo_pct", opts.margenMinimoPct);
    if (opts.top != null) params.set("top", opts.top);
    if (opts.requiereStock != null) params.set("requiere_stock", opts.requiereStock ? "true" : "false");
    const query = params.toString();
    return request(`/api/seleccion${query ? `?${query}` : ""}`);
  }

  async function prepararPublicaciones(variantIds, opts = {}) {
    return request("/api/publicaciones/preparar", {
      method: "POST",
      body: { variant_ids: variantIds, canal: opts.canal || "tienda", requiere_stock: opts.requiereStock !== false },
    });
  }

  LC.backendApi = {
    API_BASE_URL,
    fetchReporte,
    checkHealth,
    fetchDashboardResumen,
    fetchProductos,
    fetchProductoDetalle,
    actualizarCostoProducto,
    fetchMercadoLibreEstado,
    analizarCatalogo,
    confirmarImportacion,
    obtenerSeleccion,
    prepararPublicaciones,
  };
})();
