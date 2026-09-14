"use strict";

/**
 * Nexo — datos de demostración (Demo Mode).
 *
 * Todo lo de este archivo es ficticio, generado en el navegador. Existe
 * únicamente para poder navegar y probar la interfaz completa sin depender
 * todavía del backend real ni de WooCommerce/Mercado Libre. Cuando el
 * backend real esté conectado, este archivo deja de usarse — el único lugar
 * que las pantallas consultan es js/dataSource.js, y es el único archivo
 * que habrá que tocar para pasar a datos reales (ver ese archivo).
 *
 * 22 de agosto de 2026 — reconstruido con un catálogo más realista (nombres
 * de una librería real, no "Producto modelo N") y con ventas/pedidos de
 * Mercado Libre de ejemplo, para que el Dashboard y la sección de Mercado
 * Libre tengan suficientes datos de demostración para evaluarse a fondo.
 */

window.LC = window.LC || {};

(function () {
  function seededRandom(seed) {
    let s = seed % 2147483647;
    if (s <= 0) s += 2147483646;
    return function () {
      s = (s * 16807) % 2147483647;
      return (s - 1) / 2147483646;
    };
  }

  function daysAgo(n, hour, minute) {
    const d = new Date();
    d.setHours(hour ?? 9 + Math.floor(d.getDate() % 8), minute ?? (d.getMinutes() % 60), 0, 0);
    d.setDate(d.getDate() - n);
    return d;
  }

  const rand = seededRandom(20260822);

  // ------------------------------------------------------------------
  // Catálogo — productos reales de una librería (nombres, categorías y
  // precios pensados para parecer un catálogo real, no aleatorio). Cada
  // producto simple tiene su propio SKU; cada producto variable tiene un
  // color por variante, con su propio SKU/precio/stock — igual criterio
  // que ya usa el backend real (ver backend/app/domain/analysis.py,
  // expand_variable_products: "una fila por color").
  // ------------------------------------------------------------------

  const CATALOG_DEFS = [
    // ---- Libros — narrativa y clásicos ----
    { categoria: "Libros", nombre: "Cien años de soledad", sku: "LIB-001", precio: 12990, stock: 34 },
    { categoria: "Libros", nombre: "Rayuela", sku: "LIB-002", precio: 11490, stock: 22 },
    { categoria: "Libros", nombre: "El túnel", sku: "LIB-003", precio: 8990, stock: 3 },
    { categoria: "Libros", nombre: "1984", sku: "LIB-004", precio: 9990, stock: 0 },
    { categoria: "Libros", nombre: "El principito", sku: "LIB-005", precio: 7990, stock: 48 },
    { categoria: "Libros", nombre: "Don Quijote de la Mancha", sku: "LIB-006", precio: 15990, stock: 12 },
    { categoria: "Libros", nombre: "Crónica de una muerte anunciada", sku: "LIB-007", precio: 9490, stock: 19 },
    { categoria: "Libros", nombre: "La casa de los espíritus", sku: "LIB-008", precio: 10990, stock: 27 },
    { categoria: "Libros", nombre: "Ficciones", sku: "LIB-009", precio: 9990, stock: 2 },
    { categoria: "Libros", nombre: "Los detectives salvajes", sku: "LIB-010", precio: 12490, stock: 15 },
    { categoria: "Libros", nombre: "Sapiens: de animales a dioses", sku: "LIB-011", precio: 16990, stock: 31 },
    { categoria: "Libros", nombre: "Hábitos atómicos", sku: "LIB-012", precio: 14990, stock: 40 },
    { categoria: "Libros", nombre: "El alquimista", sku: "LIB-013", precio: 8990, stock: 0 },
    { categoria: "Libros", nombre: "Harry Potter y la piedra filosofal", sku: "LIB-014", precio: 13990, stock: 26 },
    { categoria: "Libros", nombre: "El nombre del viento", sku: "LIB-015", precio: 15490, stock: 9 },
    { categoria: "Libros", nombre: "Como agua para chocolate", sku: "LIB-016", precio: 9990, stock: 17 },
    { categoria: "Libros", nombre: "Veinte poemas de amor y una canción desesperada", sku: "LIB-017", precio: 7490, stock: 33 },
    { categoria: "Libros", nombre: "Cuentos de la selva", sku: "LIB-018", precio: 6990, stock: 4 },

    // ---- Libros — infantil y escolar ----
    { categoria: "Escolares", nombre: "Diccionario escolar ilustrado", sku: "ESC-001", precio: 11990, stock: 20 },
    { categoria: "Escolares", nombre: "Atlas geográfico escolar", sku: "ESC-002", precio: 13990, stock: 8 },
    { categoria: "Escolares", nombre: "Cuaderno de caligrafía", sku: "ESC-003", precio: 3990, stock: 45 },
    { categoria: "Escolares", nombre: "Libro para colorear — Animales", sku: "ESC-004", precio: 5990, stock: 30 },
    { categoria: "Escolares", nombre: "Libro para colorear — Dinosaurios", sku: "ESC-005", precio: 5990, stock: 0 },
    { categoria: "Escolares", nombre: "Enciclopedia infantil ilustrada", sku: "ESC-006", precio: 18990, stock: 6 },

    // ---- Cuadernos (varios con color) ----
    {
      categoria: "Cuadernos", nombre: "Cuaderno universitario 100 hojas cuadriculado", precio: 3490,
      variantes: [
        { color: "Azul", sku: "CUA-001-AZU", stock: 25 },
        { color: "Rojo", sku: "CUA-001-ROJ", stock: 3 },
        { color: "Verde", sku: "CUA-001-VER", stock: 0 },
        { color: "Negro", sku: "CUA-001-NEG", stock: 14 },
      ],
    },
    {
      categoria: "Cuadernos", nombre: "Cuaderno universitario 100 hojas rayado", precio: 3490,
      variantes: [
        { color: "Azul", sku: "CUA-002-AZU", stock: 18 },
        { color: "Rojo", sku: "CUA-002-ROJ", stock: 21 },
        { color: "Verde", sku: "CUA-002-VER", stock: 5 },
      ],
    },
    {
      categoria: "Cuadernos", nombre: "Cuaderno college 7 materias", precio: 6990,
      variantes: [
        { color: "Negro", sku: "CUA-003-NEG", stock: 11 },
        { color: "Azul", sku: "CUA-003-AZU", stock: 0 },
      ],
    },
    {
      categoria: "Cuadernos", nombre: "Croquera tapa dura A5", precio: 5990,
      variantes: [
        { color: "Negro", sku: "CUA-004-NEG", stock: 16 },
        { color: "Kraft", sku: "CUA-004-KRA", stock: 9 },
      ],
    },
    { categoria: "Cuadernos", nombre: "Cuaderno de arte 80 hojas", sku: "CUA-005", precio: 4490, stock: 18 },

    // ---- Agendas y oficina ----
    { categoria: "Agendas", nombre: "Agenda semanal 2027", sku: "AGE-001", precio: 8990, stock: 11 },
    { categoria: "Agendas", nombre: "Agenda diaria 2027 tapa dura", sku: "AGE-002", precio: 10990, stock: 14 },
    { categoria: "Oficina", nombre: "Organizador de escritorio", sku: "OFI-001", precio: 12990, stock: 5 },
    { categoria: "Oficina", nombre: "Corchetera estándar", sku: "OFI-002", precio: 4990, stock: 22 },
    { categoria: "Oficina", nombre: "Perforadora 2 huecos", sku: "OFI-003", precio: 6490, stock: 16 },
    { categoria: "Oficina", nombre: "Resma papel carta 500 hojas", sku: "OFI-004", precio: 5490, stock: 60 },
    { categoria: "Oficina", nombre: "Carpeta archivadora oficio", sku: "OFI-005", precio: 3990, stock: 38 },
    { categoria: "Oficina", nombre: "Set clips metálicos", sku: "OFI-006", precio: 1490, stock: 90 },
    { categoria: "Oficina", nombre: "Post-it notas adhesivas", sku: "OFI-007", precio: 2490, stock: 0 },

    // ---- Papelería / útiles escolares ----
    { categoria: "Papelería", nombre: "Set de lápices de colores x12", sku: "PAP-001", precio: 4990, stock: 25 },
    { categoria: "Papelería", nombre: "Lápiz grafito HB caja x12", sku: "PAP-002", precio: 2990, stock: 55 },
    { categoria: "Papelería", nombre: "Goma de borrar blanca", sku: "PAP-003", precio: 690, stock: 120 },
    { categoria: "Papelería", nombre: "Sacapuntas doble", sku: "PAP-004", precio: 990, stock: 4 },
    {
      categoria: "Papelería", nombre: "Resaltador fluorescente", precio: 990,
      variantes: [
        { color: "Amarillo", sku: "PAP-005-AMA", stock: 40 },
        { color: "Rosado", sku: "PAP-005-ROS", stock: 12 },
        { color: "Verde", sku: "PAP-005-VER", stock: 0 },
        { color: "Celeste", sku: "PAP-005-CEL", stock: 8 },
      ],
    },
    {
      categoria: "Papelería", nombre: "Marcador permanente", precio: 1290,
      variantes: [
        { color: "Negro", sku: "PAP-006-NEG", stock: 30 },
        { color: "Azul", sku: "PAP-006-AZU", stock: 4 },
        { color: "Rojo", sku: "PAP-006-ROJ", stock: 17 },
      ],
    },
    { categoria: "Papelería", nombre: "Corrector líquido", sku: "PAP-007", precio: 1490, stock: 0 },
    { categoria: "Papelería", nombre: "Regla 30 cm", sku: "PAP-008", precio: 890, stock: 40 },
    { categoria: "Papelería", nombre: "Tijera escolar punta roma", sku: "PAP-009", precio: 1990, stock: 26 },
    { categoria: "Papelería", nombre: "Pegamento en barra", sku: "PAP-010", precio: 1290, stock: 33 },

    // ---- Arte ----
    { categoria: "Arte", nombre: "Set de témperas x12 colores", sku: "ART-001", precio: 8990, stock: 14 },
    { categoria: "Arte", nombre: "Acuarelas en pastillas x24", sku: "ART-002", precio: 12990, stock: 5 },
    { categoria: "Arte", nombre: "Set de pinceles de cerdas x6", sku: "ART-003", precio: 5990, stock: 19 },
    { categoria: "Arte", nombre: "Block de dibujo A4", sku: "ART-004", precio: 3490, stock: 28 },
    { categoria: "Arte", nombre: "Plasticina x12 colores", sku: "ART-005", precio: 3990, stock: 0 },
    { categoria: "Arte", nombre: "Set de arcilla para modelar", sku: "ART-006", precio: 6990, stock: 12 },
    { categoria: "Arte", nombre: "Papel crepé x10 colores", sku: "ART-007", precio: 2990, stock: 21 },
    { categoria: "Arte", nombre: "Cartulina de colores x20", sku: "ART-008", precio: 4490, stock: 16 },

    // ---- Mochilas y estuches (variable por color) ----
    {
      categoria: "Mochilas", nombre: "Mochila escolar reforzada", precio: 24990,
      variantes: [
        { color: "Negro", sku: "MOC-001-NEG", stock: 9 },
        { color: "Azul", sku: "MOC-001-AZU", stock: 6 },
        { color: "Rosado", sku: "MOC-001-ROS", stock: 0 },
      ],
    },
    {
      categoria: "Mochilas", nombre: "Estuche escolar doble cierre", precio: 6990,
      variantes: [
        { color: "Negro", sku: "MOC-002-NEG", stock: 20 },
        { color: "Azul", sku: "MOC-002-AZU", stock: 14 },
        { color: "Rosado", sku: "MOC-002-ROS", stock: 3 },
        { color: "Verde", sku: "MOC-002-VER", stock: 11 },
      ],
    },
  ];

  let nextInternalId = 1000;
  let nextWooProductId = 8000;
  let nextWooVariationId = 9000;

  function buildCatalog() {
    return CATALOG_DEFS.map((def, index) => {
      const id = nextInternalId++;
      const woocommerceParentId = nextWooProductId++;
      // Spread determinístico de fechas de creación (no todos "hoy") — entre
      // ~15 días y ~14 meses atrás, sin usar valores aleatorios por producto.
      const creado = daysAgo(15 + ((index * 53) % 420));

      if (def.variantes) {
        const variantes = def.variantes.map((v) => ({
          id: nextInternalId++,
          color: v.color,
          sku: v.sku,
          stockQuantity: v.stock,
          precio: v.precio ?? def.precio,
          woocommerceVariationId: nextWooVariationId++,
        }));
        return {
          id,
          woocommerceParentId,
          nombre: def.nombre,
          categoria: def.categoria,
          precio: def.precio,
          creado,
          tipo: "variable",
          sku: "",
          variantes,
          gestionaStock: false,
          estadoStock: "instock",
        };
      }

      const stockQuantity = def.stock;
      return {
        id,
        woocommerceParentId,
        nombre: def.nombre,
        categoria: def.categoria,
        precio: def.precio,
        creado,
        tipo: "simple",
        sku: def.sku,
        stockQuantity,
        gestionaStock: true,
        estadoStock: stockQuantity > 0 ? "instock" : "outofstock",
        variantes: [],
      };
    });
  }

  // Expande variantes en una fila por color — mismo criterio que ya usa el
  // backend real (ver backend/app/domain/analysis.py, expand_variable_products).
  function expandForTable(catalog) {
    const rows = [];
    for (const p of catalog) {
      if (p.tipo !== "variable" || !p.variantes.length) {
        rows.push({
          id: p.id,
          sku: p.sku,
          nombre: p.nombre,
          tipo: p.tipo,
          categoria: p.categoria,
          precio: p.precio,
          stockQuantity: p.tipo === "variable" ? null : p.stockQuantity,
          gestionaStock: p.gestionaStock,
          estadoStock: p.estadoStock,
          esVariante: false,
          colorVariante: null,
          parentId: p.id,
          woocommerceParentId: p.woocommerceParentId,
          woocommerceVariationId: null,
        });
        continue;
      }
      for (const v of p.variantes) {
        rows.push({
          id: v.id,
          sku: v.sku,
          nombre: `${p.nombre} - ${v.color}`,
          tipo: "variable",
          categoria: p.categoria,
          precio: v.precio,
          stockQuantity: v.stockQuantity,
          gestionaStock: true,
          estadoStock: v.stockQuantity > 0 ? "instock" : "outofstock",
          esVariante: true,
          colorVariante: v.color,
          parentId: p.id,
          woocommerceParentId: p.woocommerceParentId,
          woocommerceVariationId: v.woocommerceVariationId,
        });
      }
    }
    return rows;
  }

  const CATALOG_RAW = buildCatalog();
  const CATALOG_ROWS = expandForTable(CATALOG_RAW);
  const CATALOG_ROWS_BY_SKU = new Map(CATALOG_ROWS.map((r) => [r.sku, r]));

  // 6 de septiembre de 2026 — alineado a los planes reales (ver
  // backend/app/domain/plans.py) para no mostrar, ni siquiera en Demo
  // Mode, un precio o un nombre de plan que no existe de verdad.
  const PLANS = [
    {
      id: "basico",
      nombre: "Nexo Básico",
      limite: 200,
      precio: "$80.000 CLP/mes",
      descripcion: "Para partir con lo esencial.",
      features: ["Hasta 1.000 productos", "Hasta 150 publicaciones activas en Mercado Libre", "Conexión con Mercado Libre", "Soporte por email"],
    },
    {
      id: "pro",
      nombre: "Nexo Pro",
      limite: 1000,
      precio: "$200.000 CLP/mes",
      descripcion: "Para catálogos en crecimiento.",
      features: ["Hasta 5.000 productos", "Hasta 800 publicaciones activas en Mercado Libre", "Soporte prioritario"],
    },
  ];

  function getProductoRaw(id) {
    return CATALOG_RAW.find((p) => p.id === id || (p.variantes || []).some((v) => v.id === id));
  }

  function getHistorial(row) {
    const eventos = [
      { fecha: daysAgo(180), evento: "Producto creado en el catálogo." },
      { fecha: daysAgo(45), evento: `Precio actualizado a $${Math.round(row.precio).toLocaleString("es-CL")}.` },
    ];
    if (row.gestionaStock && row.stockQuantity !== null) {
      eventos.push({ fecha: daysAgo(3), evento: `Stock actualizado a ${row.stockQuantity} unidades.` });
    }
    return eventos.sort((a, b) => b.fecha - a.fecha);
  }

  // ------------------------------------------------------------------
  // Mercado Libre — ventas/pedidos de ejemplo. TODOS los pedidos apuntan a
  // un SKU que realmente existe en el catálogo de arriba, para poder probar
  // más adelante la relación Producto → Venta → Cantidad vendida → Stock,
  // y (cuando conectemos Mercado Libre de verdad) WooCommerce → Producto →
  // Mercado Libre → Venta → Descuento de stock.
  //
  // NADA de esto es una venta real: no hay conexión con Mercado Libre
  // todavía (ver js/dataSource.js, getEstadoSistema — sigue "no_conectado").
  // Esto es solo suficiente volumen de datos ficticios para poder evaluar
  // la interfaz (gráfico, resumen, pedidos, productos más vendidos).
  // ------------------------------------------------------------------

  const DIAS_HISTORIAL_VENTAS = 45;

  // Un subconjunto de SKUs "populares" para que el ranking de productos más
  // vendidos sea estable y creíble (no todos los productos venden igual).
  const SKUS_POPULARES = [
    "LIB-001", "LIB-005", "LIB-011", "LIB-012", "LIB-014",
    "PAP-002", "PAP-003", "OFI-005", "CUA-001-AZU", "PAP-005-AMA",
  ];

  function elegirFilaVenta() {
    // El doble de probabilidad de caer en un SKU "popular" que en cualquier
    // otro — determinístico según la semilla del módulo, no por Math.random().
    const usarPopular = rand() < 0.55;
    if (usarPopular) {
      const sku = SKUS_POPULARES[Math.floor(rand() * SKUS_POPULARES.length)];
      const row = CATALOG_ROWS_BY_SKU.get(sku);
      if (row) return row;
    }
    return CATALOG_ROWS[Math.floor(rand() * CATALOG_ROWS.length)];
  }

  function elegirEstadoPedido(diasAtras) {
    const r = rand();
    if (diasAtras === 0) {
      if (r < 0.7) return "pendiente";
      if (r < 0.93) return "enviado";
      if (r < 0.98) return "entregado";
      return "cancelado";
    }
    if (diasAtras === 1) {
      if (r < 0.4) return "pendiente";
      if (r < 0.75) return "enviado";
      if (r < 0.95) return "entregado";
      return "cancelado";
    }
    if (diasAtras <= 5) {
      if (r < 0.15) return "pendiente";
      if (r < 0.4) return "enviado";
      if (r < 0.95) return "entregado";
      return "cancelado";
    }
    if (r < 0.03) return "pendiente";
    if (r < 0.09) return "enviado";
    if (r < 0.95) return "entregado";
    return "cancelado";
  }

  function buildPedidosML() {
    const pedidos = [];
    let externalSeq = 10200;
    let internalSeq = 1;

    for (let diasAtras = DIAS_HISTORIAL_VENTAS - 1; diasAtras >= 0; diasAtras--) {
      const cantidadPedidosHoy = 2 + Math.floor(rand() * 4); // 2 a 5 pedidos ese día
      for (let i = 0; i < cantidadPedidosHoy; i++) {
        const fila = elegirFilaVenta();
        const cantidad = rand() < 0.85 ? 1 + Math.floor(rand() * 2) : 3 + Math.floor(rand() * 2); // mayormente 1-2, a veces 3-4
        const precioUnitario = fila.precio || 0;
        const hora = 9 + Math.floor(rand() * 12);
        const minuto = Math.floor(rand() * 60);
        pedidos.push({
          id: internalSeq++,
          externalId: `ML-${externalSeq++}`,
          sku: fila.sku,
          productoNombre: fila.nombre,
          cantidad,
          precioUnitario,
          total: precioUnitario * cantidad,
          estado: elegirEstadoPedido(diasAtras),
          fecha: daysAgo(diasAtras, hora, minuto),
        });
      }
    }
    // Orden cronológico ascendente (más antiguo primero) — cada pantalla que
    // necesite "los últimos pedidos" ordena/pagina como corresponda.
    return pedidos.sort((a, b) => a.fecha - b.fecha);
  }

  const PEDIDOS_ML = buildPedidosML();

  LC.demoData = {
    account: {
      nombre: "Usuario Demo",
      email: "demo@nexo.local",
      empresa: "Empresa Demo",
      tienda: "Empresa Demo",
    },
    catalogRaw: CATALOG_RAW,
    catalogRows: CATALOG_ROWS,
    plans: PLANS,
    getProductoRaw,
    getHistorial,
    findRowBySku: (sku) => CATALOG_ROWS_BY_SKU.get(sku) || null,
    pedidosML: PEDIDOS_ML,
  };
})();
