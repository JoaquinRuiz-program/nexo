import type { MercadoLibrePublicationInfo, Product } from '@/types/product';

// ---------------------------------------------------------------------------
// INTEGRACIÓN CON MERCADO LIBRE — todavía no conectada.
//
// Todas las funciones de este archivo son simulaciones (mock): no hacen
// ninguna llamada de red real, pero sí calculan resultados dinámicos
// (validación, IDs de publicación, historial) para que el resto de la app
// pueda construir un flujo de publicación completo y funcional.
//
// Cuando conectemos la API oficial de Mercado Libre en la Fase 3, solo este
// archivo debería cambiar — reemplazando cada cuerpo de función por la
// llamada real (OAuth, POST /items, etc.) y manteniendo la misma firma.
// Nada en componentes ni páginas debería necesitar cambios.
// ---------------------------------------------------------------------------

export interface MercadoLibreResult {
  ok: boolean;
  mensaje: string;
}

export interface PublishResult extends MercadoLibreResult {
  publicacion?: MercadoLibrePublicationInfo;
}

export type ValidationSeverity = 'ok' | 'warn' | 'error';

export interface ValidationCheck {
  id: string;
  label: string;
  severity: ValidationSeverity;
  detalle?: string;
}

export interface ValidationResult {
  checks: ValidationCheck[];
  resultado: 'listo' | 'revision' | 'bloqueado';
}

function fakeNetworkDelay(ms = 300): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// -------------------------------------------------------------------------
// Conexión (mock) — hoy siempre desconectada.
// -------------------------------------------------------------------------

export function isConnected(): boolean {
  return false;
}

export async function connectMercadoLibre(): Promise<MercadoLibreResult> {
  await fakeNetworkDelay(200);
  return { ok: false, mensaje: 'Disponible en la próxima versión.' };
}

// -------------------------------------------------------------------------
// Validación previa a publicar. No requiere red: son reglas locales, pero
// se expone acá porque en Fase 3 Mercado Libre podría rechazar la
// publicación con sus propias reglas — este es el lugar donde se
// combinarían ambas.
// -------------------------------------------------------------------------

export function validateProductForPublication(product: Product): ValidationResult {
  const checks: ValidationCheck[] = [];

  checks.push({ id: 'titulo', label: 'Título válido', severity: product.nombre.trim().length >= 5 ? 'ok' : 'error' });
  checks.push({ id: 'precio', label: 'Precio válido', severity: product.precio > 0 ? 'ok' : 'error' });
  checks.push({
    id: 'stock',
    label: 'Stock válido',
    severity: product.stock > 0 ? 'ok' : 'warn',
    detalle: product.stock > 0 ? undefined : 'El stock está en 0.',
  });
  checks.push({ id: 'categoria', label: 'Categoría definida', severity: product.categoria ? 'ok' : 'error' });
  checks.push({ id: 'marca', label: 'Marca definida', severity: product.marca?.trim() ? 'ok' : 'warn' });
  checks.push({
    id: 'descripcion',
    label: 'Descripción disponible',
    severity: product.descripcion?.trim() ? 'ok' : 'error',
  });
  checks.push({
    id: 'imagen',
    label: 'Imagen principal disponible',
    severity: product.imagenUrl ? 'ok' : 'error',
    detalle: product.imagenUrl ? undefined : 'Falta imagen principal.',
  });
  checks.push({ id: 'sku', label: 'SKU disponible', severity: product.sku?.trim() ? 'ok' : 'error' });
  checks.push({
    id: 'atributos',
    label: 'Atributos básicos completos',
    severity: product.atributos.length > 0 ? 'ok' : 'warn',
    detalle: product.atributos.length > 0 ? undefined : 'No hay características cargadas todavía.',
  });

  const hasError = checks.some((c) => c.severity === 'error');
  const hasWarn = checks.some((c) => c.severity === 'warn');
  const resultado: ValidationResult['resultado'] = hasError ? 'bloqueado' : hasWarn ? 'revision' : 'listo';

  return { checks, resultado };
}

// -------------------------------------------------------------------------
// Generación de ID de publicación simulado (único por sesión).
// -------------------------------------------------------------------------

const usedIds = new Set<string>();

export function generateMercadoLibreId(): string {
  let id: string;
  do {
    const n = Math.floor(100000 + Math.random() * 900000);
    id = `ML-${n}`;
  } while (usedIds.has(id));
  usedIds.add(id);
  return id;
}

// -------------------------------------------------------------------------
// Publicación individual y masiva.
// -------------------------------------------------------------------------

export async function publishProduct(product: Product): Promise<PublishResult> {
  const validation = validateProductForPublication(product);
  if (validation.resultado === 'bloqueado') {
    return { ok: false, mensaje: 'Este producto necesita correcciones antes de poder publicarse.' };
  }

  await fakeNetworkDelay(500);

  const now = new Date().toISOString();
  const publicacion: MercadoLibrePublicationInfo = {
    id: generateMercadoLibreId(),
    publicadoEn: now,
    precioPublicado: product.precio,
    stockPublicado: product.stock,
    estadoPublicacion: 'publicado',
    historial: [
      { id: `h-${Date.now()}`, fecha: now, mensaje: 'Publicación creada', precio: product.precio, stock: product.stock },
    ],
  };

  return { ok: true, mensaje: 'Publicación creada.', publicacion };
}

// Publica una lista de productos en secuencia, reportando avance —
// consumido por la pantalla "Publicación masiva".
export async function publishProducts(
  products: Product[],
  onProgress?: (done: number, total: number, product: Product, result: PublishResult) => void,
): Promise<Map<string, PublishResult>> {
  const results = new Map<string, PublishResult>();
  for (let i = 0; i < products.length; i++) {
    const result = await publishProduct(products[i]);
    results.set(products[i].id, result);
    onProgress?.(i + 1, products.length, products[i], result);
  }
  return results;
}

// -------------------------------------------------------------------------
// Sincronización de precio/stock/datos de una publicación existente.
// -------------------------------------------------------------------------

export async function updateProduct(_product: Product): Promise<MercadoLibreResult> {
  await fakeNetworkDelay(400);
  return { ok: true, mensaje: 'Publicación actualizada.' };
}

export async function updateStock(_productId: string, _stock: number): Promise<MercadoLibreResult> {
  await fakeNetworkDelay(350);
  return { ok: true, mensaje: 'Stock sincronizado.' };
}

export async function updatePrice(_productId: string, _precio: number): Promise<MercadoLibreResult> {
  await fakeNetworkDelay(350);
  return { ok: true, mensaje: 'Precio sincronizado.' };
}

export async function getPublication(product: Product): Promise<MercadoLibrePublicationInfo | null> {
  await fakeNetworkDelay(150);
  return product.publicacionML ?? null;
}

export async function pausePublication(_productId: string): Promise<MercadoLibreResult> {
  await fakeNetworkDelay(300);
  return { ok: true, mensaje: 'Publicación pausada.' };
}
