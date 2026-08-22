/**
 * WooCommerceAdapter — capa de solo lectura sobre la API REST de
 * administración de WooCommerce (`/wp-json/wc/v3/`).
 *
 * Diseño (ver arquitectura-fase0-decisiones.md, punto 1): este adaptador es
 * la ÚNICA parte del proyecto que sabe hablar el formato de WooCommerce.
 * Nada más debería importar `fetch` contra `/wp-json/...` directamente —
 * así, el día que se necesite otro origen (Mercado Libre, el sistema físico,
 * o nuestra propia base de datos como fuente de verdad), se agrega un
 * adaptador nuevo con la misma forma, sin tocar el código que ya consume
 * este.
 *
 * Mismo motivo por el que este archivo sirve TANTO para el WooCommerce de
 * prueba local (LocalWP) COMO para el WooCommerce real de la librería más
 * adelante: no hay nada aquí específico de un entorno u otro, todo llega
 * por configuración (URL + credenciales).
 *
 * IMPORTANTE — alcance de esta fase: solo lectura. Deliberadamente NO se
 * implementa getOrders() todavía (se agregará en una fase posterior, junto
 * con el resto de la lógica de pedidos) ni ninguna operación de escritura
 * (createProduct/updateProduct/deleteProduct/updateStock). Esas firmas
 * quedan documentadas más abajo como referencia futura, sin cuerpo.
 */

export interface WooCommerceConfig {
  /** URL base del sitio, sin barra final. Ej: http://libreria-central-test.local */
  baseUrl: string;
  consumerKey: string;
  consumerSecret: string;
  /** Timeout por request, en ms. Default: 15000. */
  timeoutMs?: number;
  /** Reintentos máximos ante 429/5xx/timeout. Default: 3. */
  maxRetries?: number;
  /**
   * Cómo autenticar. Por defecto se decide solo según el protocolo de
   * baseUrl: "basic" (cabecera Authorization) si es https, "query"
   * (?consumer_key=...&consumer_secret=...) si es http — que es lo que
   * WooCommerce documenta como método soportado cuando no hay HTTPS
   * disponible (como suele pasar en un sitio local de desarrollo).
   */
  authMethod?: "basic" | "query";
}

export interface WooCommerceImage {
  id: number;
  src: string;
  name?: string;
  alt?: string;
}

export interface WooCommerceCategoryRef {
  id: number;
  name: string;
  slug: string;
}

export interface WooCommerceMetaData {
  id: number;
  key: string;
  value: unknown;
}

/**
 * Forma de un producto tal como lo devuelve WooCommerce. Se declaran los
 * campos que sabemos que vamos a usar, pero se conserva cualquier campo
 * adicional (índice abierto) para no descartar información — igual que
 * pedía el plan: "no descartar información todavía".
 */
export interface WooCommerceProduct {
  id: number;
  sku: string;
  name: string;
  slug: string;
  status: string;
  /**
   * "simple" | "variable" | "grouped" | "external" (campo real de WooCommerce).
   * Importa especialmente "variable": ese producto NO trae su propio SKU/
   * precio/stock reales en este mismo registro — viven en sus variaciones
   * (ver getVariationsPage/getAllVariations más abajo). Antes de agregar este
   * campo, el resto del script no tenía forma de distinguir un producto
   * "variable" de uno "simple", y los contaba igual — lo cual subestima
   * SKU/stock reales en cualquier catálogo con variantes (color, talla, etc.).
   */
  type: string;
  price: string;
  regular_price: string;
  sale_price: string;
  description: string;
  short_description: string;
  stock_quantity: number | null;
  manage_stock: boolean;
  stock_status: string;
  categories: WooCommerceCategoryRef[];
  images: WooCommerceImage[];
  meta_data: WooCommerceMetaData[];
  date_created: string;
  date_modified: string;
  [extra: string]: unknown;
}

export interface WooCommerceCategory {
  id: number;
  name: string;
  slug: string;
  count: number;
  parent: number;
}

export interface WooCommerceVariationAttribute {
  id: number;
  name: string;
  /** El valor legible del atributo para ESTA variación (ej. "Rojo"), no el slug. */
  option: string;
}

/**
 * Forma real de una variación de un producto "variable" en `wc/v3`
 * (`/products/{id}/variations`). A diferencia de la Store API pública (que
 * solo expone `{ id, attributes }` por variación), esta sí trae SKU, precio
 * y stock reales — es la razón por la que necesitamos la clave de
 * administración para completar lo que la muestra pública dejó pendiente.
 */
export interface WooCommerceVariation {
  id: number;
  sku: string;
  price: string;
  regular_price: string;
  sale_price: string;
  description: string;
  stock_quantity: number | null;
  manage_stock: boolean;
  stock_status: string;
  image: WooCommerceImage | null;
  attributes: WooCommerceVariationAttribute[];
  meta_data: WooCommerceMetaData[];
  date_created: string;
  date_modified: string;
  [extra: string]: unknown;
}

export interface PagedResult<T> {
  items: T[];
  total: number;
  totalPages: number;
  page: number;
}

