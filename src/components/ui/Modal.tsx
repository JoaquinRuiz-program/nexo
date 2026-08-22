import type { ReactNode } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

export function Modal({ open, onClose, title, children }: ModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div className="relative w-full max-w-md rounded-[--radius-card] bg-white p-6 shadow-xl">
        <div className="flex items-start justify-between gap-4">
          <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-[--color-neutral-600] hover:bg-[--color-ink-50]" aria-label="Cerrar">
            <X size={20} />
          </button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}
