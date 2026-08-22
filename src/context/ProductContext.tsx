import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { ActivityEntry, Product, ProductFormInput } from '@/types/product';
import { mockActivity, mockProducts } from '@/data/mockProducts';
import { applyInputToProduct, buildProductFromInput, formatCLP } from '@/services/productService';
import * as mercadoLibreService from '@/services/mercadoLibreService';
import type { PublishResult } from '@/services/mercadoLibreService';
import {
  loadActivity,
  loadAutomationState,
  loadProducts,
  saveActivity,
  saveAutomationState,
  saveProducts,
  type AutomationState,
} from '@/services/storageService';

interface ProductContextValue {
  products: Product[];
  activity: ActivityEntry[];
  automation: AutomationState;
  getProduct: (id: string) => Product | undefined;
  addProduct: (input: ProductFormInput) => Product;
  editProduct: (id: string, input: ProductFormInput) => void;
  deleteProduct: (id: string) => void;
  updateStock: (id: string, stock: number) => void;
  updatePrice: (id: string, precio: number) => void;
  updateStatus: (id: string, publicar: boolean) => void;
  updateProductFields: (id: string, fields: Partial<Product>) => void;
  // Fase 1.5 — importación
  importProducts: (nuevos: Product[]) => void;
  markProcessed: (count: number) => void;
  // Fase 2 — publicación en Mercado Libre (simulada)
  publishProduct: (id: string) => Promise<PublishResult>;
  publishProductsBulk: (
    ids: string[],
    onProgress?: (done: number, total: number, product: Product, result: PublishResult) => void,
  ) => Promise<{ ok: string[]; fail: string[] }>;
  syncPrice: (id: string) => Promise<void>;
  syncStock: (id: string) => Promise<void>;
}

const ProductContext = createContext<ProductContextValue | undefined>(undefined);

