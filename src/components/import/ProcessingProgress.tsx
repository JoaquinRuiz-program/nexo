import { CheckCircle2, Loader2 } from 'lucide-react';

const TASKS = [
  'Información básica validada',
  'SKU verificados',
  'Precios verificados',
  'Stock verificado',
  'Categorías identificadas',
  'Productos duplicados detectados',
  'Imágenes verificadas',
  'Preparando publicaciones',
];

interface ProcessingProgressProps {
  processed: number;
  total: number;
}

export function ProcessingProgress({ processed, total }: ProcessingProgressProps) {
  const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const tasksDone = Math.min(TASKS.length, Math.floor((pct / 100) * TASKS.length) + (pct > 0 ? 1 : 0));

  return (
    <div className="flex flex-col items-center gap-6 py-6 text-center">
      <div>
        <h2 className="font-display text-2xl font-semibold text-[--color-ink-950]">Procesando catálogo…</h2>
        <p className="mt-1 text-base text-[--color-neutral-600]">
          {processed.toLocaleString('es-CL')} / {total.toLocaleString('es-CL')} productos procesados
        </p>
      </div>

      <div className="w-full max-w-md">
        <div className="h-4 w-full overflow-hidden rounded-full bg-[--color-ink-100]">
          <div
            className="h-full rounded-full bg-[--color-gold-500] transition-all duration-300 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-2 text-sm font-medium text-[--color-ink-900]">{pct}%</p>
      </div>

      <ul className="flex w-full max-w-sm flex-col gap-2 text-left">
        {TASKS.map((task, i) => {
          const done = i < tasksDone;
          const active = i === tasksDone && pct < 100;
          return (
            <li key={task} className="flex items-center gap-3 text-base">
              {done ? (
                <CheckCircle2 size={20} className="shrink-0 text-[--color-ok-600]" />
              ) : active ? (
                <Loader2 size={20} className="shrink-0 animate-spin text-[--color-gold-500]" />
              ) : (
                <span className="h-5 w-5 shrink-0 rounded-full border-2 border-[--color-ink-100]" />
              )}
              <span className={done ? 'text-[--color-ink-950]' : 'text-[--color-neutral-600]'}>{task}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
