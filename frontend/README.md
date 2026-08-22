# Librería Central — Frontend (Fase 3, ahora en Demo Mode)

Panel web del proyecto: vanilla HTML + CSS + JavaScript (sin frameworks —
no había una razón que justificara React/Vue/Next). Usa Tailwind CSS vía
CDN solo para utilidades de estilo; toda la lógica es JavaScript plano,
repartida en módulos pequeños dentro de `js/`.

Vive fuera de `src/` (el prototipo React original, que no se toca) y de
`backend/` (el backend real en FastAPI) — es su propio proyecto estático,
sin build ni dependencias que instalar.

## Demo Mode (actualizado 22 de agosto de 2026)

Por pedido explícito del dueño, esta fase se enfoca solo en dejar la
interfaz completa, navegable y profesional — **sin conectar todavía
WooCommerce ni Mercado Libre real**, aunque el backend (`backend/`) ya
funciona contra la tienda real. El frontend hoy NO llama a ese backend:
todos los datos que ves (productos, stock, precios, ventas y pedidos de
Mercado Libre, suscripción, cuenta) son de ejemplo, generados en el
navegador por `js/demoData.js`.

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

## Arquitectura: dónde se conecta el backend real más adelante

Las pantallas (`js/app.js`) nunca leen `js/demoData.js` directamente — todas
piden datos a través de `js/dataSource.js`, que es la única puerta de
entrada. Cuando llegue el momento de conectar el backend real:

1. `js/dataSource.js` es el único archivo que hay que reescribir, para que
   sus funciones llamen a `js/backendApi.js` (el cliente HTTP real, ya
   construido y probado en la fase anterior contra `GET
   /api/productos/reporte`) en vez de a los datos de ejemplo.
2. Ninguna pantalla ni componente visual necesita cambios.

`js/backendApi.js` no se usa todavía, pero queda listo para ese momento.

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
    dataSource.js       Única puerta de datos para las pantallas — hoy lee
                       demoData.js; el día de mañana hablará con el
                       backend real sin que las pantallas cambien.
    backendApi.js       Cliente HTTP del backend real (FastAPI). Construido
                       y probado, pero NO se usa todavía (ver Demo Mode).
    auth.js             Sesión mock (login/registro/logout).
    app.js               Todas las pantallas: dashboard, productos, detalle
                       de producto, Mercado Libre, sincronización,
                       suscripción, configuración, y el shell (sidebar,
                       header, menú de usuario).
    router.js           Router de hash (#/dashboard, #/productos/:id, etc.),
                       protege las rutas según haya o no sesión.
  README.md
```

## Cómo correrlo

No necesita el backend corriendo — todo funciona con datos de ejemplo.

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

## Qué es Demo Mode y qué está preparado para el backend real

Ver el informe completo entregado junto con este frontend (sección "C" y
"D" del reporte final) para el detalle pantalla por pantalla. En resumen:
todo lo que hoy se ve (catálogo, cuenta, suscripción, sincronización) es de
ejemplo; lo que ya está preparado es la arquitectura (`dataSource.js` +
`backendApi.js`) y el endpoint real del backend (`/api/productos/reporte`,
que ya expone `productos: [...]` con los campos que la tabla necesita).
