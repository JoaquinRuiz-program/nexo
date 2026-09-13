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
  // Valores reales de MarketplaceAccount.status (backend/app/api/routes/mercadolibre.py)
  // -- sin esto se mostraba el valor crudo en inglés en el detalle de cliente del panel admin.
  const ML_ESTADO_LABEL = { connected: "Conectado", not_connected: "No conectado", token_expired: "Token vencido — necesita reconectar" };

  const SOPORTE_CATEGORIA_LABEL = {
    mercadolibre: "Mercado Libre", publicar: "Publicar", productos: "Productos",
    imagenes: "Imágenes", cuenta: "Cuenta", suscripcion: "Suscripción", otro: "Otro",
  };
  const SOPORTE_ESTADO_LABEL = { abierto: "Abierto", en_revision: "En revisión", resuelto: "Resuelto", cerrado: "Cerrado" };
  const SOPORTE_ESTADO_CLASE = { abierto: "reco-activo", en_revision: "reco-trial", resuelto: "reco-rentable", cerrado: "reco-pendiente_configuracion" };
  const ESTADO_SUSCRIPCION_LABEL = { trialing: "Prueba gratuita", active: "Activa", past_due: "Pago pendiente", canceled: "Cancelada", expired: "Vencida" };

  async function render(main, storeId) {
    if (storeId === "usuarios") await renderUsuarios(main);
    else if (storeId === "soporte") await renderSoporte(main);
    else if (storeId && storeId.startsWith("soporte-")) await renderSoporteDetalle(main, Number(storeId.slice("soporte-".length)));
    else if (storeId) await renderDetalle(main, Number(storeId));
    else await renderClientes(main);
  }

  function tabs(activa) {
    return `
      <div class="chart-tabs mb-5">
        <a href="#/admin" class="chart-tab ${activa === "clientes" ? "chart-tab-active" : ""}">Clientes</a>
        <a href="#/admin/usuarios" class="chart-tab ${activa === "usuarios" ? "chart-tab-active" : ""}">Usuarios</a>
        <a href="#/admin/soporte" class="chart-tab ${activa === "soporte" ? "chart-tab-active" : ""}">Soporte</a>
      </div>
    `;
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
        ${tabs("clientes")}
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
  // Usuarios (vista cruzada, todas las empresas)
  // ------------------------------------------------------------------

  async function renderUsuarios(main) {
    main.innerHTML = `<div class="page-wrap app-fade">${tabs("usuarios")}<div class="skeleton-line h-64 w-full"></div></div>`;
    const res = await LC.backendApi.listarUsuariosAdmin();
    if (!res.ok) {
      main.innerHTML = `<div class="page-wrap">${tabs("usuarios")}<div class="empty-state"><p class="empty-state-title">No pudimos cargar los usuarios</p><p class="empty-state-desc">${escapeHtml(res.error.mensaje)}</p></div></div>`;
      return;
    }
    const usuarios = res.data;

    main.innerHTML = `
      <div class="page-wrap app-fade">
        ${tabs("usuarios")}
        <div class="panel-card">
          <h3 class="panel-title mb-4">Usuarios</h3>
          ${usuarios.length === 0 ? `
            <div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("store")}</div><p class="empty-state-title">Todavía no hay usuarios registrados</p></div>
          ` : `
          <div class="table-wrap"><table class="w-full text-sm">
            <thead>
              <tr class="text-left border-b border-slate-200 dark:border-slate-700">
                <th class="px-3 py-2 font-medium">Nombre</th>
                <th class="px-3 py-2 font-medium">Email</th>
                <th class="px-3 py-2 font-medium">Empresa</th>
                <th class="px-3 py-2 font-medium">Rol</th>
                <th class="px-3 py-2 font-medium">Estado</th>
                <th class="px-3 py-2 font-medium">Registrado</th>
                <th class="px-3 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              ${usuarios.map((u) => `
                <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0 ${u.empresa ? "cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50" : ""}" ${u.empresa ? `data-open="${u.empresa.storeId}"` : ""}>
                  <td class="px-3 py-2.5 font-medium text-slate-800 dark:text-slate-100">${escapeHtml(u.nombre)}</td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${escapeHtml(u.email)}</td>
                  <td class="px-3 py-2.5">${u.empresa ? escapeHtml(u.empresa.nombre) : "—"}</td>
                  <td class="px-3 py-2.5">${u.esNexoAdmin ? '<span class="badge badge-variable">Administrador</span>' : "Cliente"}${u.esVos ? ' <span class="text-xs text-slate-400">(vos)</span>' : ""}</td>
                  <td class="px-3 py-2.5">${u.estadoCuenta === "suspended" ? "Suspendida" : "Activa"}</td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${formatDate(new Date(u.creadoEn))}</td>
                  <td class="px-3 py-2.5 text-right">${u.esVos ? "" : `<button data-rol="${u.id}" data-rol-nuevo="${u.esNexoAdmin ? "quitar" : "dar"}" class="text-xs text-indigo-600 dark:text-indigo-400 hover:underline whitespace-nowrap">${u.esNexoAdmin ? "Quitar administrador" : "Hacer administrador"}</button>`}</td>
                </tr>
              `).join("")}
            </tbody>
          </table></div>`}
        </div>
      </div>
    `;
    main.querySelectorAll("[data-open]").forEach((tr) => {
      tr.addEventListener("click", (e) => {
        if (e.target.closest("[data-rol]")) return;   // el boton de rol no navega a la empresa
        LC.router.navigate(`/admin/${tr.dataset.open}`);
      });
    });

    // 13 de septiembre de 2026 — dar o quitar el rol de administrador de
    // Nexo. Siempre se confirma: es un cambio de privilegios, no una
    // preferencia. El backend rechaza cambiarse el rol a uno mismo y quitar
    // el ultimo administrador que queda.
    main.querySelectorAll("[data-rol]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const userId = Number(btn.dataset.rol);
        const dar = btn.dataset.rolNuevo === "dar";
        const usuario = usuarios.find((u) => u.id === userId);
        openModal({
          title: dar ? "¿Hacer administrador?" : "¿Quitar el rol de administrador?",
          body: dar
            ? `<p><strong>${escapeHtml(usuario.nombre)}</strong> (${escapeHtml(usuario.email)}) va a poder ver y administrar <strong>todas</strong> las empresas de Nexo, entrar a verlas y cambiarles el plan.${usuario.empresa ? " Su propia empresa deja de aparecer en Clientes." : ""}</p>`
            : `<p><strong>${escapeHtml(usuario.nombre)}</strong> (${escapeHtml(usuario.email)}) pierde el acceso al panel de inmediato. Si estaba viendo la cuenta de un cliente, deja de verla.</p>`,
          primaryLabel: dar ? "Sí, hacer administrador" : "Sí, quitar el rol",
          secondaryLabel: "Cancelar",
          onPrimary: async () => {
            const res = await LC.backendApi.cambiarRolAdministrador(userId, dar);
            if (!res.ok) {
              toast("error", res.error.mensaje);
              return;
            }
            toast("success", dar ? "Ahora es administrador de Nexo." : "Ya no es administrador de Nexo.");
            await renderUsuarios(main);
          },
        });
      });
    });
  }

  // ------------------------------------------------------------------
  // Soporte (vista global de solicitudes, todas las empresas)
  // ------------------------------------------------------------------

  async function renderSoporte(main) {
    main.innerHTML = `<div class="page-wrap app-fade">${tabs("soporte")}<div class="skeleton-line h-64 w-full"></div></div>`;
    const res = await LC.backendApi.listarSolicitudesSoporteAdmin();
    if (!res.ok) {
      main.innerHTML = `<div class="page-wrap">${tabs("soporte")}<div class="empty-state"><p class="empty-state-title">No pudimos cargar las solicitudes</p><p class="empty-state-desc">${escapeHtml(res.error.mensaje)}</p></div></div>`;
      return;
    }
    const solicitudes = res.data;

    main.innerHTML = `
      <div class="page-wrap app-fade">
        ${tabs("soporte")}
        <div class="panel-card">
          <h3 class="panel-title mb-4">Solicitudes de soporte</h3>
          ${solicitudes.length === 0 ? `
            <div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("help")}</div><p class="empty-state-title">Todavía no hay solicitudes</p></div>
          ` : `
          <div class="table-wrap"><table class="w-full text-sm">
            <thead>
              <tr class="text-left border-b border-slate-200 dark:border-slate-700">
                <th class="px-3 py-2 font-medium">Empresa</th>
                <th class="px-3 py-2 font-medium">Usuario</th>
                <th class="px-3 py-2 font-medium">Categoría</th>
                <th class="px-3 py-2 font-medium">Asunto</th>
                <th class="px-3 py-2 font-medium">Estado</th>
                <th class="px-3 py-2 font-medium">Enviado</th>
                <th class="px-3 py-2 font-medium">Última actualización</th>
              </tr>
            </thead>
            <tbody>
              ${solicitudes.map((s) => `
                <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50" data-open="${s.id}">
                  <td class="px-3 py-2.5 font-medium text-slate-800 dark:text-slate-100">${escapeHtml(s.empresa.nombre)}</td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${escapeHtml(s.usuario.email)}</td>
                  <td class="px-3 py-2.5">${escapeHtml(SOPORTE_CATEGORIA_LABEL[s.categoria] || s.categoria)}</td>
                  <td class="px-3 py-2.5">${escapeHtml(s.asunto)}</td>
                  <td class="px-3 py-2.5"><span class="reco-badge ${SOPORTE_ESTADO_CLASE[s.estado] || ""} !text-xs !py-1">${escapeHtml(SOPORTE_ESTADO_LABEL[s.estado] || s.estado)}</span></td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${formatDate(new Date(s.creadoEn))}</td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${formatDate(new Date(s.actualizadoEn))}</td>
                </tr>
              `).join("")}
            </tbody>
          </table></div>`}
        </div>
      </div>
    `;
    main.querySelectorAll("[data-open]").forEach((tr) => {
      tr.addEventListener("click", () => LC.router.navigate(`/admin/soporte-${tr.dataset.open}`));
    });
  }

  async function renderSoporteDetalle(main, ticketId) {
    main.innerHTML = `<div class="page-wrap app-fade"><div class="skeleton-line h-64 w-full"></div></div>`;
    const res = await LC.backendApi.detalleSolicitudSoporteAdmin(ticketId);
    if (!res.ok) {
      main.innerHTML = `<div class="page-wrap"><div class="empty-state"><p class="empty-state-title">Solicitud no encontrada</p><button id="soporte-volver" class="btn-secondary mt-4">← Volver</button></div></div>`;
      document.getElementById("soporte-volver").addEventListener("click", () => LC.router.navigate("/admin/soporte"));
      return;
    }
    const s = res.data;
    main.innerHTML = `
      <div class="page-wrap app-fade max-w-2xl">
        <button id="soporte-volver" class="text-sm text-slate-500 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 mb-4 inline-flex items-center gap-1">← Volver a Soporte</button>
        <div class="panel-card mb-5">
          <div class="flex flex-wrap items-start justify-between gap-4 mb-3">
            <div>
              <h2 class="text-lg font-semibold">${escapeHtml(s.asunto)}</h2>
              <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">${escapeHtml(s.empresa.nombre)} · ${escapeHtml(s.usuario.email)}</p>
            </div>
            <span class="reco-badge ${SOPORTE_ESTADO_CLASE[s.estado] || ""}">${escapeHtml(SOPORTE_ESTADO_LABEL[s.estado] || s.estado)}</span>
          </div>
          <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">Categoría: ${escapeHtml(SOPORTE_CATEGORIA_LABEL[s.categoria] || s.categoria)}${s.referencia ? ` · Referencia: ${escapeHtml(s.referencia)}` : ""} · Enviado el ${formatDate(new Date(s.creadoEn))}</p>
          <p class="text-sm text-slate-700 dark:text-slate-200 whitespace-pre-wrap">${escapeHtml(s.descripcion)}</p>
        </div>

        <div class="panel-card">
          <h3 class="panel-title mb-3">Responder</h3>
          ${s.respuestaAdmin ? `<p class="text-xs text-slate-400 mb-2">Última respuesta — ${formatDate(new Date(s.respuestaAdminEn))}</p><p class="text-sm text-slate-700 dark:text-slate-200 whitespace-pre-wrap mb-4">${escapeHtml(s.respuestaAdmin)}</p>` : ""}
          <textarea id="soporte-respuesta" class="form-input mb-3" rows="4" placeholder="Escribí una respuesta para el cliente"></textarea>
          <div class="flex flex-wrap items-center gap-2">
            <select id="soporte-estado" class="form-input !w-auto">
              ${Object.entries(SOPORTE_ESTADO_LABEL).map(([v, l]) => `<option value="${v}" ${v === s.estado ? "selected" : ""}>${escapeHtml(l)}</option>`).join("")}
            </select>
            <button id="soporte-guardar" class="btn-primary">Guardar</button>
          </div>
        </div>
      </div>
    `;
    document.getElementById("soporte-volver").addEventListener("click", () => LC.router.navigate("/admin/soporte"));
    document.getElementById("soporte-guardar").addEventListener("click", async () => {
      const respuesta = document.getElementById("soporte-respuesta").value.trim();
      const estado = document.getElementById("soporte-estado").value;
      const res2 = await LC.backendApi.responderSolicitudSoporteAdmin(ticketId, { respuesta: respuesta || undefined, estado });
      if (!res2.ok) {
        toast("error", res2.error.mensaje);
        return;
      }
      toast("success", "Solicitud actualizada.");
      renderSoporteDetalle(main, ticketId);
    });
  }

  // ------------------------------------------------------------------
  // Detalle de un cliente
  // ------------------------------------------------------------------

  async function renderDetalle(main, storeId) {
    main.innerHTML = `<div class="page-wrap app-fade"><div class="skeleton-line h-8 w-64 mb-6"></div><div class="skeleton-line h-64 w-full"></div></div>`;
    const [res, resPlanes] = await Promise.all([LC.backendApi.detalleClienteAdmin(storeId), LC.backendApi.listarPlanesAdmin()]);
    if (!res.ok) {
      main.innerHTML = `<div class="page-wrap"><div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("help")}</div><p class="empty-state-title">Cliente no encontrado</p><button data-back class="btn-secondary mt-4">← Volver</button></div></div>`;
      main.querySelector("[data-back]").addEventListener("click", () => LC.router.navigate("/admin"));
      return;
    }
    const c = res.data;
    const dueno = c.usuarios[0];
    const planesDisponibles = resPlanes.ok ? resPlanes.data : [];

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
          <div class="mt-4">
            <button id="admin-entrar-soporte" class="btn-secondary">Ver como esta empresa</button>
            <p class="text-xs text-slate-400 mt-1.5">Vas a ver Nexo exactamente como lo ve este cliente, sin cerrar tu sesión de administrador — queda registrado en el historial de acciones administrativas.</p>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mt-6">
            <div><p class="stat-label">Productos</p><p class="text-lg font-semibold mt-1">${c.productos.cantidad}</p></div>
            <div><p class="stat-label">Publicaciones</p><p class="text-lg font-semibold mt-1">${c.publicaciones.total}</p></div>
            <div><p class="stat-label">Mercado Libre</p><p class="text-lg font-semibold mt-1">${c.mercadoLibre && c.mercadoLibre.estado === "connected" ? "Conectado" : "No conectado"}</p></div>
            <div><p class="stat-label">Plan</p><p class="text-lg font-semibold mt-1">${c.plan ? escapeHtml(c.plan.nombre) : "Sin asignar"}</p></div>
            <div><p class="stat-label">Usuarios</p><p class="text-lg font-semibold mt-1">${c.cantidadUsuarios}</p></div>
            <div><p class="stat-label">Tickets abiertos</p><p class="text-lg font-semibold mt-1 ${c.soporte.ticketsAbiertos > 0 ? "text-amber-600 dark:text-amber-400" : ""}">${c.soporte.ticketsAbiertos}</p></div>
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
          <h3 class="panel-title mb-3">Suscripción</h3>
          <div class="flex flex-wrap items-end gap-3">
            <div>
              <label class="form-label" for="admin-plan-select">Plan</label>
              <select id="admin-plan-select" class="form-input !w-auto">
                ${planesDisponibles.map((p) => `<option value="${p.codigo}" ${c.plan && c.plan.codigo === p.codigo ? "selected" : ""}>${escapeHtml(p.nombre)}</option>`).join("")}
              </select>
            </div>
            <div>
              <label class="form-label" for="admin-estado-suscripcion-select">Estado</label>
              <select id="admin-estado-suscripcion-select" class="form-input !w-auto">
                ${["trialing", "active", "past_due", "canceled", "expired"].map((v) => `<option value="${v}" ${c.plan && c.plan.estado === v ? "selected" : ""}>${escapeHtml(ESTADO_SUSCRIPCION_LABEL[v] || v)}</option>`).join("")}
              </select>
            </div>
            <button id="admin-guardar-suscripcion" class="btn-secondary">${c.plan ? "Guardar" : "Asignar plan"}</button>
          </div>
          ${c.plan ? "" : '<p class="text-xs text-slate-400 mt-3">Esta empresa todavía no tiene ninguna suscripción (dato viejo, previo al sistema de planes) — elegí un plan arriba y guardá para crearle la primera.</p>'}
        </div>

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Mercado Libre</h3>
          ${c.mercadoLibre ? `
            <div class="text-sm space-y-1.5">
              <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">Estado</span><span>${escapeHtml(ML_ESTADO_LABEL[c.mercadoLibre.estado] || c.mercadoLibre.estado)}</span></div>
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
          <h3 class="panel-title mb-3">Productos (${c.productos.cantidad})</h3>
          ${c.productos.filas.length ? `
            <div class="table-wrap"><table class="w-full text-sm">
              <thead><tr class="text-left border-b border-slate-200 dark:border-slate-700"><th class="px-3 py-2 font-medium">SKU</th><th class="px-3 py-2 font-medium">Nombre</th><th class="px-3 py-2 font-medium text-right">Precio</th></tr></thead>
              <tbody>
                ${c.productos.filas.slice(0, 20).map((p) => `
                  <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0">
                    <td class="px-3 py-2.5 font-mono text-xs text-slate-500 dark:text-slate-400">${escapeHtml(p.sku) || "—"}</td>
                    <td class="px-3 py-2.5">${escapeHtml(p.nombre)}</td>
                    <td class="px-3 py-2.5 text-right">${p.precio != null ? formatCLPReal(p.precio) : "—"}</td>
                  </tr>`).join("")}
              </tbody>
            </table></div>
            ${c.productos.cantidad > 20 ? `<p class="text-xs text-slate-400 mt-2">Mostrando 20 de ${c.productos.cantidad}.</p>` : ""}
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">Sin productos todavía.</p>`}
        </div>

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Publicaciones (${c.publicaciones.total})</h3>
          ${Object.keys(c.publicaciones.porEstado).length ? `
            <div class="flex flex-wrap gap-2 mb-3">${Object.entries(c.publicaciones.porEstado).map(([estado, n]) => `<span class="badge badge-simple">${escapeHtml(estado)}: ${n}</span>`).join("")}</div>
          ` : ""}
          ${c.publicaciones.filas.length ? `
            <div class="table-wrap"><table class="w-full text-sm">
              <thead><tr class="text-left border-b border-slate-200 dark:border-slate-700"><th class="px-3 py-2 font-medium">Producto</th><th class="px-3 py-2 font-medium">Estado</th><th class="px-3 py-2 font-medium text-right">Precio</th></tr></thead>
              <tbody>
                ${c.publicaciones.filas.map((p) => `
                  <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0">
                    <td class="px-3 py-2.5">${escapeHtml(p.producto || "—")}</td>
                    <td class="px-3 py-2.5"><span class="badge badge-simple">${escapeHtml(p.status)}</span></td>
                    <td class="px-3 py-2.5 text-right">${p.precio != null ? formatCLPReal(p.precio) : "—"}</td>
                  </tr>`).join("")}
              </tbody>
            </table></div>
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">Sin publicaciones todavía.</p>`}
        </div>

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Soporte ${c.soporte.ticketsAbiertos > 0 ? `<span class="badge badge-variable">${c.soporte.ticketsAbiertos} abierta${c.soporte.ticketsAbiertos === 1 ? "" : "s"}</span>` : ""}</h3>
          ${c.soporte.solicitudes.length ? `
            <div class="space-y-2">${c.soporte.solicitudes.map((s) => `
              <div class="flex items-center justify-between gap-3 text-sm border-b border-slate-100 dark:border-slate-800 last:border-0 pb-2 last:pb-0 cursor-pointer hover:text-indigo-600 dark:hover:text-indigo-400" data-open-ticket="${s.id}">
                <span>${escapeHtml(s.asunto)}</span>
                <span class="badge badge-simple shrink-0">${escapeHtml(SOPORTE_ESTADO_LABEL[s.estado] || s.estado)}</span>
              </div>
            `).join("")}</div>
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">Sin solicitudes de soporte todavía.</p>`}
        </div>

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Últimos inicios de sesión</h3>
          ${c.actividadReciente.length ? `
            <div class="space-y-1.5 text-sm">${c.actividadReciente.map((a) => `<p class="text-slate-500 dark:text-slate-400">Inicio de sesión — ${formatDate(new Date(a.fecha))}</p>`).join("")}</div>
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">Sin inicios de sesión registrados todavía.</p>`}
          ${c.erroresRecientes === null ? `<p class="text-xs text-slate-400 mt-4 pt-3 border-t border-slate-100 dark:border-slate-800">Todavía no existe un registro de errores por cliente — se ve en los logs del servidor.</p>` : ""}
        </div>

        <div class="panel-card">
          <h3 class="panel-title mb-3">Actividad administrativa</h3>
          ${c.accionesAdministrativas.length ? `
            <div class="space-y-1.5 text-sm">${c.accionesAdministrativas.map((a) => `<p class="text-slate-500 dark:text-slate-400">${escapeHtml(a.admin)} — ${escapeHtml(a.accion)}${a.detalle ? ` (${escapeHtml(a.detalle)})` : ""} — ${formatDate(new Date(a.fecha))}</p>`).join("")}</div>
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">Sin acciones administrativas registradas todavía.</p>`}
        </div>
      </div>
    `;

    document.getElementById("admin-back").addEventListener("click", () => LC.router.navigate("/admin"));
    document.getElementById("admin-entrar-soporte").addEventListener("click", () => {
      openModal({
        title: "¿Ver esta empresa?",
        body: `<p>Vas a ver Nexo exactamente como lo ve <strong>${escapeHtml(c.nombre)}</strong> (usuario ${escapeHtml(dueno.email)}). Tu sesión de administrador sigue abierta: salís cuando quieras desde el aviso de arriba. Queda registrado en el historial de acciones administrativas.</p>`,
        primaryLabel: "Ver esta empresa",
        secondaryLabel: "Cancelar",
        onPrimary: async () => {
          const res = await LC.backendApi.entrarComoSoporte(storeId);
          if (!res.ok) {
            toast("error", res.error.mensaje);
            return;
          }
          // La sesión (la cookie) no cambió, pero la copia en memoria de
          // LC.auth sí quedó vieja: recarga completa, nunca un navigate()
          // de SPA, para rehidratarla desde /api/auth/me.
          window.location.hash = "/dashboard";
          window.location.reload();
        },
      });
    });
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
    const btnGuardarSuscripcion = document.getElementById("admin-guardar-suscripcion");
    if (btnGuardarSuscripcion) {
      btnGuardarSuscripcion.addEventListener("click", async () => {
        const planCode = document.getElementById("admin-plan-select").value;
        const estado = document.getElementById("admin-estado-suscripcion-select").value;
        const res2 = await LC.backendApi.actualizarSuscripcionAdmin(storeId, { planCode, estado });
        if (!res2.ok) {
          toast("error", res2.error.mensaje);
          return;
        }
        toast("success", "Suscripción actualizada.");
        renderDetalle(main, storeId);
      });
    }
    main.querySelectorAll("[data-open-ticket]").forEach((el) => {
      el.addEventListener("click", () => LC.router.navigate(`/admin/soporte-${el.dataset.openTicket}`));
    });
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
