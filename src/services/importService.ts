import type {
  ColumnMapping,
  DuplicateGroup,
  ImportField,
  ImportRowResult,
  ImportSummary,
  ParsedSpreadsheet,
  RawRow,
} from '@/types/import';
import { IMPORT_FIELD_ORDER } from '@/types/import';
import { CATEGORIAS, type ProductCategory } from '@/types/product';

// ---------------------------------------------------------------------------
// 1. Lectura del archivo (.xlsx, .xls, .csv)
// ---------------------------------------------------------------------------

export function parseSpreadsheetFile(file: File): Promise<ParsedSpreadsheet> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('No pudimos leer el archivo.'));
    reader.onload = async () => {
      try {
        const XLSX = await import('xlsx');
        const data = reader.result;
        const workbook = XLSX.read(data, { type: 'binary' });
        const firstSheetName = workbook.SheetNames[0];
        const sheet = workbook.Sheets[firstSheetName];
        const json: Record<string, unknown>[] = XLSX.utils.sheet_to_json(sheet, { defval: '' });

        if (json.length === 0) {
          resolve({ fileName: file.name, headers: [], rows: [] });
          return;
        }

        const headers = Object.keys(json[0]);
        const rows: RawRow[] = json.map((row) => {
          const out: RawRow = {};
          headers.forEach((h) => {
            const value = row[h];
            out[h] = value === undefined || value === null ? '' : String(value);
          });
          return out;
        });

        resolve({ fileName: file.name, headers, rows });
      } catch {
        reject(new Error('El archivo no tiene un formato de planilla válido.'));
      }
    };
    reader.readAsBinaryString(file);
  });
}

// ---------------------------------------------------------------------------
// 2. Detección automática de columnas (no requiere que los nombres coincidan)
// ---------------------------------------------------------------------------

function normalizeHeader(header: string): string {
  return header
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '') // quita tildes
    .replace(/[^a-z0-9]/g, '');
}

// Sinónimos habituales que un dueño de librería podría usar en su planilla.
const FIELD_SYNONYMS: Record<ImportField, string[]> = {
  sku: ['sku', 'codigo', 'code', 'cod', 'id'],
  nombre: ['nombre', 'producto', 'titulo', 'name', 'descripcionproducto', 'articulo'],
  marca: ['marca', 'brand', 'fabricante'],
  categoria: ['categoria', 'category', 'rubro', 'tipo', 'familia'],
  precio: ['precio', 'valor', 'price', 'pvp', 'preciodeventa'],
  stock: ['stock', 'cantidad', 'existencia', 'qty', 'unidades'],
  descripcion: ['descripcion', 'description', 'detalle', 'observacion'],
  imagen: ['imagen', 'image', 'foto', 'picture', 'imagenurl', 'urlimagen'],
};

export function detectColumns(headers: string[]): ColumnMapping {
  const normalized = headers.map((h) => ({ original: h, norm: normalizeHeader(h) }));
  const mapping = {} as ColumnMapping;
  const used = new Set<string>();

  for (const field of IMPORT_FIELD_ORDER) {
    const synonyms = FIELD_SYNONYMS[field];
    const match = normalized.find((h) => !used.has(h.original) && synonyms.some((syn) => h.norm === syn));
    const partial =
      match ?? normalized.find((h) => !used.has(h.original) && synonyms.some((syn) => h.norm.includes(syn)));
    if (partial) {
      mapping[field] = partial.original;
      used.add(partial.original);
    } else {
      mapping[field] = null;
    }
  }

  return mapping;
}

// ---------------------------------------------------------------------------
// 3. Validación de filas usando el mapeo de columnas elegido
// ---------------------------------------------------------------------------

function toNumber(value: string): number {
  const cleaned = value.replace(/[^0-9.,-]/g, '').replace(/\.(?=\d{3},)/g, '').replace(',', '.');
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : NaN;
}

function matchCategory(raw: string): ProductCategory | null {
  const norm = normalizeHeader(raw);
  const found = CATEGORIAS.find((c) => normalizeHeader(c) === norm);
  return found ?? null;
}

