import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ShoppingBag, RefreshCw, CheckCircle2, Sparkles, Pencil } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { ProductImage } from '@/components/products/ProductImage';
import { ValidationChecklist, ValidationSummary } from '@/components/publish/ValidationChecklist';
import { AttributesEditor } from '@/components/publish/AttributesEditor';
import { ImagesManager } from '@/components/publish/ImagesManager';
import { PublishingSteps } from '@/components/publish/PublishingSteps';
import { useProducts } from '@/context/ProductContext';
import { validateProductForPublication } from '@/services/mercadoLibreService';
import { formatCLP, formatDateTime, isOutOfSync } from '@/services/productService';
import { CATEGORIAS, type ProductCategory } from '@/types/product';

type Step = 'review' | 'publishing' | 'done';

export function PreparePublication() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { getProduct, updateProductFields, publishProduct, syncPrice, syncStock } = useProducts();
  const product = id ? getProduct(id) : undefined;

  const [step, setStep] = useState<Step>('review');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [editingCategory, setEditingCategory] = useState(false);
  const [syncing, setSyncing] = useState<'precio' | 'stock' | null>(null);

  const validation = useMemo(() => (product ? validateProductForPublication(product) : null), [product]);

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

  const yaPublicado = !!product.publicacionML;
  const desactualizado = yaPublicado && isOutOfSync(product);

  function handlePublishClick() {
    setPublishError(null);
    setConfirmOpen(true);
  }

  function handleSimulate() {
    setConfirmOpen(false);
    setStep('publishing');
  }

  async function handlePublishingComplete() {
    if (!product) return;
    const result = await publishProduct(product.id);
    if (!result.ok) {
      setPublishError(result.mensaje);
      setStep('review');
      return;
    }
    setStep('done');
  }

  async function handleSyncPrice() {
    if (!product) return;
    setSyncing('precio');
    await syncPrice(product.id);
    setSyncing(null);
  }

  async function handleSyncStock() {
    if (!product) return;
    setSyncing('stock');
    await syncStock(product.id);
    setSyncing(null);
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

      {step === 'publishing' && (
        <Card className="p-6 lg:p-8">
          <PublishingSteps onComplete={handlePublishingComplete} />
        </Card>
      )}

      {step === 'done' && product.publicacionML && (
        <Card className="flex flex-col items-center gap-3 p-10 text-center">
          <CheckCircle2 size={44} className="text-[--color-ok-600]" />
          <h2 className="font-display text-2xl font-semibold text-[--color-ink-950]">Publicación creada</h2>
          <p className="text-lg font-medium text-[--color-ink-950]">{product.nombre}</p>
          <p className="text-base text-[--color-neutral-600]">ID de publicación: <span className="font-semibold text-[--color-ink-950]">{product.publicacionML.id}</span></p>
          <div className="mt-2 flex gap-8">
            <div>
              <p className="text-sm text-[--color-neutral-600]">Estado</p>
              <p className="text-base font-medium text-[--color-ink-950]">Publicado</p>
            </div>
            <div>
              <p className="text-sm text-[--color-neutral-600]">Precio</p>
              <p className="text-base font-medium text-[--color-ink-950]">{formatCLP(product.publicacionML.precioPublicado)}</p>
            </div>
            <div>
              <p className="text-sm text-[--color-neutral-600]">Stock</p>
              <p className="text-base font-medium text-[--color-ink-950]">{product.publicacionML.stockPublicado}</p>
            </div>
          </div>
          <div className="mt-4 flex gap-3">
            <Button icon={<ShoppingBag size={18} />} onClick={() => window.alert('Publicación simulada: todavía no existe una publicación real en Mercado Libre.')}>
              Ver publicación
            </Button>
            <Button variant="secondary" onClick={() => navigate('/productos')}>
              Volver a productos
            </Button>
          </div>
        </Card>
      )}

      {step === 'review' && (
        <div className="flex flex-col gap-6">
          {publishError && (
            <Card className="border-[--color-err-100] bg-[--color-err-100]/40 p-4">
              <p className="text-base text-[--color-err-600]">{publishError}</p>
            </Card>
          )}

          {yaPublicado ? (
            <>
              <Card className="p-6 lg:p-8">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h1 className="font-display text-2xl font-semibold text-[--color-ink-950]">Publicación en Mercado Libre</h1>
                  <StatusBadge status={product.estado} />
                </div>
                <div className="mt-4 flex flex-col gap-6 sm:flex-row">
                  <ProductImage src={product.imagenUrl} alt={product.nombre} size="lg" />
                  <div className="flex flex-1 flex-col gap-2">
                    <p className="text-lg font-medium text-[--color-ink-950]">{product.nombre}</p>
                    <p className="text-sm text-[--color-neutral-600]">ID de publicación: {product.publicacionML!.id}</p>
                    <p className="text-sm text-[--color-neutral-600]">Publicado el {formatDateTime(product.publicacionML!.publicadoEn)}</p>
                  </div>
                </div>
              </Card>

              {desactualizado && (
                <Card className="border-[--color-warn-100] bg-[--color-warn-100]/30 p-6">
                  <h2 className="font-display text-lg font-semibold text-[--color-ink-950]">Cambio detectado</h2>
                  <div className="mt-3 flex flex-col gap-4">
                    {product.precio !== product.publicacionML!.precioPublicado && (
                      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-white p-4">
                        <div>
                          <p className="text-sm text-[--color-neutral-600]">Precio local: <span className="font-medium text-[--color-ink-950]">{formatCLP(product.precio)}</span></p>
                          <p className="text-sm text-[--color-neutral-600]">Precio publicado: <span className="font-medium text-[--color-ink-950]">{formatCLP(product.publicacionML!.precioPublicado)}</span></p>
                          <p className="mt-1 text-sm font-medium text-[--color-warn-600]">🟡 Desactualizado</p>
                        </div>
                        <Button
                          variant="secondary"
                          icon={syncing === 'precio' ? <RefreshCw size={18} className="animate-spin" /> : <RefreshCw size={18} />}
                          onClick={handleSyncPrice}
                          disabled={syncing === 'precio'}
                        >
                          {syncing === 'precio' ? 'Actualizando…' : 'Actualizar Mercado Libre'}
                        </Button>
                      </div>
                    )}
                    {product.stock !== product.publicacionML!.stockPublicado && (
                      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-white p-4">
                        <div>
                          <p className="text-sm text-[--color-neutral-600]">Stock local: <span className="font-medium text-[--color-ink-950]">{product.stock}</span></p>
                          <p className="text-sm text-[--color-neutral-600]">Stock publicado: <span className="font-medium text-[--color-ink-950]">{product.publicacionML!.stockPublicado}</span></p>
                          <p className="mt-1 text-sm font-medium text-[--color-warn-600]">🟡 Stock desactualizado</p>
                        </div>
                        <Button
                          variant="secondary"
                          icon={syncing === 'stock' ? <RefreshCw size={18} className="animate-spin" /> : <RefreshCw size={18} />}
                          onClick={handleSyncStock}
                          disabled={syncing === 'stock'}
                        >
                          {syncing === 'stock' ? 'Sincronizando…' : 'Sincronizar stock'}
                        </Button>
                      </div>
                    )}
                  </div>
                </Card>
              )}

              {!desactualizado && (
                <Card className="flex items-center gap-3 border-[--color-ok-100] bg-[--color-ok-100]/30 p-4">
                  <CheckCircle2 size={20} className="text-[--color-ok-600]" />
                  <p className="text-base font-medium text-[--color-ok-600]">Sincronizado con Mercado Libre</p>
                </Card>
              )}

              <Card className="p-6 lg:p-8">
                <h2 className="font-display text-lg font-semibold text-[--color-ink-950]">Historial de publicación</h2>
                <ul className="mt-4 flex flex-col gap-4">
                  {product.publicacionML!.historial.map((h) => (
                    <li key={h.id} className="border-l-2 border-[--color-ink-100] pl-4">
                      <p className="text-sm font-medium text-[--color-ink-950]">{formatDateTime(h.fecha)}</p>
                      <p className="text-base text-[--color-ink-900]">{h.mensaje}</p>
                      <p className="text-sm text-[--color-neutral-600]">
                        {h.precio !== undefined && `Precio: ${formatCLP(h.precio)}`}
                        {h.precio !== undefined && h.stock !== undefined && ' · '}
                        {h.stock !== undefined && `Stock: ${h.stock}`}
                      </p>
                    </li>
                  ))}
                </ul>
              </Card>
            </>
          ) : (
            <>
              <Card className="p-6 lg:p-8">
                <h1 className="font-display text-2xl font-semibold text-[--color-ink-950]">Preparar publicación</h1>
                <p className="mt-1 text-base text-[--color-neutral-600]">Así se vería tu producto en Mercado Libre.</p>

                <div className="mt-6 rounded-[--radius-card] border border-[--color-ink-100] p-5">
                  <p className="text-sm font-medium uppercase tracking-wide text-[--color-neutral-600]">Vista previa</p>
                  <div className="mt-3 flex flex-col gap-6 sm:flex-row">
                    <ImagesManager
                      imagenUrl={product.imagenUrl}
                      imagenesSecundarias={product.imagenesSecundarias}
                      onChangeMain={(url) => updateProductFields(product.id, { imagenUrl: url })}
                      onChangeSecondary={(urls) => updateProductFields(product.id, { imagenesSecundarias: urls })}
                    />
                    <div className="flex-1">
                      <h3 className="font-display text-xl font-semibold text-[--color-ink-950]">{product.nombre}</h3>
                      <p className="mt-2 font-display text-2xl font-semibold text-[--color-ink-950]">{formatCLP(product.precio)}</p>
                      <p className="mt-1 text-base text-[--color-ink-900]">Stock: {product.stock} unidades</p>
                      <p className="mt-1 text-base text-[--color-ink-900]">Marca: {product.marca}</p>
                      <p className="mt-3 text-base text-[--color-neutral-600]">{product.descripcion || 'Sin descripción todavía.'}</p>
                    </div>
                  </div>
                </div>
              </Card>

              <Card className="p-6 lg:p-8">
                <h2 className="font-display text-lg font-semibold text-[--color-ink-950]">Categoría</h2>
                <p className="mt-1 text-sm text-[--color-neutral-600]">Categoría sugerida por el procesamiento:</p>
                {editingCategory ? (
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <select
                      value={product.categoria}
                      onChange={(e) => updateProductFields(product.id, { categoria: e.target.value as ProductCategory })}
                      className="rounded-lg border border-[--color-ink-100] bg-white px-4 py-2.5 text-base text-[--color-ink-950]"
                    >
                      {CATEGORIAS.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                    <Button variant="secondary" onClick={() => setEditingCategory(false)}>
                      Listo
                    </Button>
                  </div>
                ) : (
                  <div className="mt-2 flex items-center gap-3">
                    <p className="text-lg font-medium text-[--color-ink-950]">{product.categoria}</p>
                    <Button variant="secondary" icon={<Pencil size={16} />} onClick={() => setEditingCategory(true)}>
                      Cambiar categoría
                    </Button>
                  </div>
                )}
              </Card>

              <Card className="p-6 lg:p-8">
                <h2 className="font-display text-lg font-semibold text-[--color-ink-950]">Características del producto</h2>
                <div className="mt-4">
                  <AttributesEditor atributos={product.atributos} onChange={(atributos) => updateProductFields(product.id, { atributos })} />
                </div>
              </Card>

              {product.procesado && (
                <Card className="border-[--color-gold-100] bg-[--color-gold-100]/20 p-6 lg:p-8">
                  <p className="flex items-center gap-1.5 text-sm font-medium uppercase tracking-wide text-[--color-gold-600]">
                    <Sparkles size={14} /> Descripción sugerida por el procesamiento
                  </p>
                  <p className="mt-2 text-base text-[--color-ink-900]">{product.procesado.descripcion}</p>
                </Card>
              )}

              <Card className="p-6 lg:p-8">
                <h2 className="font-display text-lg font-semibold text-[--color-ink-950]">Validación de publicación</h2>
                <div className="mt-4">{validation && <ValidationChecklist checks={validation.checks} />}</div>
                <div className="mt-5">{validation && <ValidationSummary result={validation} />}</div>

                <div className="mt-6">
                  <Button
                    icon={<ShoppingBag size={18} />}
                    onClick={handlePublishClick}
                    disabled={validation?.resultado === 'bloqueado'}
                  >
                    Publicar en Mercado Libre
                  </Button>
                </div>
              </Card>
            </>
          )}
        </div>
      )}

      <Modal open={confirmOpen} onClose={() => setConfirmOpen(false)} title="¿Publicar producto?">
        <p className="text-base text-[--color-ink-900]">El producto será enviado a Mercado Libre cuando la integración esté conectada.</p>
        <div className="mt-6 flex gap-3">
          <Button onClick={handleSimulate}>Simular publicación</Button>
          <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
            Cancelar
          </Button>
        </div>
      </Modal>
    </div>
  );
}
