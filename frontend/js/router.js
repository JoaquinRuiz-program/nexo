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
      // 6 de septiembre de 2026 — mientras el admin está VIENDO una empresa
      // (session.modoSoporte, ver app/api/routes/admin.py) sí tiene una
      // empresa activa de verdad, así que las pantallas de cliente cargan
      // bien y no hay que sacarlo de ahí: justamente entró para verlas.
      const viendoEmpresa = !!(session && session.modoSoporte);
      if (session && session.esNexoAdmin && !viendoEmpresa && !RUTAS_ADMIN.includes(name)) {
        window.location.hash = "/admin";
        return;
      }
      // 15 de septiembre de 2026 (QA integral): un vendedor que escribía
      // #/admin veía el esqueleto del panel de administrador con "No
      // encontrado" (el backend ya respondía 404). Ahora vuelve a su Dashboard.
      if (session && !session.esNexoAdmin && RUTAS_ADMIN.includes(name)) {
        window.location.hash = "/dashboard";
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

  // 15 de septiembre de 2026 (QA fase 2): el contexto "ver como empresa" vive
  // en el servidor y lo comparten todas las pestañas del admin. Si otra pestaña
  // cambiaba de empresa, esta seguía mostrando el aviso de la anterior mientras
  // sus datos ya eran de la nueva. Para un admin se relee la sesión al navegar.
  async function alCambiarRuta() {
    const session = LC.auth.getSession();
    if (session && session.esNexoAdmin) await LC.auth.hydrate();
    handleRoute();
  }

  window.addEventListener("hashchange", alCambiarRuta);
  window.addEventListener("DOMContentLoaded", init);

  LC.router = { navigate, parseHash, handleRoute };
})();
