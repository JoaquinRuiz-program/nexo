/**
 * Funciones puras de análisis del catálogo (sin red, sin filesystem) —
 * separadas del resto justamente para poder probarlas de forma aislada y
 * rápida (ver src/analysis.test.ts).
 */
import type { WooCommerceProduct, WooCommerceVariation } from "./woocommerceAdapter.js";

export interface CatalogSummary {
  total: number;
  conSku: number;
  sinSku: number;
  conGestionStock: number;
  sinGestionStock: number;
  conStockNumerico: number;
  sinStockNumerico: number;
  conImagenes: number;
  sinImagenes: number;
  conMultiplesImagenes: number;
  conDescripcion: number;
  sinDescripcion: number;
  cantidadCategorias: number;
  categorias: string[];
}

/** Normaliza texto para comparar SKU/nombres sin depender de tildes/mayúsculas/espacios. */
export function normalize(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "") // quita tildes
    .replace(/\s+/g, " ");
}

export function summarizeCatalog(products: WooCommerceProduct[]): CatalogSummary {
  const categoriesSet = new Set<string>();
  let conSku = 0;
  let conGestionStock = 0;
  let conStockNumerico = 0;
  let conImagenes = 0;
  let conMultiplesImagenes = 0;
  let conDescripcion = 0;

  for (const p of products) {
    if (p.sku && p.sku.trim() !== "") conSku++;
    if (p.manage_stock) conGestionStock++;
    if (p.manage_stock && typeof p.stock_quantity === "number") conStockNumerico++;
    if (p.images && p.images.length > 0) conImagenes++;
    if (p.images && p.images.length > 1) conMultiplesImagenes++;
    if (p.description && p.description.trim() !== "") conDescripcion++;
    for (const c of p.categories ?? []) categoriesSet.add(c.name);
  }

  const total = products.length;
  return {
    total,
    conSku,
    sinSku: total - conSku,
    conGestionStock,
    sinGestionStock: total - conGestionStock,
    conStockNumerico,
    sinStockNumerico: total - conStockNumerico,
    conImagenes,
    sinImagenes: total - conImagenes,
    conMultiplesImagenes,
    conDescripcion,
    sinDescripcion: total - conDescripcion,
    cantidadCategorias: categoriesSet.size,
    categorias: Array.from(categoriesSet).sort(),
  };
}

export interface DuplicateGroup {
  criterio: "sku" | "nombre";
  clave: string;
  productos: { woocommerce_id: number; nombre: string; sku: string }[];
}

/**
 * Detecta duplicados: primero por SKU exacto/normalizado cuando existe;
 * los productos ya agrupados por SKU no se vuelven a reportar por nombre
 * (el nombre es solo una segunda señal para los que no tienen SKU).
 */
export function detectDuplicates(products: WooCommerceProduct[]): DuplicateGroup[] {
  const groups: DuplicateGroup[] = [];
  const bySku = new Map<string, WooCommerceProduct[]>();
  const alreadyGrouped = new Set<number>();

  for (const p of products) {
    if (!p.sku || p.sku.trim() === "") continue;
    const key = normalize(p.sku);
    const arr = bySku.get(key) ?? [];
    arr.push(p);
    bySku.set(key, arr);
  }
  for (const [sku, items] of bySku.entries()) {
    if (items.length > 1) {
      groups.push({
        criterio: "sku",
        clave: sku,
        productos: items.map((p) => ({ woocommerce_id: p.id, nombre: p.name, sku: p.sku })),
      });
      items.forEach((p) => alreadyGrouped.add(p.id));
    }
  }

  const byName = new Map<string, WooCommerceProduct[]>();
  for (const p of products) {
    if (alreadyGrouped.has(p.id)) continue;
    const key = normalize(p.name);
    const arr = byName.get(key) ?? [];
    arr.push(p);
    byName.set(key, arr);
  }
  for (const [name, items] of byName.entries()) {
    if (items.length > 1) {
      groups.push({
        criterio: "nombre",
        clave: name,
        productos: items.map((p) => ({ woocommerce_id: p.id, nombre: p.name, sku: p.sku })),
      });
    }
  }

  return groups;
}

export interface BarcodeCandidate {
  key: string;
  productCount: number;
  examples: { woocommerce_id: number; value: unknown }[];
}

