"use strict";

/**
 * Librería Central — sesión (Demo Mode).
 *
 * No existe todavía un backend de autenticación real, así que esto es un
 * mock local: cualquier email + contraseña no vacía "inicia sesión". La
 * contraseña NUNCA se guarda en ningún lado, ni siquiera acá — se recibe
 * como argumento y se descarta apenas se valida que no esté vacía. Lo único
 * que se guarda es la sesión visible (nombre, email), para que la interfaz
 * sepa que "hay alguien conectado". Cuando exista un backend de
 * autenticación real, este es el único archivo que habrá que reescribir.
 */

window.LC = window.LC || {};

(function () {
  const SESSION_KEY = "lc_session";

  function readSession() {
    try {
      const raw = window.localStorage.getItem(SESSION_KEY) || window.sessionStorage.getItem(SESSION_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_e) {
      return null;
    }
  }

  function writeSession(session, remember) {
    try {
      const raw = JSON.stringify(session);
      if (remember) {
        window.localStorage.setItem(SESSION_KEY, raw);
        window.sessionStorage.removeItem(SESSION_KEY);
      } else {
        window.sessionStorage.setItem(SESSION_KEY, raw);
        window.localStorage.removeItem(SESSION_KEY);
      }
    } catch (_e) {}
  }

  function clearSession() {
    try {
      window.localStorage.removeItem(SESSION_KEY);
      window.sessionStorage.removeItem(SESSION_KEY);
    } catch (_e) {}
  }

  function isLoggedIn() {
    return !!readSession();
  }

  function login(email, remember) {
    const session = { nombre: LC.demoData.account.nombre, email: email || LC.demoData.account.email };
    writeSession(session, remember);
    return session;
  }

  function signup(nombre, email) {
    const session = { nombre: nombre || LC.demoData.account.nombre, email };
    writeSession(session, true);
    return session;
  }

  function logout() {
    clearSession();
  }

  LC.auth = { isLoggedIn, login, signup, logout, getSession: readSession };
})();
