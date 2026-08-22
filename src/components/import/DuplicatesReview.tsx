import type { DuplicateGroup, ImportRowResult } from '@/types/import';

interface DuplicatesReviewProps {
  groups: DuplicateGroup[];
  rows: ImportRowResult[];
  onResolve: (clave: string, resolucion: DuplicateGroup['resolucion']) => void;
}

export function DuplicatesReview({ groups, rows, onResolve }: DuplicatesReviewProps) {
  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">Productos duplicados</h2>
      <p className="text-base text-[--color-neutral-600]">
        Encontramos SKU que se repiten en tu archivo. Elige qué hacer con cada uno.
      </p>

      <div className="flex flex-col gap-4">
        {groups.map((group) => {
          const filas = group.filas.map((i) => rows[i]).filter(Boolean);
          const nombre = filas[0]?.nombre || '(sin nombre)';
          return (
            <div key={group.clave} className="rounded-[--radius-card] border border-[--color-ink-100] p-5">
              <p className="text-sm font-medium text-[--color-neutral-600]">SKU {group.clave.toUpperCase()}</p>
              <p className="mt-1 text-lg font-medium text-[--color-ink-950]">"{nombre}"</p>
              <p className="mt-1 text-sm text-[--color-neutral-600]">Aparece {filas.length} veces en el archivo.</p>

              <div className="mt-4 flex flex-wrap gap-2">
                <ResolutionButton
                  label="Mantener primero"
                  active={group.resolucion === 'primero'}
                  onClick={() => onResolve(group.clave, 'primero')}
                />
                <ResolutionButton
                  label="Mantener último"
                  active={group.resolucion === 'ultimo'}
                  onClick={() => onResolve(group.clave, 'ultimo')}
                />
                <ResolutionButton
                  label="Revisar manualmente"
                  active={group.resolucion === 'manual'}
                  onClick={() => onResolve(group.clave, 'manual')}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ResolutionButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border px-4 py-2 text-sm font-semibold transition-colors ${
        active
          ? 'border-[--color-ink-900] bg-[--color-ink-900] text-white'
          : 'border-[--color-ink-100] bg-white text-[--color-ink-900] hover:bg-[--color-ink-50]'
      }`}
    >
      {label}
    </button>
  );
}
