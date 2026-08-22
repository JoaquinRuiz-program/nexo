import type { ProcessedProductInfo } from '@/types/product';
import { CATEGORIAS, type ProductCategory } from '@/types/product';

// ---------------------------------------------------------------------------
// SIMULACIÓN DE IA — Fase 1.5
//
// Esta función imita lo que hará un modelo de lenguaje real en la Fase 4:
// recibe los datos crudos de un producto y devuelve una versión "optimizada"
// (título prolijo, descripción de venta, categoría sugerida, atributos).
//
// Para conectar una IA real más adelante, basta con reemplazar el cuerpo de
// `processProduct` por una llamada a la API correspondiente y mantener la
// misma firma (mismo input, mismo `ProcessedProductInfo` de salida). Nada
// fuera de este archivo debería cambiar.
// ---------------------------------------------------------------------------

export interface RawProductInput {
  nombre: string;
  marca: string;
  categoria: string;
  descripcion: string;
}

function titleCase(text: string): string {
  return text
    .toLowerCase()
    .split(' ')
    .filter(Boolean)
    .map((word) => (word.length <= 2 && !/\d/.test(word) ? word : word.charAt(0).toUpperCase() + word.slice(1)))
    .join(' ');
}

// Extrae pares "clave: valor" simples desde el nombre crudo, buscando
// patrones comunes en catálogos de librería (hojas, formato, espaciado, mm).
function extractAttributes(nombreCrudo: string, marca: string): { etiqueta: string; valor: string }[] {
  const attrs: { etiqueta: string; valor: string }[] = [];
  if (marca) attrs.push({ etiqueta: 'Marca', valor: titleCase(marca) });

  const hojas = nombreCrudo.match(/(\d+)\s*h(?:ojas)?\b/i);
  if (hojas) attrs.push({ etiqueta: 'Hojas', valor: hojas[1] });

  const espaciado = nombreCrudo.match(/(\d+)\s*mm/i);
  if (espaciado) attrs.push({ etiqueta: 'Espaciado', valor: `${espaciado[1]} mm` });

  const formato = nombreCrudo.match(/\b(college|universitario|oficio|carta|a4|a5)\b/i);
  if (formato) attrs.push({ etiqueta: 'Formato', valor: titleCase(formato[1]) });

  const tipoConocido = ['cuaderno', 'lapiz', 'lápiz', 'mochila', 'carpeta', 'libro', 'calculadora', 'plumon', 'plumón', 'goma', 'archivador'].find(
    (t) => nombreCrudo.toLowerCase().includes(t),
  );
  if (tipoConocido) attrs.push({ etiqueta: 'Tipo', valor: titleCase(tipoConocido) });

  return attrs;
}

function suggestCategory(nombreCrudo: string, categoriaCruda: string): ProductCategory {
  const yaValida = CATEGORIAS.find((c) => c.toLowerCase() === categoriaCruda.trim().toLowerCase());
  if (yaValida) return yaValida;

  const texto = nombreCrudo.toLowerCase();
  const rules: [RegExp, ProductCategory][] = [
    [/cuaderno|croquis|libreta/, 'Cuadernos'],
    [/l[aá]piz|l[aá]pices|plum[oó]n|goma|birome|boligrafo|bolígrafo/, 'Escritura'],
    [/mochila/, 'Mochilas'],
    [/carpeta|archivador/, 'Carpetas'],
    [/libro|novela/, 'Libros'],
    [/calculadora/, 'Calculadoras'],
    [/estuche|escuadra|transportador|regla/, 'Artículos escolares'],
    [/resma|papel|oficina/, 'Artículos de oficina'],
  ];
  const match = rules.find(([re]) => re.test(texto));
  return match ? match[1] : 'Artículos de oficina';
}

function buildDescription(nombre: string, marca: string, categoria: ProductCategory, attrs: { etiqueta: string; valor: string }[]): string {
  const partes: string[] = [];
  const attrText = attrs
    .filter((a) => a.etiqueta !== 'Marca' && a.etiqueta !== 'Tipo')
    .map((a) => `${a.valor}`)
    .join(', ');

  partes.push(`${nombre}${marca ? ` de la marca ${marca}` : ''}.`);
  if (attrText) partes.push(`Incluye ${attrText.toLowerCase()}.`);
  partes.push(`Ideal para uso escolar u oficina, dentro de la categoría ${categoria.toLowerCase()}.`);
  return partes.join(' ');
}

// Simula el tiempo que tomaría una llamada real a un modelo de IA.
function fakeLatency(): Promise<void> {
  const ms = 45 + Math.random() * 90;
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function processProduct(input: RawProductInput): Promise<ProcessedProductInfo> {
  await fakeLatency();

  const tituloLimpio = titleCase(input.nombre.trim());
  const categoria = suggestCategory(input.nombre, input.categoria);
  const atributos = extractAttributes(input.nombre, input.marca);
  const descripcion = input.descripcion.trim() || buildDescription(tituloLimpio, input.marca, categoria, atributos);

  return {
    titulo: tituloLimpio,
    descripcion,
    categoria,
    atributos,
    procesadoEn: new Date().toISOString(),
  };
}

// Procesa un lote completo, reportando avance a través de `onProgress` —
// usado por la pantalla "Procesamiento automático" para animar la barra.
export async function processBatch<T extends RawProductInput>(
  items: T[],
  onProgress?: (done: number, total: number) => void,
): Promise<ProcessedProductInfo[]> {
  const results: ProcessedProductInfo[] = [];
  for (let i = 0; i < items.length; i++) {
    const result = await processProduct(items[i]);
    results.push(result);
    onProgress?.(i + 1, items.length);
  }
  return results;
}
