import { test } from "node:test";
import assert from "node:assert/strict";
import {
  detectDuplicates,
  expandVariableProducts,
  findBarcodeCandidates,
  productsWithoutDescription,
  productsWithoutImages,
  productsWithoutSku,
  productsWithoutStockManagement,
  summarizeCatalog,
} from "./analysis.js";
import type { WooCommerceProduct, WooCommerceVariation } from "./woocommerceAdapter.js";

function product(overrides: Partial<WooCommerceProduct>): WooCommerceProduct {
  return {
    id: 1,
    sku: "LIB-0001",
    name: "Producto de prueba",
    slug: "producto-de-prueba",
    status: "publish",
    type: "simple",
    price: "1000",
    regular_price: "1000",
    sale_price: "",
    description: "Una descripción cualquiera.",
    short_description: "",
    stock_quantity: 10,
    manage_stock: true,
    stock_status: "instock",
    categories: [{ id: 1, name: "Cuadernos", slug: "cuadernos" }],
    images: [{ id: 1, src: "http://example.test/a.png" }],
    meta_data: [],
    date_created: "2026-01-01T00:00:00",
    date_modified: "2026-01-01T00:00:00",
    ...overrides,
  };
}

test("producto sin SKU se detecta correctamente", () => {
  const products = [product({ id: 1, sku: "LIB-0001" }), product({ id: 2, sku: "" })];
  const sinSku = productsWithoutSku(products);
  assert.equal(sinSku.length, 1);
  assert.equal(sinSku[0]!.id, 2);
});

test("producto sin gestión de stock se detecta correctamente", () => {
  const products = [product({ id: 1, manage_stock: true }), product({ id: 2, manage_stock: false, stock_quantity: null })];
  const sinGestion = productsWithoutStockManagement(products);
  assert.equal(sinGestion.length, 1);
  assert.equal(sinGestion[0]!.id, 2);
});

test("producto sin stock numérico (agotado) se refleja en el resumen", () => {
  const products = [product({ id: 1, manage_stock: true, stock_quantity: 0, stock_status: "outofstock" })];
  const summary = summarizeCatalog(products);
  // manage_stock=true y stock_quantity es número (0), así que SÍ cuenta como
  // "con stock numérico" — 0 es un valor válido, distinto de "sin gestión".
  assert.equal(summary.conStockNumerico, 1);
});

test("producto sin imagen se detecta correctamente", () => {
  const products = [product({ id: 1, images: [{ id: 1, src: "x" }] }), product({ id: 2, images: [] })];
  const sinImagen = productsWithoutImages(products);
  assert.equal(sinImagen.length, 1);
  assert.equal(sinImagen[0]!.id, 2);
});

test("producto con múltiples imágenes se cuenta en el resumen", () => {
  const products = [
    product({ id: 1, images: [{ id: 1, src: "a" }] }),
    product({
      id: 2,
      images: [
        { id: 2, src: "b" },
        { id: 3, src: "c" },
      ],
    }),
  ];
  const summary = summarizeCatalog(products);
  assert.equal(summary.conMultiplesImagenes, 1);
  assert.equal(summary.conImagenes, 2);
});

test("descripción vacía se detecta correctamente", () => {
  const products = [product({ id: 1, description: "algo" }), product({ id: 2, description: "" }), product({ id: 3, description: "   " })];
  const sinDescripcion = productsWithoutDescription(products);
  assert.equal(sinDescripcion.length, 2);
});

test("SKU duplicado se detecta y agrupa por woocommerce_id distinto", () => {
  const products = [
    product({ id: 3, sku: "LIB-0003", name: "Mochila Head" }),
    product({ id: 4, sku: "LIB-0003", name: "Mochila Head" }),
    product({ id: 5, sku: "LIB-0005", name: "Carpeta Oficio" }),
  ];
  const dup = detectDuplicates(products);
  assert.equal(dup.length, 1);
  assert.equal(dup[0]!.criterio, "sku");
  assert.equal(dup[0]!.clave, "lib-0003");
  assert.deepEqual(
    dup[0]!.productos.map((p) => p.woocommerce_id).sort(),
    [3, 4],
  );
});

test("SKU duplicado se detecta también si difiere en mayúsculas/espacios", () => {
  const products = [product({ id: 1, sku: " lib-0009 " }), product({ id: 2, sku: "LIB-0009" })];
  const dup = detectDuplicates(products);
  assert.equal(dup.length, 1);
});

test("productos sin SKU no generan falsos duplicados por SKU, pero sí por nombre si coinciden", () => {
  const products = [
    product({ id: 1, sku: "", name: "Estuche Triple" }),
    product({ id: 2, sku: "", name: "Témpera" }),
    product({ id: 3, sku: "", name: "Estuche Triple" }),
  ];
  const dup = detectDuplicates(products);
  assert.equal(dup.length, 1);
  assert.equal(dup[0]!.criterio, "nombre");
  assert.deepEqual(
    dup[0]!.productos.map((p) => p.woocommerce_id).sort(),
    [1, 3],
  );
});

