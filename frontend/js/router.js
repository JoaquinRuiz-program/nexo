"use strict";

/**
 * Librería Central — router de hash, sin dependencias.
 *
 * Rutas: #/login, #/signup, #/dashboard, #/productos, #/productos/:id,
 * #/mercadolibre, #/sincronizacion, #/suscripcion, #/configuracion.
 * Protege las rutas de la app (redirige a /login si no hay sesión) y las
 * de autenticación (redirige a /dashboard si ya hay sesión).
 */

window.LC = window.LC || {};

(function () {
  const PUBLIC_ROUTES = ["login", "signup"];

  function parseHash() {
    const hash = window.location.hash.replace(/^#\/?/, "");
    const parts = hash.split("/").filter(Boolean);
    return { name: parts[0] || "dashboard", param: parts[1] || null };
  }

  function navigate(path) {
    if (window.location.hash === `#${path}`) {
      handleRoute();
    } else {
      window.location.hash = path;
    }
  }

  function handleRoute() {
    const { name, param } = parseHash();
    const loggedIn = LC.auth.isLoggedIn();

    if (!loggedIn && !PUBLIC_ROUTES.includes(name)) {
      window.location.hash = "/login";
      return;
    }
    if (loggedIn && PUBLIC_ROUTES.includes(name)) {
      window.location.hash = "/dashboard";
      return;
    }
    LC.app.render(name, param);
  }

  window.addEventListener("hashchange", handleRoute);
  window.addEventListener("DOMContentLoaded", handleRoute);

  LC.router = { navigate, parseHash, handleRoute };
})();
