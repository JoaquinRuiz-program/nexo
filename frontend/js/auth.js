"use strict";

/**
 * Nexo — sesión real (29 de agosto de 2026).
 *
 * Reemplaza el mock anterior (cualquier email/contraseña entraba,
 * localStorage/sessionStorage) por el backend real
 * (app/api/routes/auth.py). La sesión vive SOLO en la cookie HttpOnly que
 * pone el backend — este archivo nunca la lee, nunca la escribe, nunca la
 * guarda en localStorage/sessionStorage. Lo único que se cachea acá es una
 * copia EN MEMORIA (una variable de módulo, se pierde al recargar la
 * página a propósito) de los datos no sensibles que ya devolvió el backend
 * (nombre, email, empresa) — para que isLoggedIn()/getSession() puedan ser
 * síncronos en el resto de la app sin volver a pedir /me en cada chequeo.
 *
 * Por eso hace falta hidratar ese caché UNA vez al cargar la página, antes
 * del primer render — ver hydrate() y su uso en js/router.js.
 */

window.LC = window.LC || {};

(function () {
  let cachedSession = null; // null = no hay sesión (o todavía no se hidrató)
  let hydrated = false;

  function sesionDesdeRespuesta(data) {
    // Misma forma que _sesion_publica() en app/api/routes/auth.py —
    // aplanada acá para que el resto de la app siga leyendo
    // session.nombre/session.email como ya hacía con el mock anterior.
    return {
      nombre: data.usuario.nombre,
      email: data.usuario.email,
      empresa: data.empresa, // {id, nombre} — el nombre REAL, nunca de LC.settings
    };
  }

  // Se llama UNA vez al cargar la página (ver js/router.js) — pregunta al
  // backend "¿hay una sesión válida en la cookie que mandó el navegador?".
  // Un 401 acá es el caso normal de "todavía nadie inició sesión", nunca
  // un error (por eso backendApi.js lo excluye del interceptor global).
  async function hydrate() {
    const res = await LC.backendApi.me();
    cachedSession = res.ok ? sesionDesdeRespuesta(res.data) : null;
    hydrated = true;
    if (res.ok) LC.backendApi.resetUnauthorizedGuard();
    return cachedSession;
  }

  function isLoggedIn() {
    return !!cachedSession;
  }

  function getSession() {
    return cachedSession;
  }

  async function login(email, password, rememberMe) {
    const res = await LC.backendApi.login(email, password, rememberMe);
    if (!res.ok) return { ok: false, mensaje: res.error.mensaje };
    cachedSession = sesionDesdeRespuesta(res.data);
    LC.backendApi.resetUnauthorizedGuard();
    return { ok: true };
  }

  async function signup(fullName, email, password, companyName, rememberMe) {
    const res = await LC.backendApi.registro(email, password, fullName, companyName, rememberMe);
    if (!res.ok) return { ok: false, mensaje: res.error.mensaje };
    cachedSession = sesionDesdeRespuesta(res.data);
    LC.backendApi.resetUnauthorizedGuard();
    return { ok: true };
  }

  async function logout() {
    // Se limpia el caché local SIEMPRE, aunque la request de red falle —
    // quien decidió cerrar sesión en este dispositivo no debería quedar
    // "atrapado" adentro por un problema de conexión.
    try {
      await LC.backendApi.logout();
    } finally {
      cachedSession = null;
    }
  }

  // Lo usa el interceptor de 401 de backendApi.js (sesión vencida/revocada
  // en medio de la navegación) — nunca se llama desde login/hydrate.
  function clearCachedSession() {
    cachedSession = null;
  }

  LC.auth = {
    hydrate,
    isLoggedIn,
    getSession,
    login,
    signup,
    logout,
    clearCachedSession,
    isHydrated: () => hydrated,
  };
})();
