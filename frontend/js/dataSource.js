"use strict";

/**
 * Librería Central — capa de datos.
 *
 * Esta es la ÚNICA puerta por la que las pantallas (js/app.js) piden datos.
 * Ningún componente visual llama a fetch() ni a js/demoData.js directo.
 *
 * 29 de agosto de 2026 — dashboard/productos ya hablan con el backend real
 * cuando está disponible: `getModo()` resuelve "real"/"demo" una sola vez
 * por carga de página con LC.backendApi.checkHealth(), y cada función de
 * acá cae a Demo Mode sola si el backend no responde. Nunca se mezclan
 * datos reales con datos de ejemplo en la misma pantalla — app.js usa
 * `getModo()` para decidir qué aviso mostrar.
 *
 * getSincronizacion() y las funciones de ventas/pedidos de Mercado Libre
 * (getResumenMercadoLibre y el resto) siguen en Demo Mode: no hay motor de
 * sincronización real todavía, y el agregado de ventas por rango de fechas
 * no tiene endpoint propio (solo el conteo que ya expone
 * /api/dashboard/resumen) — quedan para una próxima etapa, no esta.
 *
 * ---------------------------------------------------------------------
 * Endpoints reales usados hoy (ver backend/app/api/routes/):
 *   getDashboardResumen()   -> GET /api/dashboard/resumen
 *   getEstadoSistema()      -> GET /api/mercadolibre/estado (WooCommerce
 *                              sigue sin ser prioridad — nunca se inventa
 *                              un "conectado" para eso)
 *   getProductos()          -> GET /api/productos
 *   getProductoDetalle(id)  -> GET /api/productos/:id (+ getProductos()
 *                              para armar la lista de variantes hermanas,
 *                              mismo criterio que expand_variable_products
 *                              en el backend)
 * ---------------------------------------------------------------------
 *
 * 22 de agosto de 2026 — se agregaron 5 funciones más para las ventas y
 * pedidos de Mercado Libre (getResumenMercadoLibre, getGraficoVentasMercadoLibre,
 * getProductosMasVendidosMercadoLibre, getPedidosMercadoLibre,
 * getProductosVendidosEnMercadoLibre). Hoy leen y CALCULAN todo a partir de
 * LC.demoData.pedidosML (datos de ejemplo). El día de mañana, cada una se
 * reemplaza por una consulta a la tabla `orders`/`order_items` ya diseñada
 * en la base de datos (ver backend/DATABASE.md) — el cálculo (sumas,
 * agrupaciones, filtros) se puede seguir haciendo acá o moverlo al backend;
 * lo importante es que las pantallas de Mercado Libre y el Dashboard siguen
 * llamando exactamente a estas mismas funciones, sin cambios.
 */

window.LC = window.LC || {};

