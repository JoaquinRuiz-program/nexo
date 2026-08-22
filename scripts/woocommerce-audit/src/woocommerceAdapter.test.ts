import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { createWooCommerceAdapter, WooCommerceAuthError, WooCommerceRequestError } from "./woocommerceAdapter.js";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "content-type": "application/json", ...init.headers },
  });
}

const baseConfig = {
  baseUrl: "http://libreria-central-test.local",
  consumerKey: "ck_test",
  consumerSecret: "cs_test",
  maxRetries: 2,
  timeoutMs: 500,
};

test("conexión correcta: getProduct devuelve el producto y usa autenticación por query en http", async () => {
  let capturedUrl: URL | undefined;
  globalThis.fetch = (async (input: any) => {
    capturedUrl = new URL(String(input));
    return jsonResponse({ id: 42, name: "Cuaderno Torre 100 hojas", sku: "LIB-0001" });
  }) as typeof fetch;

  const adapter = createWooCommerceAdapter(baseConfig);
  const product = await adapter.getProduct(42);

  assert.equal(product.id, 42);
  assert.equal(product.name, "Cuaderno Torre 100 hojas");
  assert.ok(capturedUrl);
  assert.equal(capturedUrl!.searchParams.get("consumer_key"), "ck_test");
  assert.equal(capturedUrl!.searchParams.get("consumer_secret"), "cs_test");
  assert.equal(capturedUrl!.pathname, "/wp-json/wc/v3/products/42");
});

test("https usa cabecera Authorization Basic en vez de query params", async () => {
  let capturedUrl: URL | undefined;
  let capturedHeaders: Record<string, string> | undefined;
  globalThis.fetch = (async (input: any, init?: any) => {
    capturedUrl = new URL(String(input));
    capturedHeaders = init?.headers;
    return jsonResponse({ id: 1, name: "x" });
  }) as typeof fetch;

  const adapter = createWooCommerceAdapter({ ...baseConfig, baseUrl: "https://libreria-real.cl" });
  await adapter.getProduct(1);

  assert.equal(capturedUrl!.searchParams.get("consumer_key"), null);
  const headers = capturedHeaders as Record<string, string>;
  assert.ok(headers.Authorization?.startsWith("Basic "));
});

test("credenciales inválidas (401) lanzan WooCommerceAuthError y NO reintentan", async () => {
  let callCount = 0;
  globalThis.fetch = (async () => {
    callCount++;
    return jsonResponse({ message: "no autorizado" }, { status: 401 });
  }) as typeof fetch;

  const adapter = createWooCommerceAdapter(baseConfig);
  await assert.rejects(() => adapter.getProduct(1), WooCommerceAuthError);
  assert.equal(callCount, 1, "no debería reintentar un error de autenticación");
});

test("catálogo paginado: recorre todas las páginas usando X-WP-Total / X-WP-TotalPages", async () => {
  const pages = [
    [{ id: 1, name: "A" }, { id: 2, name: "B" }],
    [{ id: 3, name: "C" }],
  ];
  let calls = 0;
  globalThis.fetch = (async (input: any) => {
    const url = new URL(String(input));
    const page = Number(url.searchParams.get("page"));
    calls++;
    return jsonResponse(pages[page - 1], {
      headers: { "X-WP-Total": "3", "X-WP-TotalPages": "2" },
    });
  }) as typeof fetch;

  const adapter = createWooCommerceAdapter(baseConfig);
  const progressCalls: [number, number][] = [];
  const all = await adapter.getAllProducts((page, totalPages) => progressCalls.push([page, totalPages]));

  assert.equal(all.length, 3);
  assert.equal(calls, 2);
  assert.deepEqual(
    all.map((p: any) => p.id),
    [1, 2, 3],
  );
  assert.deepEqual(progressCalls, [
    [1, 2],
    [2, 2],
  ]);
});

test("respuesta vacía: catálogo sin productos no rompe getAllProducts", async () => {
  globalThis.fetch = (async () =>
    jsonResponse([], { headers: { "X-WP-Total": "0", "X-WP-TotalPages": "1" } })) as typeof fetch;

  const adapter = createWooCommerceAdapter(baseConfig);
  const all = await adapter.getAllProducts();
  assert.deepEqual(all, []);
});

test("errores 429/5xx se reintentan y terminan bien si un intento posterior funciona", async () => {
  let attempt = 0;
  globalThis.fetch = (async () => {
    attempt++;
    if (attempt < 3) return jsonResponse({}, { status: attempt === 1 ? 429 : 503 });
    return jsonResponse({ id: 1, name: "ok tras reintentos" });
  }) as typeof fetch;

  const adapter = createWooCommerceAdapter({ ...baseConfig, maxRetries: 3 });
  const product = await adapter.getProduct(1);
  assert.equal(product.name, "ok tras reintentos");
  assert.equal(attempt, 3);
});

test("errores 5xx persistentes agotan los reintentos y lanzan WooCommerceRequestError", async () => {
  let attempt = 0;
  globalThis.fetch = (async () => {
    attempt++;
    return jsonResponse({}, { status: 500 });
  }) as typeof fetch;

  const adapter = createWooCommerceAdapter({ ...baseConfig, maxRetries: 2 });
  await assert.rejects(() => adapter.getProduct(1), WooCommerceRequestError);
  assert.equal(attempt, 3); // intento inicial + 2 reintentos
});

test("getAllVariations: pagina las variaciones de un producto 'variable' usando X-WP-TotalPages", async () => {
  const pages = [
    [{ id: 101, sku: "LIB-ROJO", attributes: [{ id: 7, name: "Color", option: "Rojo" }] }],
    [{ id: 102, sku: "LIB-AZUL", attributes: [{ id: 7, name: "Color", option: "Azul" }] }],
  ];
  let capturedUrl: URL | undefined;
  globalThis.fetch = (async (input: any) => {
    capturedUrl = new URL(String(input));
    const page = Number(capturedUrl.searchParams.get("page"));
    return jsonResponse(pages[page - 1], { headers: { "X-WP-Total": "2", "X-WP-TotalPages": "2" } });
  }) as typeof fetch;

  const adapter = createWooCommerceAdapter(baseConfig);
  const progressCalls: [number, number][] = [];
  const variations = await adapter.getAllVariations(3335, (page, totalPages) => progressCalls.push([page, totalPages]));

  assert.equal(variations.length, 2);
  assert.deepEqual(
    variations.map((v) => v.sku),
    ["LIB-ROJO", "LIB-AZUL"],
  );
  assert.equal(capturedUrl!.pathname, "/wp-json/wc/v3/products/3335/variations");
  assert.deepEqual(progressCalls, [
    [1, 2],
    [2, 2],
  ]);
});

test("timeout: una petición que nunca responde termina en WooCommerceRequestError", async () => {
  globalThis.fetch = ((_input: any, init?: any) => {
    return new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        const err = new Error("aborted");
        err.name = "AbortError";
        reject(err);
      });
    });
  }) as typeof fetch;

  const adapter = createWooCommerceAdapter({ ...baseConfig, timeoutMs: 50, maxRetries: 1 });
  await assert.rejects(() => adapter.getProduct(1), WooCommerceRequestError);
});
