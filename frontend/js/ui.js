"use strict";

/**
 * Librería Central — componentes de interfaz reutilizables: toasts, modales
 * y helpers de formato. No sabe nada de productos, cuentas ni suscripciones
 * — solo sabe mostrar cosas.
 */

window.LC = window.LC || {};

(function () {
  function escapeHtml(str) {
    return String(str ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---------------- Íconos ----------------
  // 29 de agosto de 2026 — set propio de íconos de línea (sin depender de
  // ningún CDN) para reemplazar los emojis de toda la interfaz: pedido
  // explícito del dueño para que se vea sobrio y corporativo, no como un
  // prototipo. "1em" en vez de un tamaño fijo — el ícono hereda el
  // font-size de donde se use (igual que un emoji dentro de texto).
  const ICON_PATHS = {
    dashboard: '<rect x="3" y="10" width="3" height="7" rx="0.5"/><rect x="8.5" y="6" width="3" height="11" rx="0.5"/><rect x="14" y="3" width="3" height="14" rx="0.5"/>',
    box: '<path d="M10 2.5 17 6.5v7L10 17.5 3 13.5v-7z"/><path d="M3 6.5 10 10.5l7-4"/><path d="M10 10.5v7"/>',
    upload: '<path d="M10 3v9"/><path d="M6.5 6.5 10 3l3.5 3.5"/><path d="M3.5 13v2a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5v-2"/>',
    cart: '<path d="M3 4h2l1.6 9.2a1.5 1.5 0 0 0 1.48 1.3h6.44a1.5 1.5 0 0 0 1.47-1.2L17.5 7H6"/><circle cx="8.5" cy="16.5" r="1" fill="currentColor" stroke="none"/><circle cx="14.5" cy="16.5" r="1" fill="currentColor" stroke="none"/>',
    sync: '<path d="M16 5.5A6.5 6.5 0 0 0 5 8"/><path d="M4 3v3.5h3.5"/><path d="M4 14.5A6.5 6.5 0 0 0 15 12"/><path d="M16 17v-3.5h-3.5"/>',
    card: '<rect x="2.5" y="5" width="15" height="10" rx="1.5"/><path d="M2.5 8.5h15"/>',
    settings: '<path d="M4 6h4.4M12.6 6H16"/><circle cx="10.5" cy="6" r="1.6" fill="currentColor" stroke="none"/><path d="M4 10.5h2M9 10.5H16"/><circle cx="6.5" cy="10.5" r="1.6" fill="currentColor" stroke="none"/><path d="M4 15h8.4M16 15h.01"/><circle cx="14" cy="15" r="1.6" fill="currentColor" stroke="none"/>',
    menu: '<path d="M3 5.5h14M3 10h14M3 14.5h14"/>',
    sun: '<circle cx="10" cy="10" r="3.2"/><path d="M10 2.5v2M10 15.5v2M17.5 10h-2M4.5 10h-2M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4M15.3 15.3l-1.4-1.4M6.1 6.1 4.7 4.7"/>',
    moon: '<path d="M15.5 12.9A6.5 6.5 0 0 1 7.1 4.5a6.5 6.5 0 1 0 8.4 8.4z" fill="currentColor" stroke="none"/>',
    eye: '<path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10Z"/><circle cx="10" cy="10" r="2.3"/>',
    eyeOff: '<path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10Z"/><circle cx="10" cy="10" r="2.3"/><path d="M4 4l12 12"/>',
    search: '<circle cx="8.5" cy="8.5" r="5.5"/><path d="M17 17l-4-4"/>',
    document: '<path d="M6 2.5h6l3 3v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1Z"/><path d="M12 2.5V6h3"/>',
    help: '<circle cx="10" cy="10" r="8"/><path d="M7.5 7.7a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.3"/><circle cx="10" cy="14" r="0.9" fill="currentColor" stroke="none"/>',
    alert: '<circle cx="10" cy="10" r="8"/><path d="M10 6v5"/><circle cx="10" cy="14" r="0.9" fill="currentColor" stroke="none"/>',
    checkCircle: '<circle cx="10" cy="10" r="8"/><path d="M6.5 10.3l2.3 2.3 4.7-5"/>',
    store: '<path d="M3 8.5 4 3.5h12l1 5"/><path d="M3 8.5v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7"/><path d="M7.5 16.5v-4a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v4"/>',
  };

  function icon(name, cls) {
    const body = ICON_PATHS[name] || "";
    const classAttr = cls ? ` class="${cls}"` : "";
    return `<svg width="1em" height="1em" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"${classAttr} aria-hidden="true">${body}</svg>`;
  }

  function formatCLP(_value) {
    // Por pedido explícito del dueño (22 de agosto de 2026): no mostrar
    // montos exactos en la demo para el cliente, ni siquiera de ejemplo —
    // todo lo que antes pasaba por acá (precios de producto, ventas de
    // Mercado Libre) ahora muestra este texto en vez de un número.
    return "Próximamente";
  }

  function formatDate(date) {
    if (!date) return "—";
    return new Intl.DateTimeFormat("es-CL", { day: "2-digit", month: "short", year: "numeric" }).format(date);
  }

  function initials(name) {
    return String(name || "")
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0].toUpperCase())
      .join("");
  }

  // ---------------- Toasts ----------------
  // Punto sólido de color en vez de un emoji — el color ya distingue el
  // tipo, y coincide con el borde/fondo del toast (mismo criterio en toda
  // la interfaz: ver ".dot" en css/styles.css).
  const TOAST_DOT_CLASS = { success: "dot--green", info: "dot--blue", warning: "dot--amber", error: "dot--red" };
  const TOAST_CLASSES = {
    success: "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
    info: "border-indigo-200 bg-indigo-50 text-indigo-800 dark:border-indigo-800 dark:bg-indigo-950 dark:text-indigo-200",
    warning: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200",
    error: "border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200",
  };

  function toast(type, message) {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const node = document.createElement("div");
    node.className = `toast-item flex items-start gap-2 border rounded-xl px-4 py-3 shadow-lg text-sm max-w-sm ${TOAST_CLASSES[type] || TOAST_CLASSES.info}`;
    node.innerHTML = `
      <span class="dot ${TOAST_DOT_CLASS[type] || TOAST_DOT_CLASS.info} mt-2"></span>
      <span class="flex-1">${escapeHtml(message)}</span>
      <button class="toast-close text-current opacity-60 hover:opacity-100 leading-none" aria-label="Cerrar">✕</button>
    `;
    node.querySelector(".toast-close").addEventListener("click", () => removeToast(node));
    container.appendChild(node);
    requestAnimationFrame(() => node.classList.add("toast-in"));
    node._timer = setTimeout(() => removeToast(node), 4200);
  }

  function removeToast(node) {
    if (!node || !node.parentNode) return;
    clearTimeout(node._timer);
    node.classList.add("toast-out");
    setTimeout(() => node.remove(), 180);
  }

  // ---------------- Modal ----------------
  function openModal({ title, body, primaryLabel = "Entendido", onPrimary, secondaryLabel, onSecondary }) {
    const root = document.getElementById("modal-root");
    if (!root) return;
    root.innerHTML = `
      <div class="modal-overlay fixed inset-0 bg-slate-900/50 dark:bg-slate-950/70 flex items-center justify-center z-[60] p-4">
        <div class="modal-card bg-white dark:bg-slate-800 rounded-2xl shadow-2xl max-w-md w-full p-6">
          <div class="flex items-start justify-between gap-4 mb-3">
            <h3 class="text-lg font-semibold text-slate-900 dark:text-slate-100">${escapeHtml(title)}</h3>
            <button class="modal-close text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 leading-none text-xl" aria-label="Cerrar">✕</button>
          </div>
          <div class="text-sm text-slate-600 dark:text-slate-300 leading-relaxed mb-6">${body}</div>
          <div class="flex justify-end gap-3">
            ${secondaryLabel ? `<button class="modal-secondary px-4 py-2 text-sm font-medium rounded-lg border border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 transition">${escapeHtml(secondaryLabel)}</button>` : ""}
            <button class="modal-primary px-4 py-2 text-sm font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white transition">${escapeHtml(primaryLabel)}</button>
          </div>
        </div>
      </div>
    `;
    const close = () => {
      root.innerHTML = "";
      document.removeEventListener("keydown", onKey);
    };
    const onKey = (e) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    root.querySelector(".modal-close").addEventListener("click", close);
    root.querySelector(".modal-overlay").addEventListener("click", (e) => {
      if (e.target.classList.contains("modal-overlay")) close();
    });
    root.querySelector(".modal-primary").addEventListener("click", () => {
      if (onPrimary) onPrimary();
      close();
    });
    const secBtn = root.querySelector(".modal-secondary");
    if (secBtn) {
      secBtn.addEventListener("click", () => {
        if (onSecondary) onSecondary();
        close();
      });
    }
  }

  function infoModal(title, message, opts) {
    openModal({ title, body: `<p>${escapeHtml(message)}</p>`, primaryLabel: "Entendido", ...(opts || {}) });
  }

  LC.ui = { toast, openModal, infoModal, escapeHtml, formatCLP, formatDate, initials, icon };
})();
