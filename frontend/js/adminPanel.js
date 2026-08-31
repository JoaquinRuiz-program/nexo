"use strict";

/**
 * Nexo — Panel de administrador (30 de agosto de 2026).
 *
 * Segunda capa de usuario: el dueño de la plataforma Nexo, no un cliente.
 * Ve TODAS las empresas — nunca datos sensibles (tokens/secrets/passwords,
 * ver backend/app/api/routes/admin.py, que ya los excluye de la respuesta;
 * este archivo tampoco los mostraría aunque llegaran, por las dudas no se
 * itera sobre campos desconocidos del objeto).
 *
 * Ruta #/admin (lista de clientes) y #/admin/:storeId (detalle).
 */

window.LC = window.LC || {};

(function () {
  const { escapeHtml, formatDate, toast, openModal, icon, formatCLPReal, formatPct } = LC.ui;

  const ESTADO_LABEL = { activo: "Activo", trial: "Trial", pendiente_configuracion: "Pendiente de configuración", suspendido: "Suspendido" };

  async function render(main, storeId) {
    if (storeId) await renderDetalle(main, Number(storeId));
    else await renderClientes(main);
  }

  // ------------------------------------------------------------------
  // Lista de clientes
  // ------------------------------------------------------------------

  async function renderClientes(main) {
    main.innerHTML = `<div class="page-wrap app-fade"><div class="skeleton-line h-8 w-64 mb-6"></div><div class="skeleton-line h-64 w-full"></div></div>`;
    const res = await LC.backendApi.listarClientesAdmin();
    if (!res.ok) {
      main.innerHTML = `<div class="page-wrap"><div class="empty-state"><p class="empty-state-title">No pudimos cargar los clientes</p><p class="empty-state-desc">${escapeHtml(res.error.mensaje)}</p></div></div>`;
      return;
    }
    const clientes = res.data;

    main.innerHTML = `
      <div class="page-wrap app-fade">
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          <div class="stat-card"><p class="stat-label">Total de clientes</p><p class="stat-value stat-value--sm">${clientes.length}</p></div>
          <div class="stat-card"><p class="stat-label">Activos</p><p class="stat-value stat-value--sm stat-value--success">${clientes.filter((c) => c.estado === "activo").length}</p></div>
          <div class="stat-card"><p class="stat-label">Pendientes de configuración</p><p class="stat-value stat-value--sm stat-value--warning">${clientes.filter((c) => c.estado === "pendiente_configuracion").length}</p></div>
          <div class="stat-card"><p class="stat-label">Con Mercado Libre conectado</p><p class="stat-value stat-value--sm">${clientes.filter((c) => c.mercadoLibreConectado).length}</p></div>
        </div>

        <div class="panel-card">
          <h3 class="panel-title mb-4">Clientes</h3>
          ${clientes.length === 0 ? `
            <div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("store")}</div><p class="empty-state-title">Todavía no hay clientes registrados</p></div>
          ` : `
          <div class="table-wrap"><table class="w-full text-sm">
            <thead>
              <tr class="text-left border-b border-slate-200 dark:border-slate-700">
                <th class="px-3 py-2 font-medium">Empresa</th>
                <th class="px-3 py-2 font-medium">Usuario principal</th>
                <th class="px-3 py-2 font-medium">Registrado</th>
                <th class="px-3 py-2 font-medium">Estado</th>
                <th class="px-3 py-2 font-medium">Mercado Libre</th>
                <th class="px-3 py-2 font-medium text-right">Productos</th>
                <th class="px-3 py-2 font-medium">Última actividad</th>
                <th class="px-3 py-2 font-medium">Plan</th>
              </tr>
            </thead>
            <tbody>
              ${clientes.map((c) => `
                <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50" data-open="${c.storeId}">
                  <td class="px-3 py-2.5 font-medium text-slate-800 dark:text-slate-100">${escapeHtml(c.nombre)}</td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${escapeHtml(c.usuarioPrincipal.email)}</td>
                  <td class="px-3 py-2.5">${formatDate(new Date(c.fechaRegistro))}</td>
                  <td class="px-3 py-2.5"><span class="reco-badge reco-${c.estado} !text-xs !py-1">${escapeHtml(ESTADO_LABEL[c.estado] || c.estado)}</span></td>
                  <td class="px-3 py-2.5"><span class="dot ${c.mercadoLibreConectado ? "dot--green" : "dot--gray"}"></span></td>
                  <td class="px-3 py-2.5 text-right">${c.cantidadProductos}</td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${c.ultimaActividad ? formatDate(new Date(c.ultimaActividad)) : "—"}</td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${c.plan ? escapeHtml(c.plan) : "Sin plan asignado"}</td>
                </tr>
              `).join("")}
            </tbody>
          </table></div>`}
        </div>
      </div>
    `;
    main.querySelectorAll("[data-open]").forEach((tr) => {
      tr.addEventListener("click", () => LC.router.navigate(`/admin/${tr.dataset.open}`));
    });
  }

  // ------------------------------------------------------------------
  // Detalle de un cliente
  // ------------------------------------------------------------------

  async function renderDetalle(main, storeId) {
    main.innerHTML = `<div class="page-wrap app-fade"><div class="skeleton-line h-8 w-64 mb-6"></div><div class="skeleton-line h-64 w-full"></div></div>`;
    const res = await LC.backendApi.detalleClienteAdmin(storeId);
    if (!res.ok) {
      main.innerHTML = `<div class="page-wrap"><div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("help")}</div><p class="empty-state-title">Cliente no encontrado</p><button data-back class="btn-secondary mt-4">← Volver</button></div></div>`;
      main.querySelector("[data-back]").addEventListener("click", () => LC.router.navigate("/admin"));
      return;
    }
    const c = res.data;
    const dueno = c.usuarios[0];

    main.innerHTML = `
      <div class="page-wrap app-fade max-w-4xl">
        <button id="admin-back" class="text-sm text-slate-500 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 mb-4 inline-flex items-center gap-1">← Volver a Clientes</button>

        <div class="panel-card mb-5">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 class="text-xl font-semibold">${escapeHtml(c.nombre)}</h2>
              <p class="text-sm text-slate-500 dark:text-slate-400">Cliente desde ${formatDate(new Date(c.fechaRegistro))}</p>
            </div>
            <span class="reco-badge reco-${c.estado}">${escapeHtml(ESTADO_LABEL[c.estado] || c.estado)}</span>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
            <div><p class="stat-label">Productos</p><p class="text-lg font-semibold mt-1">${c.productos.cantidad}</p></div>
            <div><p class="stat-label">Publicaciones</p><p class="text-lg font-semibold mt-1">${c.publicaciones.total}</p></div>
            <div><p class="stat-label">Mercado Libre</p><p class="text-lg font-semibold mt-1">${c.mercadoLibre && c.mercadoLibre.estado === "connected" ? "Conectado" : "No conectado"}</p></div>
            <div><p class="stat-label">Plan</p><p class="text-lg font-semibold mt-1">${c.plan ? escapeHtml(c.plan.nombre) : "Sin asignar"}</p></div>
          </div>
        </div>

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Usuario principal</h3>
          <div class="text-sm space-y-1.5">
            <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Nombre</span><span>${escapeHtml(dueno.nombre)}</span></div>
            <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Email</span><span>${escapeHtml(dueno.email)}</span></div>
            <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Estado de la cuenta</span><span>${dueno.estadoCuenta === "suspended" ? "Suspendida" : dueno.estadoCuenta === "active" ? "Activa" : escapeHtml(dueno.estadoCuenta)}</span></div>
          </div>
          <div class="mt-4">
            ${c.estado === "suspendido"
              ? `<button id="admin-reactivar" class="btn-secondary">Reactivar cliente</button>`
              : `<button id="admin-suspender" class="btn-secondary btn-secondary--danger">Suspender cliente</button>`}
          </div>
        </div>

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Mercado Libre</h3>
          ${c.mercadoLibre ? `
            <div class="text-sm space-y-1.5">
              <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Estado</span><span>${escapeHtml(c.mercadoLibre.estado)}</span></div>
              <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Cuenta</span><span>${escapeHtml(c.mercadoLibre.nickname || "—")}${c.mercadoLibre.siteId ? ` · ${escapeHtml(c.mercadoLibre.siteId)}` : ""}</span></div>
              <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Conectado el</span><span>${c.mercadoLibre.conectadoEn ? formatDate(new Date(c.mercadoLibre.conectadoEn)) : "—"}</span></div>
              <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Última sincronización</span><span>${c.mercadoLibre.ultimaSincronizacion ? formatDate(new Date(c.mercadoLibre.ultimaSincronizacion)) : "—"}</span></div>
            </div>
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">No conectó Mercado Libre todavía.</p>`}
        </div>

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Costos configurados por canal</h3>
          ${c.costosConfigurados.length ? `
            <div class="table-wrap"><table class="w-full text-sm">
              <thead><tr class="text-left border-b border-slate-200 dark:border-slate-700"><th class="px-3 py-2 font-medium">Canal</th><th class="px-3 py-2 font-medium text-right">Comisión</th><th class="px-3 py-2 font-medium text-right">Margen objetivo</th><th class="px-3 py-2 font-medium text-right">Margen mínimo</th></tr></thead>
              <tbody>
                ${c.costosConfigurados.map((cc) => `
                  <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0">
                    <td class="px-3 py-2.5">${escapeHtml(cc.canal)}</td>
                    <td class="px-3 py-2.5 text-right">${cc.comisionPct != null ? formatPct(cc.comisionPct) : "Sin configurar"}</td>
                    <td class="px-3 py-2.5 text-right">${cc.margenObjetivoPct != null ? formatPct(cc.margenObjetivoPct) : "Sin configurar"}</td>
                    <td class="px-3 py-2.5 text-right">${cc.margenMinimoPct != null ? formatPct(cc.margenMinimoPct) : "Sin configurar"}</td>
                  </tr>`).join("")}
              </tbody>
            </table></div>
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">Sin canales configurados todavía.</p>`}
        </div>

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Publicaciones por estado</h3>
          ${Object.keys(c.publicaciones.porEstado).length ? `
            <div class="flex flex-wrap gap-2">${Object.entries(c.publicaciones.porEstado).map(([estado, n]) => `<span class="badge badge-simple">${escapeHtml(estado)}: ${n}</span>`).join("")}</div>
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">Sin publicaciones todavía.</p>`}
        </div>

        <div class="panel-card">
          <h3 class="panel-title mb-3">Actividad reciente</h3>
          ${c.actividadReciente.length ? `
            <div class="space-y-1.5 text-sm">${c.actividadReciente.map((a) => `<p class="text-slate-500 dark:text-slate-400">${formatDate(new Date(a.fecha))}</p>`).join("")}</div>
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">Sin inicios de sesión registrados todavía.</p>`}
          ${c.erroresRecientes === null ? `<p class="text-xs text-slate-400 mt-4 pt-3 border-t border-slate-100 dark:border-slate-800">Todavía no existe un registro de errores por cliente — se ve en los logs del servidor.</p>` : ""}
        </div>
      </div>
    `;

    document.getElementById("admin-back").addEventListener("click", () => LC.router.navigate("/admin"));
    const btnSuspender = document.getElementById("admin-suspender");
    if (btnSuspender) {
      btnSuspender.addEventListener("click", () => {
        openModal({
          title: "¿Suspender este cliente?",
          body: `<p>${escapeHtml(c.nombre)} no va a poder iniciar sesión hasta que lo reactives.</p>`,
          primaryLabel: "Sí, suspender",
          secondaryLabel: "Cancelar",
          onPrimary: () => cambiarEstadoSuspendido(main, storeId, true),
        });
      });
    }
    const btnReactivar = document.getElementById("admin-reactivar");
    if (btnReactivar) {
      btnReactivar.addEventListener("click", () => cambiarEstadoSuspendido(main, storeId, false));
    }
  }

  async function cambiarEstadoSuspendido(main, storeId, suspendido) {
    const res = await LC.backendApi.actualizarEstadoClienteAdmin(storeId, suspendido);
    if (!res.ok) {
      toast("error", res.error.mensaje);
      return;
    }
    toast("success", suspendido ? "Cliente suspendido." : "Cliente reactivado.");
    renderDetalle(main, storeId);
  }

  LC.adminPanel = { render };
})();
