import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, CirclePlus, ArrowUpDown, FileUp, ShoppingBag, Eye, ClipboardCheck } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { ProductImage } from '@/components/products/ProductImage';
import { useProducts } from '@/context/ProductContext';
import { formatCLP, formatDate } from '@/services/productService';
import { CATEGORIAS, ESTADOS, type ProductCategory, type ProductStatus } from '@/types/product';

type SortKey = 'none' | 'precio-asc' | 'precio-desc' | 'stock-asc' | 'stock-desc';

export function Products() {
  const { products, deleteProduct } = useProducts();
  const navigate = useNavigate();

  const [query, setQuery] = useState('');
  const [categoria, setCategoria] = useState<ProductCategory | 'todas'>('todas');
  const [estado, setEstado] = useState<ProductStatus | 'todos'>('todos');
  const [sort, setSort] = useState<SortKey>('none');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [blockedNotice, setBlockedNotice] = useState(false);

  const filtered = useMemo(() => {
    let list = products;

    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter((p) => p.nombre.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || p.marca.toLowerCase().includes(q));
    }
    if (categoria !== 'todas') {
      list = list.filter((p) => p.categoria === categoria);
    }
    if (estado !== 'todos') {
      list = list.filter((p) => p.estado === estado);
    }

    if (sort === 'precio-asc') list = [...list].sort((a, b) => a.precio - b.precio);
    if (sort === 'precio-desc') list = [...list].sort((a, b) => b.precio - a.precio);
    if (sort === 'stock-asc') list = [...list].sort((a, b) => a.stock - b.stock);
    if (sort === 'stock-desc') list = [...list].sort((a, b) => b.stock - a.stock);

    return list;
  }, [products, query, categoria, estado, sort]);

  const handleDelete = (id: string, nombre: string) => {
    if (window.confirm(`¿Eliminar "${nombre}"? Esta acción no se puede deshacer.`)) {
      deleteProduct(id);
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  function toggleSelect(id: string, estadoProducto: ProductStatus) {
    if (estadoProducto === 'error') {
      setBlockedNotice(true);
      setTimeout(() => setBlockedNotice(false), 3500);
      return;
    }
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    const selectable = filtered.filter((p) => p.estado !== 'error').map((p) => p.id);
    const allSelected = selectable.every((id) => selected.has(id)) && selectable.length > 0;
    if (allSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        selectable.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelected((prev) => new Set([...prev, ...selectable]));
    }
  }

  function goPrepare(id: string) {
    navigate(`/productos/${id}/publicar`);
  }

  function publicationAction(p: (typeof products)[number]) {
    if (p.estado === 'publicado') {
      return (
        <Button variant="secondary" size="sm" icon={<Eye size={16} />} onClick={() => goPrepare(p.id)}>
          Ver
        </Button>
      );
    }
    if (p.estado === 'pendiente' || p.estado === 'error') {
      return (
        <Button variant="secondary" size="sm" icon={<ClipboardCheck size={16} />} onClick={() => navigate(`/productos/${p.id}`)}>
          Revisar
        </Button>
      );
    }
    return (
      <Button variant="secondary" size="sm" icon={<ShoppingBag size={16} />} onClick={() => goPrepare(p.id)}>
        Preparar
      </Button>
    );
  }

  const selectableInView = filtered.filter((p) => p.estado !== 'error');
  const allSelected = selectableInView.length > 0 && selectableInView.every((p) => selected.has(p.id));

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-lg text-[--color-neutral-600]">
          {filtered.length} de {products.length} productos
        </p>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" icon={<FileUp size={20} />} onClick={() => navigate('/productos/importar')}>
            Importar productos
          </Button>
          <Button icon={<CirclePlus size={20} />} onClick={() => navigate('/agregar-producto')}>
            Agregar producto
          </Button>
        </div>
      </div>

      {blockedNotice && (
        <Card className="border-[--color-warn-100] bg-[--color-warn-100]/40 p-4">
          <p className="text-base text-[--color-warn-600]">Este producto necesita correcciones antes de poder publicarse.</p>
        </Card>
      )}

      {selected.size > 0 && (
        <Card className="flex flex-wrap items-center justify-between gap-3 border-[--color-gold-100] bg-[--color-gold-100]/30 p-4">
          <p className="text-base font-medium text-[--color-ink-950]">
            {selected.size} producto{selected.size === 1 ? '' : 's'} seleccionado{selected.size === 1 ? '' : 's'}
          </p>
          <div className="flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => setSelected(new Set())}>
              Limpiar selección
            </Button>
            <Button icon={<ShoppingBag size={18} />} onClick={() => navigate('/productos/publicar-masivo', { state: { ids: Array.from(selected) } })}>
              Publicar seleccionados
            </Button>
          </div>
        </Card>
      )}

      <Card className="p-4 lg:p-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[--color-neutral-600]" size={20} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar por nombre, SKU o marca"
              className="w-full rounded-lg border border-[--color-ink-100] bg-white py-3 pl-10 pr-4 text-base text-[--color-ink-950] placeholder:text-[--color-neutral-600] focus:border-[--color-ink-800]"
            />
          </div>
          <select
            value={categoria}
            onChange={(e) => setCategoria(e.target.value as ProductCategory | 'todas')}
            className="rounded-lg border border-[--color-ink-100] bg-white px-4 py-3 text-base text-[--color-ink-950]"
          >
            <option value="todas">Todas las categorías</option>
            {CATEGORIAS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            value={estado}
            onChange={(e) => setEstado(e.target.value as ProductStatus | 'todos')}
            className="rounded-lg border border-[--color-ink-100] bg-white px-4 py-3 text-base text-[--color-ink-950]"
          >
            <option value="todos">Todos los estados</option>
            {ESTADOS.map((e) => (
              <option key={e.value} value={e.value}>
                {e.label}
              </option>
            ))}
          </select>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="rounded-lg border border-[--color-ink-100] bg-white px-4 py-3 text-base text-[--color-ink-950]"
          >
            <option value="none">Sin ordenar</option>
            <option value="precio-asc">Precio: menor a mayor</option>
            <option value="precio-desc">Precio: mayor a menor</option>
            <option value="stock-asc">Stock: menor a mayor</option>
            <option value="stock-desc">Stock: mayor a menor</option>
          </select>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1280px] text-left">
            <thead>
              <tr className="border-b border-[--color-ink-100] bg-[--color-ink-50] text-sm text-[--color-neutral-600]">
                <th className="px-4 py-3 font-medium">
                  <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} className="h-4 w-4" aria-label="Seleccionar todos" />
                </th>
                <th className="px-5 py-3 font-medium">Imagen</th>
                <th className="px-5 py-3 font-medium">SKU</th>
                <th className="px-5 py-3 font-medium">Producto</th>
                <th className="px-5 py-3 font-medium">Categoría</th>
                <th className="px-5 py-3 text-right font-medium">
                  <span className="inline-flex items-center gap-1">
                    Precio <ArrowUpDown size={14} />
                  </span>
                </th>
                <th className="px-5 py-3 text-right font-medium">
                  <span className="inline-flex items-center gap-1">
                    Stock <ArrowUpDown size={14} />
                  </span>
                </th>
                <th className="px-5 py-3 font-medium">Estado</th>
                <th className="px-5 py-3 font-medium">Publicación</th>
                <th className="px-5 py-3 font-medium">Actualizado</th>
                <th className="px-5 py-3 font-medium">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[--color-ink-100]">
              {filtered.map((p) => (
                <tr key={p.id} className="text-base text-[--color-ink-950] hover:bg-[--color-ink-50]/60">
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selected.has(p.id)}
                      onChange={() => toggleSelect(p.id, p.estado)}
                      className="h-4 w-4"
                      aria-label={`Seleccionar ${p.nombre}`}
                    />
                  </td>
                  <td className="px-5 py-3">
                    <button onClick={() => navigate(`/productos/${p.id}`)} aria-label={`Ver ${p.nombre}`}>
                      <ProductImage src={p.imagenUrl} alt={p.nombre} size="sm" />
                    </button>
                  </td>
                  <td className="px-5 py-3 text-[--color-neutral-600]">{p.sku}</td>
                  <td className="px-5 py-3 font-medium">
                    <button onClick={() => navigate(`/productos/${p.id}`)} className="text-left hover:underline">
                      {p.nombre}
                    </button>
                  </td>
                  <td className="px-5 py-3 text-[--color-neutral-600]">{p.categoria}</td>
                  <td className="px-5 py-3 text-right tabular-nums">{formatCLP(p.precio)}</td>
                  <td className="px-5 py-3 text-right tabular-nums">{p.stock}</td>
                  <td className="px-5 py-3">
                    <StatusBadge status={p.estado} />
                  </td>
                  <td className="px-5 py-3 text-[--color-neutral-600]">{p.mercadoLibreId || 'No publicado'}</td>
                  <td className="px-5 py-3 text-[--color-neutral-600]">{formatDate(p.actualizadoEn)}</td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      {publicationAction(p)}
                      <button onClick={() => handleDelete(p.id, p.nombre)} className="text-sm font-semibold text-[--color-err-600] hover:underline">
                        Eliminar
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-5 py-10 text-center text-base text-[--color-neutral-600]">
                    No encontramos productos con esos filtros. Prueba ajustando la búsqueda.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
