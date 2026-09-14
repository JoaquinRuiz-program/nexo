"use strict";

/**
 * Nexo — capa de datos.
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
 * getProductosVendidosEnMercadoLibre). En Demo Mode calculan todo a partir
 * de LC.demoData.pedidosML (datos de ejemplo, nunca en modo real desde el
 * 6 de septiembre de 2026 — hallazgo de auditoría comercial: antes se
 * usaban SIEMPRE, así que una empresa real sin ventas veía cifras
 * inventadas). En modo real devuelven honestamente "sin ventas todavía"
 * (no hay ningún job que sincronice pedidos reales de Mercado Libre a la
 * tabla `orders`/`order_items` todavía) — el día que exista, acá es donde
 * hay que reemplazar esa rama por la consulta real; las pantallas de
 * Mercado Libre y el Dashboard siguen llamando exactamente a estas mismas
 * funciones, sin cambios.
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

  /**
   * 6 de septiembre de 2026 — auditoría pre-producción, hallazgo P0-1.
   *
   * Hasta hoy, si una consulta puntual fallaba estando en modo REAL (el
   * backend se reinició, timeout, 500, sesión vencida), estas funciones
   * devolvían en silencio los datos de `LC.demoData` — 65 productos
   * inventados con nombres, SKU, precios y stock realistas — y el pill
   * "Modo demostración" NI SIQUIERA se mostraba (depende de getModo(),
   * que seguía diciendo "real"). Un cliente veía un catálogo que no era
   * el suyo, sin ninguna señal, y podía decidir sobre datos que no
   * existen.
   *
   * Regla desde ahora: en modo REAL nunca se responde con datos de
   * demostración. Si la consulta falla, se lanza este error y la pantalla
   * muestra un estado de error claro y accionable (ver js/app.js,
   * renderErrorDeDatos). Los datos de demostración siguen sirviendo
   * ÚNICAMENTE al modo demo declarado (backend inalcanzable al cargar la
   * página, señalizado con el pill del header) — ese flujo no cambia.
   */
  class ErrorDatosReales extends Error {
    constructor(error) {
      super((error && error.mensaje) || "No pudimos cargar tus datos en este momento.");
      this.name = "ErrorDatosReales";
      // Mismo vocabulario que classifyHttpError (js/backendApi.js):
      // red | timeout | servidor | datos | endpoint | http | json | integracion
      this.tipo = (error && error.tipo) || "desconocido";
    }
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
      productosConImagenes: data.catalogo.productosConImagenes,
      ultimaActualizacion: new Date(data.ultimaActualizacion),
      alertasStockBajo: data.catalogo.alertasStockBajo,
      alertasSinStock: data.catalogo.alertasSinStock,
      rentabilidad: data.rentabilidad,
      ventas: data.ventas,
      mercadoLibre: data.mercadoLibre,
      publicaciones: data.publicaciones,
      suscripcion: data.suscripcion,
    };
  }

  async function getDashboardResumen() {
    if ((await getModo()) === "real") {
      const res = await LC.backendApi.fetchDashboardResumen();
      if (!res.ok) throw new ErrorDatosReales(res.error);
      return adaptarDashboardResumen(res.data);
    }
    return demoDashboardResumen();
  }

  async function getEstadoSistema() {
    // 6 de septiembre de 2026 — auditoría comercial pre-cliente: se sacó
    // WooCommerce de acá (nunca fue una integración real por-empresa, solo
    // credenciales globales de un único piloto legacy — ver
    // backend/app/api/routes/productos.py) y se agregó Google Sheets, que
    // SÍ es una integración real desde el 5 de septiembre de 2026. Nunca
    // mostrarle a un cliente el estado de una integración que no existe.
    if ((await getModo()) === "real") {
      const [resMl, resGs] = await Promise.all([
        LC.backendApi.fetchMercadoLibreEstado(),
        LC.backendApi.fetchGoogleSheetsEstado(),
      ]);
      const estadoConexion = (res, detalleConectado) =>
        res.ok
          ? res.data.conectado
            ? { estado: "conectado", detalle: detalleConectado(res.data) }
            : { estado: "no_conectado", detalle: res.data.credencialesConfiguradas ? "Credenciales configuradas — falta autorizar la cuenta" : "Pendiente de configuración" }
          // 6 de septiembre de 2026 (P0-1): si la consulta falla, NO se
          // afirma "no conectado" — no lo sabemos. Decirlo sería tan falso
          // como mostrar datos demo.
          : { estado: "desconocido", detalle: "No pudimos consultar el estado ahora mismo." };
      return {
        mercadoLibre: estadoConexion(resMl, (d) => `Cuenta ${d.cuentaExternaId}`),
        googleSheets: estadoConexion(resGs, (d) => (d.spreadsheetTitulo ? `Catálogo: ${d.spreadsheetTitulo}` : "Conectado")),
        baseDeDatos: { estado: "conectada", detalle: "Funcionando correctamente" },
      };
    }
    return {
      mercadoLibre: { estado: "no_conectado", detalle: "Pendiente de configuración" },
      googleSheets: { estado: "no_conectado", detalle: "Pendiente de configuración" },
      baseDeDatos: { estado: "demo", detalle: "Demo / Sin conexión" },
    };
  }

  async function getProductos() {
    if ((await getModo()) === "real") {
      const res = await LC.backendApi.fetchProductos();
      if (!res.ok) throw new ErrorDatosReales(res.error);
      return res.data;
    }
    return LC.demoData.catalogRows;
  }

  async function getProductoDetalle(id) {
    if ((await getModo()) === "real") {
      const res = await LC.backendApi.fetchProductoDetalle(id);
      if (!res.ok) {
        // 404 = el producto no existe o es de otra empresa: eso SÍ es
        // "no encontrado" de verdad. Cualquier otro fallo (backend caído,
        // timeout, 500) es un error de carga — nunca se disfraza de
        // "producto no encontrado", que haría pensar que se borró.
        if (res.error.tipo === "endpoint") return null;
        throw new ErrorDatosReales(res.error);
      }
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
      // Canal Mercado Libre: margen NETO (comisión real + envío) y el mismo
      // margen mínimo que "¿Conviene?", para que ambas pantallas coincidan.
      const res = await LC.backendApi.obtenerSeleccion({ canal: "mercadolibre", requiereStock: false });
      if (!res.ok) throw new ErrorDatosReales(res.error);
      return res.data;
    }
    return LC.demoImportResult.seleccion;
  }

  // ------------------------------------------------------------------
  // Integraciones — con qué sistemas puede conectarse la empresa. Mercado
  // Libre usa su estado real (GET /api/mercadolibre/estado); Excel/CSV
  // siempre está disponible. Solo se listan integraciones que existen de
  // verdad hoy — nunca una prometida ("próximamente") que todavía no está
  // construida, ver 6 de septiembre de 2026 más abajo.
  // ------------------------------------------------------------------

  async function getIntegraciones() {
    const modo = await getModo();
    // En modo real estos valores solo quedan si la consulta FALLA — por eso
    // dicen "no pudimos consultar", nunca "no conectado" (6 de septiembre
    // de 2026, P0-1: no afirmar un estado que no verificamos).
    let ml = modo === "real"
      ? { estado: "desconocido", detalle: "No pudimos consultar el estado ahora mismo." }
      : { estado: "no_conectado", detalle: "Pendiente de configuración" };
    let gs = { ...ml };
    if (modo === "real") {
      const [resMl, resGs] = await Promise.all([
        LC.backendApi.fetchMercadoLibreEstado(),
        LC.backendApi.fetchGoogleSheetsEstado(),
      ]);
      if (resMl.ok) {
        ml = resMl.data.conectado
          ? { estado: "conectado", detalle: `Tu cuenta está conectada correctamente${resMl.data.nickname ? ` (${resMl.data.nickname})` : ""}.` }
          : {
              estado: "no_conectado",
              detalle: resMl.data.credencialesConfiguradas
                ? "Conecta tu cuenta para comenzar."
                : "Conecta tu cuenta para comenzar — falta configurar las credenciales en el servidor.",
            };
      }
      if (resGs.ok) {
        gs = resGs.data.conectado
          ? { estado: "conectado", detalle: resGs.data.spreadsheetTitulo ? `Usando "${resGs.data.spreadsheetTitulo}" como catálogo.` : "Conectado — todavía no elegiste una hoja de cálculo." }
          : {
              estado: "no_conectado",
              detalle: resGs.data.credencialesConfiguradas
                ? "Conecta tu cuenta de Google para usar una hoja de cálculo como catálogo."
                : "Conecta tu cuenta para comenzar — falta configurar las credenciales en el servidor.",
            };
      }
    }
    // 6 de septiembre de 2026 — auditoría comercial: se sacó WooCommerce (no
    // es una integración real por-empresa hoy, solo credenciales globales de
    // un único piloto legacy — ver backend/app/api/routes/productos.py) y
    // Shopify (no existe). Google Sheets SÍ es real desde el 5 de septiembre
    // de 2026 (ver app/api/routes/google_sheets.py) — no se le promete al
    // cliente una integración que no puede usar, pero tampoco se le esconde
    // una que sí puede.
    return {
      modo,
      integraciones: [
        { id: "mercadolibre", nombre: "Mercado Libre", categoria: "Canal de venta", ...ml, ruta: "/mercadolibre" },
        { id: "excel", nombre: "Excel / CSV", categoria: "Importación de catálogo", estado: "disponible", detalle: "Siempre disponible — sube un archivo cuando quieras", ruta: "/importar" },
        { id: "google-sheets", nombre: "Google Sheets", categoria: "Importación de catálogo", ...gs, ruta: "/google-sheets" },
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

  // 6 de septiembre de 2026 — hallazgo de auditoría comercial: estas 5
  // funciones leían SIEMPRE de LC.demoData.pedidosML, incluso con el
  // backend real conectado — una empresa real, recién registrada, sin
  // ninguna venta real, veía cifras de ventas y "más vendidos" inventados
  // en su propio Dashboard. Nunca hay hoy ningún job que importe pedidos
  // reales de Mercado Libre a la tabla `orders` (confirmado: ningún
  // endpoint hace `db.add(Order(...))` todavía) — así que en modo real la
  // respuesta honesta es "sin ventas todavía", nunca datos de ejemplo.
  // Mismo criterio que getSincronizacion() de abajo, que ya devuelve
  // "no_conectado" fijo por la misma razón. El día que exista sincronización
  // real de ventas, acá es donde hay que reemplazar el bloque `if` de abajo
  // por la consulta real a `orders`/`order_items`.
  const RESUMEN_ML_VACIO = {
    ventasHoy: 0, pedidosHoy: 0, ventasAyer: 0, pedidosAyer: 0,
    ventasUltimos7Dias: 0, pedidosUltimos7Dias: 0, ventasMes: 0, pedidosMes: 0,
    productosVendidosMes: 0, ticketPromedioMes: 0,
    pedidosPendientes: 0, pedidosEnviados: 0, pedidosEntregados: 0, pedidosCancelados: 0,
  };

  async function getResumenMercadoLibre() {
    if ((await getModo()) === "real") return { ...RESUMEN_ML_VACIO };
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
    // Real: sin sincronización de ventas todavía, ver comentario de
    // getResumenMercadoLibre — el gráfico se muestra igual, en cero.
    if ((await getModo()) === "real") return dias.map((fecha) => ({ fecha, ingresos: 0, pedidos: 0 }));
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
    if ((await getModo()) === "real") return [];
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
    if ((await getModo()) === "real") return { rows: [], total: 0, page: 1, totalPages: 1 };
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
    if ((await getModo()) === "real") return [];
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

  // 5 de septiembre de 2026 — "Mi plan" pasa a leer la Subscription real
  // (GET /api/suscripcion, ver backend) cuando hay backend disponible.
  // Nunca permite elegir plan por su cuenta (real=true): mientras no exista
  // un proveedor de pago conectado, cambiar de plan es exclusivo del
  // administrador de Nexo (ver ADMINISTRADOR.md / admin.py) — la pantalla
  // se muestra de solo lectura en modo real, con "planes: []".
  function adaptarSuscripcion(data) {
    if (!data.plan) {
      // Empresa vieja, creada antes de que existiera el sistema de planes
      // (ver app/domain/plans.py) — nunca se inventa un plan acá.
      return {
        real: true, sinPlan: true,
        plan: { nombre: "Sin plan asignado", limite: null, precio: "—", features: [] },
        productosUtilizados: data.uso.productos, publicacionesUtilizadas: data.uso.publicaciones,
        fechaRenovacion: null, estado: null, planes: [],
      };
    }
    return {
      real: true,
      plan: {
        id: data.plan.codigo, nombre: data.plan.nombre, limite: data.plan.limiteProductos,
        limitePublicaciones: data.plan.limitePublicaciones, precio: data.plan.precio, features: data.plan.features,
      },
      estado: data.estado,
      cicloFacturacion: data.cicloFacturacion,
      productosUtilizados: data.uso.productos,
      publicacionesUtilizadas: data.uso.publicaciones,
      fechaRenovacion: data.fechaRenovacion ? new Date(data.fechaRenovacion) : null,
      planes: [],
    };
  }

  async function getSuscripcion() {
    if ((await getModo()) === "real") {
      const res = await LC.backendApi.fetchMiSuscripcion();
      if (!res.ok) throw new ErrorDatosReales(res.error);
      return adaptarSuscripcion(res.data);
    }
    const planId = LC.settings.getCurrentPlanId();
    const plan = LC.demoData.plans.find((p) => p.id === planId) || LC.demoData.plans[0];
    return {
      real: false,
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
    ErrorDatosReales,
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
