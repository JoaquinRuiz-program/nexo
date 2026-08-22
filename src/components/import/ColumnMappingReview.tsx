import { CheckCircle2, Circle } from 'lucide-react';
import type { ColumnMapping, ImportField } from '@/types/import';
import { IMPORT_FIELD_LABELS, IMPORT_FIELD_ORDER } from '@/types/import';

interface ColumnMappingReviewProps {
  headers: string[];
  mapping: ColumnMapping;
  rowCount: number;
  onChange: (field: ImportField, header: string | null) => void;
}

export function ColumnMappingReview({ headers, mapping, rowCount, onChange }: ColumnMappingReviewProps) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="font-display text-2xl font-semibold text-[--color-ink-950]">Hemos encontrado tus productos</h2>
        <p className="mt-2 text-lg text-[--color-ink-900]">
          <span className="font-semibold">{rowCount.toLocaleString('es-CL')}</span> productos encontrados
        </p>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-sm font-medium text-[--color-ink-900]">Columnas detectadas</p>
        {IMPORT_FIELD_ORDER.map((field) => {
          const matched = mapping[field];
          return (
            <div key={field} className="flex flex-col gap-2 rounded-lg border border-[--color-ink-100] p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                {matched ? (
                  <CheckCircle2 size={20} className="shrink-0 text-[--color-ok-600]" />
                ) : (
                  <Circle size={20} className="shrink-0 text-[--color-neutral-600]" />
                )}
                <span className="text-base font-medium text-[--color-ink-950]">{IMPORT_FIELD_LABELS[field]}</span>
              </div>
              <select
                value={matched ?? ''}
                onChange={(e) => onChange(field, e.target.value || null)}
                className="rounded-lg border border-[--color-ink-100] bg-white px-4 py-2.5 text-base text-[--color-ink-950] sm:min-w-[220px]"
              >
                <option value="">No encontrada — elegir columna</option>
                {headers.map((h) => (
                  <option key={h} value={h}>
                    {h}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>
    </div>
  );
}
