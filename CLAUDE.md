# Nexo — Guía para Claude Code

Nexo es un **SaaS B2B multiempresa** para automatizar catálogo y publicaciones en
Mercado Libre (Chile). Etapa: **Production Release Candidate**. No es una demo.

## Arquitectura (no reescribir, reutilizar)
- **Backend**: FastAPI + SQLAlchemy + Alembic. Rutas en `backend/app/api/routes/`,
  lógica pura (testeable, sin red/DB) en `backend/app/domain/`, adaptadores externos
  en `backend/app/adapters/` (Mercado Libre OAuth real).
- **Frontend**: HTML + JS vanilla, **sin build step**. Todo cuelga de `window.LC.*`
  (`frontend/js/`). Los `<script src="...?v=N">` de `index.html` se versionan a mano
  para bustear caché: **al cambiar un JS/CSS hay que subir su `?v=`**.
- **DB**: SQLite en dev (`backend/nexo.db`), Postgres en prod (`DATABASE_URL`).
  Modelos en `backend/app/db/models/`. Migraciones Alembic.
- **Multiempresa**: `Store` = empresa/tenant. `get_current_store` es el ÚNICO
  resolutor de tenant. Un acceso a datos de otra empresa devuelve **404, nunca 403**
  (IDOR). El admin de plataforma es `User.is_nexo_admin` (global, vía
  `require_nexo_admin`) — un admin de empresa jamás llega a `/api/admin/*`.

## Restricciones críticas (production RC)
- **No romper**: autenticación, aislamiento multiempresa, OAuth de Mercado Libre,
  publicaciones, ventas, rentabilidad, suscripciones, impersonación ("ver como
  empresa"), importador.
- **Solo datos reales**: nunca inventar números ni simular datos. Si no hay datos
  suficientes, mostrar `Sin datos suficientes` o `0`. **No introducir datos demo.**
  No usar nada de "Librería Central" (ya no existe).
- **Secretos**: nunca pedir ni exponer tokens/secrets/contraseñas en el chat ni en
  respuestas de API (ni `access_token`, `client_secret`, `password_hash`). El `.env`
  real tiene el Client Secret de ML y `TOKEN_ENCRYPTION_KEY`.
- **No commitear sin confirmación** del usuario. El usuario commitea/pushea él mismo.
- **Ritual de reset de DB**: si una prueba en vivo modifica `nexo.db`, restaurar el
  estado anterior al terminar.
- Auditar y reutilizar endpoints/modelos/servicios/componentes existentes antes de
  crear nuevos. No sobreingenierizar.

## Convenciones del proyecto
- Comisión de ML **exacta por producto** (categoría + precio + tipo de publicación),
  cacheada en `MercadoLibreCategoryFee`; nunca un % fijo asumido. `resolver_costos_ml`
  (rentabilidad.py) es la única fuente de verdad "comisión real vs. manual".
- Rentabilidad = **solo margen monetario**; el stock nunca decide si algo es rentable
  (se completa aparte, al revisar la publicación).
- Sin desarrollo local de ML: el callback OAuth necesita el túnel **ngrok**
  (`ngrok http 8000 --domain=tanned-gruffly-previous.ngrok-free.dev`) corriendo.
- Servidores dev: backend `uvicorn app.main:app` en :8000, frontend
  `python -m http.server 5500` (carpeta `frontend/`). Nunca dejar dos backends en :8000.

## Docs de referencia (leer antes de tocar el área)
`backend/DEPLOY.md`, `backend/DATABASE.md`, `backend/ADMIN_NEXO.md`,
`backend/DECISION_NEGOCIO.md`, `backend/PRECIO_RECOMENDADO.md`,
`backend/PUBLICACION_MERCADOLIBRE.md`. Estado y pendientes: `PROGRESS.md`, `TODO.md`.

---

# Reglas de trabajo — Ahorra Tokens

## 1. No programar sin contexto
- ANTES de escribir codigo: lee los archivos relevantes, revisa git log, entiende la arquitectura.
- Si no tienes contexto suficiente, pregunta. No asumas.

## 2. Respuestas cortas
- Responde en 1-3 oraciones. Sin preambulos, sin resumen final.
- No repitas lo que el usuario dijo. No expliques lo obvio.
- Codigo habla por si mismo: no narres cada linea que escribes.

## 3. No reescribir archivos completos
- Usa Edit (reemplazo parcial), NUNCA Write para archivos existentes salvo que el cambio sea >80% del archivo.
- Cambia solo lo necesario. No "limpies" codigo alrededor del cambio.

## 4. No releer archivos ya leidos
- Si ya leiste un archivo en esta conversacion, no lo vuelvas a leer salvo que haya cambiado.

## 5. Validar antes de declarar hecho
- Despues de un cambio: compila, corre tests, o verifica que funciona.
- Nunca digas "listo" sin evidencia de que funciona.

## 6. Cero charla aduladora
- No halagues al usuario. Ve directo al trabajo.

## 7. Soluciones simples
- Implementa lo minimo que resuelve el problema. Nada mas.
- No agregues abstracciones, helpers, tipos, validaciones, ni features que no se pidieron.

## 8. No pelear con el usuario
- Si el usuario dice "hazlo asi", hazlo asi. Si discrepas, menciona tu concern en 1 oracion y procede.

## 9. Leer solo lo necesario
- No leas archivos completos si solo necesitas una seccion. Usa offset y limit.

## 10. No narrar el plan antes de ejecutar
- El usuario ve tus tool calls. No necesita un preview en texto.

## 11. Paralelizar tool calls
- Si necesitas leer 3 archivos independientes, lee los 3 en un solo mensaje.

## 12. No duplicar codigo en la respuesta
- Si ya editaste un archivo, no copies el resultado en tu respuesta. El usuario lo ve en el diff.

## 13. No usar Agent cuando Grep/Read basta
- Agent duplica todo el contexto. Solo usalo para busquedas amplias o tareas complejas.