export function buildRowResults(rows: RawRow[], mapping: ColumnMapping): ImportRowResult[] {
  const seenSku = new Map<string, number[]>();
  const seenNombre = new Map<string, number[]>();

  const results: ImportRowResult[] = rows.map((row, index) => {
    const get = (field: ImportField) => {
      const header = mapping[field];
      return header ? (row[header] ?? '').toString().trim() : '';
    };

    const sku = get('sku');
    const nombre = get('nombre');
    const marca = get('marca');
    const categoriaRaw = get('categoria');
    const precioRaw = get('precio');
    const stockRaw = get('stock');
    const descripcion = get('descripcion');
    const imagen = get('imagen');

    const precio = precioRaw ? toNumber(precioRaw) : NaN;
    const stock = stockRaw ? toNumber(stockRaw) : NaN;
    const categoriaMatch = categoriaRaw ? matchCategory(categoriaRaw) : null;

    const problemas: string[] = [];
    if (!sku) problemas.push('Falta SKU');
    if (!nombre) problemas.push('Falta nombre');
    if (precioRaw && Number.isNaN(precio)) problemas.push('Precio no válido');
    if (stockRaw && Number.isNaN(stock)) problemas.push('Stock no válido');
    if (!descripcion) problemas.push('Falta descripción');
    if (!imagen) problemas.push('Falta imagen');
    if (categoriaRaw && !categoriaMatch) problemas.push('Categoría no reconocida');
    if (!categoriaRaw) problemas.push('Categoría no definida');

    if (sku) {
      const key = sku.toLowerCase();
      seenSku.set(key, [...(seenSku.get(key) ?? []), index]);
    }
    if (nombre) {
      const key = nombre.toLowerCase();
      seenNombre.set(key, [...(seenNombre.get(key) ?? []), index]);
    }

    // Errores "duros" (bloquean el procesamiento) vs. observaciones que solo
    // requieren revisión.
    const blocking = !sku || !nombre || (!!precioRaw && Number.isNaN(precio)) || (!!stockRaw && Number.isNaN(stock));

    return {
      rowIndex: index,
      sku,
      nombre,
      marca,
      categoria: categoriaMatch ?? categoriaRaw,
      precio: Number.isFinite(precio) ? precio : 0,
      stock: Number.isFinite(stock) ? stock : 0,
      descripcion,
      imagenUrl: imagen || null,
      estado: blocking ? 'error' : problemas.length > 0 ? 'revision' : 'valido',
      problemas,
      duplicado: false,
    };
  });

  // Marca como duplicado (y como error) cualquier fila cuyo SKU o nombre se
  // repita más de una vez en el archivo.
  for (const indices of seenSku.values()) {
    if (indices.length > 1) {
      indices.forEach((i) => {
        results[i].duplicado = true;
        if (!results[i].problemas.includes('SKU duplicado')) results[i].problemas.push('SKU duplicado');
        results[i].estado = 'error';
      });
    }
  }
  for (const indices of seenNombre.values()) {
    if (indices.length > 1) {
      indices.forEach((i) => {
        if (!results[i].duplicado) {
          results[i].duplicado = true;
          if (!results[i].problemas.includes('Nombre duplicado')) results[i].problemas.push('Nombre duplicado');
          if (results[i].estado !== 'error') results[i].estado = 'revision';
        }
      });
    }
  }

  return results;
}

export function summarize(results: ImportRowResult[]): ImportSummary {
  return {
    totalFilas: results.length,
    validos: results.filter((r) => r.estado === 'valido').length,
    revision: results.filter((r) => r.estado === 'revision').length,
    errores: results.filter((r) => r.estado === 'error').length,
  };
}

// ---------------------------------------------------------------------------
// 4. Grupos de duplicados, listos para que el usuario decida qué hacer
// ---------------------------------------------------------------------------

export function findDuplicateGroups(results: ImportRowResult[]): DuplicateGroup[] {
  const groups: DuplicateGroup[] = [];
  const bySku = new Map<string, number[]>();

  results.forEach((r) => {
    if (!r.sku) return;
    const key = r.sku.toLowerCase();
    bySku.set(key, [...(bySku.get(key) ?? []), r.rowIndex]);
  });

  for (const [key, indices] of bySku.entries()) {
    if (indices.length > 1) {
      groups.push({ clave: key, criterio: 'sku', filas: indices, resolucion: null });
    }
  }

  return groups;
}

// Aplica la resolución elegida por el usuario para cada grupo de duplicados,
// devolviendo el conjunto de índices de fila que deben excluirse de la
// importación final.
export function resolveDuplicates(groups: DuplicateGroup[]): Set<number> {
  const excluded = new Set<number>();
  for (const group of groups) {
    if (group.resolucion === 'primero') {
      group.filas.slice(1).forEach((i) => excluded.add(i));
    } else if (group.resolucion === 'ultimo') {
      group.filas.slice(0, -1).forEach((i) => excluded.add(i));
    }
    // 'manual' o null: no se excluye nada, todas quedan marcadas para revisión.
  }
  return excluded;
}

// ---------------------------------------------------------------------------
// 5. Plantilla de Excel descargable
// ---------------------------------------------------------------------------

export async function downloadExcelTemplate() {
  const XLSX = await import('xlsx');
  const headers = ['SKU', 'Nombre', 'Marca', 'Categoría', 'Precio', 'Stock', 'Descripción', 'Imagen'];
  const example = ['018', 'Cuaderno Universitario 100 hojas', 'Torre', 'Cuadernos', '3990', '25', 'Cuaderno universitario cuadro grande', ''];
  const sheet = XLSX.utils.aoa_to_sheet([headers, example]);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, sheet, 'Productos');
  XLSX.writeFile(workbook, 'plantilla-productos.xlsx');
}
