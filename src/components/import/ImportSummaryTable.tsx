import type { ImportRowResult, ImportSummary } from '@/types/import';

export function ImportSummaryCards({ summary }: { summary: ImportSummary }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <div className="rounded-[--radius-card] border border-[--color-ok-100] bg-[--color-ok-100]/40 p-5">
        <p className="font-display text-3xl font-semibold text-[--color-ok-600]">{summary.validos.toLocaleString('es-CL')}</p>
        <p className="mt-1 text-base text-[--color-ink-900]">productos válidos</p>
      </div>
      <div className="rounded-[--radius-card] border border-[--color-warn-100] bg-[--color-warn-100]/40 p-5">
        <p className="font-display text-3xl font-semibold text-[--color-warn-600]">{summary.revision.toLocaleString('es-CL')}</p>
        <p className="mt-1 text-base text-[--color-ink-900]">requieren revisión</p>
      </div>
      <div className="rounded-[--radius-card] border border-[--color-err-100] bg-[--color-err-100]/40 p-5">
        <p className="font-display text-3xl font-semibold text-[--color-err-600]">{summary.errores.toLocaleString('es-CL')}</p>
        <p className="mt-1 text-base text-[--color-ink-900]">productos con errores</p>
      </div>
    </div>
  );
}

export function ImportProblemsTable({ rows }: { rows: ImportRowResult[] }) {
  const withProblems = rows.filter((r) => r.problemas.length > 0);

  if (withProblems.length === 0) {
    return <p className="text-base text-[--color-neutral-600]">No detectamos problemas en los productos importados.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-[--radius-card] border border-[--color-ink-100]">
      <table className="w-full min-w-[560px] text-left">
        <thead>
          <tr className="border-b border-[--color-ink-100] bg-[--color-ink-50] text-sm text-[--color-neutral-600]">
            <th className="px-4 py-3 font-medium">SKU</th>
            <th className="px-4 py-3 font-medium">Producto</th>
            <th className="px-4 py-3 font-medium">Problema</th>
            <th className="px-4 py-3 font-medium">Estado</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[--color-ink-100]">
          {withProblems.map((row) => (
            <tr key={row.rowIndex} className="text-base text-[--color-ink-950]">
              <td className="px-4 py-3 text-[--color-neutral-600]">{row.sku || '—'}</td>
              <td className="px-4 py-3 font-medium">{row.nombre || '(sin nombre)'}</td>
              <td className="px-4 py-3 text-[--color-neutral-600]">{row.problemas.join(', ')}</td>
              <td className="px-4 py-3">
                {row.estado === 'error' ? (
                  <span className="text-sm font-medium text-[--color-err-600]">Error</span>
                ) : (
                  <span className="text-sm font-medium text-[--color-warn-600]">Pendiente</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