export class WooCommerceAuthError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "WooCommerceAuthError";
  }
}

export class WooCommerceRequestError extends Error {
  constructor(
    message: string,
    public status?: number,
    public attempts?: number,
  ) {
    super(message);
    this.name = "WooCommerceRequestError";
  }
}

const DEFAULT_TIMEOUT_MS = 15_000;
const DEFAULT_MAX_RETRIES = 3;
const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Backoff exponencial con un poco de jitter, capado a 8s. */
export function backoffDelayMs(attempt: number): number {
  const base = Math.min(8000, 300 * 2 ** attempt);
  const jitter = Math.random() * 200;
  return base + jitter;
}

function resolveAuthMethod(cfg: WooCommerceConfig): "basic" | "query" {
  if (cfg.authMethod) return cfg.authMethod;
  return cfg.baseUrl.startsWith("https://") ? "basic" : "query";
}

function buildUrl(
  cfg: WooCommerceConfig,
  path: string,
  params: Record<string, string | number | undefined> = {},
): URL {
  const url = new URL(cfg.baseUrl.replace(/\/+$/, "") + "/wp-json/wc/v3" + path);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }
  if (resolveAuthMethod(cfg) === "query") {
    url.searchParams.set("consumer_key", cfg.consumerKey);
    url.searchParams.set("consumer_secret", cfg.consumerSecret);
  }
  return url;
}

function buildHeaders(cfg: WooCommerceConfig): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (resolveAuthMethod(cfg) === "basic") {
    const token = Buffer.from(`${cfg.consumerKey}:${cfg.consumerSecret}`).toString("base64");
    headers.Authorization = `Basic ${token}`;
  }
  return headers;
}

/**
 * GET con reintentos/backoff para 429 y 5xx, y timeout por intento.
 * Los errores de autenticación (401/403) NO se reintentan — reintentar una
 * clave inválida no la va a arreglar.
 *
 * Nunca registra (console.log/error) la URL completa cuando la autenticación
 * es por query string, para no filtrar las credenciales a los logs.
 */
