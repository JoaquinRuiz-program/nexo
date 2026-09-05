"use strict";

/**
 * Nexo — modo oscuro.
 *
 * Guarda la preferencia ("light" | "dark" | "auto") en localStorage y
 * aplica/quita la clase "dark" en <html>, que es lo que Tailwind (con
 * darkMode:"class") y css/styles.css usan para pintar ambos temas. Un
 * script mínimo en el <head> de index.html ya aplicó esta misma preferencia
 * antes de que se pinte la página, para evitar el parpadeo del tema
 * equivocado — este archivo es la versión completa, con los listeners.
 */

window.LC = window.LC || {};

(function () {
  const KEY = "lc_theme";

  function getPreference() {
    try {
      return window.localStorage.getItem(KEY) || "auto";
    } catch (_e) {
      return "auto";
    }
  }

  function setPreference(value) {
    try {
      window.localStorage.setItem(KEY, value);
    } catch (_e) {}
  }

  function systemPrefersDark() {
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  function isDarkEffective(pref) {
    pref = pref || getPreference();
    return pref === "dark" || (pref === "auto" && systemPrefersDark());
  }

  function apply(pref) {
    document.documentElement.classList.toggle("dark", isDarkEffective(pref));
  }

  function set(pref) {
    setPreference(pref);
    apply(pref);
    document.dispatchEvent(new CustomEvent("lc:theme-changed", { detail: { pref } }));
  }

  function toggleQuick() {
    // Toggle rápido del header: si estaba en "auto", pasa al opuesto del
    // efectivo actual; si estaba explícito, alterna light/dark.
    set(isDarkEffective() ? "light" : "dark");
  }

  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (getPreference() === "auto") apply("auto");
    });
  }

  LC.theme = { get: getPreference, set, isDark: () => isDarkEffective(), apply, toggleQuick };
})();
