"use strict";

/**
 * Nexo — resultado de ejemplo para el asistente "Importar
 * catálogo" (js/importFlow.js), usado SOLO cuando el backend real no está
 * disponible (ver LC.backendApi.checkHealth).
 *
 * Esto NO es lógica de negocio reimplementada en JavaScript — es una
 * fotografía estática de lo que el backend real devuelve, con la forma
 * EXACTA de sus respuestas (mismos nombres de campo que
 * GET/POST /api/catalogo/importar/*, /api/seleccion y
 * /api/publicaciones/preparar), tomada a mano a partir de
 * backend/demo_data/09-multi-categoria.xlsx: los márgenes de acá son
 * cálculos reales de precio-costo de esos productos de ejemplo, no números
 * inventados para que "se vean bien". Así el asistente se puede recorrer
 * completo sin backend, y el día que haya uno corriendo, exactamente el
 * mismo código de pantalla consume datos reales sin cambiar una línea.
 *
 * Nunca se mezcla con datos reales: LC.importFlow marca cada corrida como
 * "demo" o "real" y lo muestra explícito en la interfaz.
 */

window.LC = window.LC || {};

(function () {
  const ENCABEZADOS = ["SKU", "Nombre", "Marca", "Categoría", "Costo", "Precio", "Stock", "Descripción", "Imagen", "Código de barras"];

  const analisis = {
    encabezados: ENCABEZADOS,
    mapeoPropuesto: {
      sku: "SKU", nombre: "Nombre", marca: "Marca", categoria: "Categoría",
      costo: "Costo", precio: "Precio", stock: "Stock", descripcion: "Descripción",
      imagen_url: "Imagen", codigo_barras: "Código de barras",
    },
    camposReconocidos: ["sku", "nombre", "marca", "categoria", "costo", "precio", "stock", "descripcion", "imagen_url", "codigo_barras"],
    resumen: { totalFilas: 10, validos: 10, revision: 0, errores: 0 },
    fileName: "09-multi-categoria.xlsx (ejemplo)",
  };

  const confirmar = { creados: 10, actualizados: 0, omitidos: 0, detalleOmitidos: [] };

  // Márgenes = precio − costo de cada producto real de
  // backend/demo_data/09-multi-categoria.xlsx — no inventados.
  const productos = [
    { id: 1, sku: "MULTI-008", nombre: "Everlast Guantes de boxeo 12oz", precio: 24990, costo: 15000, marketplaceStock: null, tieneCosto: true, margenTiendaClp: 9990, margenTiendaPct: 40.0, mercadoLibreConfigurado: false, margenMercadoLibreClp: null, margenMercadoLibrePct: null, clasificacion: "rentable", razon: null },
    { id: 2, sku: "MULTI-001", nombre: "JBL Audífonos inalámbricos deportivos", precio: 22990, costo: 14000, marketplaceStock: null, tieneCosto: true, margenTiendaClp: 8990, margenTiendaPct: 39.1, mercadoLibreConfigurado: false, margenMercadoLibreClp: null, margenMercadoLibrePct: null, clasificacion: "rentable", razon: null },
    { id: 3, sku: "MULTI-006", nombre: "Anker Cargador solar portátil 10000mAh", precio: 19990, costo: 12000, marketplaceStock: null, tieneCosto: true, margenTiendaClp: 7990, margenTiendaPct: 40.0, mercadoLibreConfigurado: false, margenMercadoLibreClp: null, margenMercadoLibrePct: null, clasificacion: "rentable", razon: null },
    { id: 4, sku: "MULTI-003", nombre: "Maybelline Set de maquillaje profesional", precio: 16990, costo: 9800, marketplaceStock: null, tieneCosto: true, margenTiendaClp: 7190, margenTiendaPct: 42.3, mercadoLibreConfigurado: false, margenMercadoLibreClp: null, margenMercadoLibrePct: null, clasificacion: "rentable", razon: null },
    { id: 5, sku: "MULTI-010", nombre: "Ergohuman Silla ergonómica de oficina", precio: 129990, costo: 85000, marketplaceStock: null, tieneCosto: true, margenTiendaClp: 44990, margenTiendaPct: 34.6, mercadoLibreConfigurado: false, margenMercadoLibreClp: null, margenMercadoLibrePct: null, clasificacion: "rentable", razon: null },
    { id: 6, sku: "MULTI-007", nombre: "Set de té gourmet x6 variedades", precio: 5500, costo: 6000, marketplaceStock: null, tieneCosto: true, margenTiendaClp: -500, margenTiendaPct: -9.1, mercadoLibreConfigurado: false, margenMercadoLibreClp: null, margenMercadoLibrePct: null, clasificacion: "no_rentable", razon: "La utilidad estimada sería negativa (-$500) después de costos." },
  ];

  const seleccion = {
    resumen: { total: productos.length, rentables: 5, margenBajo: 0, noRentables: 1, sinStock: 0, sinDatos: 0, noSeleccionados: 0 },
    productos,
  };

  const borradores = productos.slice(0, 3).map((p) => ({
    id: p.id,
    sku: p.sku,
    tituloPropuesto: p.nombre,
    descripcionPropuesta: `${p.nombre}.`,
    contenidoSimulado: true,
    categoriaSugerida: "Sin categoría de ejemplo",
    categoriaEsOficialDeMercadoLibre: false,
    marca: p.nombre.split(" ")[0],
    codigoBarras: null,
    atributos: { Marca: p.nombre.split(" ")[0] },
    precio: p.precio,
    costo: p.costo,
    imagenes: [],
    rentabilidad: {
      margenTiendaClp: p.margenTiendaClp, margenTiendaPct: p.margenTiendaPct,
      margenMercadoLibreClp: null, margenMercadoLibrePct: null,
    },
    clasificacion: p.clasificacion,
    razonClasificacion: p.razon,
    estado: p.clasificacion === "rentable" ? "listo_para_publicar" : "no_recomendado",
    advertencias: p.clasificacion === "rentable" ? ["Sin imagen cargada.", "Sin categoría — se recomienda completarla antes de publicar."] : ["Sin imagen cargada.", "Sin categoría — se recomienda completarla antes de publicar.", p.razon],
  }));

  const preparar = {
    resumen: {
      total: borradores.length,
      listosParaPublicar: borradores.filter((b) => b.estado === "listo_para_publicar").length,
      requierenRevision: 0,
      noRecomendados: borradores.filter((b) => b.estado === "no_recomendado").length,
    },
    borradores,
    noEncontrados: [],
  };

  LC.demoImportResult = { analisis, confirmar, seleccion, preparar };
})();
