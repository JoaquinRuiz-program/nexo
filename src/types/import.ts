// Tipos para el flujo de importación de catálogo (Excel/CSV). Separados de
// product.ts porque describen datos "en tránsito" — filas crudas del
// archivo — antes de convertirse en `Product`.

// Los campos de nuestro dominio que intentamos encontrar en el archivo.
export type ImportField = 'sku' | 'nombre' | 'marca' | 'categoria' | 'precio' | 'stock' | 'descripcion' | 'imagen';

export const IMPORT_FIELD_LABELS: Record<ImportField, string> = {
  sku: 'SKU',
  nombre: 'Nombre',
  marca: 'Marca',
  categoria: 'Categoría',
  precio: 'Precio',
  stock: 'Stock',
  descripcion: 'Descripción',
  imagen: 'Imagen',
};

export const IMPORT_FIELD_ORDER: ImportField[] = ['sku', 'nombre', 'marca', 'categoria', 'precio', 'stock', 'descripcion', 'imagen'];

// Una fila cruda leída del archivo: encabezado original → valor de texto.
export type RawRow = Record<string, string>;

export interface ParsedSpreadsheet {
  fileName: string;
  headers: string[];
  rows: RawRow[];
}

// Mapa de nuestro campo → el encabezado del archivo que se le asignó
// (o null si no se encontró/eligió ninguno).
export type ColumnMapping = Record<ImportField, string | null>;

export type ImportRowStatus = 'valido' | 'revision' | 'error';

export interface ImportRowResult {
  rowIndex: number;
  sku: string;
  nombre: string;
  marca: string;
  categoria: string;
  precio: number;
  stock: number;
  descripcion: string;
  imagenUrl: string | null;
  estado: ImportRowStatus;
  problemas: string[];
  duplicado: boolean;
}

export interface DuplicateGroup {
  clave: string; // SKU o nombre normalizado que se repite
  criterio: 'sku' | 'nombre';
  filas: number[]; // rowIndex de las filas involucradas
  resolucion: 'primero' | 'ultimo' | 'manual' | null;
}

export interface ImportSummary {
  totalFilas: number;
  validos: number;
  revision: number;
  errores: number;
}
