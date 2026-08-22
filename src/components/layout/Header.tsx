import { Menu, UserCircle } from 'lucide-react';

export function Header({ onMenuClick, title }: { onMenuClick: () => void; title: string }) {
  return (
    <header className="flex items-center justify-between border-b border-[--color-ink-100] bg-white/80 px-5 py-4 backdrop-blur lg:px-8 lg:py-5">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onMenuClick}
          className="rounded-lg p-2 text-[--color-ink-900] hover:bg-[--color-ink-50] lg:hidden"
          aria-label="Abrir menú"
        >
          <Menu size={24} />
        </button>
        <div>
          <p className="font-display text-xl font-semibold text-[--color-ink-950] lg:text-2xl">{title}</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="hidden text-right sm:block">
          <p className="text-sm font-medium text-[--color-ink-950]">Administrador</p>
          <p className="text-xs text-[--color-neutral-600]">Librería Central</p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[--color-ink-100] text-[--color-ink-800]">
          <UserCircle size={26} />
        </div>
      </div>
    </header>
  );
}
