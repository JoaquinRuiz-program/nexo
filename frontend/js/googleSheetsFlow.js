"use strict";

/**
 * Nexo — Google Sheets como fuente de catálogo (5 de septiembre de 2026).
 *
 * Flujo simple, a propósito (pedido explícito): Conectar con Google →
 * pegar el link de una hoja de cálculo → revisar columnas detectadas →
 * confirmar → importar → ver el resultado. Reutiliza el mismo backend que
 * ya valida/crea productos para Excel/CSV (app/api/routes/google_sheets.py
 * llama a los mismos app/domain/catalog_import.py + catalog_writer.py) —
 * esta pantalla solo agrega el paso de "vincular una hoja" antes de llegar
 * al mismo tipo de revisión de columnas que ya existe en js/importFlow.js.
 *
 * Nunca guarda ningún token de Google acá — todo lo que esta pantalla ve es
 * lo que devuelve GET /api/google-sheets/estado (nunca un access/refresh
 * token, ver app/api/routes/google_sheets.py::_account_status).
 */

window.LC = window.LC || {};

(function () {
  const { escapeHtml, toast, openModal, icon } = LC.ui;

  const CAMPOS_LABEL = {
    sku: "SKU", nombre: "Nombre del producto", marca: "Marca", categoria: "Categoría",
    costo: "Costo de compra", precio: "Precio de venta", stock: "Stock",
    descripcion: "Descripción", imagen_url: "Imagen (URL)", codigo_barras: "Código de barras",
  };

  // Mismo criterio que RAZON_ERROR_ML en js/app.js: nunca se muestra el
  // "razon" crudo que manda el backend, siempre se traduce a lenguaje humano.
  const RAZON_ERROR_GS = {
    rechazado: "No se completó la autorización en Google.",
    error_autorizacion: "Google no pudo autorizar la conexión.",
    solicitud_invalida: "La respuesta de Google no fue la esperada.",
    estado_invalido: "El enlace de conexión venció — prueba conectar de nuevo.",
    credenciales_faltantes: "Todavía no configuraste las credenciales de Google.",
    conexion_fallida: "No pudimos conectar con Google. Prueba de nuevo en un momento.",
    cifrado_no_configurado: "Hay un problema de configuración interno — avísale a soporte.",
    sin_refresh_token: "Google no autorizó el acceso permanente — prueba conectar de nuevo y acepta todos los permisos pedidos.",
  };

  function estadoInicial() {
    return {
      fase: "cargando",
      estado: null,
      hojasDisponibles: [],
      hojaElegida: null,
      analisis: null,
      mapeo: null,
      confirmarResultado: null,
    };
  }

  let state = estadoInicial();

  async function render(main) {
    consumirRedirect();
    state = estadoInicial();
    main.innerHTML = skeleton();

    const res = await LC.backendApi.fetchGoogleSheetsEstado();
    if (!res.ok) {
      main.innerHTML = `<div class="page-wrap app-fade"><div class="panel-card"><p class="text-sm text-red-600 dark:text-red-400">No pudimos consultar el estado de Google Sheets ahora mismo.</p></div></div>`;
      return;
    }
    state.estado = res.data;
    state.fase = !res.data.conectado ? "conectar" : !res.data.spreadsheetId ? "vincular" : "listo";
    renderFase(main);
  }

  function consumirRedirect() {
    const url = new URL(window.location.href);
    const gsParam = url.searchParams.get("gs");
    if (!gsParam) return;
    if (gsParam === "conectado") toast("success", "Google conectado correctamente.");
    else toast("error", RAZON_ERROR_GS[url.searchParams.get("razon")] || "No se completó la conexión con Google.");
    url.searchParams.delete("gs");
    url.searchParams.delete("razon");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }

  function skeleton() {
    return `<div class="page-wrap app-fade">
      <div class="skeleton-line h-8 w-64 mb-6"></div>
      <div class="skeleton-line h-40 w-full"></div>
    </div>`;
  }

  function renderFase(main) {
    const contenido = {
      conectar: renderPasoConectar,
      vincular: renderPasoVincular,
      listo: renderPasoListo,
      analizando: () => `<div class="panel-card text-center py-16"><div class="text-4xl mb-4 animate-pulse">${icon("search")}</div><p class="font-medium text-slate-700 dark:text-slate-200">Leyendo tu hoja de cálculo…</p></div>`,
      revision: renderPasoRevision,
      resultado: renderPasoResultado,
    }[state.fase];

    main.innerHTML = `<div class="page-wrap app-fade max-w-4xl">${contenido()}</div>`;
    wireFase(main);
  }

  function wireFase(main) {
    ({
      conectar: wirePasoConectar,
      vincular: wirePasoVincular,
      listo: wirePasoListo,
      analizando: () => {},
      revision: wirePasoRevision,
      resultado: wirePasoResultado,
    })[state.fase](main);
  }

  // ------------------------------------------------------------------
  // Paso 1 — Conectar con Google
  // ------------------------------------------------------------------

  function renderPasoConectar() {
    const conf = state.estado.credencialesConfiguradas;
    return `
      <div class="panel-card text-center py-12">
        <div class="text-4xl mb-4">${icon("link")}</div>
        <h2 class="text-xl font-semibold mb-2">Conecta Google Sheets</h2>
        <p class="text-slate-500 dark:text-slate-400 max-w-md mx-auto mb-6">
          Usa una hoja de cálculo de Google como fuente de tu catálogo — una alternativa a subir un Excel cada vez.
          Vas a tener que autorizar el acceso de solo lectura a tus hojas de cálculo.
        </p>
        <button id="btn-conectar-gs" class="btn-primary" ${conf ? "" : "disabled"}>Conectar con Google</button>
        ${conf ? "" : `<p class="text-xs text-slate-400 mt-3">Todavía no está lista esta conexión — contáctanos para activarla.</p>`}
      </div>
    `;
  }

  function wirePasoConectar(main) {
    const btn = document.getElementById("btn-conectar-gs");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Conectando…";
      const res = await LC.backendApi.conectarGoogleSheets();
      if (!res.ok) {
        btn.disabled = false;
        btn.textContent = "Conectar con Google";
        toast("error", res.error.mensaje);
        return;
      }
      // Página completa: es Google quien tiene que mostrar su propia
      // pantalla de login/consentimiento, nunca algo que se haga con fetch().
      window.location.href = res.data.authorizationUrl;
    });
  }

  // ------------------------------------------------------------------
  // Paso 2 — Vincular una hoja de cálculo
  // ------------------------------------------------------------------

  function renderPasoVincular() {
    return `
      <div class="panel-card">
        <div class="flex items-center justify-between gap-3 mb-1">
          <h2 class="panel-title">Elige tu hoja de cálculo</h2>
          <span class="dot dot--green" title="Google conectado"></span>
        </div>
        <p class="panel-subtitle mb-5">Pega el link de la hoja de cálculo de Google Sheets que quieras usar como catálogo (tiene que estar compartida con tu cuenta de Google).</p>
        <div class="flex flex-col sm:flex-row gap-2.5">
          <input id="gs-url-input" type="text" placeholder="https://docs.google.com/spreadsheets/d/..."
            class="flex-1 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-200 dark:focus:ring-indigo-800 focus:border-indigo-400" />
          <button id="btn-vincular-gs" class="btn-primary shrink-0">Continuar</button>
        </div>
        <div id="gs-hojas-selector" class="hidden mt-5">
          <p class="text-sm font-medium mb-2">Esa hoja de cálculo tiene varias pestañas — elige con cuál trabajar:</p>
          <div class="flex flex-col sm:flex-row gap-2.5">
            <select id="gs-hoja-select" class="flex-1 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2.5"></select>
            <button id="btn-elegir-hoja" class="btn-primary shrink-0">Usar esta pestaña</button>
          </div>
        </div>
        <p class="text-xs text-slate-400 dark:text-slate-500 mt-4">¿Te equivocaste de cuenta? <a id="link-desconectar-gs" href="#" class="text-indigo-600 dark:text-indigo-400 hover:underline">Desconectar Google</a></p>
      </div>
    `;
  }

  function wirePasoVincular(main) {
    document.getElementById("btn-vincular-gs").addEventListener("click", () => vincularHoja(main));
    document.getElementById("gs-url-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") vincularHoja(main);
    });
    wireDesconectar(main);
  }

  async function vincularHoja(main) {
    const input = document.getElementById("gs-url-input");
    const url = input.value.trim();
    if (!url) {
      toast("error", "Pegá el link (o el ID) de la hoja de cálculo.");
      return;
    }
    const btn = document.getElementById("btn-vincular-gs");
    btn.disabled = true;
    btn.textContent = "Buscando…";
    const res = await LC.backendApi.vincularHojaGoogleSheets(url);
    btn.disabled = false;
    btn.textContent = "Continuar";
    if (!res.ok) {
      toast("error", res.error.mensaje);
      return;
    }
    if (res.data.hojaSeleccionada) {
      toast("success", `Vinculado: ${res.data.titulo}`);
      state.hojaElegida = res.data.hojaSeleccionada;
      cargarAnalisis(main);
      return;
    }
    // Varias pestañas — el dueño elige antes de seguir.
    state.hojasDisponibles = res.data.hojas;
    const selector = document.getElementById("gs-hojas-selector");
    const select = document.getElementById("gs-hoja-select");
    select.innerHTML = res.data.hojas.map((h) => `<option value="${escapeHtml(h)}">${escapeHtml(h)}</option>`).join("");
    selector.classList.remove("hidden");
    document.getElementById("btn-elegir-hoja").addEventListener("click", () => {
      state.hojaElegida = select.value;
      cargarAnalisis(main);
    });
  }

  function wireDesconectar(main) {
    const link = document.getElementById("link-desconectar-gs");
    if (!link) return;
    link.addEventListener("click", (e) => {
      e.preventDefault();
      confirmarDesconectar(main);
    });
  }

  function confirmarDesconectar(main) {
    openModal({
      title: "¿Desconectar Google Sheets?",
      body: `<p>Vas a poder volver a conectar tu cuenta (u otra) cuando quieras.</p>`,
      primaryLabel: "Desconectar",
      secondaryLabel: "Cancelar",
      onPrimary: async () => {
        const res = await LC.backendApi.desconectarGoogleSheets();
        if (!res.ok) {
          toast("error", res.error.mensaje);
          return;
        }
        toast("info", "Google Sheets desconectado.");
        render(main);
      },
    });
  }

  // ------------------------------------------------------------------
  // Paso 3 — Ya vinculada (pantalla "home" de esta integración)
  // ------------------------------------------------------------------

  function renderPasoListo() {
    const e = state.estado;
    return `
      <div class="panel-card mb-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2.5">
            <span class="dot dot--green"></span>
            <div>
              <p class="text-sm font-medium">Google Sheets conectado</p>
              <p class="text-xs text-slate-400">Catálogo: ${escapeHtml(e.spreadsheetTitulo || e.spreadsheetId)}${e.hojaSeleccionada ? ` · Pestaña "${escapeHtml(e.hojaSeleccionada)}"` : ""}</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button id="btn-sincronizar-gs" class="btn-primary">Sincronizar ahora</button>
            <button id="btn-cambiar-hoja-gs" class="btn-secondary">Cambiar hoja</button>
          </div>
        </div>
        <p class="text-sm text-slate-500 dark:text-slate-400 mt-3">
          "Sincronizar ahora" vuelve a leer esa pestaña y te muestra qué va a cambiar antes de importar nada — nunca se actualiza tu catálogo solo.
        </p>
        <p class="text-xs text-slate-400 dark:text-slate-500 mt-3"><a id="link-desconectar-gs" href="#" class="text-indigo-600 dark:text-indigo-400 hover:underline">Desconectar Google</a></p>
      </div>
    `;
  }

  function wirePasoListo(main) {
    document.getElementById("btn-sincronizar-gs").addEventListener("click", () => cargarAnalisis(main));
    document.getElementById("btn-cambiar-hoja-gs").addEventListener("click", () => {
      state.fase = "vincular";
      renderFase(main);
    });
    wireDesconectar(main);
  }

  // ------------------------------------------------------------------
  // Paso 4 — Revisión de columnas (mismo criterio que js/importFlow.js)
  // ------------------------------------------------------------------

  async function cargarAnalisis(main) {
    state.fase = "analizando";
    renderFase(main);
    const res = await LC.backendApi.analizarHojaGoogleSheets(state.hojaElegida);
    if (!res.ok) {
      toast("error", `No pudimos leer esa hoja: ${res.error.mensaje}`);
      state.fase = state.estado.spreadsheetId ? "listo" : "vincular";
      renderFase(main);
      return;
    }
    state.analisis = res.data;
    state.mapeo = { ...res.data.mapeoPropuesto };
    state.fase = "revision";
    renderFase(main);
  }

  function renderPasoRevision() {
    const { resumen, encabezados, filas, spreadsheetTitulo, hojaUsada } = state.analisis;
    const conProblemas = filas.filter((f) => f.estado !== "valido").slice(0, 8);

    return `
      <div class="panel-card mb-5">
        <h2 class="panel-title mb-1">Así entendimos tu hoja de cálculo</h2>
        <p class="panel-subtitle mb-5">${escapeHtml(spreadsheetTitulo || "")} · pestaña "${escapeHtml(hojaUsada)}" — revisa que las columnas estén bien asignadas.</p>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div class="stat-card"><p class="stat-label">Filas encontradas</p><p class="stat-value stat-value--sm">${resumen.totalFilas}</p></div>
          <div class="stat-card"><p class="stat-label">Listas</p><p class="stat-value stat-value--sm stat-value--success">${resumen.validos}</p></div>
          <div class="stat-card"><p class="stat-label">Para revisar</p><p class="stat-value stat-value--sm stat-value--warning">${resumen.revision}</p></div>
          <div class="stat-card"><p class="stat-label">Con error</p><p class="stat-value stat-value--sm stat-value--danger">${resumen.errores}</p></div>
        </div>

        <h3 class="text-sm font-semibold mb-2 text-slate-600 dark:text-slate-300">Columnas detectadas</h3>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mb-2">
          ${Object.keys(CAMPOS_LABEL).map((campo) => `
            <label class="flex items-center justify-between gap-3 text-sm border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2">
              <span class="text-slate-500 dark:text-slate-400">${escapeHtml(CAMPOS_LABEL[campo])}</span>
              <select data-campo="${campo}" class="mapeo-select text-sm rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2 py-1 max-w-[55%]">
                <option value="">(ninguna)</option>
                ${encabezados.map((h) => `<option value="${escapeHtml(h)}" ${state.mapeo[campo] === h ? "selected" : ""}>${escapeHtml(h)}</option>`).join("")}
              </select>
            </label>
          `).join("")}
        </div>
      </div>

      ${conProblemas.length ? `
      <div class="panel-card mb-5">
        <h3 class="panel-title mb-1">Filas que requieren atención</h3>
        <p class="panel-subtitle mb-3">Estas se importan igual (salvo las que dicen "error"), pero conviene revisarlas después.</p>
        <div class="space-y-2">
          ${conProblemas.map((f) => `
            <div class="flex items-start gap-3 text-sm border-b border-slate-100 dark:border-slate-800 pb-2 last:border-0">
              <span class="reco-badge ${f.estado === "error" ? "reco-no_rentable" : "reco-margen_bajo"} shrink-0">${f.estado === "error" ? "Error" : "Revisar"}</span>
              <div class="min-w-0">
                <p class="font-medium truncate">${escapeHtml(f.nombre || "(sin nombre)")}</p>
                <p class="text-xs text-slate-400">${escapeHtml(f.problemas.join(" · "))}</p>
              </div>
            </div>
          `).join("")}
        </div>
      </div>` : ""}

      <div class="flex items-center justify-between gap-4 flex-wrap">
        <button id="btn-cancelar-revision-gs" class="btn-secondary">← Volver</button>
        <button id="btn-confirmar-importacion-gs" class="btn-primary">Confirmar e importar ${resumen.totalFilas - resumen.errores} productos</button>
      </div>
    `;
  }

  function wirePasoRevision(main) {
    main.querySelectorAll(".mapeo-select").forEach((sel) => {
      sel.addEventListener("change", () => {
        state.mapeo[sel.dataset.campo] = sel.value || null;
      });
    });
    document.getElementById("btn-cancelar-revision-gs").addEventListener("click", () => {
      state.fase = "listo";
      renderFase(main);
    });
    document.getElementById("btn-confirmar-importacion-gs").addEventListener("click", () => confirmarImportacion(main));
  }

  async function confirmarImportacion(main) {
    const btn = document.getElementById("btn-confirmar-importacion-gs");
    btn.disabled = true;
    btn.textContent = "Importando…";
    const res = await LC.backendApi.confirmarHojaGoogleSheets(state.analisis.hojaUsada, state.mapeo, true);
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "Confirmar e importar";
      toast("error", `No pudimos importar el catálogo: ${res.error.mensaje}`);
      return;
    }
    state.confirmarResultado = res.data;
    state.fase = "resultado";
    renderFase(main);
  }

  // ------------------------------------------------------------------
  // Paso 5 — Resultado
  // ------------------------------------------------------------------

  function renderPasoResultado() {
    const r = state.confirmarResultado;
    return `
      <div class="panel-card text-center py-10 mb-5">
        <div class="text-5xl mb-4">${icon("checkCircle")}</div>
        <h2 class="text-xl font-semibold mb-2">Catálogo sincronizado desde Google Sheets</h2>
        <div class="grid grid-cols-3 gap-4 max-w-md mx-auto my-6">
          <div><p class="stat-label">Creados</p><p class="stat-value stat-value--sm stat-value--success">${r.creados}</p></div>
          <div><p class="stat-label">Actualizados</p><p class="stat-value stat-value--sm">${r.actualizados}</p></div>
          <div><p class="stat-label">Omitidos</p><p class="stat-value stat-value--sm ${r.omitidos ? "stat-value--warning" : ""}">${r.omitidos}</p></div>
        </div>
        ${r.limitePlan ? `<p class="text-sm text-amber-600 dark:text-amber-400 mb-4">No importamos ${r.limitePlan.omitidosPorLimite} producto${r.limitePlan.omitidosPorLimite === 1 ? "" : "s"}: llegaste al límite de ${Number(r.limitePlan.limite).toLocaleString("es-CL")} productos de tu plan. <a href="#/suscripcion" class="underline">Ver planes</a></p>` : ""}
        <div class="flex items-center justify-center gap-3">
          <button id="btn-ver-productos-gs" class="btn-primary">Ver productos</button>
          <button id="btn-sincronizar-otra-vez-gs" class="btn-secondary">Sincronizar de nuevo</button>
        </div>
      </div>
      ${r.detalleOmitidos && r.detalleOmitidos.length ? `
      <div class="panel-card">
        <h3 class="panel-title mb-3">Filas omitidas</h3>
        <div class="space-y-2">
          ${r.detalleOmitidos.map((o) => `
            <div class="flex items-start gap-3 text-sm border-b border-slate-100 dark:border-slate-800 pb-2 last:border-0">
              <span class="reco-badge reco-no_rentable shrink-0">Fila ${o.fila}</span>
              <div class="min-w-0">
                <p class="font-medium truncate">${escapeHtml(o.nombre || "(sin nombre)")}</p>
                <p class="text-xs text-slate-400">${escapeHtml(o.problemas.join(" · "))}</p>
              </div>
            </div>
          `).join("")}
        </div>
      </div>` : ""}
    `;
  }

  function wirePasoResultado(main) {
    document.getElementById("btn-ver-productos-gs").addEventListener("click", () => LC.router.navigate("/productos"));
    document.getElementById("btn-sincronizar-otra-vez-gs").addEventListener("click", () => cargarAnalisis(main));
  }

  LC.googleSheetsFlow = { render };
})();
