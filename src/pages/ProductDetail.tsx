import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Pencil, Trash2, Save, ShoppingBag, CheckCircle2, Sparkles } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { ProductImage } from '@/components/products/ProductImage';
import { ProductForm } from '@/components/products/ProductForm';
import { useProducts } from '@/context/ProductContext';
import { formatCLP, formatDate } from '@/services/productService';
import type { ProductFormInput } from '@/types/product';

export function ProductDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { getProduct, editProduct, deleteProduct, updateStatus } = useProducts();
  const [editing, setEditing] = useState(false);

  const product = id ? getProduct(id) : undefined;

  if (!product) {
    return (
      <div className="mx-auto max-w-3xl">
        <Card className="p-8 text-center">
          <p className="text-lg text-[--color-ink-950]">No encontramos este producto.</p>
          <Button className="mt-4" onClick={() => navigate('/productos')}>
            Volver a productos
          </Button>
        </Card>
      </div>
    );
  }

  function handleSave(input: ProductFormInput) {
    if (!product) return;
    editProduct(product.id, input);
    setEditing(false);
  }

  function handleDelete() {
    if (!product) return;
    if (window.confirm(`¿Eliminar "${product.nombre}"? Esta acción no se puede deshacer.`)) {
      deleteProduct(product.id);
      navigate('/productos');
    }
  }

  function handleMarkReady() {
    if (!product) return;
    updateStatus(product.id, true);
  }

  return (
    <div className="mx-auto max-w-3xl">
      <button
        onClick={() => navigate('/productos')}
        className="mb-6 inline-flex items-center gap-2 text-base font-medium text-[--color-ink-900] hover:underline"
      >
        <ArrowLeft size={18} />
        Volver a productos
      </button>

      {editing ? (
        <Card className="p-6 lg:p-8">
          <h1 className="mb-6 font-display text-2xl font-semibold text-[--color-ink-950]">Editar información</h1>
          <ProductForm
            initial={{
              sku: product.sku,
              nombre: product.nombre,
              marca: product.marca,
              categoria: product.categoria,
              precio: product.precio,
              stock: product.stock,
              descripcion: product.descripcion,
              imagenUrl: product.imagenUrl,
              publicar: product.publicar,
            }}
            submitLabel="Guardar cambios"
            onSubmit={handleSave}
            onCancel={() => setEditing(false)}
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-6">
          <Card className="p-6 lg:p-8">
            <div className="flex flex-col gap-6 sm:flex-row">
              <ProductImage src={product.imagenUrl} alt={product.nombre} size="lg" />
              <div className="flex flex-1 flex-col gap-3">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="font-display text-2xl font-semibold text-[--color-ink-950]">{product.nombre}</h1>
                  <StatusBadge status={product.estado} />
                </div>
                <p className="text-base text-[--color-neutral-600]">SKU {product.sku} · {product.marca} · {product.categoria}</p>
                <p className="font-display text-3xl font-semibold text-[--color-ink-950]">{formatCLP(product.precio)}</p>
                <p className="text-base text-[--color-ink-900]">Stock disponible: <span className="font-semibold">{product.stock}</span></p>
                <p className="text-sm text-[--color-neutral-600]">
                  Última actualización: {formatDate(product.actualizadoEn)}
                  {product.origen === 'excel' && ' · Importado desde Excel'}
                </p>
              </div>
            </div>

            <div className="mt-6 border-t border-[--color-ink-100] pt-6">
              <h2 className="font-display text-lg font-semibold text-[--color-ink-950]">Descripción</h2>
              <p className="mt-2 text-base text-[--color-ink-900]">
                {product.descripcion || <span className="text-[--color-neutral-600]">Sin descripción todavía.</span>}
              </p>
            </div>

            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
              <Button icon={<Pencil size={18} />} onClick={() => setEditing(true)}>
                Editar información
              </Button>
              <Button variant="secondary" icon={<Save size={18} />} onClick={() => setEditing(true)}>
                Guardar cambios
              </Button>
              {product.estado !== 'listo' && product.estado !== 'publicado' && (
                <Button variant="secondary" icon={<CheckCircle2 size={18} />} onClick={handleMarkReady}>
                  Marcar como listo
                </Button>
              )}
              <Button variant="danger" icon={<Trash2 size={18} />} onClick={handleDelete}>
                Eliminar producto
              </Button>
            </div>
          </Card>

          {(product.original || product.procesado) && (
            <Card className="p-6 lg:p-8">
              <h2 className="font-display text-lg font-semibold text-[--color-ink-950]">Cómo se preparó este producto</h2>
              <p className="mt-1 text-sm text-[--color-neutral-600]">
                Comparación entre los datos que llegaron desde tu Excel y lo que el sistema preparó automáticamente.
              </p>
              <div className="mt-5 grid grid-cols-1 gap-6 sm:grid-cols-2">
                <div>
                  <p className="text-sm font-medium uppercase tracking-wide text-[--color-neutral-600]">Original</p>
                  <div className="mt-2 flex flex-col gap-2 rounded-lg border border-[--color-ink-100] p-4">
                    <Field label="Nombre" value={product.original?.nombre || '—'} />
                    <Field label="Categoría" value={product.original?.categoria || '—'} />
                    <Field label="Descripción" value={product.original?.descripcion || 'Sin descripción'} />
                  </div>
                </div>
                <div>
                  <p className="flex items-center gap-1.5 text-sm font-medium uppercase tracking-wide text-[--color-gold-600]">
                    <Sparkles size={14} /> Procesado
                  </p>
                  <div className="mt-2 flex flex-col gap-2 rounded-lg border border-[--color-gold-100] bg-[--color-gold-100]/30 p-4">
                    <Field label="Título" value={product.procesado?.titulo || '—'} />
                    <Field label="Categoría sugerida" value={product.procesado?.categoria || '—'} />
                    <Field label="Descripción" value={product.procesado?.descripcion || '—'} />
                    {product.procesado && product.procesado.atributos.length > 0 && (
                      <div>
                        <p className="text-sm text-[--color-neutral-600]">Atributos detectados</p>
                        <ul className="mt-1 flex flex-wrap gap-1.5">
                          {product.procesado.atributos.map((a) => (
                            <li key={a.etiqueta} className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-[--color-ink-900]">
                              {a.etiqueta}: {a.valor}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          )}

          <Card className="p-6 lg:p-8">
            <h2 className="font-display text-lg font-semibold text-[--color-ink-950]">Publicación en Mercado Libre</h2>
            <p className="mt-1 text-base font-medium text-[--color-ink-900]">
              Estado: {product.mercadoLibreId ? `Publicado (${product.mercadoLibreId})` : 'No publicado'}
            </p>
            {!product.mercadoLibreId && (
              <p className="mt-2 text-base text-[--color-neutral-600]">
                Este producto está listo para ser enviado a Mercado Libre cuando la integración esté disponible.
              </p>
            )}
            <div className="mt-4">
              <Button
                variant="secondary"
                icon={<ShoppingBag size={18} />}
                onClick={() => navigate(`/productos/${product.id}/publicar`)}
              >
                {product.mercadoLibreId ? 'Ver publicación' : 'Preparar publicación'}
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-sm text-[--color-neutral-600]">{label}</p>
      <p className="text-base text-[--color-ink-950]">{value}</p>
    </div>
  );
}