test("un producto ya agrupado por SKU no se vuelve a reportar por nombre", () => {
  const products = [
    product({ id: 1, sku: "LIB-0003", name: "Mochila Head" }),
    product({ id: 2, sku: "LIB-0003", name: "Mochila Head" }),
  ];
  const dup = detectDuplicates(products);
  assert.equal(dup.length, 1); // no un segundo grupo por nombre
});

test("findBarcodeCandidates encuentra claves candidatas sin asumir cuál es la correcta", () => {
  const products = [
    product({ id: 1, meta_data: [{ id: 1, key: "codigo_prod", value: "7801234560012" }] }),
    product({ id: 2, meta_data: [{ id: 2, key: "isbn_interno", value: "978-950-04-0000-0" }] }),
    product({ id: 3, meta_data: [{ id: 3, key: "_lc_test_case", value: "control" }] }),
    product({ id: 4, meta_data: [{ id: 4, key: "color", value: "azul" }] }),
  ];
  const candidates = findBarcodeCandidates(products);
  const keys = candidates.map((c) => c.key).sort();
  assert.deepEqual(keys, ["codigo_prod", "isbn_interno"]);
  // La clave interna de trazabilidad del seed no debe aparecer como candidata.
  assert.ok(!keys.includes("_lc_test_case"));
  // Una clave sin relación (color) tampoco debe aparecer.
  assert.ok(!keys.includes("color"));
});

function variation(overrides: Partial<WooCommerceVariation>): WooCommerceVariation {
  return {
    id: 100,
    sku: "",
    price: "1000",
    regular_price: "1000",
    sale_price: "",
    description: "",
    stock_quantity: null,
    manage_stock: false,
    stock_status: "instock",
    image: null,
    attributes: [],
    meta_data: [],
    date_created: "2026-01-01T00:00:00",
    date_modified: "2026-01-01T00:00:00",
    ...overrides,
  };
}

test("expandVariableProducts: un producto 'simple' pasa sin cambios (marcado esVariante:false)", () => {
  const products = [product({ id: 1, type: "simple" })];
  const expanded = expandVariableProducts(products, new Map());
  assert.equal(expanded.length, 1);
  assert.equal(expanded[0]!.esVariante, false);
  assert.equal(expanded[0]!.woocommerceParentId, null);
});

test("expandVariableProducts: un producto 'variable' con variaciones se reemplaza por una fila por color, con SKU/stock reales de la variación", () => {
  const products = [product({ id: 50, type: "variable", sku: "", name: "ARCHIVADOR PLASTIFICADO", manage_stock: false, stock_quantity: null })];
  const variationsByProductId = new Map<number, WooCommerceVariation[]>([
    [
      50,
      [
        variation({ id: 501, sku: "ARCH-ROJO", manage_stock: true, stock_quantity: 12, attributes: [{ id: 7, name: "Colores disponibles", option: "Rojo" }] }),
        variation({ id: 502, sku: "ARCH-AZUL", manage_stock: true, stock_quantity: 7, attributes: [{ id: 7, name: "Colores disponibles", option: "Azul" }] }),
      ],
    ],
  ]);

  const expanded = expandVariableProducts(products, variationsByProductId);

  assert.equal(expanded.length, 2, "el producto padre se reemplaza por sus 2 variaciones, no se agrega aparte");
  assert.deepEqual(expanded.map((p) => p.id).sort(), [501, 502]);
  assert.deepEqual(expanded.map((p) => p.sku).sort(), ["ARCH-AZUL", "ARCH-ROJO"]);
  assert.deepEqual(
    expanded.map((p) => p.stock_quantity).sort((a, b) => (a as number) - (b as number)),
    [7, 12],
  );
  assert.ok(expanded.every((p) => p.esVariante === true));
  assert.ok(expanded.every((p) => p.woocommerceParentId === 50));
  const rojo = expanded.find((p) => p.colorVariante === "Rojo");
  assert.ok(rojo);
  assert.equal(rojo!.name, "ARCHIVADOR PLASTIFICADO - Rojo");
});

test("expandVariableProducts: un producto 'variable' SIN variaciones cargadas se conserva como padre, no se descarta", () => {
  const products = [product({ id: 60, type: "variable" })];
  const expanded = expandVariableProducts(products, new Map());
  assert.equal(expanded.length, 1, "no se pierde el producto aunque no se hayan podido traer sus variaciones");
  assert.equal(expanded[0]!.id, 60);
  assert.equal(expanded[0]!.esVariante, false);
});

test("resumen general cuenta categorías distintas correctamente", () => {
  const products = [
    product({ id: 1, categories: [{ id: 1, name: "Cuadernos", slug: "cuadernos" }] }),
    product({ id: 2, categories: [{ id: 2, name: "Arte", slug: "arte" }] }),
    product({ id: 3, categories: [{ id: 1, name: "Cuadernos", slug: "cuadernos" }] }),
  ];
  const summary = summarizeCatalog(products);
  assert.equal(summary.cantidadCategorias, 2);
  assert.deepEqual(summary.categorias, ["Arte", "Cuadernos"]);
});
