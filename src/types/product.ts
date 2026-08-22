// Tipos centrales del dominio "producto". Mantener este archivo como la
// única fuente de verdad para la forma de los datos: cuando en Fase 2
// conectemos una base de datos real, este contrato es lo que persiste.

// 🟢 listo         — tiene toda la información necesaria para publicarse
// 🟡 pendiente      — falta información que puede completarse/revisarse
// 🔴 error          — tiene un problema que impide procesarlo (ej. SKU duplicado)
// 🔵 publicado      — publicado en Mercado Libre (fase futura)
// ⚪ sin-publicar    — existe en el catálogo pero no se ha enviado a publicar
export type ProductStatus = 'listo' | 'pendiente' | 'error' | 'publicado' | 'sin-publicar';

export type ProductCategory =
  | 'Cuadernos'
  | 'Escritura'
  | 'Mochilas'
  | 'Carpetas'
  | 'Libros'
  | 'Calculadoras'
  | 'Artículos escolares'
  | 'Artículos de oficina';

export interface ProductIssue {
  id: string;
  label: string;
}

// De dónde vino el producto: escrito a mano en el formulario, o importado
// desde un Excel/CSV.
export type ProductOrigin = 'manual' | 'excel';

// Datos originales tal como llegaron del Excel, antes de cualquier
// procesamiento. Solo existe para productos importados — permite mostrar
// "qué cambió" el procesamiento automático.
export interface OriginalProductInfo {
  nombre: string;
  marca: string;
  categoria: string;
  precio: number;
  stock: number;
  descripcion: string;
}

// Salida del procesamiento automático (hoy simulado, mañana IA real). Ver
// src/services/aiService.ts — ese es el único archivo que debería
// reemplazarse para conectar un modelo real.
export interface ProcessedProductInfo {
  titulo: string;
  descripcion: string;
  categoria: ProductCategory;
  atributos: { etiqueta: string; valor: string }[];
  procesadoEn: string; // ISO date string
}

export type ProductCondition = 'Nuevo' | 'Usado';

// Una entrada del historial de publicación: se agrega cada vez que se
// publica, se sincroniza el precio o se sincroniza el stock.
export interface PublicationHistoryEntry {
  id: string;
  fecha: string; // ISO date string
  mensaje: string;
  precio?: number;
  stock?: number;
}

// Registro de la publicación simulada en Mercado Libre. Solo existe una vez
// que el producto pasó por `mercadoLibreService.publishProduct`. En Fase 3
// esto reflejaría la respuesta real de la API.
export interface MercadoLibrePublicationInfo {
  id: string; // ej: "ML-847291"
  publicadoEn: string; // ISO date string
  precioPublicado: number;
  stockPublicado: number;
  estadoPublicacion: 'publicado' | 'pausado';
  historial: PublicationHistoryEntry[];
}

export interface Product {
  id: string;
  sku: string;
  nombre: string;
  marca: string;
  categoria: ProductCategory;
  precio: number;
  stock: number;
  descripcion: string;
  condicion: ProductCondition;
  estado: ProductStatus;
  imagenUrl: string | null;
  imagenesSecundarias: string[];
  // Características/atributos editables que se muestran en la publicación
  // (marca, tipo, formato, hojas, etc.). Se inicializan a partir del
  // procesamiento automático, pero el usuario puede editarlos.
  atributos: { etiqueta: string; valor: string }[];
  publicar: boolean;
  actualizadoEn: string; // ISO date string
  creadoEn: string; // ISO date string
  origen: ProductOrigin;
  // Presente solo si el producto vino de una importación.
  original?: OriginalProductInfo;
  // Presente solo después de pasar por el procesamiento automático.
  procesado?: ProcessedProductInfo;
  // Fase 3+: usado cuando exista integración real con Mercado Libre.
  // Se mantiene como espejo de publicacionML?.id por conveniencia (se usa
  // en la tabla de Productos).
  mercadoLibreId?: string | null;
  publicacionML?: MercadoLibrePublicationInfo | null;
}

export interface ActivityEntry {
  id: string;
  mensaje: string;
  fecha: string; // ISO date string
}

// Entrada de formulario: todo lo que el usuario puede escribir al crear o
// editar un producto. Separado de `Product` porque el formulario no conoce
// campos derivados como id/estado/fechas.
export interface ProductFormInput {
  sku: string;
  nombre: string;
  marca: string;
  categoria: ProductCategory;
  precio: number;
  stock: number;
  descripcion: string;
  imagenUrl: string | null;
  publicar: boolean;
}

export const CATEGORIAS: ProductCategory[] = [
  'Cuadernos',
  'Escritura',
  'Mochilas',
  'Carpetas',
  'Libros',
  'Calculadoras',
  'Artículos escolares',
  'Artículos de oficina',
];

export const ESTADOS: { value: ProductStatus; label: string }[] = [
  { value: 'listo', label: 'Listo para publicar' },
  { value: 'pendiente', label: 'Pendiente' },
  { value: 'error', label: 'Con errores' },
  { value: 'publicado', label: 'Publicado' },
  { value: 'sin-publicar', label: 'Sin publicar' },
];