function logActivity(mensaje: string) {
  const entry: ActivityEntry = { id: `a-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, mensaje, fecha: new Date().toISOString() };
  return entry;
}

export function ProductProvider({ children }: { children: ReactNode }) {
  const [products, setProducts] = useState<Product[]>(() => loadProducts() ?? mockProducts);
  const [activity, setActivity] = useState<ActivityEntry[]>(() => loadActivity() ?? mockActivity);
  const [automation, setAutomation] = useState<AutomationState>(() => loadAutomationState());

  // Persistimos en localStorage cada vez que cambian los datos. En Fase 2
  // este efecto desaparece: cada acción llamará directamente a la base de
  // datos real dentro de storageService.
  useEffect(() => {
    saveProducts(products);
  }, [products]);

  useEffect(() => {
    saveActivity(activity);
  }, [activity]);

  useEffect(() => {
    saveAutomationState(automation);
  }, [automation]);

  const pushActivity = useCallback((mensaje: string) => {
    setActivity((prev) => [logActivity(mensaje), ...prev].slice(0, 30));
  }, []);

  const getProduct = useCallback((id: string) => products.find((p) => p.id === id), [products]);

  const addProduct = useCallback(
    (input: ProductFormInput) => {
      const product = buildProductFromInput(input);
      setProducts((prev) => [product, ...prev]);
      pushActivity(`Nuevo producto agregado: ${product.nombre}`);
      return product;
    },
    [pushActivity],
  );

  const editProduct = useCallback(
    (id: string, input: ProductFormInput) => {
      setProducts((prev) =>
        prev.map((p) => (p.id === id ? applyInputToProduct(p, input) : p)),
      );
      pushActivity(`${input.nombre} actualizado`);
    },
    [pushActivity],
  );

  const deleteProduct = useCallback(
    (id: string) => {
      setProducts((prev) => {
        const target = prev.find((p) => p.id === id);
        if (target) pushActivity(`Producto eliminado: ${target.nombre}`);
        return prev.filter((p) => p.id !== id);
      });
    },
    [pushActivity],
  );

  const updateStock = useCallback(
    (id: string, stock: number) => {
      setProducts((prev) => prev.map((p) => (p.id === id ? { ...p, stock, actualizadoEn: new Date().toISOString() } : p)));
      const target = products.find((p) => p.id === id);
      if (target) pushActivity(`Stock actualizado: ${target.nombre}`);
    },
    [products, pushActivity],
  );

  const updatePrice = useCallback(
    (id: string, precio: number) => {
      setProducts((prev) => prev.map((p) => (p.id === id ? { ...p, precio, actualizadoEn: new Date().toISOString() } : p)));
      const target = products.find((p) => p.id === id);
      if (target) pushActivity(`Precio actualizado: ${target.nombre}`);
    },
    [products, pushActivity],
  );

  const updateStatus = useCallback(
    (id: string, publicar: boolean) => {
      setProducts((prev) =>
        prev.map((p) => {
          if (p.id !== id) return p;
          if (p.publicacionML) return p; // ya publicado: esto no aplica
          const estado = publicar ? 'listo' : 'sin-publicar';
          return { ...p, publicar, estado, actualizadoEn: new Date().toISOString() };
        }),
      );
      const target = products.find((p) => p.id === id);
      if (target) pushActivity(publicar ? `Producto listo para publicar: ${target.nombre}` : `${target.nombre} despublicado`);
    },
    [products, pushActivity],
  );

  // Actualización flexible usada por la pantalla "Preparar publicación"
  // para editar categoría, características e imágenes secundarias sin
  // pasar por el formulario completo de producto.
  const updateProductFields = useCallback((id: string, fields: Partial<Product>) => {
    setProducts((prev) => prev.map((p) => (p.id === id ? { ...p, ...fields, actualizadoEn: new Date().toISOString() } : p)));
  }, []);

  const importProducts = useCallback(
    (nuevos: Product[]) => {
      setProducts((prev) => [...nuevos, ...prev]);
      pushActivity(`Catálogo importado: ${nuevos.length} productos`);
      setAutomation((prev) => ({
        ...prev,
        lastImport: new Date().toISOString(),
        lastSync: new Date().toISOString(),
        processedCount: prev.processedCount + nuevos.length,
      }));
    },
    [pushActivity],
  );

  const markProcessed = useCallback((count: number) => {
    setAutomation((prev) => ({ ...prev, processedCount: prev.processedCount + count, lastSync: new Date().toISOString() }));
  }, []);

  // -------------------------------------------------------------------
  // Fase 2 — publicación en Mercado Libre (simulada)
  // -------------------------------------------------------------------

  const publishProduct = useCallback(
    async (id: string) => {
      const target = products.find((p) => p.id === id);
      if (!target) return { ok: false, mensaje: 'Producto no encontrado.' };

      const result = await mercadoLibreService.publishProduct(target);
      if (result.ok && result.publicacion) {
        setProducts((prev) =>
          prev.map((p) =>
            p.id === id
              ? {
                  ...p,
                  estado: 'publicado',
                  publicar: true,
                  mercadoLibreId: result.publicacion!.id,
                  publicacionML: result.publicacion!,
                  actualizadoEn: new Date().toISOString(),
                }
              : p,
          ),
        );
        pushActivity(`Publicado en Mercado Libre: ${target.nombre} (${result.publicacion.id})`);
        setAutomation((prev) => ({ ...prev, lastSync: new Date().toISOString() }));
      }
      return result;
    },
    [products, pushActivity],
  );

  const publishProductsBulk = useCallback(
    async (ids: string[], onProgress?: (done: number, total: number, product: Product, result: PublishResult) => void) => {
      const ok: string[] = [];
      const fail: string[] = [];
      for (let i = 0; i < ids.length; i++) {
        const id = ids[i];
        const target = products.find((p) => p.id === id);
        if (!target) {
          fail.push(id);
          continue;
        }
        const result = await mercadoLibreService.publishProduct(target);
        if (result.ok && result.publicacion) {
          ok.push(id);
          const publicacion = result.publicacion;
          setProducts((prev) =>
            prev.map((p) =>
              p.id === id
                ? {
                    ...p,
                    estado: 'publicado',
                    publicar: true,
                    mercadoLibreId: publicacion.id,
                    publicacionML: publicacion,
                    actualizadoEn: new Date().toISOString(),
                  }
                : p,
            ),
          );
        } else {
          fail.push(id);
        }
        onProgress?.(i + 1, ids.length, target, result);
      }
      if (ok.length > 0) {
        pushActivity(`Publicación masiva: ${ok.length} productos publicados`);
        setAutomation((prev) => ({ ...prev, lastSync: new Date().toISOString() }));
      }
      return { ok, fail };
    },
    [products, pushActivity],
  );

  const syncPrice = useCallback(
    async (id: string) => {
      const target = products.find((p) => p.id === id);
      if (!target || !target.publicacionML) return;
      await mercadoLibreService.updatePrice(id, target.precio);
      const now = new Date().toISOString();
      setProducts((prev) =>
        prev.map((p) => {
          if (p.id !== id || !p.publicacionML) return p;
          return {
            ...p,
            publicacionML: {
              ...p.publicacionML,
              precioPublicado: p.precio,
              historial: [
                { id: `h-${Date.now()}`, fecha: now, mensaje: `Precio sincronizado a ${formatCLP(p.precio)}`, precio: p.precio },
                ...p.publicacionML.historial,
              ],
            },
            actualizadoEn: now,
          };
        }),
      );
      pushActivity(`Precio sincronizado con Mercado Libre: ${target.nombre}`);
      setAutomation((prev) => ({ ...prev, lastSync: now }));
    },
    [products, pushActivity],
  );

  const syncStock = useCallback(
    async (id: string) => {
      const target = products.find((p) => p.id === id);
      if (!target || !target.publicacionML) return;
      await mercadoLibreService.updateStock(id, target.stock);
      const now = new Date().toISOString();
      setProducts((prev) =>
        prev.map((p) => {
          if (p.id !== id || !p.publicacionML) return p;
          return {
            ...p,
            publicacionML: {
              ...p.publicacionML,
              stockPublicado: p.stock,
              historial: [
                { id: `h-${Date.now()}`, fecha: now, mensaje: `Stock sincronizado a ${p.stock} unidades`, stock: p.stock },
                ...p.publicacionML.historial,
              ],
            },
            actualizadoEn: now,
          };
        }),
      );
      pushActivity(`Stock sincronizado con Mercado Libre: ${target.nombre}`);
      setAutomation((prev) => ({ ...prev, lastSync: now }));
    },
    [products, pushActivity],
  );

  const value = useMemo<ProductContextValue>(
    () => ({
      products,
      activity,
      automation,
      getProduct,
      addProduct,
      editProduct,
      deleteProduct,
      updateStock,
      updatePrice,
      updateStatus,
      updateProductFields,
      importProducts,
      markProcessed,
      publishProduct,
      publishProductsBulk,
      syncPrice,
      syncStock,
    }),
    [
      products,
      activity,
      automation,
      getProduct,
      addProduct,
      editProduct,
      deleteProduct,
      updateStock,
      updatePrice,
      updateStatus,
      updateProductFields,
      importProducts,
      markProcessed,
      publishProduct,
      publishProductsBulk,
      syncPrice,
      syncStock,
    ],
  );

  return <ProductContext.Provider value={value}>{children}</ProductContext.Provider>;
}

export function useProducts() {
  const ctx = useContext(ProductContext);
  if (!ctx) throw new Error('useProducts debe usarse dentro de <ProductProvider>');
  return ctx;
}
