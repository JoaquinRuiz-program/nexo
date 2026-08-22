import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { MobileDrawer } from './MobileDrawer';

const TITLES: Record<string, string> = {
  '/': 'Inicio',
  '/productos': 'Productos',
  '/productos/importar': 'Importar productos',
  '/productos/publicar-masivo': 'Publicación masiva',
  '/agregar-producto': 'Agregar producto',
  '/pendientes': 'Pendientes',
  '/configuracion': 'Configuración',
};

function resolveTitle(pathname: string): string {
  if (TITLES[pathname]) return TITLES[pathname];
  if (pathname.endsWith('/publicar')) return 'Preparar publicación';
  if (pathname.startsWith('/productos/')) return 'Detalle de producto';
  return 'Librería Central';
}

export function AppLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const title = resolveTitle(location.pathname);

  return (
    <div className="flex h-screen overflow-hidden bg-[--color-paper]">
      <Sidebar />
      <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header onMenuClick={() => setDrawerOpen(true)} title={title} />
        <main className="flex-1 overflow-y-auto px-5 py-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
