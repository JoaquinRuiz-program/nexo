"use strict";

/**
 * Nexo — flujo de decisión + publicación de UN producto en Mercado Libre
 * (30 de agosto de 2026, frontend de FASE 6).
 *
 * Producto → Rentabilidad/Competencia/Precio recomendado → ¿Conviene? →
 * Preparar publicación → Revisar → Publicar.
 *
 * Mismo criterio que js/importFlow.js: esta pantalla no calcula ningún
 * margen, ninguna competencia ni ninguna decisión — todo eso ya lo hizo el
 * backend (domain/pricing.py, domain/competencia.py, domain/decision.py).
 * Acá solo se pide el dato (LC.backendApi) y se pinta.
 *
 * IMPORTANTE: el paso "Preparar publicación" es edición local — ninguna
 * llamada de acá publica nada real. Solo /confirmar (llamado al final,
 * después de una doble confirmación explícita) puede crear una publicación
 * real en Mercado Libre.
 */

window.LC = window.LC || {};

(function () {
  const { escapeHtml, toast, openModal, icon, formatCLPReal, formatPct } = LC.ui;

  const DECISION_LABEL = {
    conviene: "Conviene publicarlo",
    revisar: "Conviene revisarlo antes de publicar",
    no_conviene: "No conviene publicarlo todavía",
  };
  const DECISION_ICON = { conviene: "checkCircle", revisar: "alert", no_conviene: "alert" };

  const PASOS = [
    { fase: "decision", titulo: "¿Conviene?" },
    { fase: "preparar", titulo: "Preparar publicación" },
    { fase: "revisar", titulo: "Revisar" },
    { fase: "publicado", titulo: "Publicado" },
  ];

  const LISTING_TYPE_LABEL = { classic: "Clásica", premium: "Premium" };

  function estadoInicial(variantId) {
    return {
      variantId,
      fase: "decision",
      cargando: true,
      error: null,
      producto: null, // {nombre, sku, precio} — de LC.dataSource.getProductoDetalle
      decision: null, // respuesta de /decision
      verAnalisis: false,
      competenciaDetalle: null, // respuesta completa de /competencia (perezoso, al abrir "Ver análisis")
      preparado: null, // respuesta de /preparar
      tituloEditado: null,
      categoryId: "",
      condition: "new",
      listingType: "classic",
      validacion: null, // respuesta de /validar
      atributosValores: {}, // id atributo -> valor elegido
      gtinSinCodigoConfirmado: false,
      confirmandoSinCodigo: false,
      preview: null, // respuesta de /confirmar/preview
      erroresPreview: null,
      aceptoPublicar: false,
      publicando: false,
      publicado: null, // respuesta de /confirmar
      // 1 de septiembre de 2026 — gestión de una publicación ya creada:
      // si el producto YA tiene una publicación real, esta pantalla NO
      // entra al wizard de decisión/preparar (no tiene sentido volver a
      // decidir si conviene algo que ya está publicado) — muestra en
      // cambio el estado real y las acciones (pausar/reactivar/eliminar).
      modoGestion: false,
      gestion: null, // respuesta de GET .../mercadolibre/publicacion
      gestionAccionEnCurso: false,
    };
  }

  let state = estadoInicial(null);

  // ------------------------------------------------------------------
  // Entrada
  // ------------------------------------------------------------------

  async function render(main, variantId) {
    if (!variantId) {
      main.innerHTML = `<div class="page-wrap"><div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("box")}</div><p class="empty-state-title">Elige un producto para publicarlo</p><p class="empty-state-desc">Entra a Productos, abre el que quieres publicar en Mercado Libre y empieza desde ahí.</p><button data-ir-productos class="btn-primary mt-4">Ir a Productos</button></div></div>`;
      main.querySelector("[data-ir-productos]").addEventListener("click", () => LC.router.navigate("/productos"));
      return;
    }
    // Siempre se arranca de cero al entrar a esta pantalla — nunca se
    // muestran datos guardados de una visita anterior (costo, márgenes o
    // competencia pueden haber cambiado desde entonces).
    state = estadoInicial(Number(variantId));
    const miState = state; // ver esVigente() — evita que una respuesta
    // tardía de ESTE producto pise el estado si el dueño ya navegó a otro.
    {
      main.innerHTML = skeleton();
      const [detalle, estadoRes] = await Promise.all([
        LC.dataSource.getProductoDetalle(miState.variantId),
        LC.backendApi.estadoPublicacionMercadoLibre(miState.variantId),
      ]);
      if (!esVigente(miState)) return;
      if (!detalle) {
        main.innerHTML = `<div class="page-wrap"><div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("help")}</div><p class="empty-state-title">Producto no encontrado</p><button data-back class="btn-secondary mt-4">← Volver</button></div></div>`;
        main.querySelector("[data-back]").addEventListener("click", () => LC.router.navigate("/productos"));
        return;
      }
      miState.producto = detalle.row;

      // Ya tiene una publicación real -- se gestiona (pausar/reactivar/
      // eliminar), nunca se vuelve a preguntar "¿conviene publicarlo?".
      if (estadoRes.ok) {
        miState.modoGestion = true;
        miState.gestion = estadoRes.data;
        miState.cargando = false;
        renderGestion(main);
        return;
      }

      // 15 de septiembre de 2026 — revisión por perfil: sin Mercado Libre
      // conectado, "Preparar publicación" terminaba en un error con
      // "Reintentar". Se consulta la conexión junto con la decisión.
      const [decisionRes, estadoMlRes] = await Promise.all([
        LC.backendApi.decisionMercadoLibre(miState.variantId),
        LC.backendApi.fetchMercadoLibreEstado(),
      ]);
      if (!esVigente(miState)) return;
      miState.mlConectado = estadoMlRes.ok ? Boolean(estadoMlRes.data.conectado) : null;
      if (decisionRes.ok) {
        miState.decision = decisionRes.data;
      } else {
        miState.error = decisionRes.error.mensaje;
      }
      miState.cargando = false;
    }
    renderFase(main);
  }

  // Guard contra estado obsoleto (30 de agosto de 2026, hallazgo de
  // qa-engineer): `state` se reemplaza entero al navegar a otro producto
  // (ver render()) — cualquier callback async debe comparar contra la
  // referencia que tenía ANTES de esperar, nunca releer `state` a ciegas
  // después de un `await`, o una respuesta tardía de un producto viejo
  // puede pisar la pantalla del producto que se está viendo ahora.
  function esVigente(miState) {
    return state === miState;
  }

  function skeleton() {
    return `<div class="page-wrap app-fade">
      <div class="skeleton-line h-8 w-64 mb-6"></div>
      <div class="skeleton-line h-40 w-full"></div>
    </div>`;
  }

  function stepper() {
    const idxActual = Math.max(0, PASOS.findIndex((p) => p.fase === state.fase));
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
      </div>`;
  }

  function renderFase(main) {
    const contenido = { decision: renderPasoDecision, preparar: renderPasoPreparar, revisar: renderPasoRevisar, publicado: renderPasoPublicado }[state.fase];
    main.innerHTML = `
      <div class="page-wrap app-fade max-w-4xl">
        <button id="ml-back" class="text-sm text-slate-500 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 mb-4 inline-flex items-center gap-1">← Volver al producto</button>
        <div class="flex items-center gap-2 mb-1">
          <h2 class="text-xl font-semibold">${escapeHtml(state.producto.nombre)}</h2>
        </div>
        <p class="text-sm text-slate-500 dark:text-slate-400 font-mono mb-5">${escapeHtml(state.producto.sku) || "Sin SKU"}</p>
        ${stepper()}
        <div class="mt-6">${contenido()}</div>
      </div>`;
    document.getElementById("ml-back").addEventListener("click", () => LC.router.navigate(`/productos/${state.variantId}`));
    wireFase(main);
  }

  // ------------------------------------------------------------------
  // Paso 1 — Decisión
  // ------------------------------------------------------------------

  function estadoVisual(decision) {
    // El backend solo manda 3 valores ("conviene"|"revisar"|"no_conviene")
    // — "datos insuficientes" se deriva acá: es "revisar" con faltantes no
    // vacío (ver DECISION_NEGOCIO.md), nunca un 4° valor propio del backend.
    if (decision.decision === "revisar" && decision.faltantes && decision.faltantes.length > 0) return "datos_insuficientes";
    return decision.decision;
  }

  function renderPasoDecision() {
    if (state.error) {
      return errorBox(state.error, "ml-reintentar-decision");
    }
    const d = state.decision;
    const visual = estadoVisual(d);
    const label = visual === "datos_insuficientes" ? "Faltan datos para poder decidir" : DECISION_LABEL[d.decision];
    const preparaDeshabilitado = d.decision === "no_conviene";
    // 14 de septiembre de 2026 — la decisión se toma con el precio REAL del
    // producto; el precio recomendado es solo una sugerencia (margen objetivo).
    const claseGanancia = d.gananciaActual == null ? "" : d.gananciaActual < 0 ? "stat-value--danger" : "stat-value--success";
    return `
      <div class="panel-card mb-5">
        <div class="flex items-center justify-between gap-3 mb-4">
          <h3 class="panel-title">¿Conviene venderlo en Mercado Libre?</h3>
          <span class="reco-badge reco-${visual}">${icon(DECISION_ICON[d.decision] || "help")} ${escapeHtml(label)}</span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-4">
          <div><p class="stat-label">Tu precio</p><p class="stat-value stat-value--sm mt-1">${formatCLPReal(d.precioActual)}</p></div>
          <div><p class="stat-label">Ganancia con tu precio</p><p class="stat-value stat-value--sm mt-1 ${claseGanancia}">${formatCLPReal(d.gananciaActual)}</p></div>
          <div><p class="stat-label">Margen con tu precio</p><p class="stat-value stat-value--sm mt-1">${formatPct(d.margenActualPct)}</p></div>
          <div><p class="stat-label">Precio para tu margen objetivo</p><p class="stat-value stat-value--sm mt-1">${formatCLPReal(d.precioRecomendado)}</p>${d.precioRecomendado != null && d.margenEstimadoPct != null ? `<p class="text-xs text-slate-400 mt-0.5">Para ganar ${formatPct(d.margenEstimadoPct)}</p>` : ""}</div>
          <div><p class="stat-label">Competencia</p><p class="stat-value stat-value--sm mt-1">${d.competencia ? `${formatCLPReal(d.competencia.rangoPrecioMinimo)} – ${formatCLPReal(d.competencia.rangoPrecioMaximo)}` : "Sin datos"}</p></div>
        </div>
        ${etiquetaComisionMl(d.comisionMlFuente)}
        ${etiquetaTipoDecision(d)}
        <p class="text-sm text-slate-600 dark:text-slate-300 mb-4">${escapeHtml(d.razon)}</p>
        ${d.avisoMargenObjetivo ? `<p class="text-sm text-amber-600 dark:text-amber-400 mb-4">${escapeHtml(d.avisoMargenObjetivo)}</p>` : ""}
        ${d.faltantes && d.faltantes.length ? `
          <div class="space-y-1.5 mb-4">
            ${d.faltantes.map((f) => `<p class="text-sm flex items-center gap-2"><span class="dot dot--gray"></span> ${f === "costo de compra"
              // 15/09/2026: sin costo la ganancia se calcula con costo $0; lo único que falta es el precio por margen objetivo.
              ? "Sin costo de compra: la ganancia se calcula con costo $0 y no hay precio para tu margen objetivo (se usa tu precio de venta)."
              : `Falta cargar: ${escapeHtml(f)}`}</p>`).join("")}
          </div>` : ""}
        <div class="flex flex-wrap items-center justify-between gap-3">
          <button id="ml-ver-analisis" class="btn-secondary">${state.verAnalisis ? "Ocultar análisis" : "Ver análisis"}</button>
          ${state.mlConectado === false
            ? `<div class="flex flex-wrap items-center gap-3"><span class="text-xs text-slate-500 dark:text-slate-400">Para publicar, primero conecta tu cuenta de Mercado Libre.</span><button id="ml-conectar" class="btn-primary">Conectar Mercado Libre</button></div>`
            : `<button id="ml-preparar" class="btn-primary" ${preparaDeshabilitado ? "disabled" : ""} ${preparaDeshabilitado ? 'title="No conviene publicar este producto en Mercado Libre con los datos actuales"' : ""}>
            ${d.decision === "revisar" ? "Preparar de todas formas" : "Preparar publicación"}
          </button>`}
        </div>
      </div>
      ${state.verAnalisis ? renderAnalisisDetalle() : ""}
    `;
  }

  function renderAnalisisDetalle() {
    const d = state.decision;
    const c = state.competenciaDetalle;
    return `
      <div class="panel-card">
        <h3 class="panel-title mb-4">Análisis completo</h3>

        <div class="mb-5">
          <h4 class="text-sm font-semibold mb-2">Precio recomendado</h4>
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <div><p class="stat-label">Precio mínimo rentable</p><p class="font-medium mt-1">${formatCLPReal(d.precioMinimoRentable)}</p></div>
            <div><p class="stat-label">Precio recomendado</p><p class="font-medium mt-1">${formatCLPReal(d.precioRecomendado)}</p></div>
            <div><p class="stat-label">Margen esperado</p><p class="font-medium mt-1">${formatPct(d.margenEstimadoPct)}</p></div>
          </div>
          ${etiquetaComisionMl(d.comisionMlFuente)}
        </div>

        <div class="mb-5">
          <h4 class="text-sm font-semibold mb-2">Competencia</h4>
          ${
            c === null
              ? `<p class="text-sm text-slate-400">Cargando…</p>`
              : c.error
              ? `<p class="text-sm text-red-600 dark:text-red-400">${escapeHtml(c.error)}</p>`
              : !c.encontrado
              ? `<p class="text-sm text-slate-500 dark:text-slate-400">No encontramos este producto en el catálogo de Mercado Libre.</p>`
              : !c.analisis.hayCompetencia
              ? `<p class="text-sm text-slate-500 dark:text-slate-400">Encontramos el producto, pero no hay competencia activa en este momento.</p>`
              : `<div class="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  <div><p class="stat-label">Precio del ganador</p><p class="font-medium mt-1">${formatCLPReal(c.analisis.precioGanador)}</p></div>
                  <div><p class="stat-label">Rango de mercado</p><p class="font-medium mt-1">${formatCLPReal(c.analisis.rangoPrecioMinimo)} – ${formatCLPReal(c.analisis.rangoPrecioMaximo)}</p></div>
                  <div><p class="stat-label">Tu posición</p><p class="font-medium mt-1">${textoPosicion(c.analisis.posicionPrecioPropio)}</p></div>
                  <div><p class="stat-label">Condición</p><p class="font-medium mt-1">${c.analisis.condicionGanador === "used" ? "Usado" : "Nuevo"}</p></div>
                  <div><p class="stat-label">Envío gratis</p><p class="font-medium mt-1">${c.analisis.envioGratisGanador ? "Sí" : "No"}</p></div>
                  <div><p class="stat-label">Reputación del vendedor</p><p class="font-medium mt-1">${escapeHtml(c.analisis.reputacionGanador || "—")}</p></div>
                </div>`
          }
        </div>

        <div>
          <h4 class="text-sm font-semibold mb-2">Decisión</h4>
          <p class="text-sm text-slate-600 dark:text-slate-300">${escapeHtml(d.razon)}</p>
        </div>
      </div>
    `;
  }

  // Muestra el nombre legible de la categoría si coincide con la que se
  // sugirió en "Preparar" — el checkpoint de mayor responsabilidad de todo
  // el flujo (revisar y confirmar antes de publicar de verdad) no debería
  // ser el único que solo muestra un ID de categoría sin nombre.
  function nombreCategoriaPara(pv) {
    if (state.preparado && state.preparado.categoriaSugerida && state.preparado.categoriaSugerida.id === pv.categoryId) {
      return state.preparado.categoriaSugerida.nombre;
    }
    return pv.categoryId;
  }

  // 31 de agosto de 2026 — el dueño pidió explícitamente no confundir una
  // estimación con un dato real: cuando hay comisión REAL de Mercado
  // Libre ya verificada (cacheada por categoría+precio, ver
  // resolver_costos_ml en el backend), el precio/margen mostrados arriba
  // se calcularon con esa; si no, con la comisión manual configurada a
  // mano. Nunca se oculta cuál de las dos se usó.
  // Costo de envío (14 de septiembre de 2026) — solo el REAL que informa
  // Mercado Libre para la publicación. Sin ese dato: "No disponible" y la
  // ganancia en Mercado Libre queda marcada como provisional.
  function etiquetaEnvioMl(r) {
    if (!r || !r.envioMlFuente) return "";
    const origen = r.envioMlFuente === "mercadolibre"
      ? `<p class="flex items-center gap-1.5"><span class="dot dot--green"></span>Costo de envío: ${formatCLPReal(r.costoEnvioMl)} · Obtenido de Mercado Libre</p>`
      : `<p class="flex items-center gap-1.5"><span class="dot dot--gray"></span>Costo de envío: No disponible</p>
         ${r.envioMlMotivo ? `<p class="text-slate-400 mt-1">${escapeHtml(r.envioMlMotivo)}</p>` : ""}`;
    const provisional = r.rentabilidadMlProvisional
      ? `<p class="text-amber-600 dark:text-amber-400 mt-1">Rentabilidad provisional: todavía no incluye el costo de envío real de Mercado Libre${r.envioMlManualAplicado ? ` (se usó el envío manual de Configuración, ${formatCLPReal(r.envioMlManualAplicado)})` : ""}.</p>`
      : "";
    return `<div class="text-xs text-slate-600 dark:text-slate-300 mb-3">${origen}${provisional}</div>`;
  }

  function etiquetaComisionMl(fuente) {
    if (fuente === "real") {
      return `<p class="text-xs text-emerald-600 dark:text-emerald-400 mb-3 flex items-center gap-1">${icon("checkCircle")} Comisión Mercado Libre: Real</p>`;
    }
    if (fuente === "manual") {
      return `<p class="text-xs text-amber-600 dark:text-amber-400 mb-3">Comisión de respaldo de Configuración — Mercado Libre todavía no informó la comisión real de este producto</p>`;
    }
    return "";
  }

  // 31 de agosto de 2026 — cierre de la segunda inconsistencia de negocio:
  // la tabla de Oportunidades (columna "Decisión preliminar") evalúa SIN
  // competencia por rendimiento, mientras que ESTA pantalla sí la consulta
  // cuando hay dato disponible — el mismo producto puede mostrar "Conviene"
  // en la tabla y "Revisar" acá, sin que sea una contradicción real (son
  // dos evaluaciones con distinto insumo). Se los distingue con la misma
  // etiqueta visual que ya usa etiquetaComisionMl, reusando `d.competencia`
  // (null cuando no hubo dato de competencia, igual que en la tabla) —
  // ningún campo nuevo del backend, ninguna consulta extra.
  function etiquetaTipoDecision(d) {
    // 15 de septiembre de 2026 — la competencia ya no cambia la decisión (se
    // decide con tu precio real contra tus mínimos): solo se informa si hay datos.
    if (d.competencia) {
      return `<p class="text-xs text-slate-400 dark:text-slate-500 mb-3">Incluye el rango de precios de la competencia, solo como referencia.</p>`;
    }
    return "";
  }

  function textoPosicion(pos) {
    if (pos === "por_debajo") return "Más barato que la competencia";
    if (pos === "en_rango") return "Dentro del rango de mercado";
    if (pos === "por_encima") return "Más caro que la competencia";
    return "—";
  }

  // ------------------------------------------------------------------
  // Paso 2 — Preparar publicación
  // ------------------------------------------------------------------

  function renderPasoPreparar() {
    if (state.cargando) return skeletonInner();
    if (state.error) return errorBox(state.error, "ml-reintentar-preparar");
    const p = state.preparado;
    if (!p) return skeletonInner();

    return `
      <div class="rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950 px-4 py-3 mb-5 text-sm text-indigo-800 dark:text-indigo-200">
        Esto es un borrador — todavía no se envía nada a Mercado Libre.
      </div>

      <div class="panel-card mb-5">
        <h3 class="panel-title mb-3">Título y descripción</h3>
        <label class="form-label">Título</label>
        <input id="ml-titulo" type="text" class="form-input mb-3" value="${escapeHtml(state.tituloEditado ?? p.titulo)}" />
        <details class="mb-2">
          <summary class="cursor-pointer text-sm text-slate-500 dark:text-slate-400">Ver descripción completa</summary>
          <p class="text-sm mt-2 text-slate-600 dark:text-slate-300">${escapeHtml(p.descripcionCompleta)}</p>
          ${p.caracteristicas && p.caracteristicas.length ? `<ul class="list-disc pl-5 mt-2 text-sm text-slate-600 dark:text-slate-300">${p.caracteristicas.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>` : ""}
        </details>
      </div>

      <div class="panel-card mb-5">
        <h3 class="panel-title mb-3">Precio y rentabilidad</h3>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-2">
          <div><p class="stat-label">Precio de venta</p><p class="font-medium mt-1">${formatCLPReal(p.precio)}</p></div>
          <div><p class="stat-label">Ganancia en tu tienda</p><p class="font-medium mt-1 ${p.rentabilidad.margenTiendaClp != null && p.rentabilidad.margenTiendaClp < 0 ? "text-red-600 dark:text-red-400" : ""}">${formatCLPReal(p.rentabilidad.margenTiendaClp)}</p></div>
          <div><p class="stat-label">Ganancia en Mercado Libre</p><p class="font-medium mt-1 ${p.rentabilidad.margenMercadoLibreClp != null && p.rentabilidad.margenMercadoLibreClp < 0 ? "text-red-600 dark:text-red-400" : ""}">${formatCLPReal(p.rentabilidad.margenMercadoLibreClp)}</p></div>
          <div><p class="stat-label">Margen en Mercado Libre</p><p class="font-medium mt-1">${formatPct(p.rentabilidad.margenMercadoLibrePct)}</p></div>
        </div>
        ${etiquetaComisionMl(p.rentabilidad.comisionMlFuente)}
        ${etiquetaEnvioMl(p.rentabilidad)}
        <p class="text-xs text-slate-400 dark:text-slate-500">El precio se lee de tu producto en Nexo — para cambiarlo, editá el producto.</p>
      </div>

      <div class="panel-card mb-5">
        <h3 class="panel-title mb-3">Imágenes</h3>
        ${p.imagenes && p.imagenes.length
          ? `<div class="flex flex-wrap gap-2">${p.imagenes.map((url) => `<img src="${escapeHtml(url)}" class="w-20 h-20 object-cover rounded-lg border border-slate-200 dark:border-slate-700" />`).join("")}</div>`
          : `<p class="text-sm text-red-600 dark:text-red-400">Sin imagen cargada — Mercado Libre no permite publicar sin al menos una imagen.</p>`}
      </div>

      ${p.advertencias && p.advertencias.length ? `
        <div class="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 px-4 py-3 mb-5 text-sm text-amber-800 dark:text-amber-200 space-y-1">
          ${p.advertencias.map((a) => `<p>${escapeHtml(a)}</p>`).join("")}
        </div>` : ""}

      <div class="panel-card mb-5">
        <h3 class="panel-title mb-3">Categoría y condición</h3>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
          <div>
            <label class="form-label">Categoría de Mercado Libre (ID)</label>
            <input id="ml-category-id" type="text" class="form-input" value="${escapeHtml(state.categoryId || (p.categoriaSugerida ? p.categoriaSugerida.id : ""))}" placeholder="ej. MLC180937" />
            ${p.categoriaSugerida ? `<p class="text-xs text-slate-400 mt-1">Sugerida: ${escapeHtml(p.categoriaSugerida.nombre)} — revisala antes de continuar.</p>` : `<p class="text-xs text-amber-600 dark:text-amber-400 mt-1">No pudimos sugerir una categoría automáticamente. Para encontrar el ID: buscá un producto parecido en <a href="https://listado.mercadolibre.cl" target="_blank" rel="noopener" class="underline">mercadolibre.cl</a> y copiá el código que empieza con "MLC" de la URL de esa publicación (ej. MLC180937).</p>`}
          </div>
          <div>
            <label class="form-label">Condición</label>
            <select id="ml-condition" class="form-input">
              <option value="new" ${state.condition === "new" ? "selected" : ""}>Nuevo</option>
              <option value="used" ${state.condition === "used" ? "selected" : ""}>Usado</option>
            </select>
          </div>
        </div>
        <button id="ml-validar" class="btn-secondary">Validar categoría y atributos</button>
      </div>

      ${state.validacion ? renderValidacion() : ""}

      <div class="flex justify-between gap-3">
        <button id="ml-volver-decision" class="btn-secondary">← Volver</button>
        <button id="ml-ir-revisar" class="btn-primary" ${puedeRevisar() ? "" : "disabled"} ${!(p.imagenes && p.imagenes.length) ? 'title="Carga al menos una imagen antes de continuar — Mercado Libre no permite publicar sin imagen"' : ""}>Revisar publicación</button>
      </div>
    `;
  }

  function renderValidacion() {
    const v = state.validacion;
    return `
      <div class="panel-card mb-5">
        <h3 class="panel-title mb-3">Atributos de la categoría</h3>
        ${v.sugerenciasCatalogo ? `<p class="text-sm text-slate-500 dark:text-slate-400 mb-3">Completamos lo que encontramos en el catálogo de Mercado Libre${v.sugerenciasCatalogo.coincidencia === "codigo" ? " por el código de barras" : ` buscando por nombre ("${escapeHtml(v.sugerenciasCatalogo.productoCatalogo || "")}")`}. Confirma cada dato marcado.</p>` : ""}
        ${v.atributosFaltantes.length === 0 ? `<p class="text-sm text-slate-500 dark:text-slate-400 mb-2">No falta ningún atributo más.</p>` : ""}
        ${v.atributosFaltantes.map((f) => renderCampoAtributo(f)).join("")}
        ${v.atributosCompletos.length ? `
          <details class="mt-2">
            <summary class="cursor-pointer text-sm text-slate-500 dark:text-slate-400">Atributos ya resueltos (${v.atributosCompletos.length})</summary>
            <ul class="text-sm text-slate-500 dark:text-slate-400 mt-2 space-y-1">
              ${v.atributosCompletos.map((a) => `<li>${escapeHtml(a.nombre || a.id)}: ${escapeHtml(a.valueName || "")}</li>`).join("")}
            </ul>
          </details>` : ""}
      </div>
    `;
  }

  function renderCampoAtributo(f) {
    const valorActual = state.atributosValores[f.id] || "";
    const esRazonGtinVacio = f.id === "EMPTY_GTIN_REASON";
    const eligioSinCodigo = esRazonGtinVacio && valorActual === "El producto no tiene código registrado";
    const campo = f.opciones && f.opciones.length
      ? `<select data-attr="${escapeHtml(f.id)}" class="form-input ml-attr-input">
          <option value="">Elige una opción</option>
          ${f.opciones.map((o) => `<option value="${escapeHtml(o.name)}" ${valorActual === o.name ? "selected" : ""}>${escapeHtml(o.name)}</option>`).join("")}
        </select>`
      : `<input data-attr="${escapeHtml(f.id)}" type="text" class="form-input ml-attr-input" value="${escapeHtml(valorActual)}" />`;
    return `
      <div class="mb-3">
        <label class="form-label">${escapeHtml(f.nombre)}</label>
        ${campo}
        ${f.valorSugerido && valorActual === f.valorSugerido ? `<p class="text-xs text-amber-600 dark:text-amber-400 mt-1">Por confirmar: dato del catálogo de Mercado Libre. Revisalo antes de publicar.</p>` : ""}
        ${eligioSinCodigo ? `
          <label class="flex items-center gap-2 mt-2 text-sm text-slate-600 dark:text-slate-300">
            <input type="checkbox" id="ml-confirmar-sin-codigo" class="form-checkbox" ${state.gtinSinCodigoConfirmado ? "checked" : ""} ${state.confirmandoSinCodigo ? "disabled" : ""} />
            ${state.confirmandoSinCodigo ? "Guardando…" : "Confirmo que este producto no tiene código de barras"}
          </label>` : ""}
      </div>`;
  }

  // Alias reales del mismo dato (código de barras) que puede pedir una
  // categoría — mismo criterio que _ALIAS_GTIN en
  // domain/listing_validation.py (backend).
  const ALIAS_GTIN = ["GTIN", "EAN", "UPC"];

  function puedeRevisar() {
    if (!state.validacion) return false;
    // Mercado Libre rechaza duro publicar sin imagen — no tiene sentido
    // dejar avanzar hasta el preview para recién ahí enterarse.
    if (!state.preparado.imagenes || state.preparado.imagenes.length === 0) return false;
    const razon = state.atributosValores.EMPTY_GTIN_REASON;
    if (razon === "El producto no tiene código registrado" && !state.gtinSinCodigoConfirmado) return false;
    // 1 de septiembre de 2026 — bug real encontrado en la primera prueba
    // en vivo contra Mercado Libre: una vez confirmado "sin código", el
    // backend (evaluar_atributos) ya no exige GTIN/EAN/UPC — pero acá
    // seguían listados en atributosFaltantes (la respuesta de /validar no
    // se vuelve a pedir al tildar el checkbox) y el dueño quedaba
    // trabado, sin poder avanzar a "Revisar" sin escribir algo en un
    // campo que ya no correspondía completar.
    const sinCodigoConfirmado = razon === "El producto no tiene código registrado" && state.gtinSinCodigoConfirmado;
    return state.validacion.atributosFaltantes.every((f) => {
      if (sinCodigoConfirmado && ALIAS_GTIN.includes(f.id)) return true;
      return (state.atributosValores[f.id] || "").trim() !== "";
    });
  }

  // ------------------------------------------------------------------
  // Paso 3 — Revisar (preview, nunca publica)
  // ------------------------------------------------------------------

  function renderPasoRevisar() {
    if (state.cargando) return skeletonInner();
    if (state.erroresPreview) return errorBox(state.erroresPreview, "ml-volver-preparar-error");
    const pv = state.preview;
    if (!pv) return skeletonInner();

    return `
      <div class="rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950 px-4 py-3 mb-5 text-sm text-indigo-800 dark:text-indigo-200">
        Esto es exactamente lo que se va a enviar a Mercado Libre si confirmás. Todavía no se publicó nada.
      </div>

      <div class="panel-card mb-5">
        <h3 class="panel-title mb-3">Publicación</h3>
        <div class="text-sm space-y-1.5">
          <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Vendedor</span><span>${escapeHtml(pv.seller.nickname || "—")} · ${escapeHtml(pv.seller.siteId || "")}</span></div>
          <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Categoría</span><span>${escapeHtml(nombreCategoriaPara(pv))}</span></div>
          <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">${pv.userProductSeller ? "Nombre de familia" : "Título"}</span><span>${escapeHtml(pv.userProductSeller ? pv.familyName : pv.title)}</span></div>
          ${pv.model ? `<div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Modelo</span><span>${escapeHtml(pv.model)}</span></div>` : ""}
          <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Código de barras (GTIN)</span><span>${pv.gtin ? escapeHtml(pv.gtin) : pv.emptyGtinReason ? escapeHtml(pv.emptyGtinReason) : "—"}</span></div>
          <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Precio</span><span>${formatCLPReal(pv.price)} ${escapeHtml(pv.currencyId || "")}</span></div>
          <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Stock disponible</span><span>${pv.availableQuantity}</span></div>
          <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Tipo de publicación</span><span>${LISTING_TYPE_LABEL[state.listingType] || escapeHtml(pv.listingTypeId || "")}</span></div>
        </div>
        ${pv.pictures && pv.pictures.length
          ? `<div class="flex flex-wrap gap-2 mt-3">${pv.pictures.map((p) => `<img src="${escapeHtml(p.source)}" class="w-16 h-16 object-cover rounded-lg border border-slate-200 dark:border-slate-700" />`).join("")}</div>`
          : `<p class="text-sm text-red-600 dark:text-red-400 mt-3">Sin imagen — Mercado Libre va a rechazar esta publicación.</p>`}
      </div>

      <div class="panel-card mb-5">
        <label class="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
          <input type="checkbox" id="ml-acepto-publicar" class="form-checkbox" ${state.aceptoPublicar ? "checked" : ""} />
          Entiendo que esto va a publicar este producto en Mercado Libre de verdad
        </label>
      </div>

      <div class="flex justify-between gap-3">
        <button id="ml-volver-preparar" class="btn-secondary" ${state.publicando ? "disabled" : ""}>← Editar</button>
        <button id="ml-publicar" class="btn-primary" ${state.aceptoPublicar && !state.publicando ? "" : "disabled"}>${state.publicando ? "Publicando…" : "Publicar en Mercado Libre"}</button>
      </div>
    `;
  }

  // ------------------------------------------------------------------
  // Paso 4 — Publicado
  // ------------------------------------------------------------------

  function renderPasoPublicado() {
    const r = state.publicado;
    if (!r) return skeletonInner();
    return `
      <div class="panel-card text-center py-10">
        <div class="empty-state-icon text-emerald-500">${icon("checkCircle")}</div>
        <p class="text-lg font-semibold mt-3">Publicación creada en Mercado Libre</p>
        <p class="text-sm text-slate-500 dark:text-slate-400 mt-1 font-mono">item_id: ${escapeHtml(r.itemId)}</p>
        <div class="flex justify-center gap-3 mt-6">
          ${r.permalink && /^https:\/\//i.test(r.permalink) ? `<a href="${escapeHtml(r.permalink)}" target="_blank" rel="noopener" class="btn-primary">Ver en Mercado Libre</a>` : ""}
          <button id="ml-ir-gestion" class="btn-secondary">Gestionar publicación</button>
          <button id="ml-volver-producto" class="btn-secondary">Volver al producto</button>
        </div>
      </div>
    `;
  }

  // ------------------------------------------------------------------
  // Helpers de estado de carga/error
  // ------------------------------------------------------------------

  function skeletonInner() {
    return `<div class="skeleton-line h-32 w-full"></div>`;
  }

  function errorBox(mensaje, retryId) {
    // Sin cuenta de Mercado Libre conectada "Reintentar" no arregla nada: se
    // ofrece conectarla (15 de septiembre de 2026).
    const faltaConexion = /conect/i.test(mensaje || "") && /mercado libre/i.test(mensaje || "");
    const boton = faltaConexion
      ? `<button id="ml-conectar" class="btn-primary">Conectar Mercado Libre</button>`
      : `<button id="${retryId}" class="btn-secondary">Reintentar</button>`;
    return `<div class="panel-card"><p class="text-sm text-red-600 dark:text-red-400 mb-3">${escapeHtml(mensaje)}</p>${boton}</div>`;
  }

  // ------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------

  function wireFase(main) {
    const conectar = document.getElementById("ml-conectar");
    if (conectar) conectar.addEventListener("click", () => LC.router.navigate("/integraciones"));
    if (state.fase === "decision") wireDecision(main);
    else if (state.fase === "preparar") wirePreparar(main);
    else if (state.fase === "revisar") wireRevisar(main);
    else if (state.fase === "publicado") wirePublicado(main);
  }

  function wireDecision(main) {
    const retry = document.getElementById("ml-reintentar-decision");
    if (retry) retry.addEventListener("click", () => render(main, state.variantId));

    const btnVer = document.getElementById("ml-ver-analisis");
    if (btnVer) {
      btnVer.addEventListener("click", async () => {
        const miState = state;
        state.verAnalisis = !state.verAnalisis;
        if (state.verAnalisis && state.competenciaDetalle === undefined) state.competenciaDetalle = null;
        renderFase(main);
        if (miState.verAnalisis && miState.competenciaDetalle === null) {
          const res = await LC.backendApi.competenciaMercadoLibre(miState.variantId);
          if (!esVigente(miState)) return;
          // Un error real (ej. cuenta de Mercado Libre no conectada) nunca
          // se disfraza de "no encontrado" — son dos situaciones distintas
          // y el dueño necesita saber cuál es.
          miState.competenciaDetalle = res.ok ? res.data : { encontrado: false, analisis: null, error: res.error.mensaje };
          if (miState.fase === "decision" && miState.verAnalisis) renderFase(main);
        }
      });
    }
    const btnPreparar = document.getElementById("ml-preparar");
    if (btnPreparar) {
      btnPreparar.addEventListener("click", () => {
        state.fase = "preparar";
        cargarPreparacion(main);
      });
    }
  }

  async function cargarPreparacion(main) {
    const miState = state;
    state.cargando = true;
    state.error = null;
    renderFase(main);
    const res = await LC.backendApi.prepararPublicacionMercadoLibre(miState.variantId);
    if (!esVigente(miState)) return;
    miState.cargando = false;
    if (!res.ok) {
      miState.error = res.error.mensaje;
    } else {
      miState.preparado = res.data;
      miState.categoryId = res.data.categoriaSugerida ? res.data.categoriaSugerida.id : "";
    }
    renderFase(main);
  }

  function wirePreparar(main) {
    const retry = document.getElementById("ml-reintentar-preparar");
    if (retry) retry.addEventListener("click", () => cargarPreparacion(main));

    const tituloInput = document.getElementById("ml-titulo");
    if (tituloInput) tituloInput.addEventListener("input", (e) => { state.tituloEditado = e.target.value; });

    const catInput = document.getElementById("ml-category-id");
    if (catInput) catInput.addEventListener("input", (e) => { state.categoryId = e.target.value; });
    const condSelect = document.getElementById("ml-condition");
    if (condSelect) condSelect.addEventListener("change", (e) => { state.condition = e.target.value; });

    const btnValidar = document.getElementById("ml-validar");
    if (btnValidar) {
      btnValidar.addEventListener("click", async () => {
        if (!state.categoryId || !state.categoryId.trim()) {
          toast("error", "Indicá una categoría antes de validar.");
          return;
        }
        const miState = state;
        btnValidar.disabled = true;
        btnValidar.textContent = "Validando…";
        const res = await LC.backendApi.validarPublicacionMercadoLibre(miState.variantId, { categoryId: miState.categoryId.trim(), condition: miState.condition });
        if (!esVigente(miState)) return;
        if (!res.ok) {
          toast("error", res.error.mensaje);
          btnValidar.disabled = false;
          btnValidar.textContent = "Validar categoría y atributos";
          return;
        }
        // Se resetean los valores elegidos antes de esta validación — si
        // el dueño cambió de categoría, un valor viejo (de otro conjunto
        // de atributos, con otras opciones) nunca debe quedar arrastrado
        // como si siguiera siendo válido (hallazgo de qa-engineer, FASE 6).
        miState.atributosValores = {};
        // Sugerencias del catálogo real de Mercado Libre (ej. Autor,
        // Editorial): quedan precargadas pero marcadas "Por confirmar".
        (res.data.atributosFaltantes || []).forEach((f) => {
          if (f.valorSugerido) miState.atributosValores[f.id] = f.valorSugerido;
        });
        miState.gtinSinCodigoConfirmado = false;
        miState.validacion = res.data;
        renderFase(main);
      });
    }

    main.querySelectorAll(".ml-attr-input").forEach((el) => {
      el.addEventListener("change", (e) => {
        state.atributosValores[e.target.dataset.attr] = e.target.value;
        renderFase(main);
      });
    });
    const chkSinCodigo = document.getElementById("ml-confirmar-sin-codigo");
    if (chkSinCodigo) {
      chkSinCodigo.addEventListener("change", async (e) => {
        const miState = state;
        miState.gtinSinCodigoConfirmado = e.target.checked;
        if (e.target.checked) {
          miState.confirmandoSinCodigo = true;
          renderFase(main);
          const res = await LC.backendApi.actualizarCodigoBarras(miState.variantId, { confirmarSinCodigo: true });
          if (!esVigente(miState)) return;
          miState.confirmandoSinCodigo = false;
          if (!res.ok) {
            toast("error", res.error.mensaje);
            miState.gtinSinCodigoConfirmado = false;
          }
        }
        renderFase(main);
      });
    }

    const btnVolver = document.getElementById("ml-volver-decision");
    if (btnVolver) btnVolver.addEventListener("click", () => { state.fase = "decision"; renderFase(main); });

    const btnRevisar = document.getElementById("ml-ir-revisar");
    if (btnRevisar) {
      btnRevisar.addEventListener("click", async () => {
        const miState = state;
        miState.fase = "revisar";
        miState.cargando = true;
        miState.erroresPreview = null;
        renderFase(main);
        const body = {
          category_id: miState.categoryId.trim(),
          condition: miState.condition,
          listing_type: miState.listingType,
          attributes: { ...miState.atributosValores },
        };
        const res = await LC.backendApi.previewPublicacionMercadoLibre(miState.variantId, body);
        if (!esVigente(miState)) return;
        miState.cargando = false;
        if (!res.ok) {
          miState.erroresPreview = res.error.mensaje;
        } else {
          miState.preview = res.data;
        }
        renderFase(main);
      });
    }
  }

  function wireRevisar(main) {
    const retry = document.getElementById("ml-volver-preparar-error");
    if (retry) retry.addEventListener("click", () => { state.fase = "preparar"; state.erroresPreview = null; renderFase(main); });

    const btnVolver = document.getElementById("ml-volver-preparar");
    if (btnVolver) btnVolver.addEventListener("click", () => { state.fase = "preparar"; renderFase(main); });

    const chk = document.getElementById("ml-acepto-publicar");
    if (chk) chk.addEventListener("change", (e) => { state.aceptoPublicar = e.target.checked; renderFase(main); });

    const btnPublicar = document.getElementById("ml-publicar");
    if (btnPublicar) {
      btnPublicar.addEventListener("click", () => {
        if (state.publicando) return; // protección extra contra doble click
        const pv = state.preview;
        openModal({
          title: "¿Publicar en Mercado Libre?",
          body: `
            <p><strong>${escapeHtml(pv.userProductSeller ? pv.familyName : pv.title)}</strong></p>
            <p class="mt-1">Precio: ${formatCLPReal(pv.price)}</p>
            <p class="mt-1">Categoría: ${escapeHtml(nombreCategoriaPara(pv))}</p>
          `,
          primaryLabel: "Sí, publicar",
          secondaryLabel: "Cancelar",
          onPrimary: () => publicarAhora(main),
        });
      });
    }
  }

  async function publicarAhora(main) {
    // El modal ya se cerró para cuando esto corre (openModal no espera
    // promesas) — el botón "Publicar" pasa a "Publicando…" y se
    // deshabilita ACÁ, antes de la llamada real, para que nunca quede la
    // pantalla sin feedback mientras se publica algo irreversible.
    const miState = state;
    miState.publicando = true;
    renderFase(main);
    const body = {
      category_id: miState.categoryId.trim(),
      condition: miState.condition,
      listing_type: miState.listingType,
      attributes: { ...miState.atributosValores },
    };
    const res = await LC.backendApi.confirmarPublicacionMercadoLibre(miState.variantId, body);
    miState.publicando = false;
    // El dueño pudo haber navegado a otra pantalla mientras esto seguía en
    // vuelo — el resultado de una publicación REAL nunca se descarta en
    // silencio solo porque ya no está mirando esta pantalla, pero tampoco
    // se pisa el estado de lo que esté viendo ahora: se avisa por toast
    // (global, no depende de qué pantalla esté activa) en vez de
    // renderFase(main) cuando el estado ya no es el vigente.
    const sigueEnEstaPantalla = esVigente(miState);
    if (!res.ok) {
      // Cualquier error acá (incluido un timeout/corte de red DESPUÉS de
      // que el backend ya haya mandado el POST real) es demasiado
      // importante para un toast que desaparece solo — nunca se sabe con
      // certeza si la publicación se creó, así que siempre se usa el
      // modal fijo, nunca solo el caso "integracion"/502.
      openModal({
        title: "No pudimos confirmar la publicación",
        body: `<p>${escapeHtml(res.error.mensaje)}</p><p class="mt-2 text-xs text-slate-400">Si esto pasó después de intentar publicar, revisa tu cuenta de Mercado Libre antes de volver a intentar — para no duplicar la publicación.</p>`,
        primaryLabel: "Entendido",
      });
      if (sigueEnEstaPantalla) renderFase(main);
      return;
    }
    miState.publicado = res.data;
    miState.fase = "publicado";
    toast("success", "Publicación creada en Mercado Libre.");
    if (sigueEnEstaPantalla) renderFase(main);
  }

  function wirePublicado(main) {
    const btn = document.getElementById("ml-volver-producto");
    if (btn) btn.addEventListener("click", () => LC.router.navigate(`/productos/${state.variantId}`));
    const btnGestion = document.getElementById("ml-ir-gestion");
    if (btnGestion) btnGestion.addEventListener("click", async () => {
      const miState = state;
      main.innerHTML = skeleton();
      const res = await LC.backendApi.estadoPublicacionMercadoLibre(miState.variantId);
      if (!esVigente(miState)) return;
      miState.modoGestion = true;
      miState.gestion = res.ok ? res.data : null;
      renderGestion(main);
    });
  }

  // ------------------------------------------------------------------
  // Gestión de una publicación ya creada — pausar/reactivar/eliminar
  // (1 de septiembre de 2026). No es un paso del wizard (no tiene sentido
  // volver a preguntar "¿conviene publicarlo?" de algo que ya está
  // publicado) — pantalla propia, se entra directo desde render() cuando
  // el producto YA tiene una publicación real.
  // ------------------------------------------------------------------

  const ESTADO_GESTION_LABEL = { activa: "Activa", pausada: "Pausada", eliminada: "Eliminada", desconocido: "Estado desconocido" };
  const ESTADO_GESTION_BADGE = { activa: "reco-conviene", pausada: "reco-revisar", eliminada: "reco-no_conviene", desconocido: "reco-datos_insuficientes" };
  const ACCION_LABEL = { pausar: "Pausar publicación", reactivar: "Reactivar publicación", eliminar: "Eliminar publicación" };

  function renderGestion(main) {
    const g = state.gestion;
    main.innerHTML = `
      <div class="page-wrap app-fade max-w-2xl">
        <button id="ml-back" class="text-sm text-slate-500 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 mb-4 inline-flex items-center gap-1">← Volver al producto</button>
        <h2 class="text-xl font-semibold mb-1">${escapeHtml(state.producto.nombre)}</h2>
        <p class="text-sm text-slate-500 dark:text-slate-400 font-mono mb-5">${escapeHtml(state.producto.sku) || "Sin SKU"}</p>
        <div class="panel-card">
          <h3 class="panel-title mb-3">Publicación en Mercado Libre</h3>
          ${!g ? `
            <p class="text-sm text-red-600 dark:text-red-400 mb-3">No pudimos consultar el estado de esta publicación en este momento.</p>
            <button id="ml-gestion-reintentar" class="btn-secondary">Reintentar</button>
          ` : `
            <div class="flex items-center gap-3 mb-4">
              <span class="reco-badge ${ESTADO_GESTION_BADGE[g.estado] || "reco-datos_insuficientes"}">${escapeHtml(ESTADO_GESTION_LABEL[g.estado] || g.estado)}</span>
              ${g.estado === "desconocido" ? `<span class="text-xs text-slate-400">Mercado Libre no nos dejó confirmar el estado real — puede haber sido pausada o restringida directamente ahí.</span>` : ""}
            </div>
            ${g.permalink ? `<a href="${escapeHtml(g.permalink)}" target="_blank" rel="noopener" class="text-sm text-indigo-600 dark:text-indigo-400 hover:underline">Ver en Mercado Libre ↗</a>` : ""}
            <div class="flex flex-wrap gap-3 mt-5">
              ${(g.accionesDisponibles || []).map((accion) => `
                <button data-gestion-accion="${accion}" class="${accion === "eliminar" ? "btn-secondary btn-secondary--danger" : "btn-secondary"}" ${state.gestionAccionEnCurso ? "disabled" : ""}>
                  ${state.gestionAccionEnCurso ? "Procesando…" : ACCION_LABEL[accion]}
                </button>
              `).join("")}
              ${(g.accionesDisponibles || []).length === 0 && g.estado === "eliminada" ? `<p class="text-sm text-slate-400">Esta publicación está cerrada de forma definitiva — Mercado Libre no permite reabrirla.</p>` : ""}
            </div>
          `}
        </div>
      </div>`;
    document.getElementById("ml-back").addEventListener("click", () => LC.router.navigate(`/productos/${state.variantId}`));
    wireGestion(main);
  }

  function wireGestion(main) {
    const btnReintentar = document.getElementById("ml-gestion-reintentar");
    if (btnReintentar) btnReintentar.addEventListener("click", async () => {
      const miState = state;
      const res = await LC.backendApi.estadoPublicacionMercadoLibre(miState.variantId);
      if (!esVigente(miState)) return;
      miState.gestion = res.ok ? res.data : null;
      renderGestion(main);
    });
    main.querySelectorAll("[data-gestion-accion]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const accion = btn.dataset.gestionAccion;
        if (accion === "eliminar") {
          openModal({
            title: "¿Eliminar esta publicación?",
            body: `<p>Mercado Libre va a cerrar esta publicación de forma <strong>definitiva</strong> — no se puede volver a activar después. Si quieres dejar de venderla por ahora sin perder la publicación, usa "Pausar" en su lugar.</p>`,
            primaryLabel: "Sí, eliminar",
            secondaryLabel: "Cancelar",
            onPrimary: () => ejecutarAccionGestion(main, "eliminar"),
          });
        } else {
          ejecutarAccionGestion(main, accion);
        }
      });
    });
  }

  const ACCION_METODO = {
    pausar: "pausarPublicacionMercadoLibre",
    reactivar: "reactivarPublicacionMercadoLibre",
    eliminar: "eliminarPublicacionMercadoLibre",
  };

  async function ejecutarAccionGestion(main, accion) {
    const miState = state;
    miState.gestionAccionEnCurso = true;
    renderGestion(main);
    const res = await LC.backendApi[ACCION_METODO[accion]](miState.variantId);
    if (!esVigente(miState)) return;
    miState.gestionAccionEnCurso = false;
    if (!res.ok) {
      toast("error", res.error.mensaje);
      renderGestion(main);
      return;
    }
    miState.gestion = res.data;
    const MENSAJE_EXITO = { pausar: "Publicación pausada.", reactivar: "Publicación reactivada.", eliminar: "Publicación eliminada." };
    toast("success", MENSAJE_EXITO[accion]);
    renderGestion(main);
  }

  LC.mlPublicar = { render };
})();