const BARCODE_KEY_PATTERN = /barcode|ean|isbn|upc|gtin|c[oó]digo/i;
// Claves que nosotros mismos agregamos al crear el catálogo de prueba — no
// son candidatas reales de código de barras, son trazabilidad del seed.
const INTERNAL_KEYS = new Set(["_lc_test_case", "_lc_seed_source"]);

/**
 * Busca en meta_data claves que PODRÍAN ser un código de barras/EAN/ISBN/UPC/
 * GTIN, sin asumir nunca cuál es la correcta — solo reporta qué claves
 * existen, cuántos productos las tienen, y un par de valores de ejemplo,
 * para que una persona decida.
 */
export function findBarcodeCandidates(products: WooCommerceProduct[]): BarcodeCandidate[] {
  const byKey = new Map<string, { woocommerce_id: number; value: unknown }[]>();
  for (const p of products) {
    for (const meta of p.meta_data ?? []) {
      if (INTERNAL_KEYS.has(meta.key)) continue;
      if (!BARCODE_KEY_PATTERN.test(meta.key)) continue;
      const current = byKey.get(meta.key) ?? [];
      current.push({ woocommerce_id: p.id, value: meta.value });
      byKey.set(meta.key, current);
    }
  }
  return Array.from(byKey.entries()).map(([key, all]) => ({
    key,
    productCount: all.length,
    examples: all.slice(0, 3),
  }));
}

export function productsWithoutSku(products: WooCommerceProduct[]) {
  return products.filter((p) => !p.sku || p.sku.trim() === "");
}

export function productsWithoutStockManagement(products: WooCommerceProduct[]) {
  return products.filter((p) => !p.manage_stock);
}

export function productsWithoutImages(products: WooCommerceProduct[]) {
  return products.filter((p) => !p.images || p.images.length === 0);
}

export function productsWithoutDescription(products: WooCommerceProduct[]) {
  return products.filter((p) => !p.description || p.description.trim() === "");
}

/**
 * Fila resultante de "expandir" un producto "variable" en una fila por
 * variación (mismo criterio ya decidido para el mapper de la Store API
 * pública: "una fila por color"). Los productos "simple" pasan tal cual,
 * solo con los tres campos nuevos en null/false.
 */
export interface ExpandedProductRow extends WooCommerceProduct {
  esVariante: boolean;
  woocommerceParentId: number | null;
  colorVariante: string | null;
}

/**
 * Reemplaza cada producto type:"variable" por una fila por cada una de sus
 * variaciones reales (con SKU/precio/stock de la VARIACIÓN, no del padre —
 * a diferencia de la Store API pública, wc/v3 sí trae estos datos reales por
 * variación). Los productos "simple" quedan igual.
 *
 * Si un producto "variable" no tiene variaciones cargadas en
 * `variationsByProductId` (ej. porque no se pudieron traer, o porque de
 * verdad no tiene ninguna), se deja el producto padre tal cual estaba —
 * nunca se descarta silenciosamente un producto del catálogo.
 *
 * Función pura, sin red — se prueba igual que el resto de este archivo.
 */
export function expandVariableProducts(
  products: WooCommerceProduct[],
  variationsByProductId: Map<number, WooCommerceVariation[]>,
): ExpandedProductRow[] {
  const rows: ExpandedProductRow[] = [];

  for (const p of products) {
    if (p.type !== "variable") {
      rows.push({ ...p, esVariante: false, woocommerceParentId: null, colorVariante: null });
      continue;
    }

    const variations = variationsByProductId.get(p.id) ?? [];
    if (variations.length === 0) {
      rows.push({ ...p, esVariante: false, woocommerceParentId: null, colorVariante: null });
      continue;
    }

    for (const v of variations) {
      const colorAttr = v.attributes?.find((a) => /color/i.test(a.name));
      const colorLabel = colorAttr?.option ?? null;
      rows.push({
        ...p,
        id: v.id,
        sku: v.sku ?? "",
        price: v.price ?? p.price,
        regular_price: v.regular_price ?? p.regular_price,
        sale_price: v.sale_price ?? p.sale_price,
        description: v.description || p.description,
        stock_quantity: v.stock_quantity,
        manage_stock: v.manage_stock,
        stock_status: v.stock_status ?? p.stock_status,
        images: v.image ? [v.image] : p.images,
        name: colorLabel ? `${p.name} - ${colorLabel}` : p.name,
        meta_data: v.meta_data ?? [],
        esVariante: true,
        woocommerceParentId: p.id,
        colorVariante: colorLabel,
      });
    }
  }

  return rows;
}
