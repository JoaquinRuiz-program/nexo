import { useEffect, useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';

const STEPS = [
  'Validando información',
  'Preparando imágenes',
  'Preparando categoría',
  'Preparando atributos',
  'Enviando publicación…',
  'Creando publicación…',
];

export function PublishingSteps({ onComplete }: { onComplete: () => void }) {
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    if (stepIndex >= STEPS.length) {
      const t = setTimeout(onComplete, 300);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setStepIndex((s) => s + 1), 380);
    return () => clearTimeout(t);
  }, [stepIndex, onComplete]);

  return (
    <div className="flex flex-col items-center gap-6 py-6 text-center">
      <h2 className="font-display text-2xl font-semibold text-[--color-ink-950]">Publicando producto…</h2>
      <ul className="flex w-full max-w-sm flex-col gap-2 text-left">
        {STEPS.map((step, i) => {
          const done = i < stepIndex;
          const active = i === stepIndex;
          return (
            <li key={step} className="flex items-center gap-3 text-base">
              {done ? (
                <CheckCircle2 size={20} className="shrink-0 text-[--color-ok-600]" />
              ) : active ? (
                <Loader2 size={20} className="shrink-0 animate-spin text-[--color-gold-500]" />
              ) : (
                <span className="h-5 w-5 shrink-0 rounded-full border-2 border-[--color-ink-100]" />
              )}
              <span className={done ? 'text-[--color-ink-950]' : 'text-[--color-neutral-600]'}>{step}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
