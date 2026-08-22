import type { Product, ProductFormInput, ProductIssue } from '@/types/product';

// Capa de servicio: hoy opera sobre datos en memoria, pero la interfaz de
// funciones (createProduct, updateProduct, etc.) es la que debería
// mantenerse cuando en Fase 2 esto se reemplace por llamadas HTTP a una
// base de datos real. Nada fuera de este archivo debería saber que los
// datos son locales.

let idCounter = 1000;

export function generateId(): string {
  idCounter += 1;
  return `p${idCounter}`;
}

export function buildProductFromInput(input: ProductFormInput): Product {
  const now = new Date().toISOString();
  const estado = deriveStatus(input);
  return {
    id: generateId(),
    sku: input.sku,
    nombre: input.nombre,
    marca: input.marca,
    categoria: input.categoria,
    precio: input.precio,
    stock: input.stock,
    descripcion: input.descripcion,
    condicion: 'Nuevo',
    estado,
    imagenUrl: input.imagenUrl,
    imagenesSecundarias: [],
    atributos: input.marca ? [{ etiqueta: 'Marca', valor: input.marca }] : [],
    publicar: input.publicar,
    actualizadoEn: now,
    creadoEn: now,
    origen: 'manual',
    mercadoLibreId: null,
    publicacionML: null,
  };
}

export function applyInputToProduct(product: Product, input: ProductFormInput): Product {
  const merged: Product = {
    ...product,
    sku: input.sku,
    nombre: input.nombre,
    marca: input.marca,
    categoria: input.categoria,
    precio: input.precio,
    stock: input.stock,
    descripcion: input.descripcion,
    imagenUrl: input.imagenUrl,
    publicar: input.publicar,
    actualizadoEn: new Date().toISOString(),
  };
  merged.estado = deriveStatus(merged);
  return merged;
}

// Reglas de negocio simples para decidir el estado visible del producto.
// En Fase 4 esto podría incorporar validación asistida por IA.
// Importante: "publicado" ahora significa que el producto ya se envió a
// Mercado Libre (Fase 3, todavía no implementada). Antes de eso, un
// producto sin problemas que el usuario marcó para publicar queda "listo".
// Un producto que ya tiene una publicación simulada (publicacionML) se
// mantiene "publicado" aunque se vuelva a editar — dejar de estar
// publicado es una acción explícita, no un efecto secundario de editar.
function deriveStatus(input: {
  descripcion: string;
  imagenUrl: string | null;
  publicar: boolean;
  categoria?: string;
  publicacionML?: Product['publicacionML'];
}): Product['estado'] {
  if (input.publicacionML) return 'publicado';
  const issues = findIssues(input);
  if (issues.length > 0) return input.publicar ? 'error' : 'pendiente';
  return input.publicar ? 'listo' : 'sin-publicar';
}

export function findIssues(product: {
  descripcion: string;
  imagenUrl: string | null;
  categoria?: string;
}): ProductIssue[] {
  const issues: ProductIssue[] = [];
  if (!product.descripcion || product.descripcion.trim().length === 0) {
    issues.push({ id: 'desc', label: 'Falta descripción' });
  }
  if (!product.imagenUrl) {
    issues.push({ id: 'img', label: 'Falta imagen' });
  }
  if (!product.categoria) {
    issues.push({ id: 'cat', label: 'Categoría no definida' });
  }
  return issues;
}

// Construye un Product a partir de una fila importada (ya validada) y su
// resultado de procesamiento automático (real o simulado).
export function buildImportedProduct(row: {
  sku: string;
  nombre: string;
  marca: string;
  categoria: string;
  precio: number;
  stock: number;
  descripcion: string;
  imagenUrl: string | null;
  estado: 'valido' | 'revision' | 'error';
}, procesado: Product['procesado']): Product {
  const now = new Date().toISOString();
  const estado: Product['estado'] = row.estado === 'error' ? 'error' : row.estado === 'revision' ? 'pendiente' : 'listo';

  return {
    id: generateId(),
    sku: row.sku,
    nombre: procesado?.titulo ?? row.nombre,
    marca: row.marca,
    categoria: (procesado?.categoria ?? row.categoria) as Product['categoria'],
    precio: row.precio,
    stock: row.stock,
    descripcion: procesado?.descripcion ?? row.descripcion,
    condicion: 'Nuevo',
    estado,
    imagenUrl: row.imagenUrl,
    imagenesSecundarias: [],
    atributos: procesado?.atributos ?? (row.marca ? [{ etiqueta: 'Marca', valor: row.marca }] : []),
    publicar: estado === 'listo',
    actualizadoEn: now,
    creadoEn: now,
    origen: 'excel',
    original: {
      nombre: row.nombre,
      marca: row.marca,
      categoria: row.categoria,
      precio: row.precio,
      stock: row.stock,
      descripcion: row.descripcion,
    },
    procesado: procesado ?? undefined,
    mercadoLibreId: null,
    publicacionML: null,
  };
}

export function formatCLP(amount: number): string {
  return new Intl.NumberFormat('es-CL', {
    style: 'currency',
    currency: 'CLP',
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  return new Intl.DateTimeFormat('es-CL', { day: '2-digit', month: 'short', year: 'numeric' }).format(date);
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  const datePart = new Intl.DateTimeFormat('es-CL', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(date);
  const timePart = new Intl.DateTimeFormat('es-CL', { hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
  return `${datePart} — ${timePart}`;
}

export function formatRelative(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) return 'Hoy';
  if (diffDays === 1) return 'Ayer';
  if (diffDays < 7) return `Hace ${diffDays} días`;
  const weeks = Math.floor(diffDays / 7);
  if (weeks === 1) return 'Hace 1 semana';
  if (diffDays < 30) return `Hace ${weeks} semanas`;
  const months = Math.floor(diffDays / 30);
  return months <= 1 ? 'Hace 1 mes' : `Hace ${months} meses`;
}

// Un producto publicado está "desactualizado" cuando su precio o stock
// local difiere de lo que quedó registrado en la última publicación/
// sincronización simulada.
export function isOutOfSync(product: Product): boolean {
  if (!product.publicacionML) return false;
  return product.precio !== product.publicacionML.precioPublicado || product.stock !== product.publicacionML.stockPublicado;
}
