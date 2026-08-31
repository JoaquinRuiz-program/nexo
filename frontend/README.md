# Librería Central — Frontend (Fase 3, ahora en Demo Mode)

Panel web del proyecto: vanilla HTML + CSS + JavaScript (sin frameworks —
no había una razón que justificara React/Vue/Next). Usa Tailwind CSS vía
CDN solo para utilidades de estilo; toda la lógica es JavaScript plano,
repartida en módulos pequeños dentro de `js/`.

Vive fuera de `src/` (el prototipo React original, que no se toca) y de
`backend/` (el backend real en FastAPI) — es su propio proyecto estático,
sin build ni dependencias que instalar.

## Demo Mode + backend real (actualizado 29 de agosto de 2026)

Dashboard, Productos, detalle de producto e Importar catálogo ya hablan con
el backend real (`backend/`, `http://localhost:8000`) cuando está
corriendo — `js/dataSource.js` chequea `GET /api/health` una vez por carga
de página y usa datos reales si responde. **Si el backend no está
corriendo, cada pantalla cae sola a Demo Mode**, sin romperse y sin mezclar
nunca datos reales con datos de ejemplo en la misma vista — un indicador
visible (pill verde "real" o amarillo "demo", según la pantalla) dice
siempre cuál de los dos estás viendo.

Mercado Libre (ventas/pedidos/gráfico) y Sincronización siguen en Demo Mode
siempre, incluso con el backend corriendo — no hay agregación de ventas por
fecha ni motor de sincronización real todavía (ver "Qué falta" más abajo).

El catálogo demo tiene 58 productos base (75 filas contando variantes de
color) con nombres reales de librería — no "Producto modelo N". También
incluye 149 pedidos de ejemplo de Mercado Libre repartidos en los últimos
45 días, cada uno apuntando a un SKU real del catálogo, para que el
Dashboard y la sección de Mercado Libre (ventas del mes, gráfico, productos
más vendidos, pedidos) se calculen de verdad a partir de esos datos — nunca
un número escrito a mano en el HTML.

Esto se ve marcado en toda la interfaz con un indicador "● Modo
demostración" (en el header, y en cada lugar donde se muestra una
integración no conectada), para que nunca parezca que algo está conectado
cuando no lo está.

**Cuenta / inicio de sesión:** también es una demostración. Cualquier email
y contraseña permiten entrar (`js/auth.js`) — no hay backend de
autenticación real todavía. La contraseña nunca se guarda en ningún lado.

## Arquitectura: cómo se decide real vs. demo

Las pantallas (`js/app.js`) nunca leen `js/demoData.js` ni llaman a
`fetch()` directamente — todas piden datos a través de `js/dataSource.js`,
la única puerta de entrada. `js/dataSource.js` es también el único archivo
que decide el modo (`getModo()`, con `LC.backendApi.checkHealth()`) y hacia
dónde caer si el backend no responde — ninguna pantalla necesita saber de
dónde vino el dato.

`js/importFlow.js` (la pantalla "Importar catálogo") sigue el mismo patrón
por su cuenta: chequea el backend al entrar y usa
`js/demoImportResult.js` (una fotografía estática de una respuesta real,
no lógica reimplementada) si no está disponible.

## Estructura

