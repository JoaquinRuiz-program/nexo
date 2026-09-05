"use strict";

/**
 * Nexo — Ayuda y soporte (5 de septiembre de 2026).
 *
 * MVP explícito: cliente envía un problema, el admin de Nexo lo recibe y
 * responde (ver backend/app/api/routes/soporte.py y admin.py). Nada de
 * chatbot ni ticketing avanzado todavía.
 *
 * Ruta #/soporte (lista + formulario) y #/soporte/:id (detalle de una
 * solicitud propia).
 */

window.LC = window.LC || {};

(function () {
  const { escapeHtml, formatDate, toast } = LC.ui;

  const CATEGORIAS = [
    { id: "mercadolibre", label: "Problemas con Mercado Libre" },
    { id: "publicar", label: "Problemas al publicar" },
    { id: "productos", label: "Problemas con productos" },
    { id: "imagenes", label: "Problemas con imágenes" },
    { id: "cuenta", label: "Problemas con mi cuenta" },
    { id: "suscripcion", label: "Problemas con mi suscripción" },
    { id: "otro", label: "Otro" },
  ];

  const ESTADO_LABEL = { abierto: "Abierto", en_revision: "En revisión", resuelto: "Resuelto", cerrado: "Cerrado" };
  const ESTADO_CLASE = { abierto: "reco-activo", en_revision: "reco-trial", resuelto: "reco-rentable", cerrado: "reco-pendiente_configuracion" };

  async function render(main, ticketId) {
    if (ticketId) await renderDetalle(main, Number(ticketId));
    else await renderCentroDeAyuda(main);
  }

  async function renderCentroDeAyuda(main) {
    main.innerHTML = `<div class="page-wrap app-fade"><div class="skeleton-line h-64 w-full"></div></div>`;
    const res = await LC.backendApi.listarMisSolicitudesSoporte();
    const solicitudes = res.ok ? res.data : [];

    main.innerHTML = `
      <div class="page-wrap app-fade max-w-4xl">
        <div class="panel-card mb-6 text-center py-8">
          <h2 class="text-xl font-semibold mb-2">¿Necesitas ayuda?</h2>
          <p class="text-sm text-slate-500 dark:text-slate-400 max-w-md mx-auto">Estamos aquí para ayudarte. Cuéntanos qué problema tienes y te ayudaremos a resolverlo.</p>
        </div>

        <div class="panel-card mb-6">
          <h3 class="panel-title mb-4">Enviar una solicitud</h3>
          <form id="soporte-form" class="space-y-4">
            <div>
              <label class="form-label" for="soporte-categoria">Categoría del problema</label>
              <select id="soporte-categoria" class="form-input" required>
                ${CATEGORIAS.map((c) => `<option value="${c.id}">${escapeHtml(c.label)}</option>`).join("")}
              </select>
            </div>
            <div>
              <label class="form-label" for="soporte-asunto">Asunto</label>
              <input id="soporte-asunto" type="text" class="form-input" placeholder="Resumen breve del problema" required />
            </div>
            <div>
              <label class="form-label" for="soporte-descripcion">Descripción</label>
              <textarea id="soporte-descripcion" class="form-input" rows="4" placeholder="Contanos qué pasó, con el detalle que puedas" required></textarea>
            </div>
            <div>
              <label class="form-label" for="soporte-referencia">Producto o publicación afectado (opcional)</label>
              <input id="soporte-referencia" type="text" class="form-input" placeholder="Ej: SKU-123 o el nombre del producto" />
            </div>
            <button type="submit" class="btn-primary">Enviar solicitud</button>
          </form>
        </div>

        <div class="panel-card">
          <h3 class="panel-title mb-4">Mis solicitudes</h3>
          ${solicitudes.length === 0 ? `
            <p class="text-sm text-slate-500 dark:text-slate-400">Todavía no enviaste ninguna solicitud.</p>
          ` : `
          <div class="table-wrap"><table class="w-full text-sm">
            <thead>
              <tr class="text-left border-b border-slate-200 dark:border-slate-700">
                <th class="px-3 py-2 font-medium">Asunto</th>
                <th class="px-3 py-2 font-medium">Categoría</th>
                <th class="px-3 py-2 font-medium">Estado</th>
                <th class="px-3 py-2 font-medium">Enviado</th>
              </tr>
            </thead>
            <tbody>
              ${solicitudes.map((s) => `
                <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50" data-open="${s.id}">
                  <td class="px-3 py-2.5 font-medium text-slate-800 dark:text-slate-100">${escapeHtml(s.asunto)}</td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${escapeHtml((CATEGORIAS.find((c) => c.id === s.categoria) || {}).label || s.categoria)}</td>
                  <td class="px-3 py-2.5"><span class="reco-badge ${ESTADO_CLASE[s.estado] || ""} !text-xs !py-1">${escapeHtml(ESTADO_LABEL[s.estado] || s.estado)}</span></td>
                  <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${formatDate(new Date(s.creadoEn))}</td>
                </tr>
              `).join("")}
            </tbody>
          </table></div>`}
        </div>
      </div>
    `;

    main.querySelectorAll("[data-open]").forEach((tr) => {
      tr.addEventListener("click", () => LC.router.navigate(`/soporte/${tr.dataset.open}`));
    });

    document.getElementById("soporte-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const category = document.getElementById("soporte-categoria").value;
      const subject = document.getElementById("soporte-asunto").value.trim();
      const description = document.getElementById("soporte-descripcion").value.trim();
      const reference = document.getElementById("soporte-referencia").value.trim() || null;
      if (!subject || !description) {
        toast("error", "Completá el asunto y la descripción.");
        return;
      }
      const res = await LC.backendApi.crearSolicitudSoporte({ category, subject, description, reference });
      if (!res.ok) {
        toast("error", res.error.mensaje);
        return;
      }
      toast("success", "Solicitud enviada. Te vamos a responder a la brevedad.");
      renderCentroDeAyuda(main);
    });
  }

  async function renderDetalle(main, ticketId) {
    main.innerHTML = `<div class="page-wrap app-fade"><div class="skeleton-line h-64 w-full"></div></div>`;
    const res = await LC.backendApi.obtenerMiSolicitudSoporte(ticketId);
    if (!res.ok) {
      main.innerHTML = `<div class="page-wrap"><div class="empty-state"><p class="empty-state-title">Solicitud no encontrada</p><button id="soporte-volver" class="btn-secondary mt-4">← Volver</button></div></div>`;
      document.getElementById("soporte-volver").addEventListener("click", () => LC.router.navigate("/soporte"));
      return;
    }
    const s = res.data;
    main.innerHTML = `
      <div class="page-wrap app-fade max-w-2xl">
        <button id="soporte-volver" class="text-sm text-slate-500 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 mb-4 inline-flex items-center gap-1">← Volver a Ayuda y soporte</button>
        <div class="panel-card mb-5">
          <div class="flex flex-wrap items-start justify-between gap-4 mb-3">
            <h2 class="text-lg font-semibold">${escapeHtml(s.asunto)}</h2>
            <span class="reco-badge ${ESTADO_CLASE[s.estado] || ""}">${escapeHtml(ESTADO_LABEL[s.estado] || s.estado)}</span>
          </div>
          <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">Enviado el ${formatDate(new Date(s.creadoEn))}${s.referencia ? ` · Referencia: ${escapeHtml(s.referencia)}` : ""}</p>
          <p class="text-sm text-slate-700 dark:text-slate-200 whitespace-pre-wrap">${escapeHtml(s.descripcion)}</p>
        </div>
        ${s.respuestaAdmin ? `
        <div class="panel-card">
          <h3 class="panel-title mb-2">Respuesta de Nexo</h3>
          <p class="text-xs text-slate-400 mb-2">${formatDate(new Date(s.respuestaAdminEn))}</p>
          <p class="text-sm text-slate-700 dark:text-slate-200 whitespace-pre-wrap">${escapeHtml(s.respuestaAdmin)}</p>
        </div>
        ` : `<div class="panel-card text-sm text-slate-500 dark:text-slate-400">Todavía no hay respuesta — te vamos a avisar cuando la tengamos.</div>`}
      </div>
    `;
    document.getElementById("soporte-volver").addEventListener("click", () => LC.router.navigate("/soporte"));
  }

  LC.soporte = { render };
})();
