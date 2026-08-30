"use strict";

/**
 * Nexo — preferencias locales (no son datos de negocio).
 *
 * Todo lo que vive acá es una preferencia de interfaz que no tiene nada de
 * sensible (umbral de stock bajo, plan demo seleccionado, notificaciones
 * activadas, tema). Se guarda en localStorage porque es exactamente el tipo
 * de dato para el que existe: nada de esto es una credencial ni información
 * de negocio real.
 *
 * 29 de agosto de 2026: el nombre de la EMPRESA se sacó de acá a propósito
 * — antes vivía un "companyName" local, editable a mano y completamente
 * desconectado del backend real (podía decir cualquier cosa, sin relación
 * con `Store.name`). Ahora la única fuente de verdad es la sesión real
 * (GET /api/auth/me -> empresa.nombre, ver js/auth.js) — no se vuelve a
 * agregar acá hasta que exista un endpoint real para editarla.
 */

window.LC = window.LC || {};

(function () {
  const DEFAULTS = {
    lowStockThreshold: 5,
    currentPlanId: "starter",
    notifStock: true,
    notifSync: true,
    notifImportant: true,
    storeName: "La Librería Online",
  };

  function readAll() {
    try {
      const raw = window.localStorage.getItem("lc_settings");
      return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : { ...DEFAULTS };
    } catch (_e) {
      return { ...DEFAULTS };
    }
  }

  function writeAll(obj) {
    try {
      window.localStorage.setItem("lc_settings", JSON.stringify(obj));
    } catch (_e) {}
  }

  function update(patch) {
    const current = readAll();
    const next = { ...current, ...patch };
    writeAll(next);
    return next;
  }

  LC.settings = {
    getAll: readAll,
    update,
    getLowStockThreshold: () => readAll().lowStockThreshold,
    setLowStockThreshold: (n) => update({ lowStockThreshold: n }),
    getCurrentPlanId: () => readAll().currentPlanId,
    setCurrentPlanId: (id) => update({ currentPlanId: id }),
  };
})();
