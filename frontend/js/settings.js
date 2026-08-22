"use strict";

/**
 * Librería Central — preferencias locales (no son datos de negocio).
 *
 * Todo lo que vive acá es una preferencia de interfaz que no tiene nada de
 * sensible (umbral de stock bajo, plan demo seleccionado, notificaciones
 * activadas, tema). Se guarda en localStorage porque es exactamente el tipo
 * de dato para el que existe: nada de esto es una credencial ni información
 * de negocio real.
 */

window.LC = window.LC || {};

(function () {
  const DEFAULTS = {
    lowStockThreshold: 5,
    currentPlanId: "starter",
    notifStock: true,
    notifSync: true,
    notifImportant: true,
    companyName: "Librería Central",
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
