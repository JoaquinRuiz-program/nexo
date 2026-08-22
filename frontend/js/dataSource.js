"use strict";

/**
 * Librería Central — capa de datos.
 *
 * Esta es la ÚNICA puerta por la que las pantallas (js/app.js) piden datos.
 * Hoy todo viene de js/demoData.js (Demo Mode). Cuando conectemos el
 * backend real, este es el ÚNICO archivo que hay que reescribir — cambiar
 * estas funciones para que llamen a js/backendApi.js en vez de a los datos
 * de ejemplo — sin tocar ninguna pantalla ni componente visual.
 *
 * `LC.dataSource.mode` es siempre "demo" en esta fase. No intenta conectar
 * con WooCommerce, Mercado Libre ni con el backend real todavía.
 *
 * ---------------------------------------------------------------------
 * De Demo Mode a datos reales (Fase 3, base de datos ya diseñada — ver
 * backend/DATABASE.md): cada función de acá seguirá devolviendo la MISMA
 * forma de datos, pero pidiéndola a un endpoint nuevo en vez de a
 * demoData.js. No hace falta esperar a tener la sincronización con
 * Mercado Libre funcionando para reemplazar Demo Mode — apenas la base de
 * datos tenga productos reales (importados de WooCommerce), ya se puede
 * conectar todo lo de acá excepto getSincronizacion, que sí depende del
 * motor de sincronización real:
 *
 *   getDashboardResumen()   -> GET /api/dashboard/resumen
 *                              (cuenta ProductVariant por store_id: total,
 *                              con/sin stock, stock bajo según
 *                              StoreSettings.low_stock_threshold)
 *   getEstadoSistema()      -> GET /api/estado-sistema
 *                              (existe WooCommerceProduct sincronizado
 *                              reciente? existe MarketplaceAccount con
 *                              status="connected"? — nunca inventar un
 *                              "conectado" que no sea real)
 *   getProductos()          -> GET /api/productos
 *                              (join Product + ProductVariant + su
 *                              WooCommerceProduct/Variation opcional —
 *                              misma forma de fila que ya arma
 *                              build_productos_list en el backend hoy)
 *   getProductoDetalle(id)  -> GET /api/productos/:id
 *                              (Product + sus ProductVariant + su
 *                              WooCommerceProduct + sus
 *                              MarketplaceListing, si existen; el
 *                              historial viene de StockMovement)
 *   getSincronizacion()     -> GET /api/sincronizacion
 *                              (último SyncJob por store_id + sus SyncLog)
 *   getSuscripcion()        -> GET /api/suscripcion
 *                              (Subscription + Plan de la tienda; conteo
 *                              de ProductVariant como "productos usados")
 *
 * Ninguna pantalla necesita cambiar para este reemplazo: todas ya reciben
 * los datos a través de estas mismas seis funciones.
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
  const MODE = "demo";

  async function getDashboardResumen() {
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
    };
  }

  async function getEstadoSistema() {
    return {
      woocommerce: { estado: "no_conectado", detalle: "Pendiente de configuración" },
      mercadoLibre: { estado: "no_conectado", detalle: "Pendiente de configuración" },
      baseDeDatos: { estado: "demo", detalle: "Demo / Sin conexión" },
    };
  }

  async function getProductos() {
    return LC.demoData.catalogRows;
  }

  async function getProductoDetalle(id) {
    const numId = Number(id);
    const row = LC.demoData.catalogRows.find((r) => r.id === numId);
    if (!row) return null;
    const raw = LC.demoData.getProductoRaw(numId);
    const variantes = raw && raw.tipo === "variable" ? raw.variantes : [];
    const historial = LC.demoData.getHistorial(row);
    return { row, variantes, historial, creado: raw ? raw.creado : null };
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
    mode: MODE,
    getDashboardResumen,
    getEstadoSistema,
    getProductos,
    getProductoDetalle,
    getSincronizacion,
    getSuscripcion,
    getResumenMercadoLibre,
    getGraficoVentasMercadoLibre,
    getProductosMasVendidosMercadoLibre,
    getPedidosMercadoLibre,
    getProductosVendidosEnMercadoLibre,
  };
})();
