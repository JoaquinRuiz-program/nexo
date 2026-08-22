import { NavLink } from 'react-router-dom';
import { LayoutGrid, Package, CirclePlus, ClipboardList, Settings, BookOpen, X } from 'lucide-react';

const NAV_ITEMS = [
  { to: '/', label: 'Inicio', icon: LayoutGrid, end: true },
  { to: '/productos', label: 'Productos', icon: Package, end: false },
  { to: '/agregar-producto', label: 'Agregar producto', icon: CirclePlus, end: false },
  { to: '/pendientes', label: 'Pendientes', icon: ClipboardList, end: false },
  { to: '/configuracion', label: 'Configuración', icon: Settings, end: false },
] as const;

export function MobileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <aside className="absolute left-0 top-0 flex h-full w-72 flex-col bg-[--color-ink-950] text-[--color-ink-50] shadow-xl">
        <div className="flex items-center justify-between px-6 py-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[--color-gold-500] text-[--color-ink-950]">
              <BookOpen size={20} strokeWidth={2.2} />
            </div>
            <p className="font-display text-lg font-semibold text-white">Librería Central</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-white/70 hover:bg-[--color-ink-900]" aria-label="Cerrar menú">
            <X size={22} />
          </button>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-4">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-4 py-3 text-base font-medium ${
                  isActive ? 'bg-[--color-ink-800] text-white' : 'text-[--color-ink-100]/80 hover:bg-[--color-ink-900] hover:text-white'
                }`
              }
            >
              <Icon size={20} strokeWidth={2} />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
    </div>
  );
}