(function () {
  // Resuelto una sola vez por carga de página (no en cada llamada) — así
  // todas las pantallas de una misma sesión ven el mismo modo, sin
  // parpadeos entre real/demo si el backend tarda en responder.
  let modoResuelto = null;

  async function getModo() {
    if (modoResuelto === null) {
      modoResuelto = (await LC.backendApi.checkHealth()) ? "real" : "demo";
    }
    return modoResuelto;
  }

  function demoDashboardResumen() {
    const rows = LC.demoData.catalogRows;
    const total = rows.length;
    const conStock = rows.filter((r) => r.estadoStock === "instock").length;
    const sinStock = total - conStock;
    const umbral = LC.settings.getLowStockThreshold();
    const filasBajoStock = rows.filter((r) => r.gestionaStock && r.stockQuantity !== null && r.stockQuantity > 0 && r.stockQuantity <= umbral);
    const filasSinStock = rows.filter((r) => r.gestionaStock && r.stockQuantity === 0);
    return {
      total,
      conStock,
      sinStock,
      stockBajo: filasBajoStock.length,
      ultimaActualizacion: new Date(),
      // Para que el Dashboard pueda mostrar NOMBRES concretos (no solo un
      // número) cuando hay problemas de stock — las primeras 5 de cada tipo.
      alertasStockBajo: filasBajoStock.slice(0, 5),
      alertasSinStock: filasSinStock.slice(0, 5),
      rentabilidad: null,
      ventas: null,
      mercadoLibre: null,
    };
  }

  // El backend devuelve todo agrupado (catalogo/rentabilidad/ventas/
  // mercadoLibre) — acá se aplana solo lo que las pantallas de stock ya
  // esperaban (mismos nombres que la versión demo de arriba), y se agregan
  // las secciones nuevas sin nombre en conflicto para que app.js las use
  // cuando el modo sea "real".
  function adaptarDashboardResumen(data) {
    return {
      total: data.catalogo.total,
      conStock: data.catalogo.conStock,
      sinStock: data.catalogo.sinStock,
      stockBajo: data.catalogo.stockBajo,
      ultimaActualizacion: new Date(data.ultimaActualizacion),
      alertasStockBajo: data.catalogo.alertasStockBajo,
      alertasSinStock: data.catalogo.alertasSinStock,
      rentabilidad: data.rentabilidad,
      ventas: data.ventas,
      mercadoLibre: data.mercadoLibre,
    };
  }

  async function getDashboardResumen() {
    if ((await getModo()) === "real") {
      const res = await LC.backendApi.fetchDashboardResumen();
      if (res.ok) return adaptarDashboardResumen(res.data);
      // El backend estaba arriba en el healthcheck pero esta consulta
      // puntual falló (se cayó justo ahora, timeout, etc.) — no se rompe
      // la pantalla, se cae a Demo Mode para esta carga.
    }
    return demoDashboardResumen();
  }

  async function getEstadoSistema() {
    const base = { woocommerce: { estado: "no_conectado", detalle: "Pendiente de configuración" } };
    if ((await getModo()) === "real") {
      const res = await LC.backendApi.fetchMercadoLibreEstado();
      if (res.ok) {
        const ml = res.data;
        return {
          ...base,
          mercadoLibre: ml.conectado
            ? { estado: "conectado", detalle: `Cuenta ${ml.cuentaExternaId}` }
            : { estado: "no_conectado", detalle: ml.credencialesConfiguradas ? "Credenciales configuradas — falta autorizar la cuenta" : "Pendiente de configuración" },
          baseDeDatos: { estado: "conectada", detalle: "Backend real conectado" },
        };
      }
    }
    return {
      ...base,
      mercadoLibre: { estado: "no_conectado", detalle: "Pendiente de configuración" },
      baseDeDatos: { estado: "demo", detalle: "Demo / Sin conexión" },
    };
  }

  async function getProductos() {
    if ((await getModo()) === "real") {
      const res = await LC.backendApi.fetchProductos();
      if (res.ok) return res.data;
    }
    return LC.demoData.catalogRows;
  }

  async function getProductoDetalle(id) {
    if ((await getModo()) === "real") {
      const res = await LC.backendApi.fetchProductoDetalle(id);
      if (!res.ok) return null;
      const row = res.data;
      // Variantes hermanas (mismo producto padre, un color cada una) — se
      // arman filtrando la lista completa, igual que hace demoData con
      // catalogRaw; el backend no necesita un endpoint aparte para esto.
      let variantes = [];
      if (row.esVariante) {
        const todas = await getProductos();
        variantes = todas
          .filter((r) => r.parentId === row.parentId)
          .map((r) => ({ color: r.colorVariante, sku: r.sku, stockQuantity: r.stockQuantity }));
      }
      // El backend todavía no tiene un feed de historial real (StockMovement
      // sin endpoint propio) ni fecha de creación por variante — se muestra
      // vacío en vez de inventar eventos, la pantalla ya soporta un
      // historial vacío sin romperse.

      // Rentabilidad/clasificación del producto — se reusa /api/seleccion
      // (misma fuente que la pantalla Oportunidades) en vez de pedir un
      // endpoint nuevo solo para el detalle.
      const oportunidades = await getOportunidades();
      const fila = (oportunidades.productos || []).find((p) => p.id === row.id) || null;

      return { row, variantes, historial: [], creado: null, rentabilidad: fila };
    }

    const numId = Number(id);
    const row = LC.demoData.catalogRows.find((r) => r.id === numId);
    if (!row) return null;
    const raw = LC.demoData.getProductoRaw(numId);
    const variantes = raw && raw.tipo === "variable" ? raw.variantes : [];
    const historial = LC.demoData.getHistorial(row);
    return { row, variantes, historial, creado: raw ? raw.creado : null, rentabilidad: null };
  }

  // ------------------------------------------------------------------
  // Oportunidades — qué conviene vender/revisar. Reusa GET /api/seleccion
  // (ya construido y probado para el asistente de importación) en vez de
  // pedir un endpoint nuevo — misma fuente de verdad en ambos lugares.
  // ------------------------------------------------------------------

  async function getOportunidades() {
    if ((await getModo()) === "real") {
      const res = await LC.backendApi.obtenerSeleccion({ canal: "tienda", requiereStock: false });
      if (res.ok) return res.data;
    }
    return LC.demoImportResult.seleccion;
  }

  // ------------------------------------------------------------------
  // Integraciones — con qué sistemas puede conectarse la empresa. Mercado
  // Libre usa su estado real (GET /api/mercadolibre/estado); las demás
  // todavía no tienen conexión real, así que se muestran honestamente como
  // "no conectado" o "próximamente" — nunca inventado.
  // ------------------------------------------------------------------

  async function getIntegraciones() {
    const modo = await getModo();
    let ml = { estado: "no_conectado", detalle: "Pendiente de configuración" };
    if (modo === "real") {
      const res = await LC.backendApi.fetchMercadoLibreEstado();
      if (res.ok) {
        ml = res.data.conectado
          ? { estado: "conectado", detalle: `Tu cuenta está conectada correctamente${res.data.nickname ? ` (${res.data.nickname})` : ""}.` }
          : {
              estado: "no_conectado",
              detalle: res.data.credencialesConfiguradas
                ? "Conecta tu cuenta para comenzar."
                : "Conecta tu cuenta para comenzar — falta configurar las credenciales en el servidor.",
            };
      }
    }
    return {
      modo,
      integraciones: [
        { id: "mercadolibre", nombre: "Mercado Libre", categoria: "Canal de venta", ...ml, ruta: "/mercadolibre" },
        { id: "woocommerce", nombre: "WooCommerce", categoria: "Canal de venta", estado: "no_conectado", detalle: "Pendiente de configuración", ruta: null },
        { id: "excel", nombre: "Excel / CSV", categoria: "Importación de catálogo", estado: "disponible", detalle: "Siempre disponible — sube un archivo cuando quieras", ruta: "/importar" },
        { id: "shopify", nombre: "Shopify", categoria: "Canal de venta", estado: "proximamente", detalle: "Todavía no disponible", ruta: null },
        { id: "sheets", nombre: "Google Sheets", categoria: "Importación de catálogo", estado: "proximamente", detalle: "Todavía no disponible", ruta: null },
      ],
    };
  }

  // ------------------------------------------------------------------
  // Mercado Libre — ventas/pedidos de demostración (js/demoData.js,
  // LC.demoData.pedidosML). Ningún pedido de acá es real: no hay conexión
  // con Mercado Libre todavía (ver getEstadoSistema, que sigue devolviendo
  // "no_conectado"). Estas funciones solo CALCULAN totales a partir de los
  // pedidos de ejemplo — nunca hay un número escrito a mano en una pantalla.
  //
  // Se excluyen los pedidos "cancelado" de ingresos/unidades vendidas (un
  // pedido cancelado no es una venta), pero sí se cuentan como pedido para
  // el contador "Pedidos cancelados".
  // ------------------------------------------------------------------

  function startOfDay(d) {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x;
  }

  function isSameDay(a, b) {
    return startOfDay(a).getTime() === startOfDay(b).getTime();
  }

  function isThisMonth(d, ref) {
    return d.getFullYear() === ref.getFullYear() && d.getMonth() === ref.getMonth();
  }

  function sumarPedidos(pedidos) {
    const efectivos = pedidos.filter((p) => p.estado !== "cancelado");
    return {
      pedidos: efectivos.length,
      ingresos: efectivos.reduce((acc, p) => acc + p.total, 0),
      unidades: efectivos.reduce((acc, p) => acc + p.cantidad, 0),
    };
  }

  async function getResumenMercadoLibre() {
    const pedidos = LC.demoData.pedidosML;
    const hoy = new Date();
    const ayer = new Date(hoy);
    ayer.setDate(ayer.getDate() - 1);
    const hace7 = new Date(hoy);
    hace7.setDate(hace7.getDate() - 6); // ventana de 7 días, hoy incluido

    const deHoy = pedidos.filter((p) => isSameDay(p.fecha, hoy));
    const deAyer = pedidos.filter((p) => isSameDay(p.fecha, ayer));
    const de7dias = pedidos.filter((p) => startOfDay(p.fecha) >= startOfDay(hace7));
    const delMes = pedidos.filter((p) => isThisMonth(p.fecha, hoy));

    const resumenHoy = sumarPedidos(deHoy);
    const resumenAyer = sumarPedidos(deAyer);
    const resumen7dias = sumarPedidos(de7dias);
    const resumenMes = sumarPedidos(delMes);

    // Estado del "pipeline" actual — se mira sobre TODOS los pedidos de
    // ejemplo (no solo el mes en curso), porque "pendiente"/"enviado" es un
    // estado presente, no una métrica mensual.
    const contarEstado = (estado) => pedidos.filter((p) => p.estado === estado).length;

    return {
      ventasHoy: resumenHoy.ingresos,
      pedidosHoy: resumenHoy.pedidos,
      ventasAyer: resumenAyer.ingresos,
      pedidosAyer: resumenAyer.pedidos,
      ventasUltimos7Dias: resumen7dias.ingresos,
      pedidosUltimos7Dias: resumen7dias.pedidos,
      ventasMes: resumenMes.ingresos,
      pedidosMes: resumenMes.pedidos,
      productosVendidosMes: resumenMes.unidades,
      ticketPromedioMes: resumenMes.pedidos > 0 ? Math.round(resumenMes.ingresos / resumenMes.pedidos) : 0,
      pedidosPendientes: contarEstado("pendiente"),
      pedidosEnviados: contarEstado("enviado"),
      pedidosEntregados: contarEstado("entregado"),
      pedidosCancelados: contarEstado("cancelado"),
    };
  }

  function rangoAFechaInicio(rango, hoy) {
    if (rango === "7d") {
      const d = new Date(hoy);
      d.setDate(d.getDate() - 6);
      return startOfDay(d);
    }
    if (rango === "mes") {
      return new Date(hoy.getFullYear(), hoy.getMonth(), 1);
    }
    // "30d" por defecto
    const d = new Date(hoy);
    d.setDate(d.getDate() - 29);
    return startOfDay(d);
  }

  async function getGraficoVentasMercadoLibre(rango) {
    const hoy = new Date();
    const desde = rangoAFechaInicio(rango || "30d", hoy);
    const dias = [];
    for (let d = new Date(desde); d <= startOfDay(hoy); d.setDate(d.getDate() + 1)) {
      dias.push(new Date(d));
    }
    const pedidos = LC.demoData.pedidosML.filter((p) => p.estado !== "cancelado" && startOfDay(p.fecha) >= desde);

    return dias.map((fecha) => {
      const delDia = pedidos.filter((p) => isSameDay(p.fecha, fecha));
      return {
        fecha,
        ingresos: delDia.reduce((acc, p) => acc + p.total, 0),
        pedidos: delDia.length,
      };
    });
  }

  async function getProductosMasVendidosMercadoLibre(rango, limite) {
    const hoy = new Date();
    const desde = rangoAFechaInicio(rango || "30d", hoy);
    const pedidos = LC.demoData.pedidosML.filter((p) => p.estado !== "cancelado" && startOfDay(p.fecha) >= desde);

    const porSku = new Map();
    for (const p of pedidos) {
      const actual = porSku.get(p.sku) || { sku: p.sku, nombre: p.productoNombre, cantidad: 0, ingresos: 0 };
      actual.cantidad += p.cantidad;
      actual.ingresos += p.total;
      porSku.set(p.sku, actual);
    }
    return [...porSku.values()].sort((a, b) => b.cantidad - a.cantidad).slice(0, limite || 10);
  }

  async function getPedidosMercadoLibre(opts) {
    const { search = "", estado = "todos", producto = "todos", page = 1, pageSize = 10 } = opts || {};
    let rows = [...LC.demoData.pedidosML].sort((a, b) => b.fecha - a.fecha);

    if (estado !== "todos") rows = rows.filter((p) => p.estado === estado);
    if (producto !== "todos") rows = rows.filter((p) => p.productoNombre === producto);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (p) => p.externalId.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || p.productoNombre.toLowerCase().includes(q)
      );
    }

    const total = rows.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const pageSafe = Math.min(Math.max(1, page), totalPages);
    const start = (pageSafe - 1) * pageSize;

    return { rows: rows.slice(start, start + pageSize), total, page: pageSafe, totalPages };
  }

  async function getProductosVendidosEnMercadoLibre() {
    // Lista de nombres de producto distintos que aparecen en pedidos —
    // usada para el filtro "Producto" de la tabla de pedidos.
    const nombres = new Set(LC.demoData.pedidosML.map((p) => p.productoNombre));
    return [...nombres].sort((a, b) => a.localeCompare(b));
  }

  async function getSincronizacion() {
    return {
      estado: "no_conectado",
      ultimaSincronizacion: null,
      sincronizados: null,
      pendientes: null,
      errores: null,
    };
  }

  async function getSuscripcion() {
    const planId = LC.settings.getCurrentPlanId();
    const plan = LC.demoData.plans.find((p) => p.id === planId) || LC.demoData.plans[0];
    return {
      plan,
      productosUtilizados: LC.demoData.catalogRows.length,
      fechaRenovacion: (() => {
        const d = new Date();
        d.setDate(d.getDate() + 18);
        return d;
      })(),
      planes: LC.demoData.plans,
    };
  }

  LC.dataSource = {
    getModo,
    getDashboardResumen,
    getEstadoSistema,
    getProductos,
    getProductoDetalle,
    getOportunidades,
    getIntegraciones,
    getSincronizacion,
    getSuscripcion,
    getResumenMercadoLibre,
    getGraficoVentasMercadoLibre,
    getProductosMasVendidosMercadoLibre,
    getPedidosMercadoLibre,
    getProductosVendidosEnMercadoLibre,
  };
})();
