import type { ProductStatus } from '@/types/product';

const STYLES: Record<ProductStatus, { label: string; dot: string; bg: string; text: string }> = {
  listo: { label: 'Listo para publicar', dot: 'bg-[--color-ok-600]', bg: 'bg-[--color-ok-100]', text: 'text-[--color-ok-600]' },
  pendiente: { label: 'Pendiente', dot: 'bg-[--color-warn-600]', bg: 'bg-[--color-warn-100]', text: 'text-[--color-warn-600]' },
  error: { label: 'Con errores', dot: 'bg-[--color-err-600]', bg: 'bg-[--color-err-100]', text: 'text-[--color-err-600]' },
  publicado: { label: 'Publicado', dot: 'bg-[--color-ink-700]', bg: 'bg-[--color-ink-100]', text: 'text-[--color-ink-700]' },
  'sin-publicar': { label: 'Sin publicar', dot: 'bg-[--color-neutral-600]', bg: 'bg-[--color-neutral-100]', text: 'text-[--color-neutral-600]' },
};

export function StatusBadge({ status }: { status: ProductStatus }) {
  const s = STYLES[status];
  return (
    <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ${s.bg} ${s.text}`}>
      <span className={`h-2.5 w-2.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
