/**
 * Script de auditoría de SOLO LECTURA del catálogo de WooCommerce.
 *
 * Uso:
 *   npm run audit
 * (lee la configuración desde .env — ver .env.example)
 *
 * Qué hace, en orden:
 *   1. Valida que estén las tres variables de entorno necesarias.
 *   2. Trae UN producto de muestra primero, e inspecciona su meta_data
 *      (para descubrir campos como código de barras sin asumir nombres).
 *   3. Trae el catálogo completo, paginado.
 *   4. Trae las categorías.
 *   5. Calcula estadísticas, duplicados y candidatas a código de barras.
 *   6. Escribe todo en reports/woocommerce-audit/.
 *   7. Imprime un resumen en pantalla.
 *
 * No escribe nada en WooCommerce. No genera ni modifica ningún SKU. No
 * imprime ni guarda el Consumer Secret en ningún reporte ni log.
 */
import { config as loadDotenv } from "dotenv";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createWooCommerceAdapter, WooCommerceAuthError, type WooCommerceProduct, type WooCommerceVariation } from "./woocommerceAdapter.js";
import {
  detectDuplicates,
  expandVariableProducts,
  findBarcodeCandidates,
  productsWithoutDescription,
  productsWithoutImages,
  productsWithoutSku,
  productsWithoutStockManagement,
  summarizeCatalog,
  type ExpandedProductRow,
} from "./analysis.js";
import { toCsv } from "./csv.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPORTS_DIR = path.resolve(__dirname, "..", "..", "..", "reports", "woocommerce-audit");

// `.env` se busca SIEMPRE junto a este script (src/../.env, es decir
// scripts/woocommerce-audit/.env) — nunca según el directorio desde el que
// se haya invocado `npm run audit`. Antes se usaba el `.env` "por defecto"
// de dotenv, que busca en `process.cwd()`: si el comando se corre desde
// otra carpeta (la raíz del proyecto, una tarea de un editor, etc.), dotenv
// no encuentra ningún archivo, pero el script no falla con un error claro
// de "falta la variable" — sigue de largo con lo que haya en
// `process.env`, incluyendo variables sueltas que hayan quedado de una
// sesión de terminal anterior (`set WOOCOMMERCE_CONSUMER_KEY=...`, un
// perfil de PowerShell, etc.), que dotenv NO sobrescribe por defecto. Con
// ruta explícita + `override: true`, el `.env` de este proyecto manda
// siempre, sin depender de dónde se ejecutó el comando ni de qué haya
// quedado en el entorno de la terminal.
const ENV_PATH = path.resolve(__dirname, "..", ".env");
const dotenvResult = loadDotenv({ path: ENV_PATH, override: true });

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    console.error(`Falta la variable de entorno ${name}. Copia .env.example a .env y complétalo.`);
    process.exit(1);
  }
  return value;
}

/**
 * Enmascara un valor sensible dejando ver solo largo + primeros/últimos
 * caracteres — suficiente para detectar un typo o una clave equivocada sin
 * imprimir el secreto completo en la terminal.
 */
function maskSecret(value: string, visibleEdge = 4): string {
  if (value.length <= visibleEdge * 2) return "*".repeat(value.length);
  return `${value.slice(0, visibleEdge)}${"*".repeat(value.length - visibleEdge * 2)}${value.slice(-visibleEdge)} (${value.length} caracteres)`;
}

/**
 * Diagnóstico de arranque: de dónde se cargó .env y qué credenciales quedaron
 * en process.env después de cargarlo — enmascaradas, nunca el secreto
 * completo. Sirve para descartar de un vistazo variables sueltas del
 * entorno o un .env cargado desde el lugar equivocado.
 */
function printEnvDiagnostics(): void {
  if (dotenvResult.error) {
    console.warn(`⚠ No se encontró .env en ${ENV_PATH} (${dotenvResult.error.message}).`);
    console.warn("  El script va a usar solo lo que ya esté en el entorno del proceso, si es que hay algo.");
  } else {
    console.log(`.env cargado desde: ${ENV_PATH}`);
  }
  console.log(`  WOOCOMMERCE_URL=${process.env.WOOCOMMERCE_URL ?? "(no definida)"}`);
  console.log(
    `  WOOCOMMERCE_CONSUMER_KEY=${process.env.WOOCOMMERCE_CONSUMER_KEY ? maskSecret(process.env.WOOCOMMERCE_CONSUMER_KEY) : "(no definida)"}`,
  );
  console.log(
    `  WOOCOMMERCE_CONSUMER_SECRET=${process.env.WOOCOMMERCE_CONSUMER_SECRET ? maskSecret(process.env.WOOCOMMERCE_CONSUMER_SECRET) : "(no definida)"}`,
  );
}

