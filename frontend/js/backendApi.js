"use strict";

/**
 * Nexo — cliente del backend real (FastAPI).
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
 *
 * 29 de agosto de 2026 — sesión real: TODAS las requests van con
 * `credentials: "include"` (la cookie HttpOnly de sesión, ver
 * app/api/deps.py, nunca se toca desde JS ni se guarda en localStorage —
 * el navegador la maneja solo). Un 401 en cualquier endpoint que NO sea
 * login/registro/me se trata como "la sesión expiró" — ver
 * setUnauthorizedHandler, que registra js/auth.js para limpiar el estado y
 * volver a /login.
 */

window.LC = window.LC || {};

(function () {
  // 30 de agosto de 2026 — antes hardcodeado acá mismo; ahora viene de
  // js/env.js (el único archivo que cambia entre desarrollo y producción).
  // Fallback a localhost si env.js no se cargó, para no romper en dev si
  // alguien lo borra por error.
  const API_BASE_URL = (window.LC && window.LC.env && window.LC.env.API_BASE_URL) || "http://localhost:8000";
  const FETCH_TIMEOUT_MS = 10000;
  // Analizar/confirmar un catálogo grande puede tardar más que una consulta
  // normal (lee y valida cada fila) — timeout más generoso solo para eso.
  const UPLOAD_TIMEOUT_MS = 30000;

  // Un 401 acá NUNCA significa "la sesión expiró" — login/registro lo usan
  // para "credenciales incorrectas" (error de formulario, no de sesión), y
  // /me lo usa para "todavía nadie inició sesión" (el caso normal en la
  // primera visita, nunca hay que mostrar un toast de "tu sesión expiró"
  // por algo que nunca empezó).
  const RUTAS_SIN_INTERCEPTOR_401 = new Set(["/api/auth/login", "/api/auth/registro", "/api/auth/me"]);

  let unauthorizedHandler = null;
  // Evita disparar el toast/redirect más de una vez si varias requests en
  // paralelo devuelven 401 al mismo tiempo (ej. una pantalla que pide
  // varias cosas con Promise.all).
  let unauthorizedHandled = false;

  function setUnauthorizedHandler(fn) {
    unauthorizedHandler = fn;
  }

  // js/auth.js llama esto apenas confirma una sesión válida (login exitoso,
  // o /me con 200) — así el próximo 401 real vuelve a disparar el handler.
  function resetUnauthorizedGuard() {
    unauthorizedHandled = false;
  }

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
    if (status === 422) return { tipo: "datos", mensaje: detail || "Algo en los datos ingresados no es válido. Revísalos e intenta de nuevo." };
    return { tipo: "http", mensaje: detail || "Ocurrió un problema inesperado. Intenta de nuevo." };
  }

  // Punto único de fetch — cualquier función de acá abajo pasa por esto,
  // así el manejo de timeout/red/HTTP/JSON no se repite 6 veces.
  async function request(path, { method = "GET", body, isFormData = false, timeoutMs = FETCH_TIMEOUT_MS } = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    // "include": manda/recibe la cookie de sesión HttpOnly aunque el
    // frontend (:5500) y este backend (:8000) sean orígenes distintos —
    // sin esto, el navegador simplemente no la envía (ver CORS
    // allow_credentials=True del lado del backend, necesario en el otro
    // extremo de lo mismo).
    const opts = { method, signal: controller.signal, credentials: "include" };
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

      if (res.status === 401 && !RUTAS_SIN_INTERCEPTOR_401.has(path) && !unauthorizedHandled) {
        unauthorizedHandled = true;
        if (unauthorizedHandler) unauthorizedHandler();
      }

      if (!res.ok) {
        // FastAPI manda "detail" como string en los errores que el propio
        // backend redacta (los que sí queremos mostrar tal cual) — pero en
        // un 422 de validación "detail" es un ARRAY de objetos {loc, msg,
        // type}. String([...]) da literalmente "[object Object],..." — acá
        // se descarta ese caso y se cae al mensaje genérico de
        // classifyHttpError en vez de mostrar texto crudo (hallazgo de
        // frontend-ux-engineer, ronda de pulido pre-cliente, 31/08/2026).
        const detail = !bodyParseFailed && responseBody && typeof responseBody.detail === "string" ? responseBody.detail : null;
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

  // ------------------------------------------------------------------
  // Autenticación real (29 de agosto de 2026) — ver js/auth.js, que es
  // quien de verdad orquesta el estado de sesión; esto solo habla con el
  // backend. Nunca hay un token que manejar acá: el navegador se encarga
  // de la cookie de sesión solo (Set-Cookie / credentials: "include").
  // ------------------------------------------------------------------

  async function login(email, password, rememberMe) {
    return request("/api/auth/login", { method: "POST", body: { email, password, remember_me: !!rememberMe } });
  }

  async function registro(email, password, fullName, companyName, rememberMe) {
    return request("/api/auth/registro", {
      method: "POST",
      body: { email, password, full_name: fullName, company_name: companyName, remember_me: !!rememberMe },
    });
  }

  async function logout() {
    return request("/api/auth/logout", { method: "POST" });
  }

  async function me() {
    return request("/api/auth/me");
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

  // 1 de septiembre de 2026 — gestión de imágenes por URL (agregar/quitar/
  // reordenar). Las tres devuelven la ficha completa del producto ya
  // actualizada (mismo patrón que actualizarCostoProducto), para no tener
  // que volver a pedirla aparte.
  async function agregarImagenProducto(id, url) {
    return request(`/api/productos/${id}/imagenes`, { method: "POST", body: { url } });
  }

  async function eliminarImagenProducto(id, imageId) {
    return request(`/api/productos/${id}/imagenes/${imageId}`, { method: "DELETE" });
  }

  async function reordenarImagenesProducto(id, orden) {
    return request(`/api/productos/${id}/imagenes/orden`, { method: "PUT", body: { orden } });
  }

  // 5 de septiembre de 2026 — subida real desde el computador (click o
  // drag & drop, ver frontend/js/app.js). `files` es un FileList o array
  // de File — se mandan todos en un solo request multipart.
  async function subirImagenesProducto(id, files) {
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    return request(`/api/productos/${id}/imagenes/upload`, { method: "POST", body: form, isFormData: true, timeoutMs: UPLOAD_TIMEOUT_MS });
  }

  // Devuelve la URL real de autorización de Mercado Libre — el navegador
  // tiene que navegar ahí de verdad (window.location.href), no un fetch:
  // es el usuario quien inicia sesión y autoriza en el sitio de ML.
  async function conectarMercadoLibre() {
    return request("/api/mercadolibre/conectar");
  }

  async function desconectarMercadoLibre() {
    return request("/api/mercadolibre/desconectar", { method: "POST" });
  }

  async function importarVentasMercadoLibre() {
    return request("/api/mercadolibre/importar-ventas", { method: "POST", timeoutMs: UPLOAD_TIMEOUT_MS });
  }

  // Comisión REAL de Mercado Libre por producto (29 de agosto de 2026,
  // segunda ronda) — consulta la API real de ML (categoría + comisión por
  // precio), nunca instantáneo: puede tardar según el tamaño del catálogo.
  async function recalcularComisionesMercadoLibre() {
    return request("/api/mercadolibre/comisiones/recalcular", { method: "POST", timeoutMs: UPLOAD_TIMEOUT_MS });
  }

  // Google Sheets como fuente de catálogo (5 de septiembre de 2026) — mismo
  // patrón que Mercado Libre arriba: /conectar devuelve una URL real a la
  // que hay que navegar de página completa, nunca un fetch.
  async function fetchGoogleSheetsEstado() {
    return request("/api/google-sheets/estado");
  }

  async function conectarGoogleSheets() {
    return request("/api/google-sheets/conectar");
  }

  async function desconectarGoogleSheets() {
    return request("/api/google-sheets/desconectar", { method: "POST" });
  }

  async function vincularHojaGoogleSheets(url) {
    return request("/api/google-sheets/hoja", { method: "POST", body: { url } });
  }

  async function analizarHojaGoogleSheets(hoja) {
    return request("/api/google-sheets/importar/analizar", { method: "POST", body: hoja ? { hoja } : {}, timeoutMs: UPLOAD_TIMEOUT_MS });
  }

  async function confirmarHojaGoogleSheets(hoja, mapeo, omitirErrores) {
    const body = { mapeo, omitirErrores: omitirErrores !== false };
    if (hoja) body.hoja = hoja;
    return request("/api/google-sheets/importar/confirmar", { method: "POST", body, timeoutMs: UPLOAD_TIMEOUT_MS });
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

  // ------------------------------------------------------------------
  // 30 de agosto de 2026 — flujo por producto de decisión + publicación en
  // Mercado Libre (FASE 6 frontend). Nombre explícito "MercadoLibre" (no
  // "publicacion" a secas) para no confundirse con prepararPublicaciones()
  // de arriba, que es un endpoint distinto (en lote, genérico "tienda").
  // ------------------------------------------------------------------

  async function decisionMercadoLibre(variantId) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/decision`);
  }

  async function decisionLoteMercadoLibre() {
    return request("/api/publicaciones/mercadolibre/decision-lote");
  }

  async function competenciaMercadoLibre(variantId) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/competencia`);
  }

  async function precioRecomendadoMercadoLibre(variantId) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/precio-recomendado`);
  }

  async function prepararPublicacionMercadoLibre(variantId) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/preparar`, { method: "POST" });
  }

  async function validarPublicacionMercadoLibre(variantId, { categoryId, condition }) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/validar`, {
      method: "POST",
      body: { category_id: categoryId, condition },
    });
  }

  async function previewPublicacionMercadoLibre(variantId, body) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/confirmar/preview`, { method: "POST", body });
  }

  async function confirmarPublicacionMercadoLibre(variantId, body) {
    // POST /items real puede tardar más que una consulta normal (Mercado
    // Libre valida categoría/atributos/comisión antes de responder) —
    // mismo timeout generoso que las otras llamadas lentas a Mercado
    // Libre, para no cortar la request antes de que el backend confirme.
    return request(`/api/publicaciones/${variantId}/mercadolibre/confirmar`, { method: "POST", body, timeoutMs: UPLOAD_TIMEOUT_MS });
  }

  async function actualizarCodigoBarras(variantId, { barcode, confirmarSinCodigo }) {
    return request(`/api/productos/${variantId}/codigo-barras`, {
      method: "PUT",
      body: { barcode: barcode ?? null, confirmarSinCodigo: !!confirmarSinCodigo },
    });
  }

  // 1 de septiembre de 2026 — gestión de una publicación ya creada
  // (estado real/pausar/reactivar/eliminar). estadoPublicacionMercadoLibre
  // siempre reconsulta Mercado Libre (nunca un valor cacheado del
  // frontend) — timeout normal, no es una llamada lenta como confirmar.
  async function estadoPublicacionMercadoLibre(variantId) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/publicacion`);
  }

  async function pausarPublicacionMercadoLibre(variantId) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/pausar`, { method: "POST" });
  }

  async function reactivarPublicacionMercadoLibre(variantId) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/reactivar`, { method: "POST" });
  }

  async function eliminarPublicacionMercadoLibre(variantId) {
    return request(`/api/publicaciones/${variantId}/mercadolibre/eliminar`, { method: "POST" });
  }

  // ------------------------------------------------------------------
  // 30 de agosto de 2026 — panel de administrador de Nexo (dueño de la
  // plataforma). Solo responde si la sesión tiene is_nexo_admin — para
  // cualquier otro usuario, el backend devuelve 404 (nunca 403, ver
  // app/api/deps.py::require_nexo_admin).
  // ------------------------------------------------------------------

  async function listarClientesAdmin() {
    return request("/api/admin/clientes");
  }

  async function detalleClienteAdmin(storeId) {
    return request(`/api/admin/clientes/${storeId}`);
  }

  async function actualizarEstadoClienteAdmin(storeId, suspendido) {
    return request(`/api/admin/clientes/${storeId}/estado`, { method: "PUT", body: { suspendido } });
  }

  async function listarUsuariosAdmin() {
    return request("/api/admin/usuarios");
  }

  async function listarPlanesAdmin() {
    return request("/api/admin/planes");
  }

  async function actualizarSuscripcionAdmin(storeId, { planCode, estado } = {}) {
    return request(`/api/admin/clientes/${storeId}/suscripcion`, { method: "PUT", body: { planCode, estado } });
  }

  async function listarSolicitudesSoporteAdmin() {
    return request("/api/admin/soporte/solicitudes");
  }

  async function detalleSolicitudSoporteAdmin(ticketId) {
    return request(`/api/admin/soporte/solicitudes/${ticketId}`);
  }

  async function responderSolicitudSoporteAdmin(ticketId, { respuesta, estado } = {}) {
    return request(`/api/admin/soporte/solicitudes/${ticketId}`, { method: "PUT", body: { respuesta, estado } });
  }

  // ------------------------------------------------------------------
  // Mi plan (suscripción real de la empresa) y Ayuda y soporte.
  // ------------------------------------------------------------------

  async function fetchMiSuscripcion() {
    return request("/api/suscripcion");
  }

  async function listarMisSolicitudesSoporte() {
    return request("/api/soporte/solicitudes");
  }

  async function crearSolicitudSoporte({ category, subject, description, reference }) {
    return request("/api/soporte/solicitudes", { method: "POST", body: { category, subject, description, reference } });
  }

  async function obtenerMiSolicitudSoporte(ticketId) {
    return request(`/api/soporte/solicitudes/${ticketId}`);
  }

  async function obtenerConfiguracionCanales() {
    return request("/api/configuracion/canales");
  }

  async function configurarCanal(channel, body) {
    return request(`/api/configuracion/canales/${channel}`, { method: "PUT", body });
  }

  LC.backendApi = {
    API_BASE_URL,
    login,
    registro,
    logout,
    me,
    setUnauthorizedHandler,
    resetUnauthorizedGuard,
    fetchReporte,
    checkHealth,
    fetchDashboardResumen,
    fetchProductos,
    fetchProductoDetalle,
    actualizarCostoProducto,
    agregarImagenProducto,
    eliminarImagenProducto,
    reordenarImagenesProducto,
    subirImagenesProducto,
    fetchMercadoLibreEstado,
    conectarMercadoLibre,
    desconectarMercadoLibre,
    importarVentasMercadoLibre,
    recalcularComisionesMercadoLibre,
    fetchGoogleSheetsEstado,
    conectarGoogleSheets,
    desconectarGoogleSheets,
    vincularHojaGoogleSheets,
    analizarHojaGoogleSheets,
    confirmarHojaGoogleSheets,
    analizarCatalogo,
    confirmarImportacion,
    obtenerSeleccion,
    prepararPublicaciones,
    decisionMercadoLibre,
    decisionLoteMercadoLibre,
    competenciaMercadoLibre,
    precioRecomendadoMercadoLibre,
    prepararPublicacionMercadoLibre,
    validarPublicacionMercadoLibre,
    previewPublicacionMercadoLibre,
    confirmarPublicacionMercadoLibre,
    actualizarCodigoBarras,
    estadoPublicacionMercadoLibre,
    pausarPublicacionMercadoLibre,
    reactivarPublicacionMercadoLibre,
    eliminarPublicacionMercadoLibre,
    obtenerConfiguracionCanales,
    configurarCanal,
    listarClientesAdmin,
    detalleClienteAdmin,
    actualizarEstadoClienteAdmin,
    listarUsuariosAdmin,
    listarPlanesAdmin,
    actualizarSuscripcionAdmin,
    listarSolicitudesSoporteAdmin,
    detalleSolicitudSoporteAdmin,
    responderSolicitudSoporteAdmin,
    fetchMiSuscripcion,
    listarMisSolicitudesSoporte,
    crearSolicitudSoporte,
    obtenerMiSolicitudSoporte,
  };
})();
