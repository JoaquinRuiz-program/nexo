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

  function formatCLP(value) {
    if (value === null || value === undefined || value === "") return "—";
    const n = typeof value === "number" ? value : parseFloat(value);
    if (Number.isNaN(n)) return "—";
    try {
      return new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);
    } catch (_e) {
      return `$${n}`;
    }
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
  const TOAST_ICONS = { success: "✅", info: "ℹ️", warning: "⚠️", error: "🔴" };
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
      <span class="text-base leading-none">${TOAST_ICONS[type] || TOAST_ICONS.info}</span>
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

  LC.ui = { toast, openModal, infoModal, escapeHtml, formatCLP, formatDate, initials };
})();
