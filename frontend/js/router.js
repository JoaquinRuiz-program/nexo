"use strict";

/**
 * Nexo — router de hash, sin dependencias.
 *
 * Rutas: #/login, #/signup, #/dashboard, #/productos, #/productos/:id,
 * #/oportunidades, #/importar, #/integraciones, #/mercadolibre,
 * #/automatizaciones (#/sincronizacion redirige ahí), #/suscripcion,
 * #/configuracion. Protege las rutas de la app (redirige a /login si no
 * hay sesión) y las de autenticación (redirige a /dashboard si ya hay
 * sesión).
 *
 * 29 de agosto de 2026 — sesión real: antes de la primera navegación hay
 * que preguntarle al backend si la cookie que mandó el navegador todavía
 * vale (LC.auth.hydrate(), una sola vez — ver js/auth.js). Navegaciones
 * siguientes (hashchange) usan el caché ya hidratado, síncrono.
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

  // 30 de agosto de 2026 — panel de administrador de Nexo: un admin de la
  // plataforma no tiene tienda propia (session.empresa es null) — nunca
  // debería caer en una pantalla de cliente (Dashboard, Productos, etc.),
  // que asume una empresa activa y le devolvería errores del backend.
  const RUTAS_ADMIN = ["admin"];

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
    if (loggedIn) {
      const session = LC.auth.getSession();
      if (session && session.esNexoAdmin && !RUTAS_ADMIN.includes(name)) {
        window.location.hash = "/admin";
        return;
      }
    }
    LC.app.render(name, param);
  }

  async function init() {
    await LC.auth.hydrate();
    handleRoute();
  }

  // Sesión vencida/revocada en medio de la navegación (un 401 real, ver
  // backendApi.js) — nunca pasa en la primera carga (eso es hydrate() de
  // arriba, no esto). Limpia el estado, avisa, y vuelve a /login sin dejar
  // la pantalla anterior a medio pintar.
  LC.backendApi.setUnauthorizedHandler(() => {
    LC.auth.clearCachedSession();
    LC.ui.toast("info", "Tu sesión expiró. Inicia sesión de nuevo.");
    navigate("/login");
  });

  window.addEventListener("hashchange", handleRoute);
  window.addEventListener("DOMContentLoaded", init);

  LC.router = { navigate, parseHash, handleRoute };
})();
