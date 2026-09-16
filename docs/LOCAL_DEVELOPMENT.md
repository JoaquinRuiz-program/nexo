# Cómo levantar Nexo en local (después de una pausa larga)

Guía única y actual para volver a abrir y probar Nexo. Si algo de acá no
coincide con lo que ves en pantalla, el código manda — esto describe el
proyecto real al 16 de septiembre de 2026, no un plan.

**Antes que nada — NO confundir con el prototipo legado**: la raíz del
repo también tiene `package.json`, `vite.config.ts`, `src/`, `public/`,
`index.html` (en la raíz, no en `frontend/`). **Eso NO es Nexo** — es el
prototipo React/Vite con el que arrancó el proyecto, que se dejó a
propósito con un `npm run build` que falla (ver el campo `"comentario"`
de ese `package.json`). El frontend real de Nexo vive en `frontend/` y no
tiene build step. Ver `docs/ARCHITECTURE.md` sección "Ojo con la raíz".

## 1. Requisitos previos

- **Python** — el entorno de desarrollo usa 3.14.3 (mismo que producción,
  ver `render.yaml`); no hay un mínimo estricto fijado en el repo.
- **Nada de Node/npm** hace falta para el frontend real (`frontend/`) — es
  HTML/CSS/JS plano, sin build. Node solo haría falta para tocar el
  prototipo legado de la raíz, que no es parte de Nexo.
- SQLite viene con Python (no hay que instalar nada aparte) para la base
  local. Postgres solo hace falta para producción.

## 2. Instalar dependencias desde cero

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows (Git Bash: source .venv/Scripts/activate)
pip install -r requirements.txt
```

El frontend no tiene dependencias que instalar.

## 3. Variables de entorno (sin valores reales)

```bash
cd backend
copy .env.example .env        # Windows; en bash: cp .env.example .env
```

`backend/.env.example` ya trae, comentario por comentario, qué es cada
variable y de dónde sale (Mercado Libre, Google Sheets, Mercado Pago,
cifrado de tokens, cookie de sesión, CORS, subida de imágenes) — es la
referencia completa, no se duplica acá. Para **levantar Nexo localmente
sin ninguna integración externa** (catálogo, rentabilidad, publicaciones
"en borrador", multiempresa, admin) no hace falta completar nada de eso:
el único valor que conviene generar es

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

y pegarlo en `TOKEN_ENCRYPTION_KEY` del `.env` (se puede dejar vacío para
arrancar, pero cualquier flujo que toque tokens cifrados de Mercado
Libre/Google lo va a pedir). Sin `DATABASE_URL` definida, usa
`sqlite:///./nexo.db` (archivo local, gitignored) — no hace falta
Postgres para desarrollar.

Mercado Libre real en local necesita además un túnel HTTPS (ver
`CLAUDE.md` — ngrok) porque Mercado Libre exige HTTPS en la Redirect URI
incluso en desarrollo; sin eso, todo lo demás funciona igual.

## 4. Inicializar la base de datos local

```bash
cd backend
alembic upgrade head           # crea backend/nexo.db con todas las tablas
python -m app.db.seed_demo     # opcional: catálogo + usuario de prueba
                                #   (ver DEMO_USER_EMAIL y la contraseña
                                #   en app/db/seed_demo.py — son datos de
                                #   prueba, no una cuenta real)
```

Para volver a empezar de cero: borrar `backend/nexo.db` y repetir estos
dos comandos.

## 5. Ejecutar el backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Puerto **8000**. `GET http://localhost:8000/api/health` debe responder
`{"status":"ok"}`.

## 6. Ejecutar el frontend REAL de Nexo

```bash
cd frontend
python -m http.server 5500
```

(si `python` no existe en el sistema, probar `python3`). Puerto **5500**.
**Nunca** abrir `frontend/index.html` con doble clic — tiene que ser
servido por HTTP.

## 7. URL a abrir en el navegador

```
http://localhost:5500
```

Ahí vive el login/registro real (cookie de sesión, backend en
`app/api/routes/auth.py`) — crear una cuenta nueva o usar la que haya
sembrado `seed_demo.py`.

## 8. Puertos

| Servicio | Puerto | URL |
|---|---|---|
| Backend (FastAPI) | 8000 | `http://localhost:8000` |
| Frontend (Nexo real) | 5500 | `http://localhost:5500` |

`app/main.py` ya trae CORS habilitado exactamente para
`http://localhost:5500` y `http://127.0.0.1:5500` en desarrollo — no hace
falta tocar nada para que backend y frontend se hablen.

## 9. Correr los dos a la vez

Backend y frontend son dos procesos independientes — necesitan **dos
terminales abiertas en paralelo** (o dos pestañas de terminal):

- Terminal 1: pasos de la sección 5 (backend, puerto 8000).
- Terminal 2: pasos de la sección 6 (frontend, puerto 5500), desde la
  carpeta `frontend/`, no desde la raíz.

El frontend funciona igual sin el backend corriendo (cae solo a "Modo
demostración", con un indicador visible en pantalla — nunca mezcla datos
reales con datos de ejemplo), pero para ver datos reales (catálogo,
rentabilidad, importación, Mercado Libre) el backend tiene que estar
arriba antes de cargar la página.

## 10. Detener los servicios

`Ctrl+C` en cada una de las dos terminales. Ninguno de los dos deja un
proceso en segundo plano ni un daemon — cerrar la terminal alcanza.

## 11. Verificar rápido que Nexo funciona

1. `http://localhost:8000/api/health` → `{"status":"ok"}`.
2. `http://localhost:5500` → pantalla de login, sin el indicador "Modo
   demostración" en el header (si aparece, el backend no está respondiendo).
3. Iniciar sesión (con una cuenta creada, o la de `seed_demo.py`) → el
   Dashboard debe cargar sin quedarse en "Cargando…".

## 12. Ejecutar los tests

```bash
cd backend
.venv\Scripts\python.exe -m pytest -q
```

No necesita ninguna credencial real (Mercado Libre/Google/Mercado Pago
están mockeadas con `respx` donde hace falta) ni el servidor corriendo —
usa una base SQLite en memoria por prueba. Estado al 16 sept 2026:
**979/979 pasan**. Para una sola área, apuntar al archivo, ej.:

```bash
.venv\Scripts\python.exe -m pytest -q tests/test_rentabilidad.py
```

Ver `docs/ARCHITECTURE.md` sección 10 para qué archivo de test conviene
correr antes de tocar cada área del sistema.
