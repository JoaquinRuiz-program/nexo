import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { CircleCheck, AlertCircle } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { ProductImage } from '@/components/products/ProductImage';
import { useProducts } from '@/context/ProductContext';
import { findIssues } from '@/services/productService';

export function Pending() {
  const { products } = useProducts();
  const navigate = useNavigate();

  const pendientes = useMemo(
    () => products.filter((p) => p.estado === 'pendiente' || p.estado === 'error'),
    [products],
  );

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <p className="text-lg text-[--color-neutral-600]">
        Estos productos necesitan revisión antes de poder publicarse correctamente.
      </p>

      {pendientes.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 p-12 text-center">
          <CircleCheck size={40} className="text-[--color-ok-600]" />
          <p className="text-lg font-medium text-[--color-ink-950]">No hay productos pendientes</p>
          <p className="text-base text-[--color-neutral-600]">Todo tu catálogo está al día.</p>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {pendientes.map((p) => {
            const issues = findIssues(p);
            return (
              <Card key={p.id} className="p-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex gap-4">
                    <ProductImage src={p.imagenUrl} alt={p.nombre} />
                    <div>
                      <div className="flex flex-wrap items-center gap-3">
                        <h2 className="font-display text-lg font-semibold text-[--color-ink-950]">{p.nombre}</h2>
                        <StatusBadge status={p.estado} />
                      </div>
                      <p className="mt-1 text-sm text-[--color-neutral-600]">SKU {p.sku} · {p.categoria}</p>

                      {issues.length > 0 && (
                        <div className="mt-3">
                          <p className="text-sm font-medium text-[--color-ink-900]">Problemas detectados:</p>
                          <ul className="mt-1 flex flex-col gap-1">
                            {issues.map((issue) => (
                              <li key={issue.id} className="flex items-center gap-2 text-sm text-[--color-warn-600]">
                                <AlertCircle size={14} />
                                {issue.label}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex shrink-0 gap-3">
                    <Button variant="secondary" onClick={() => navigate(`/productos/${p.id}`)}>
                      Revisar
                    </Button>
                    <Button onClick={() => navigate(`/productos/${p.id}`)}>Editar</Button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