async function requestWithRetry(
  url: URL,
  headers: Record<string, string>,
  opts: { timeoutMs: number; maxRetries: number },
): Promise<Response> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= opts.maxRetries; attempt++) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), opts.timeoutMs);
    try {
      const response = await fetch(url, { headers, signal: controller.signal });
      clearTimeout(timeout);

      if (response.status === 401 || response.status === 403) {
        // El cuerpo de la respuesta de WordPress/WooCommerce trae un código
        // específico (p.ej. "woocommerce_rest_authentication_error",
        // "rest_forbidden", "rest_no_route") que dice MUCHO más que un 401
        // pelado — no son credenciales inválidas en todos los casos, a
        // veces es un problema de capacidades del usuario, de rutas, o del
        // servidor. Se muestra tal cual (no contiene datos sensibles: es la
        // respuesta pública del servidor, no algo que nosotros enviamos).
        let bodyDetail = "";
        try {
          const bodyText = await response.clone().text();
          if (bodyText) bodyDetail = ` Respuesta del servidor: ${bodyText.slice(0, 500)}`;
        } catch {
          // Si el cuerpo no se puede leer, seguimos solo con el status.
        }
        throw new WooCommerceAuthError(
          `Autenticación rechazada (HTTP ${response.status}).${bodyDetail}`,
          response.status,
        );
      }

      if (RETRYABLE_STATUS.has(response.status) && attempt < opts.maxRetries) {
        await sleep(backoffDelayMs(attempt));
        continue;
      }

      if (!response.ok) {
        throw new WooCommerceRequestError(
          `WooCommerce respondió HTTP ${response.status} en ${url.pathname}`,
          response.status,
          attempt + 1,
        );
      }

      return response;
    } catch (err) {
      clearTimeout(timeout);
      if (err instanceof WooCommerceAuthError) throw err;
      lastError = err;
      const isAbort = err instanceof Error && err.name === "AbortError";
      if (attempt < opts.maxRetries) {
        await sleep(backoffDelayMs(attempt));
        continue;
      }
      if (isAbort) {
        throw new WooCommerceRequestError(
          `Timeout después de ${opts.timeoutMs}ms contactando ${url.pathname} (${attempt + 1} intentos)`,
          undefined,
          attempt + 1,
        );
      }
      throw err;
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

export function createWooCommerceAdapter(config: WooCommerceConfig) {
  const cfg: Required<Pick<WooCommerceConfig, "timeoutMs" | "maxRetries">> & WooCommerceConfig = {
    timeoutMs: config.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    maxRetries: config.maxRetries ?? DEFAULT_MAX_RETRIES,
    ...config,
  };

  async function getProduct(id: number): Promise<WooCommerceProduct> {
    const url = buildUrl(cfg, `/products/${id}`);
    const res = await requestWithRetry(url, buildHeaders(cfg), cfg);
    return (await res.json()) as WooCommerceProduct;
  }

  async function getProductsPage(page: number, perPage = 100): Promise<PagedResult<WooCommerceProduct>> {
    const url = buildUrl(cfg, "/products", { page, per_page: perPage, status: "any" });
    const res = await requestWithRetry(url, buildHeaders(cfg), cfg);
    const items = (await res.json()) as WooCommerceProduct[];
    const total = Number(res.headers.get("X-WP-Total") ?? items.length);
    const totalPages = Number(res.headers.get("X-WP-TotalPages") ?? 1);
    return { items, total, totalPages, page };
  }

  /**
   * Trae el catálogo completo recorriendo todas las páginas (per_page=100),
   * usando X-WP-Total / X-WP-TotalPages para saber cuándo parar — nunca
   * asume una cantidad fija de productos. Pausa breve entre páginas para no
   * saturar el sitio.
   */
  async function getAllProducts(onProgress?: (page: number, totalPages: number) => void): Promise<WooCommerceProduct[]> {
    const all: WooCommerceProduct[] = [];
    let page = 1;
    let totalPages = 1;
    do {
      const result = await getProductsPage(page, 100);
      all.push(...result.items);
      totalPages = result.totalPages || 1;
      onProgress?.(page, totalPages);
      page += 1;
      if (page <= totalPages) await sleep(300);
    } while (page <= totalPages);
    return all;
  }

  /**
   * Trae una página de variaciones de un producto "variable" específico.
   * Mismo patrón exacto que getProductsPage (misma paginación por
   * X-WP-Total/X-WP-TotalPages, mismos reintentos/timeout/auth) — WooCommerce
   * pagina este endpoint igual que /products.
   */
  async function getVariationsPage(productId: number, page: number, perPage = 100): Promise<PagedResult<WooCommerceVariation>> {
    const url = buildUrl(cfg, `/products/${productId}/variations`, { page, per_page: perPage });
    const res = await requestWithRetry(url, buildHeaders(cfg), cfg);
    const items = (await res.json()) as WooCommerceVariation[];
    const total = Number(res.headers.get("X-WP-Total") ?? items.length);
    const totalPages = Number(res.headers.get("X-WP-TotalPages") ?? 1);
    return { items, total, totalPages, page };
  }

  /**
   * Trae TODAS las variaciones de un producto "variable", recorriendo
   * páginas igual que getAllProducts. La mayoría de los productos "variable"
   * de este catálogo tienen pocas variaciones (por color), así que esto
   * normalmente es una sola página — pero no se asume, se pagina igual.
   */
  async function getAllVariations(
    productId: number,
    onProgress?: (page: number, totalPages: number) => void,
  ): Promise<WooCommerceVariation[]> {
    const all: WooCommerceVariation[] = [];
    let page = 1;
    let totalPages = 1;
    do {
      const result = await getVariationsPage(productId, page, 100);
      all.push(...result.items);
      totalPages = result.totalPages || 1;
      onProgress?.(page, totalPages);
      page += 1;
      if (page <= totalPages) await sleep(300);
    } while (page <= totalPages);
    return all;
  }

  async function getCategories(): Promise<WooCommerceCategory[]> {
    const all: WooCommerceCategory[] = [];
    let page = 1;
    // El catálogo de categorías suele ser chico, pero igual paginamos por
    // si acaso — mismo criterio que productos, sin asumir un total fijo.
    for (;;) {
      const url = buildUrl(cfg, "/products/categories", { page, per_page: 100 });
      const res = await requestWithRetry(url, buildHeaders(cfg), cfg);
      const items = (await res.json()) as WooCommerceCategory[];
      all.push(...items);
      const totalPages = Number(res.headers.get("X-WP-TotalPages") ?? 1);
      if (page >= totalPages || items.length === 0) break;
      page += 1;
      await sleep(300);
    }
    return all;
  }

  async function getStock(productId: number): Promise<{ manage_stock: boolean; stock_quantity: number | null; stock_status: string }> {
    const product = await getProduct(productId);
    return {
      manage_stock: product.manage_stock,
      stock_quantity: product.stock_quantity,
      stock_status: product.stock_status,
    };
  }

  // ---------------------------------------------------------------------
  // NO IMPLEMENTADO TODAVÍA (a propósito, ver cabecera del archivo).
  // Firmas de referencia para fases posteriores — no se llaman desde
  // ningún lado en esta fase, y no deben implementarse sin aprobación
  // explícita, porque implican escritura.
  // ---------------------------------------------------------------------
  // async function getOrders(): Promise<never> { throw new Error("No implementado: fuera de alcance de la Fase 2 (solo catálogo)."); }
  // async function createProduct(): Promise<never> { throw new Error("No implementado: requiere permisos de escritura, no aprobados todavía."); }
  // async function updateProduct(): Promise<never> { throw new Error("No implementado: requiere permisos de escritura, no aprobados todavía."); }
  // async function deleteProduct(): Promise<never> { throw new Error("No implementado: requiere permisos de escritura, no aprobados todavía."); }
  // async function updateStock(): Promise<never> { throw new Error("No implementado: requiere permisos de escritura, no aprobados todavía."); }

  return { getProduct, getProductsPage, getAllProducts, getCategories, getStock, getVariationsPage, getAllVariations };
}

export type WooCommerceAdapter = ReturnType<typeof createWooCommerceAdapter>;