```
frontend/
  index.html          Estructura de la página: pantallas de login/registro
                       + la app (sidebar, header, contenedor de secciones)
  css/styles.css       Estilos propios (tarjetas, tabla, modales, toasts,
                       tema oscuro, estados vacíos, responsive)
  js/
    ui.js              Toasts, modales y helpers de formato — no sabe nada
                       de productos ni de negocio.
    theme.js           Modo oscuro (claro/oscuro/automático), persistido.
    settings.js        Preferencias locales (umbral de stock bajo, plan
                       demo elegido, notificaciones, datos de "Configuración
                       > General"). No son datos sensibles.
    chart.js            Gráfico de barras sobre &lt;canvas&gt;, sin librería
                       externa — lo usa la sección de Mercado Libre.
    demoData.js        Catálogo (58 productos, nombres reales de librería),
                       planes, cuenta y 149 pedidos de ejemplo de Mercado
                       Libre (cada uno referencia un SKU real del catálogo).
    dataSource.js       Única puerta de datos para las pantallas — decide
                       real vs. demo (getModo()) y cae a demoData.js sola
                       si el backend no responde.
    backendApi.js       Cliente HTTP del backend real (FastAPI) — usado por
                       dataSource.js e importFlow.js.
    demoImportResult.js  Fotografía estática de una respuesta real del
                       asistente de importación, para su Demo Mode propio.
    importFlow.js        Pantalla "Importar catálogo": asistente de 6 pasos
                       (subir → mapeo → confirmar → oportunidades →
                       publicaciones → listo), conectado al backend real.
    mercadolibrePublicar.js  Pantalla "Publicar en Mercado Libre" por
                       producto (30 de agosto de 2026, FASE 6): decisión
                       ¿conviene? → preparar → revisar (preview) →
                       publicar. Ruta `#/publicaciones/:id`. Solo lectura
                       hasta el último paso — el preview nunca publica;
                       publicar de verdad exige checkbox + modal explícitos.
    adminPanel.js         Panel del administrador de Nexo (dueño de la
                       plataforma, no un cliente) — 30 de agosto de 2026.
                       Rutas `#/admin` (lista de clientes) y
                       `#/admin/:storeId` (detalle + suspender/reactivar).
                       Solo visible con `session.esNexoAdmin` — ver
                       backend/ADMIN_NEXO.md.
    auth.js             Sesión real (login/registro/logout, cookie HttpOnly
                       — ver app/api/deps.py del backend).
    app.js               Todas las pantallas: dashboard, productos, detalle
                       de producto, Mercado Libre, sincronización,
                       suscripción, configuración, y el shell (sidebar,
                       header, menú de usuario).
    router.js           Router de hash (#/dashboard, #/productos/:id,
                       #/importar, etc.), protege las rutas según haya o no
                       sesión.
  README.md
```

## Cómo correrlo

No necesita el backend corriendo — todo funciona con datos de ejemplo. Si
querés ver datos reales (Dashboard, Productos, Importar catálogo), levantá
también `backend/` (ver `backend/README.md`) antes de abrir el navegador —
el frontend lo detecta solo, no hace falta configurar nada acá.

**1. Sirve el frontend con un servidor local** (no lo abras con doble clic
— algunas cosas, como el guardado de preferencias, funcionan mejor servidas
por `http://` que abiertas como archivo local):

```bash
cd frontend
python -m http.server 5500
```

Si el comando `python` no existe en tu sistema, prueba `python3 -m http.server 5500`.

**2. Abre en el navegador:**

```
http://localhost:5500
```

**3. Inicia sesión** con cualquier email y cualquier contraseña (por
ejemplo, `dueno@lalibreria.cl` / `demo1234`) — es una demostración, no hay
verificación real todavía.

Vas a ver el panel completo: Dashboard, Productos (con más de 50 productos
de ejemplo, incluyendo variantes de color), Mercado Libre, Sincronización,
Suscripción y Configuración — todo navegable, con modo oscuro, y con el
indicador "Modo demostración" visible en todo momento.

## Ajustes

- **Umbral de stock bajo**, **plan de suscripción demo**, **preferencias de
  notificación** y **nombre de empresa/tienda**: se ajustan en
  "Configuración" y se recuerdan en tu navegador entre visitas
  (`js/settings.js` — son preferencias de interfaz, no datos de negocio).
- **Tema** (claro/oscuro/automático): se ajusta en Configuración → Apariencia,
  o con el botón de sol/luna en el header. También se recuerda.

## Qué es real hoy y qué sigue en Demo Mode

**Real cuando el backend está corriendo:** Dashboard (stock, alertas,
rentabilidad, ventas importadas, estado de Mercado Libre), Productos y
detalle de producto, Importar catálogo (el asistente completo, incluida
la preparación de publicaciones en lote — sigue siendo un borrador, nunca
publica de verdad en Mercado Libre), cuenta/login (sesión real por cookie),
y el flujo completo "Publicar en Mercado Libre" por producto
(`#/publicaciones/:id` — decisión, competencia, precio recomendado,
preparación, y la publicación real en sí, protegida por doble
confirmación explícita).

**Siempre en Demo Mode todavía, con o sin backend corriendo:** suscripción,
la sección de ventas/pedidos/gráfico de Mercado Libre (no hay agregación
por fecha en el backend todavía) y sincronización (no hay motor real).
