"use strict";

/**
 * Nexo — asistente "Importar catálogo" (24 de agosto de 2026).
 *
 * Flujo: Subir archivo → Analizamos tus productos → Revisar mapeo de
 * columnas → Oportunidades (rentabilidad + selección) → Revisar
 * publicaciones (borrador/simulación) → Listas para publicar.
 *
 * Arquitectura (sección 8 del pedido): esta pantalla NO calcula ningún
 * margen, ni decide qué es "rentable" — todo eso ya lo hizo el backend
 * (domain/profitability.py, domain/catalog_selection.py). Acá solo se pide
 * el dato (LC.backendApi) y se pinta. Si el backend no está disponible, se
 * usa LC.demoImportResult (misma forma de datos, capturada de una corrida
 * real) — nunca se mezclan datos reales con datos de ejemplo en la misma
 * pantalla; el modo se muestra siempre explícito.
 */

window.LC = window.LC || {};

(function () {
  const { escapeHtml, toast, openModal, icon } = LC.ui;

  const CAMPOS_LABEL = {
    sku: "SKU", nombre: "Nombre del producto", marca: "Marca", categoria: "Categoría",
    costo: "Costo de compra", precio: "Precio de venta", stock: "Stock",
    descripcion: "Descripción", imagen_url: "Imagen (URL)", codigo_barras: "Código de barras",
  };
  // Sin estas columnas no se puede importar (nombre) o no se puede calcular si
  // conviene publicar (costo y precio) — revisión por perfil, 15/09/2026.
  const CAMPOS_CLAVE = ["nombre", "costo", "precio"];

  const PASOS = [
    { fase: "subir", titulo: "Sube tu catálogo" },
    { fase: "revision", titulo: "Analizamos tus productos" },
    { fase: "oportunidades", titulo: "Oportunidades que encontramos" },
    { fase: "publicaciones", titulo: "Revisa tus publicaciones" },
    { fase: "listo", titulo: "Listas para publicar" },
  ];

  function estadoInicial() {
    return {
      fase: "subir",
      modoBackend: null, // null = todavía no se chequeó | "real" | "demo"
      cargando: false,
      file: null,
      analisis: null,
      mapeo: null,
      confirmarResultado: null,
      seleccion: null,
      // Canal "mercadolibre": la recomendación se evalúa sobre el margen NETO
      // de ML (comisión real exacta por producto + envío), no sobre el bruto
      // de tienda. El sistema recomienda solo Clásica/Premium según el margen.
      seleccionCriterios: { canal: "mercadolibre", requiereStock: false, orden: "margenMercadoLibreClp" },
      seleccionadosIds: new Set(),
      preparacion: null,
      error: null,
    };
  }

  let state = estadoInicial();

  function formatCLPReal(value) {
    if (value === null || value === undefined) return "—";
    const n = typeof value === "number" ? value : parseFloat(value);
    if (Number.isNaN(n)) return "—";
    try {
      return new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);
    } catch (_e) {
      return `$${Math.round(n)}`;
    }
  }

  function formatPct(value) {
    if (value === null || value === undefined) return "—";
    return `${value.toFixed(1)}%`;
  }

  // ------------------------------------------------------------------
  // Entrada
  // ------------------------------------------------------------------

  async function render(main) {
    if (state.modoBackend === null) {
      main.innerHTML = skeleton();
      state.modoBackend = (await LC.backendApi.checkHealth()) ? "real" : "demo";
    }
    renderFase(main);
  }

  function skeleton() {
    return `<div class="page-wrap app-fade">
      <div class="skeleton-line h-8 w-64 mb-6"></div>
      <div class="skeleton-line h-40 w-full"></div>
    </div>`;
  }

  function renderFase(main) {
    const contenido = {
      subir: renderPasoSubir,
      analizando: renderPasoAnalizando,
      revision: renderPasoRevision,
      oportunidades: renderPasoOportunidades,
      publicaciones: renderPasoPublicaciones,
      listo: renderPasoListo,
    }[state.fase];

    main.innerHTML = `
      <div class="page-wrap app-fade max-w-5xl">
        ${sourcePill()}
        ${stepper()}
        <div class="mt-6">${contenido()}</div>
      </div>
    `;
    wireFase(main);
  }

  function sourcePill() {
    // 13 de septiembre de 2026 — en modo real no se muestra ninguna
    // etiqueta: "Backend real conectado" es vocabulario de desarrollo y no
    // le dice nada al cliente. El aviso de modo demostracion si se queda,
    // porque ahi si hay algo que advertir.
    if (state.modoBackend === "real") return "";
    return `<div class="flex justify-end mb-2"><span class="source-pill source-pill--demo">Modo demostración — backend no disponible</span></div>`;
  }

  function stepper() {
    const idxActual = PASOS.findIndex((p) => p.fase === state.fase) >= 0 ? PASOS.findIndex((p) => p.fase === state.fase) : 0;
    return `
      <div class="wizard-steps">
        ${PASOS.map((p, i) => {
          const cls = i < idxActual ? "is-done" : i === idxActual ? "is-active" : "";
          const stepGlyph = i < idxActual ? "✓" : i + 1;
          return `
            <div class="wizard-step ${cls}">
              <span class="wizard-step-dot">${stepGlyph}</span>
              <span class="wizard-step-label">${escapeHtml(p.titulo)}</span>
            </div>
            ${i < PASOS.length - 1 ? '<span class="wizard-step-connector"></span>' : ""}
          `;
        }).join("")}
      </div>
    `;
  }

  // ------------------------------------------------------------------
  // Paso 1 — Subir
  // ------------------------------------------------------------------

  function renderPasoSubir() {
    return `
      <div class="panel-card">
        <h2 class="panel-title mb-1">Sube tu catálogo</h2>
        <p class="panel-subtitle mb-5">Aceptamos Excel (.xlsx) o CSV. No importa cómo se llamen tus columnas — las reconocemos automáticamente.</p>
        <div id="dropzone" class="dropzone">
          <input type="file" id="file-input" accept=".xlsx,.xlsm,.csv" class="hidden" />
          <div class="text-4xl mb-3">${icon("document")}</div>
          <p class="font-medium text-slate-700 dark:text-slate-200">Arrastra tu archivo aquí, o haz clic para elegirlo</p>
          <p class="text-sm text-slate-400 mt-1">.xlsx o .csv</p>
        </div>
        <p class="text-xs text-slate-400 dark:text-slate-500 mt-4">No necesitas modificar tu Excel para que funcione — nosotros nos encargamos de entender su estructura.</p>
      </div>
    `;
  }

  function wirePasoSubir(main) {
    const dropzone = document.getElementById("dropzone");
    const input = document.getElementById("file-input");
    if (!dropzone || !input) return;

    dropzone.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
      if (input.files && input.files[0]) manejarArchivoSeleccionado(main, input.files[0]);
    });
    ["dragover", "dragenter"].forEach((evt) =>
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.add("dropzone-active");
      })
    );
    ["dragleave", "dragend"].forEach((evt) => dropzone.addEventListener(evt, () => dropzone.classList.remove("dropzone-active")));
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("dropzone-active");
      const file = e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) manejarArchivoSeleccionado(main, file);
    });
  }

  async function manejarArchivoSeleccionado(main, file) {
    state.file = file;
    state.fase = "analizando";
    renderFase(main);

    if (state.modoBackend === "demo") {
      // Sin backend real: se usa la fotografía estática (misma forma de
      // datos que devolvería el backend) — no se recalcula nada acá.
      state.analisis = { ...LC.demoImportResult.analisis, fileName: file.name };
      state.mapeo = { ...state.analisis.mapeoPropuesto };
      state.fase = "revision";
      renderFase(main);
      return;
    }

    const resultado = await LC.backendApi.analizarCatalogo(file);
    if (!resultado.ok) {
      state.fase = "subir";
      renderFase(main);
      toast("error", `No pudimos analizar el archivo: ${resultado.error.mensaje}`);
      return;
    }
    state.analisis = resultado.data;
    state.mapeo = { ...resultado.data.mapeoPropuesto };
    state.fase = "revision";
    renderFase(main);
  }

  function renderPasoAnalizando() {
    return `
      <div class="panel-card text-center py-16">
        <div class="text-4xl mb-4 animate-pulse">${icon("search")}</div>
        <p class="font-medium text-slate-700 dark:text-slate-200">Analizando tus productos…</p>
        <p class="text-sm text-slate-400 mt-1">Detectando columnas y revisando cada fila.</p>
      </div>
    `;
  }

  // ------------------------------------------------------------------
  // Paso 2 — Revisión del mapeo + confirmar importación
  // ------------------------------------------------------------------

  function renderPasoRevision() {
    const { resumen, encabezados, filas } = state.analisis;
    const conProblemas = filas.filter((f) => f.estado !== "valido").slice(0, 8);
    const faltanClave = CAMPOS_CLAVE.filter((c) => !state.mapeo[c]);

    return `
      <div class="panel-card mb-5">
        <h2 class="panel-title mb-1">Así entendimos tu archivo</h2>
        <p class="panel-subtitle mb-5">${escapeHtml(state.analisis.fileName || (state.file && state.file.name) || "")} — revisa que las columnas estén bien asignadas. Si algo no coincide, puedes corregirlo.</p>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div class="stat-card"><p class="stat-label">Filas encontradas</p><p class="stat-value stat-value--sm">${resumen.totalFilas}</p></div>
          <div class="stat-card"><p class="stat-label">Listas</p><p class="stat-value stat-value--sm stat-value--success">${resumen.validos}</p></div>
          <div class="stat-card"><p class="stat-label">Para revisar</p><p class="stat-value stat-value--sm stat-value--warning">${resumen.revision}</p></div>
          <div class="stat-card"><p class="stat-label">Con error</p><p class="stat-value stat-value--sm stat-value--danger">${resumen.errores}</p></div>
        </div>

        <h3 class="text-sm font-semibold mb-2 text-slate-600 dark:text-slate-300">Columnas detectadas</h3>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mb-2">
          ${Object.keys(CAMPOS_LABEL).map((campo) => `
            <label class="flex items-center justify-between gap-3 text-sm border ${faltanClave.includes(campo) ? "border-amber-400 dark:border-amber-500" : "border-slate-200 dark:border-slate-700"} rounded-lg px-3 py-2">
              <span class="text-slate-500 dark:text-slate-400">${escapeHtml(CAMPOS_LABEL[campo])}${CAMPOS_CLAVE.includes(campo) ? ` <span class="text-xs ${faltanClave.includes(campo) ? "text-amber-600 dark:text-amber-400" : "text-slate-400"}">· clave</span>` : ""}</span>
              <select data-campo="${campo}" class="mapeo-select text-sm rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2 py-1 max-w-[55%]">
                <option value="">(ninguna)</option>
                ${encabezados.map((h) => `<option value="${escapeHtml(h)}" ${state.mapeo[campo] === h ? "selected" : ""}>${escapeHtml(h)}</option>`).join("")}
              </select>
            </label>
          `).join("")}
        </div>

        <details class="mt-3">
          <summary class="text-sm text-indigo-600 dark:text-indigo-400 cursor-pointer">Ver detalles técnicos</summary>
          <div class="mt-2 text-xs text-slate-400 space-y-1">
            <p>Encabezados originales del archivo: ${escapeHtml(encabezados.join(", "))}</p>
          </div>
        </details>
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

      ${faltanClave.length ? `
      <div class="panel-card mb-5 border border-amber-300 dark:border-amber-600">
        <p class="text-sm font-medium text-amber-700 dark:text-amber-400">Falta elegir: ${escapeHtml(faltanClave.map((c) => CAMPOS_LABEL[c]).join(", "))}</p>
        <p class="text-xs text-slate-500 dark:text-slate-400 mt-1">${!state.mapeo.nombre
          ? "Sin la columna del nombre no se puede importar. Elígela arriba."
          : "Sin costo de compra y precio de venta no podemos calcular si te conviene publicar cada producto. Elige esas columnas arriba."}</p>
      </div>` : ""}

      <div class="flex items-center justify-between gap-4 flex-wrap">
        <button id="btn-cancelar-importacion" class="btn-secondary">← Elegir otro archivo</button>
        <button id="btn-confirmar-importacion" class="btn-primary" ${!state.mapeo.nombre ? "disabled" : ""}>${faltanClave.length ? "Importar igual" : "Confirmar e importar"} ${resumen.totalFilas - resumen.errores} productos</button>
      </div>
    `;
  }

  // Corregir una columna vuelve a validar las filas con ese mapeo (15 de
  // septiembre de 2026): antes los contadores y los avisos por fila seguían
  // mostrando lo del mapeo propuesto ("Falta costo de compra").
  async function reanalizarConMapeo(main) {
    if (state.modoBackend === "demo") {
      renderFase(main);
      return;
    }
    main.querySelectorAll(".mapeo-select").forEach((s) => { s.disabled = true; });
    const resultado = await LC.backendApi.analizarCatalogo(state.file, state.mapeo);
    if (!resultado.ok) {
      toast("error", `No pudimos revisar el archivo con esas columnas: ${resultado.error.mensaje}`);
      main.querySelectorAll(".mapeo-select").forEach((s) => { s.disabled = false; });
      return;
    }
    state.analisis = resultado.data;
    renderFase(main);
  }

  function wirePasoRevision(main) {
    main.querySelectorAll(".mapeo-select").forEach((sel) => {
      sel.addEventListener("change", async () => {
        state.mapeo[sel.dataset.campo] = sel.value || null;
        await reanalizarConMapeo(main);
      });
    });
    document.getElementById("btn-cancelar-importacion").addEventListener("click", () => {
      state = estadoInicial();
      state.modoBackend = state.modoBackend; // se reevalúa igual al re-render
      state.modoBackend = null;
      render(main);
    });
    document.getElementById("btn-confirmar-importacion").addEventListener("click", () => confirmarImportacion(main));
  }

  async function confirmarImportacion(main) {
    if (state.modoBackend === "demo") {
      state.confirmarResultado = LC.demoImportResult.confirmar;
      toast("success", `${state.confirmarResultado.creados} productos importados (demo).`);
      await cargarOportunidades(main);
      return;
    }

    const resultado = await LC.backendApi.confirmarImportacion(state.file, state.mapeo, true);
    if (!resultado.ok) {
      toast("error", `No pudimos importar el catálogo: ${resultado.error.mensaje}`);
      return;
    }
    state.confirmarResultado = resultado.data;
    const limite = resultado.data.limitePlan;
    toast(
      limite ? "warning" : "success",
      `${resultado.data.creados} productos creados, ${resultado.data.actualizados} actualizados.${limite ? ` ${limite.omitidosPorLimite} no entraron por el límite de tu plan.` : ""}`
    );
    await cargarOportunidades(main);
  }

  // ------------------------------------------------------------------
  // Paso 3 — Oportunidades (rentabilidad + selección)
  // ------------------------------------------------------------------

  async function cargarOportunidades(main) {
    state.fase = "analizando";
    renderFase(main);
    document.querySelector(".page-wrap").innerHTML = `<div class="panel-card text-center py-16"><div class="text-4xl mb-4">${icon("dashboard")}</div><p class="font-medium">Calculando rentabilidad…</p></div>`;

    if (state.modoBackend === "demo") {
      state.seleccion = LC.demoImportResult.seleccion;
    } else {
      const resultado = await LC.backendApi.obtenerSeleccion(state.seleccionCriterios);
      if (!resultado.ok) {
        toast("error", `No pudimos calcular la rentabilidad: ${resultado.error.mensaje}`);
        state.fase = "revision";
        renderFase(main);
        return;
      }
      state.seleccion = resultado.data;
    }
    state.seleccionadosIds = new Set();
    state.fase = "oportunidades";
    renderFase(main);
  }

  const RECO_LABEL = {
    rentable: "Recomendado",
    margen_bajo: "Margen bajo",
    no_rentable: "No recomendado",
    sin_stock: "Sin stock reservado",
    sin_datos: "Faltan datos",
    no_seleccionado: "— Fuera del cupo",
  };

  // Margen a MOSTRAR: el neto de Mercado Libre (comisión real + envío) cuando
  // existe; si no (ML no configurado, o categoría sin comisión todavía), cae
  // al bruto de tienda para no dejar la celda vacía.
  function margenClpDe(p) {
    return p.margenMercadoLibreClp != null ? p.margenMercadoLibreClp : p.margenTiendaClp;
  }
  function margenPctDe(p) {
    return p.margenMercadoLibrePct != null ? p.margenMercadoLibrePct : p.margenTiendaPct;
  }

  function filasOrdenadas() {
    const { orden } = state.seleccionCriterios;
    const filas = [...state.seleccion.productos];
    const claves = {
      margenMercadoLibreClp: margenClpDe, margenMercadoLibrePct: margenPctDe,
      margenTiendaClp: (p) => p.margenTiendaClp, margenTiendaPct: (p) => p.margenTiendaPct,
      precio: (p) => p.precio, stock: (p) => p.marketplaceStock,
    };
    const valor = claves[orden] || margenClpDe;
    return filas.sort((a, b) => (valor(b) ?? -Infinity) - (valor(a) ?? -Infinity));
  }

  // Productos que no entraron por el límite del plan (15 de septiembre de 2026).
  function avisoLimitePlan(resultado) {
    const lim = resultado && resultado.limitePlan;
    if (!lim) return "";
    return `
      <div class="panel-card mb-5 border border-amber-300 dark:border-amber-600">
        <p class="text-sm font-medium text-amber-700 dark:text-amber-400">No importamos ${lim.omitidosPorLimite} producto${lim.omitidosPorLimite === 1 ? "" : "s"}: llegaste al límite de ${Number(lim.limite).toLocaleString("es-CL")} productos de tu plan.</p>
        <p class="text-xs text-slate-500 dark:text-slate-400 mt-1">Para agregarlos, cambia a un plan con más productos en <a href="#/suscripcion" class="underline">Mi plan</a> y vuelve a subir el archivo: los productos con SKU que ya están se actualizan, no se duplican.</p>
      </div>`;
  }

  function renderPasoOportunidades() {
    const { resumen } = state.seleccion;
    const filas = filasOrdenadas();
    const seleccionados = state.seleccionadosIds.size;

    return `
      ${avisoLimitePlan(state.confirmarResultado)}
      <div class="panel-card mb-5">
        <h2 class="panel-title mb-1">Estas son las oportunidades que encontramos</h2>
        <p class="panel-subtitle mb-5">Margen NETO de Mercado Libre — ya descontada la comisión real de cada producto. El sistema recomienda solo Clásica o Premium según el margen. El costo de envío solo se descuenta cuando Mercado Libre lo informa para una publicación real; mientras tanto el margen es provisional.</p>
        <div class="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <div class="stat-card"><p class="stat-label">Total</p><p class="stat-value stat-value--sm">${resumen.total}</p></div>
          <div class="stat-card"><p class="stat-label">Recomendados</p><p class="stat-value stat-value--sm stat-value--success">${resumen.rentables}</p></div>
          <div class="stat-card"><p class="stat-label">Margen bajo</p><p class="stat-value stat-value--sm stat-value--warning">${resumen.margenBajo}</p></div>
          <div class="stat-card"><p class="stat-label">No recomendados</p><p class="stat-value stat-value--sm stat-value--danger">${resumen.noRentables}</p></div>
          <div class="stat-card"><p class="stat-label">Sin datos suficientes</p><p class="stat-value stat-value--sm">${resumen.sinDatos}</p></div>
        </div>
      </div>

      <div class="panel-card mb-5">
        <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div class="flex flex-wrap gap-2">
            <button id="btn-seleccionar-rentables" class="btn-secondary !text-xs !py-1.5">Seleccionar recomendados</button>
            <button id="btn-seleccionar-todo" class="btn-secondary !text-xs !py-1.5">Seleccionar toda la tienda</button>
            <button id="btn-limpiar-seleccion" class="btn-secondary !text-xs !py-1.5">Limpiar selección</button>
          </div>
          <div class="flex items-center gap-2 text-sm">
            <label class="text-slate-500 dark:text-slate-400">Ordenar por</label>
            <select id="orden-select" class="text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2 py-1.5">
              <option value="margenMercadoLibreClp" ${state.seleccionCriterios.orden === "margenMercadoLibreClp" ? "selected" : ""}>Mayor utilidad (neta ML)</option>
              <option value="margenMercadoLibrePct" ${state.seleccionCriterios.orden === "margenMercadoLibrePct" ? "selected" : ""}>Mayor margen (neto ML)</option>
              <option value="precio" ${state.seleccionCriterios.orden === "precio" ? "selected" : ""}>Mayor precio</option>
              <option value="stock" ${state.seleccionCriterios.orden === "stock" ? "selected" : ""}>Mayor stock reservado</option>
            </select>
          </div>
        </div>

        <div class="table-wrap">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left border-b border-slate-200 dark:border-slate-700">
                <th class="px-3 py-2 w-8"></th>
                <th class="px-3 py-2 font-medium">Producto</th>
                <th class="px-3 py-2 font-medium text-right">Precio</th>
                <th class="px-3 py-2 font-medium text-right">Costo</th>
                <th class="px-3 py-2 font-medium text-right">Utilidad neta</th>
                <th class="px-3 py-2 font-medium text-right">Margen neto</th>
                <th class="px-3 py-2 font-medium">Publicar como</th>
                <th class="px-3 py-2 font-medium">Recomendación</th>
              </tr>
            </thead>
            <tbody>
              ${filas.map((p) => `
                <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0 ${state.seleccionadosIds.has(p.id) ? "row-selected" : ""}">
                  <td class="px-3"><input type="checkbox" class="form-checkbox fila-checkbox" data-id="${p.id}" ${state.seleccionadosIds.has(p.id) ? "checked" : ""} /></td>
                  <td class="px-3 py-2.5">
                    <p class="font-medium text-slate-800 dark:text-slate-100">${escapeHtml(p.nombre)}</p>
                    <p class="text-xs text-slate-400 font-mono">${escapeHtml(p.sku || "—")}</p>
                  </td>
                  <td class="px-3 py-2.5 text-right">${formatCLPReal(p.precio)}</td>
                  <td class="px-3 py-2.5 text-right">${formatCLPReal(p.costo)}</td>
                  <td class="px-3 py-2.5 text-right font-medium ${margenClpDe(p) != null && margenClpDe(p) < 0 ? "text-red-600 dark:text-red-400" : ""}">${formatCLPReal(margenClpDe(p))}${p.rentabilidadMlProvisional ? `<p class="text-xs font-normal text-slate-400" title="${escapeHtml(p.envioMlMotivo || "")}">Provisional · envío no disponible</p>` : ""}${p.margenTiendaClp != null ? `<p class="text-xs font-normal text-slate-500 dark:text-slate-400 whitespace-nowrap">Venta − compra: ${formatCLPReal(p.margenTiendaClp)}${p.margenTiendaPct != null ? ` (${formatPct(p.margenTiendaPct)})` : ""}</p>` : ""}</td>
                  <td class="px-3 py-2.5 text-right">${formatPct(margenPctDe(p))}</td>
                  <td class="px-3 py-2.5">
                    ${p.tipoPublicacionRecomendadoLabel
                      ? `<span class="badge badge-simple" title="${escapeHtml(p.tipoPublicacionRazon || "")}">${escapeHtml(p.tipoPublicacionRecomendadoLabel)}</span>`
                      : `<span class="text-xs text-slate-400" title="Falta la categoría de Mercado Libre para calcular la comisión exacta">—</span>`}
                  </td>
                  <td class="px-3 py-2.5">
                    <span class="reco-badge reco-${p.clasificacion}" title="${escapeHtml(p.razon || "")}">${RECO_LABEL[p.clasificacion] || p.clasificacion}</span>
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>

      <div class="flex items-center justify-between gap-4 flex-wrap">
        <button id="btn-volver-revision" class="btn-secondary">← Volver</button>
        <button id="btn-preparar-publicaciones" class="btn-primary" ${seleccionados === 0 ? "disabled" : ""}>
          Preparar publicaciones (${seleccionados} seleccionados)
        </button>
      </div>
    `;
  }

  function wirePasoOportunidades(main) {
    main.querySelectorAll(".fila-checkbox").forEach((cb) => {
      cb.addEventListener("change", (e) => {
        const id = Number(e.target.dataset.id);
        if (e.target.checked) state.seleccionadosIds.add(id);
        else state.seleccionadosIds.delete(id);
        renderFase(main);
      });
    });

    document.getElementById("btn-seleccionar-rentables").addEventListener("click", () => {
      state.seleccionadosIds = new Set(state.seleccion.productos.filter((p) => p.clasificacion === "rentable").map((p) => p.id));
      renderFase(main);
      toast("info", `${state.seleccionadosIds.size} productos recomendados seleccionados.`);
    });

    document.getElementById("btn-seleccionar-todo").addEventListener("click", () => {
      const r = state.seleccion.resumen;
      openModal({
        title: "¿Seleccionar toda la tienda?",
        body: `<p>Vas a seleccionar los <strong>${r.total} productos</strong> de tu catálogo, incluyendo los que no conviene publicar:</p>
          <ul class="mt-2 space-y-1 text-sm">
            <li>${r.rentables} recomendados</li>
            <li>${r.margenBajo} con margen bajo</li>
            <li>${r.noRentables} no recomendados (perderías dinero)</li>
            <li>${r.sinDatos} sin costo cargado todavía</li>
          </ul>
          <p class="mt-2">No vamos a publicar nada todavía — solo prepararemos el borrador para que lo revises.</p>`,
        primaryLabel: "Seleccionar todos igual",
        secondaryLabel: "Cancelar",
        onPrimary: () => {
          state.seleccionadosIds = new Set(state.seleccion.productos.map((p) => p.id));
          renderFase(main);
        },
      });
    });

    document.getElementById("btn-limpiar-seleccion").addEventListener("click", () => {
      state.seleccionadosIds = new Set();
      renderFase(main);
    });

    document.getElementById("orden-select").addEventListener("change", (e) => {
      state.seleccionCriterios.orden = e.target.value;
      renderFase(main);
    });

    document.getElementById("btn-volver-revision").addEventListener("click", () => {
      state.fase = "revision";
      renderFase(main);
    });

    const btnPreparar = document.getElementById("btn-preparar-publicaciones");
    if (btnPreparar) btnPreparar.addEventListener("click", () => prepararPublicaciones(main));
  }

  // ------------------------------------------------------------------
  // Paso 4 — Publicaciones (borradores)
  // ------------------------------------------------------------------

  async function prepararPublicaciones(main) {
    state.fase = "analizando";
    renderFase(main);
    document.querySelector(".page-wrap").innerHTML = `<div class="panel-card text-center py-16"><div class="text-4xl mb-4">${icon("document")}</div><p class="font-medium">Preparando publicaciones…</p></div>`;

    if (state.modoBackend === "demo") {
      state.preparacion = LC.demoImportResult.preparar;
    } else {
      const resultado = await LC.backendApi.prepararPublicaciones([...state.seleccionadosIds], state.seleccionCriterios);
      if (!resultado.ok) {
        toast("error", `No pudimos preparar las publicaciones: ${resultado.error.mensaje}`);
        state.fase = "oportunidades";
        renderFase(main);
        return;
      }
      state.preparacion = resultado.data;
    }
    state.fase = "publicaciones";
    renderFase(main);
  }

  function renderPasoPublicaciones() {
    const { resumen, borradores } = state.preparacion;
    return `
      <div class="panel-card mb-5">
        <h2 class="panel-title mb-1">Revisa tus publicaciones</h2>
        <p class="panel-subtitle mb-4">Esto es un borrador — todavía no se envía nada a Mercado Libre.</p>
        <div class="grid grid-cols-3 gap-3">
          <div class="stat-card"><p class="stat-label">Listas para publicar</p><p class="stat-value stat-value--sm stat-value--success">${resumen.listosParaPublicar}</p></div>
          <div class="stat-card"><p class="stat-label">Requieren revisión</p><p class="stat-value stat-value--sm stat-value--warning">${resumen.requierenRevision}</p></div>
          <div class="stat-card"><p class="stat-label">No recomendadas</p><p class="stat-value stat-value--sm stat-value--danger">${resumen.noRecomendados}</p></div>
        </div>
      </div>

      <div class="space-y-4 mb-5">
        ${borradores.map((b, i) => `
          <div class="draft-card draft-card--${b.estado}">
            <div class="flex items-start justify-between gap-4 flex-wrap mb-2">
              <div class="min-w-0">
                <p class="text-xs text-slate-400 font-mono">${escapeHtml(b.sku || "—")}</p>
                <h3 class="text-lg font-semibold truncate">${escapeHtml(b.tituloPropuesto)}</h3>
              </div>
              <span class="reco-badge reco-${b.clasificacion}">${estadoLabel(b.estado)}</span>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm mb-2">
              <div><p class="stat-label">Precio</p><p class="font-medium mt-0.5">${formatCLPReal(b.precio)}</p></div>
              <div><p class="stat-label">Costo</p><p class="font-medium mt-0.5">${formatCLPReal(b.costo)}</p></div>
              <div><p class="stat-label">Utilidad estimada</p><p class="font-medium mt-0.5 ${b.rentabilidad.margenTiendaClp < 0 ? "text-red-600 dark:text-red-400" : ""}">${formatCLPReal(b.rentabilidad.margenTiendaClp)}</p></div>
              <div><p class="stat-label">Categoría sugerida</p><p class="font-medium mt-0.5">${escapeHtml(b.categoriaSugerida || "—")} <span class="text-xs text-slate-400">(no oficial de ML)</span></p></div>
            </div>
            ${b.advertencias.length ? `
              <div class="text-sm text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950 rounded-lg px-3 py-2 mt-2">
                ${b.advertencias.map((a) => `<p>${escapeHtml(a)}</p>`).join("")}
              </div>` : ""}
            <details class="mt-3">
              <summary class="text-sm text-indigo-600 dark:text-indigo-400 cursor-pointer">Ver detalles</summary>
              <div class="mt-2 text-sm space-y-2">
                <p><span class="text-slate-400">Descripción propuesta:</span> ${escapeHtml(b.descripcionPropuesta)}</p>
                <p><span class="text-slate-400">Atributos:</span> ${Object.keys(b.atributos).length ? Object.entries(b.atributos).map(([k, v]) => `${escapeHtml(k)}: ${escapeHtml(v)}`).join(" · ") : "Ninguno todavía"}</p>
                <p><span class="text-slate-400">Imágenes:</span> ${b.imagenes.length ? `${b.imagenes.length} imagen(es)` : "Sin imagen cargada"}</p>
                <p class="text-xs text-slate-400">Título y descripción generados automáticamente a partir de tus datos — no se inventó ninguna característica.</p>
              </div>
            </details>
          </div>
        `).join("")}
      </div>

      <div class="flex items-center justify-between gap-4 flex-wrap">
        <button id="btn-volver-oportunidades" class="btn-secondary">← Volver</button>
        <button id="btn-finalizar" class="btn-primary">Guardar como borrador</button>
      </div>
    `;
  }

  function estadoLabel(estado) {
    return { listo_para_publicar: "Listo para publicar", requiere_revision: "Requiere revisión", no_recomendado: "No recomendado" }[estado] || estado;
  }

  function wirePasoPublicaciones(main) {
    document.getElementById("btn-volver-oportunidades").addEventListener("click", () => {
      state.fase = "oportunidades";
      renderFase(main);
    });
    document.getElementById("btn-finalizar").addEventListener("click", () => {
      state.fase = "listo";
      renderFase(main);
    });
  }

  // ------------------------------------------------------------------
  // Paso 5 — Listo
  // ------------------------------------------------------------------

  function renderPasoListo() {
    const { resumen } = state.preparacion;
    const selResumen = state.seleccion ? state.seleccion.resumen : null;
    const totalProcesados = state.confirmarResultado ? state.confirmarResultado.creados + state.confirmarResultado.actualizados : null;
    return `
      <div class="panel-card text-center py-10 mb-5">
        <div class="text-5xl mb-4">${icon("checkCircle")}</div>
        <h2 class="text-xl font-semibold mb-2">${resumen.listosParaPublicar + resumen.requierenRevision} publicaciones quedaron guardadas como borrador</h2>
        <p class="text-slate-500 dark:text-slate-400 max-w-md mx-auto mb-6">Todavía no se envió nada a Mercado Libre — vas a poder publicarlas de verdad en cuanto conectes tu cuenta.</p>
        <div class="flex items-center justify-center gap-3">
          <button id="btn-conectar-ml" class="btn-secondary">Conectar Mercado Libre</button>
          <button id="btn-importar-otro" class="btn-primary">Importar otro catálogo</button>
        </div>
      </div>
      ${
        selResumen
          ? `<div class="panel-card">
              <h3 class="panel-title mb-1">Resumen de la importación</h3>
              <p class="panel-subtitle mb-4">${totalProcesados != null ? `${totalProcesados} productos procesados en tu catálogo.` : "Así quedó tu catálogo después de importar."}</p>
              <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-5">
                <div><p class="stat-label">Buenas oportunidades</p><p class="stat-value stat-value--sm stat-value--success">${selResumen.rentables}</p></div>
                <div><p class="stat-label">Sin costo cargado</p><p class="stat-value stat-value--sm stat-value--warning">${selResumen.sinDatos}</p></div>
                <div><p class="stat-label">Margen bajo</p><p class="stat-value stat-value--sm stat-value--warning">${selResumen.margenBajo}</p></div>
                <div><p class="stat-label">No conviene</p><p class="stat-value stat-value--sm stat-value--danger">${selResumen.noRentables}</p></div>
              </div>
              <button id="btn-ver-oportunidades" class="btn-secondary">Ver oportunidades →</button>
            </div>`
          : ""
      }
    `;
  }

  function wirePasoListo(main) {
    document.getElementById("btn-conectar-ml").addEventListener("click", () => LC.router.navigate("/integraciones"));
    document.getElementById("btn-importar-otro").addEventListener("click", () => {
      state = estadoInicial();
      render(main);
    });
    const verOportunidadesBtn = document.getElementById("btn-ver-oportunidades");
    if (verOportunidadesBtn) verOportunidadesBtn.addEventListener("click", () => LC.router.navigate("/oportunidades"));
  }

  // ------------------------------------------------------------------
  // Cableado por fase
  // ------------------------------------------------------------------

  function wireFase(main) {
    ({
      subir: wirePasoSubir,
      analizando: () => {},
      revision: wirePasoRevision,
      oportunidades: wirePasoOportunidades,
      publicaciones: wirePasoPublicaciones,
      listo: wirePasoListo,
    })[state.fase](main);
  }

  LC.importFlow = { render };
})();
