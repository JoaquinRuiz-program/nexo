import type { ActivityEntry, Product } from '@/types/product';

// ---------------------------------------------------------------------------
// PERSISTENCIA LOCAL — hoy localStorage, mañana Supabase/PostgreSQL.
//
// Todo el resto de la app solo llama a las funciones de este archivo
// (load*/save*), nunca a `localStorage` directamente. Eso significa que en
// Fase 2 podemos reemplazar el cuerpo de estas funciones por consultas a una
// base de datos real sin tocar ProductContext ni ninguna pantalla.
// ---------------------------------------------------------------------------

const KEYS = {
  products: 'libreria-central:products',
  activity: 'libreria-central:activity',
  automation: 'libreria-central:automation',
} as const;

export interface AutomationState {
  systemActive: boolean;
  lastSync: string | null;
  lastImport: string | null;
  processedCount: number;
}

export const DEFAULT_AUTOMATION_STATE: AutomationState = {
  systemActive: true,
  lastSync: null,
  lastImport: null,
  processedCount: 0,
};

function safeGet<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function safeSet(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Almacenamiento no disponible (modo privado, cuota excedida, etc.):
    // la app sigue funcionando en memoria durante la sesión.
  }
}

export function loadProducts(): Product[] | null {
  return safeGet<Product[]>(KEYS.products);
}

export function saveProducts(products: Product[]) {
  safeSet(KEYS.products, products);
}

export function loadActivity(): ActivityEntry[] | null {
  return safeGet<ActivityEntry[]>(KEYS.activity);
}

export function saveActivity(activity: ActivityEntry[]) {
  safeSet(KEYS.activity, activity);
}

export function loadAutomationState(): AutomationState {
  return safeGet<AutomationState>(KEYS.automation) ?? DEFAULT_AUTOMATION_STATE;
}

export function saveAutomationState(state: AutomationState) {
  safeSet(KEYS.automation, state);
}

export function clearAllData() {
  try {
    window.localStorage.removeItem(KEYS.products);
    window.localStorage.removeItem(KEYS.activity);
    window.localStorage.removeItem(KEYS.automation);
  } catch {
    // no-op
  }
}
