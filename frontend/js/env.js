"use strict";

/**
 * Nexo — configuración de entorno (30 de agosto de 2026).
 *
 * Frontend estático sin build (ver frontend/README.md) — no hay forma de
 * inyectar variables de entorno en tiempo de build como en un proyecto con
 * bundler. Este archivo es el punto ÚNICO que cambia entre desarrollo y
 * producción: reemplazalo (o editá el valor de abajo) al desplegar, nunca
 * toques js/backendApi.js para esto.
 *
 * Development (default): backend corriendo en localhost:8000.
 * Producción: cambiar API_BASE_URL a la URL real y pública del backend
 * (ej. "https://api.nexo.cl") — HTTPS, sin barra final.
 */

window.LC = window.LC || {};

window.LC.env = {
  API_BASE_URL: "http://localhost:8000",
};
