import { useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, ShoppingBag, CheckCircle2, XCircle } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useProducts } from '@/context/ProductContext';
import { validateProductForPublication } from '@/services/mercadoLibreService';

interface LocationState {
  ids?: string[];
}

export function BulkPublish() {
  const navigate = useNavigate();
  const location = useLocation();
  const { products, publishProductsBulk } = useProducts();
  const state = (location.state as LocationState | null) ?? {};

  const selected = useMemo(() => products.filter((p) => (state.ids ?? []).includes(p.id)), [products, state.ids]);

  const classified = useMemo(
    () =>
      selected.map((p) => ({
        product: p,
        validation: validateProductForPublication(p),
      })),
    [selected],
  );

  const listos = classified.filter((c) => c.validation.resultado === 'listo');
  const revision = classified.filter((c) => c.validation.resultado === 'revision');
  const errores = classified.filter((c) => c.validation.resultado === 'bloqueado');

  const [publishing, setPublishing] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number; entries: { id: string; nombre: string; ok: boolean }[] }>({
    done: 0,
    total: 0,
    entries: [],
  });
  const [finished, setFinished] = useState<{ ok: number; fail: number } | null>(null);

  if (selected.length === 0) {
    return (
      <div className="mx-auto max-w-2xl">
        <Card className="p-8 text-center">
          <p className="text-lg text-[--color-ink-950]">No hay productos seleccionados.</p>
          <Button className="mt-4" onClick={() => navigate('/productos')}>
            Volver a productos
          </Button>
        </Card>
      </div>
    );
  }

  async function handlePublish() {
    setPublishing(true);
    setProgress({ done: 0, total: listos.length, entries: [] });
    const ids = listos.map((c) => c.product.id);

    const result = await publishProductsBulk(ids, (done, total, product, result) => {
      setProgress((prev) => ({
        done,
        total,
        entries: [...prev.entries, { id: product.id, nombre: product.nombre, ok: result.ok }],
      }));
    });

    setFinished({ ok: result.ok.length, fail: result.fail.length });
    setPublishing(false);
  }

  return (
    <div className="mx-auto max-w-2xl">
      <button
        onClick={() => navigate('/productos')}
        className="mb-6 inline-flex items-center gap-2 text-base font-medium text-[--color-ink-900] hover:underline"
      >
        <ArrowLeft size={18} />
        Volver a productos
      </button>

      {finished ? (
        <Card className="flex flex-col items-center gap-3 p-10 text-center">
          <CheckCircle2 size={44} className="text-[--color-ok-600]" />
          <h1 className="font-display text-2xl font-semibold text-[--color-ink-950]">Publicación completada</h1>
          <p className="text-base text-[--color-neutral-600]">
            {finished.ok} producto{finished.ok === 1 ? '' : 's'} publicado{finished.ok === 1 ? '' : 's'} correctamente.
          </p>
          {finished.fail > 0 && (
            <p className="text-base text-[--color-warn-600]">{finished.fail} no se pudieron publicar.</p>
          )}
          <Button className="mt-2" onClick={() => navigate('/productos')}>
            Ver productos
          </Button>
        </Card>
      ) : publishing ? (
        <Card className="p-6 lg:p-8">
          <h1 className="font-display text-2xl font-semibold text-[--color-ink-950]">Publicando productos…</h1>
          <p className="mt-1 text-base text-[--color-neutral-600]">
            {progress.done} / {progress.total}
          </p>
          <div className="mt-4 h-3 w-full overflow-hidden rounded-full bg-[--color-ink-100]">
            <div
              className="h-full rounded-full bg-[--color-gold-500] transition-all duration-300 ease-out"
              style={{ width: `${progress.total > 0 ? (progress.done / progress.total) * 100 : 0}%` }}
            />
          </div>
          <ul className="mt-5 flex flex-col gap-2">
            {progress.entries.map((e, i) => (
              <li key={e.id} className="flex items-center gap-2 text-base text-[--color-ink-950]">
                {e.ok ? <CheckCircle2 size={18} className="text-[--color-ok-600]" /> : <XCircle size={18} className="text-[--color-err-600]" />}
                {i + 1} / {progress.total} — {e.nombre}
              </li>
            ))}
          </ul>
        </Card>
      ) : (
        <Card className="p-6 lg:p-8">
          <h1 className="font-display text-2xl font-semibold text-[--color-ink-950]">Publicación masiva</h1>
          <p className="mt-1 text-base text-[--color-neutral-600]">Productos seleccionados: {selected.length}</p>

          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-[--radius-card] border border-[--color-ok-100] bg-[--color-ok-100]/40 p-5">
              <p className="font-display text-3xl font-semibold text-[--color-ok-600]">{listos.length}</p>
              <p className="mt-1 text-base text-[--color-ink-900]">listos</p>
            </div>
            <div className="rounded-[--radius-card] border border-[--color-warn-100] bg-[--color-warn-100]/40 p-5">
              <p className="font-display text-3xl font-semibold text-[--color-warn-600]">{revision.length}</p>
              <p className="mt-1 text-base text-[--color-ink-900]">requieren revisión</p>
            </div>
            <div className="rounded-[--radius-card] border border-[--color-err-100] bg-[--color-err-100]/40 p-5">
              <p className="font-display text-3xl font-semibold text-[--color-err-600]">{errores.length}</p>
              <p className="mt-1 text-base text-[--color-ink-900]">con error</p>
            </div>
          </div>

          {(revision.length > 0 || errores.length > 0) && (
            <p className="mt-4 text-sm text-[--color-neutral-600]">
              Solo se publicarán los productos listos. Los que requieren revisión o tienen errores deben corregirse antes.
            </p>
          )}

          <div className="mt-6">
            <Button icon={<ShoppingBag size={18} />} onClick={handlePublish} disabled={listos.length === 0}>
              Publicar {listos.length} producto{listos.length === 1 ? '' : 's'}
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