function productRow(p: WooCommerceProduct) {
  return {
    woocommerce_id: p.id,
    sku: p.sku,
    nombre: p.name,
    estado: p.status,
    precio: p.price,
    precio_regular: p.regular_price,
    stock_gestionado: p.manage_stock,
    stock_cantidad: p.stock_quantity ?? "",
    stock_estado: p.stock_status,
    categorias: (p.categories ?? []).map((c) => c.name).join(" | "),
    cantidad_imagenes: (p.images ?? []).length,
    tiene_descripcion: Boolean(p.description && p.description.trim() !== ""),
    fecha_creacion: p.date_created,
    fecha_modificacion: p.date_modified,
  };
}

// Igual que productRow, pero agrega las tres columnas nuevas que distinguen
// una fila "de color" (expandida desde un producto "variable") de un
// producto normal — necesarias para no confundir ambos casos al revisar
// catalog-expandido.csv.
function expandedProductRow(p: ExpandedProductRow) {
  return {
    ...productRow(p),
    tipo_woocommerce: p.type,
    es_variante_de_color: p.esVariante,
    woocommerce_id_padre: p.woocommerceParentId ?? "",
    color_variante: p.colorVariante ?? "",
  };
}

async function main() {
  printEnvDiagnostics();

  const baseUrl = requireEnv("WOOCOMMERCE_URL");
  const consumerKey = requireEnv("WOOCOMMERCE_CONSUMER_KEY");
  const consumerSecret = requireEnv("WOOCOMMERCE_CONSUMER_SECRET");
  // Opcional: fuerza el método de autenticación en vez de decidirlo por el
  // esquema de la URL (ver resolveAuthMethod en woocommerceAdapter.ts).
  // Sirve para el caso conocido de algunos servidores locales (Nginx/PHP-FPM
  // sin `fastcgi_param HTTP_AUTHORIZATION $http_authorization;`) que
  // descartan la cabecera Authorization incluso en sitios https — ahí,
  // forzar "query" evita depender de esa cabecera.
  const authMethodEnv = process.env.WOOCOMMERCE_AUTH_METHOD;
  if (authMethodEnv && authMethodEnv !== "basic" && authMethodEnv !== "query") {
    console.error(`WOOCOMMERCE_AUTH_METHOD debe ser "basic" o "query" (valor recibido: "${authMethodEnv}").`);
    process.exit(1);
  }
  const authMethod = authMethodEnv as "basic" | "query" | undefined;
  const resolvedAuthMethod = authMethod ?? (baseUrl.startsWith("https://") ? "basic" : "query");
  console.log(
    `  Método de autenticación: ${resolvedAuthMethod}${authMethod ? " (forzado por WOOCOMMERCE_AUTH_METHOD)" : " (automático según el esquema de la URL)"}`,
  );

  const adapter = createWooCommerceAdapter({ baseUrl, consumerKey, consumerSecret, authMethod });

  console.log(`Conectando a ${baseUrl} ...`);

  // Paso 1: un producto de muestra primero, para inspeccionar meta_data
  // antes de asumir nada sobre el catálogo completo.
  let sample: WooCommerceProduct[];
  try {
    sample = (await adapter.getProductsPage(1, 1)).items;
  } catch (err) {
    if (err instanceof WooCommerceAuthError) {
      console.error(`✗ Autenticación falló: ${err.message}`);
      process.exit(1);
    }
    console.error(`✗ No se pudo conectar a WooCommerce: ${(err as Error).message}`);
    process.exit(1);
  }

  if (sample.length === 0) {
    console.warn("El sitio respondió correctamente pero no devolvió ningún producto (catálogo vacío).");
  } else {
    console.log(`✓ Conexión y autenticación OK. Producto de muestra: "${sample[0]!.name}" (id ${sample[0]!.id})`);
    console.log(`  meta_data de muestra: ${JSON.stringify(sample[0]!.meta_data ?? [], null, 2)}`);
  }

  // Paso 2: catálogo completo, paginado.
  const products = await adapter.getAllProducts((page, totalPages) => {
    console.log(`  página ${page}/${totalPages}...`);
  });
  console.log(`✓ Catálogo completo importado: ${products.length} productos.`);

  // Paso 2b: variaciones de cada producto "variable".
  //
  // Un producto type:"variable" (ej. el mismo cuaderno en varios colores) NO
  // trae su propio SKU/precio/stock reales en el registro que acabamos de
  // traer en el Paso 2 — WooCommerce los guarda en sus variaciones
  // (/products/{id}/variations), un endpoint aparte. Sin este paso, el
  // resumen contaría cada producto "variable" como "sin SKU" y "sin stock",
  // aunque cada color sí tenga SKU y stock reales cargados. Se confirmó este
  // comportamiento antes de escribir este código, probando la Store API
  // pública contra la tienda real: 11 de 30 productos de una muestra eran
  // "variable", y su SKU/stock por color solo existen en este endpoint de
  // administración (la Store API pública no los expone).
  const variableProducts = products.filter((p) => p.type === "variable");
  const variationsByProductId = new Map<number, WooCommerceVariation[]>();
  if (variableProducts.length > 0) {
    console.log(`\nTrayendo variaciones de ${variableProducts.length} productos "variable"...`);
    let procesados = 0;
    for (const parent of variableProducts) {
      try {
        const variations = await adapter.getAllVariations(parent.id);
        variationsByProductId.set(parent.id, variations);
      } catch (err) {
        // No abortamos toda la auditoría por un producto puntual: lo dejamos
        // sin variaciones (expandVariableProducts lo deja como padre, sin
        // descartarlo) y seguimos con el resto.
        console.warn(`  ⚠ No se pudieron traer las variaciones de "${parent.name}" (id ${parent.id}): ${(err as Error).message}`);
      }
      procesados += 1;
      console.log(`  ${procesados}/${variableProducts.length} productos "variable" procesados...`);
    }
  }

  // Paso 2c: expandir "variable" en una fila por color — mismo criterio ya
  // decidido para el experimento de la Store API pública. A partir de aquí,
  // todo el análisis usa `expandedProducts`, no `products`, para que las
  // estadísticas reflejen SKU/stock reales por variante en vez de contarlos
  // como faltantes a nivel del producto padre.
  const expandedProducts = expandVariableProducts(products, variationsByProductId);
  const variantesGeneradas = expandedProducts.filter((p) => p.esVariante).length;
  console.log(
    `✓ Catálogo expandido: ${products.length} productos originales → ${expandedProducts.length} filas ` +
      `(${variantesGeneradas} filas nuevas por color, de ${variableProducts.length} productos "variable").`,
  );

  // Paso 3: categorías.
  const categories = await adapter.getCategories();

  // Paso 4: análisis — sobre el catálogo EXPANDIDO, no sobre `products` en
  // bruto (ver Paso 2c).
  const summary = summarizeCatalog(expandedProducts);
  const duplicates = detectDuplicates(expandedProducts);
  const barcodeCandidates = findBarcodeCandidates(expandedProducts);
  const withoutSku = productsWithoutSku(expandedProducts);
  const withoutStockMgmt = productsWithoutStockManagement(expandedProducts);
  const withoutImages = productsWithoutImages(expandedProducts);
  const withoutDescription = productsWithoutDescription(expandedProducts);

  // Paso 5: reportes.
  await mkdir(REPORTS_DIR, { recursive: true });

  // catalog.json / catalog.csv: el catálogo TAL COMO lo devuelve WooCommerce,
  // sin expandir — un producto "variable" aparece como un solo registro, sin
  // SKU/stock reales (viven en sus variaciones). Se conserva así, sin tocar,
  // para quien quiera ver la respuesta original de la API.
  await writeFile(path.join(REPORTS_DIR, "catalog.json"), JSON.stringify(products, null, 2));
  await writeFile(path.join(REPORTS_DIR, "catalog.csv"), toCsv(products.map(productRow)));

  // catalog-expandido.json / catalog-expandido.csv: el catálogo real para
  // trabajar — cada color de un producto "variable" como su propia fila, con
  // su SKU/precio/stock real. Todas las estadísticas de abajo (summary,
  // duplicados, sin-SKU, etc.) se calculan sobre ESTE catálogo.
  await writeFile(path.join(REPORTS_DIR, "catalog-expandido.json"), JSON.stringify(expandedProducts, null, 2));
  await writeFile(path.join(REPORTS_DIR, "catalog-expandido.csv"), toCsv(expandedProducts.map(expandedProductRow)));

  await writeFile(
    path.join(REPORTS_DIR, "summary.json"),
    JSON.stringify(
      {
        generadoEn: new Date().toISOString(),
        origen: baseUrl,
        nota: "Estadísticas calculadas sobre el catálogo expandido (una fila por color en productos 'variable'), no sobre la respuesta cruda de WooCommerce.",
        productosOriginalesWooCommerce: products.length,
        productosVariable: variableProducts.length,
        filasGeneradasPorColor: variantesGeneradas,
        ...summary,
        categoriasWooCommerce: categories.map((c) => ({ nombre: c.name, cantidadProductos: c.count })),
        posiblesDuplicados: duplicates.length,
      },
      null,
      2,
    ),
  );
  await writeFile(path.join(REPORTS_DIR, "products-without-sku.csv"), toCsv(withoutSku.map(productRow)));
  await writeFile(path.join(REPORTS_DIR, "products-without-stock-management.csv"), toCsv(withoutStockMgmt.map(productRow)));
  await writeFile(path.join(REPORTS_DIR, "products-without-images.csv"), toCsv(withoutImages.map(productRow)));
  await writeFile(path.join(REPORTS_DIR, "products-without-description.csv"), toCsv(withoutDescription.map(productRow)));
  await writeFile(
    path.join(REPORTS_DIR, "possible-duplicates.csv"),
    toCsv(
      duplicates.flatMap((g) =>
        g.productos.map((p) => ({ criterio: g.criterio, clave: g.clave, woocommerce_id: p.woocommerce_id, nombre: p.nombre, sku: p.sku })),
      ),
    ),
  );
  await writeFile(path.join(REPORTS_DIR, "barcode-analysis.json"), JSON.stringify(barcodeCandidates, null, 2));

  // Paso 6: resumen en pantalla.
  console.log("\n===== RESUMEN DE LA AUDITORÍA =====");
  console.log(`Productos originales en WooCommerce: ${products.length} (${variableProducts.length} son "variable")`);
  console.log(`Filas tras expandir por color:        ${expandedProducts.length} (+${variantesGeneradas})`);
  console.log(`Total productos:            ${summary.total}`);
  console.log(`Con SKU:                    ${summary.conSku}`);
  console.log(`Sin SKU:                    ${summary.sinSku}`);
  console.log(`Con gestión de stock:       ${summary.conGestionStock}`);
  console.log(`Sin gestión de stock:       ${summary.sinGestionStock}`);
  console.log(`Con stock numérico:         ${summary.conStockNumerico}`);
  console.log(`Sin stock numérico:         ${summary.sinStockNumerico}`);
  console.log(`Con imágenes:               ${summary.conImagenes}`);
  console.log(`Sin imágenes:               ${summary.sinImagenes}`);
  console.log(`Con múltiples imágenes:     ${summary.conMultiplesImagenes}`);
  console.log(`Con descripción:            ${summary.conDescripcion}`);
  console.log(`Sin descripción:            ${summary.sinDescripcion}`);
  console.log(`Categorías (${summary.cantidadCategorias}): ${summary.categorias.join(", ")}`);

  console.log(`\nPosibles duplicados: ${duplicates.length}`);
  for (const g of duplicates) {
    console.log(`\nPOSIBLE DUPLICADO (${g.criterio})`);
    console.log(`${g.criterio === "sku" ? "SKU" : "Nombre"}: ${g.clave}`);
    g.productos.forEach((p, i) => {
      console.log(`Producto ${String.fromCharCode(65 + i)}: ${p.nombre}`);
      console.log(`WooCommerce ID: ${p.woocommerce_id}`);
    });
  }

  console.log(`\nClaves candidatas a código de barras encontradas en meta_data: ${barcodeCandidates.length}`);
  for (const c of barcodeCandidates) {
    console.log(`- "${c.key}": presente en ${c.productCount} producto(s). Ejemplos: ${JSON.stringify(c.examples)}`);
  }
  if (barcodeCandidates.length === 0) {
    console.log("  (ninguna clave con nombre reconocible — no se encontró código de barras en este catálogo)");
  }

  console.log(`\nReportes escritos en: ${REPORTS_DIR}`);
}

main().catch((err) => {
  console.error("Error inesperado en la auditoría:", err);
  process.exit(1);
});
