import { CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import type { ValidationCheck, ValidationResult } from '@/services/mercadoLibreService';

const SEVERITY_ICON = {
  ok: <CheckCircle2 size={20} className="shrink-0 text-[--color-ok-600]" />,
  warn: <AlertTriangle size={20} className="shrink-0 text-[--color-warn-600]" />,
  error: <XCircle size={20} className="shrink-0 text-[--color-err-600]" />,
};

export function ValidationChecklist({ checks }: { checks: ValidationCheck[] }) {
  return (
    <ul className="flex flex-col gap-2.5">
      {checks.map((check) => (
        <li key={check.id} className="flex items-start gap-3">
          {SEVERITY_ICON[check.severity]}
          <div>
            <p className="text-base text-[--color-ink-950]">{check.label}</p>
            {check.detalle && <p className="text-sm text-[--color-neutral-600]">{check.detalle}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ValidationSummary({ result }: { result: ValidationResult }) {
  if (result.resultado === 'listo') {
    return (
      <div className="flex items-center gap-3 rounded-lg bg-[--color-ok-100] px-4 py-3 text-[--color-ok-600]">
        <CheckCircle2 size={22} />
        <p className="text-base font-semibold">Producto listo para publicar</p>
      </div>
    );
  }
  if (result.resultado === 'revision') {
    return (
      <div className="flex items-center gap-3 rounded-lg bg-[--color-warn-100] px-4 py-3 text-[--color-warn-600]">
        <AlertTriangle size={22} />
        <p className="text-base font-semibold">Requiere revisión</p>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3 rounded-lg bg-[--color-err-100] px-4 py-3 text-[--color-err-600]">
      <XCircle size={22} />
      <p className="text-base font-semibold">Este producto necesita correcciones antes de poder publicarse</p>
    </div>
  );
}
