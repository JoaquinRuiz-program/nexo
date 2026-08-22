import { NavLink } from 'react-router-dom';
import { LayoutGrid, Package, CirclePlus, ClipboardList, Settings, BookOpen } from 'lucide-react';
import { useProducts } from '@/context/ProductContext';

const NAV_ITEMS = [
  { to: '/', label: 'Inicio', icon: LayoutGrid, end: true },
  { to: '/productos', label: 'Productos', icon: Package, end: false },
  { to: '/agregar-producto', label: 'Agregar producto', icon: CirclePlus, end: false },
  { to: '/pendientes', label: 'Pendientes', icon: ClipboardList, end: false },
  { to: '/configuracion', label: 'Configuración', icon: Settings, end: false },
] as const;

export function Sidebar() {
  const { products } = useProducts();
  const pendientesCount = products.filter((p) => p.estado === 'pendiente' || p.estado === 'error').length;

  return (
    <aside className="hidden w-72 shrink-0 flex-col bg-[--color-ink-950] text-[--color-ink-50] lg:flex">
      <div className="flex items-center gap-3 px-6 py-7">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-[--color-gold-500] text-[--color-ink-950]">
          <BookOpen size={22} strokeWidth={2.2} />
        </div>
        <div>
          <p className="font-display text-lg font-semibold leading-tight text-white">Librería Central</p>
          <p className="text-sm text-[--color-ink-600]">Gestión de productos</p>
        </div>
      </div>

      <nav className="mt-2 flex flex-1 flex-col gap-1 px-4">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center justify-between rounded-lg px-4 py-3 text-base font-medium transition-colors ${
                isActive
                  ? 'bg-[--color-ink-800] text-white'
                  : 'text-[--color-ink-100]/80 hover:bg-[--color-ink-900] hover:text-white'
              }`
            }
          >
            <span className="flex items-center gap-3">
              <Icon size={20} strokeWidth={2} />
              {label}
            </span>
            {label === 'Pendientes' && pendientesCount > 0 && (
              <span className="rounded-full bg-[--color-gold-500] px-2 py-0.5 text-xs font-semibold text-[--color-ink-950]">
                {pendientesCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-[--color-ink-800] px-6 py-5">
        <p className="text-xs uppercase tracking-wide text-[--color-ink-600]">Fase 1 — Prototipo</p>
        <p className="mt-1 text-sm text-[--color-ink-100]/70">Datos de prueba locales</p>
      </div>
    </aside>
  );
}
