import { useState } from 'react';
import { ShoppingBag } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';

export function Settings() {
  const [nombre, setNombre] = useState('Mi tienda');
  const [email, setEmail] = useState('contacto@mitienda.cl');
  const [telefono, setTelefono] = useState('+56 9 1234 5678');
  const [saved, setSaved] = useState(false);

  function handleSave() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <Card className="p-6 lg:p-8">
        <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">Información de la librería</h2>
        <div className="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-[--color-ink-900]">Nombre</span>
            <input
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              className="rounded-lg border border-[--color-ink-100] bg-white px-4 py-3 text-base text-[--color-ink-950] focus:border-[--color-ink-800]"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-[--color-ink-900]">Logo</span>
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-[--color-ink-950] text-sm font-semibold text-[--color-gold-500]">
                LC
              </div>
              <Button type="button" variant="secondary">
                Cambiar logo
              </Button>
            </div>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-[--color-ink-900]">Email</span>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-lg border border-[--color-ink-100] bg-white px-4 py-3 text-base text-[--color-ink-950] focus:border-[--color-ink-800]"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-[--color-ink-900]">Teléfono</span>
            <input
              value={telefono}
              onChange={(e) => setTelefono(e.target.value)}
              className="rounded-lg border border-[--color-ink-100] bg-white px-4 py-3 text-base text-[--color-ink-950] focus:border-[--color-ink-800]"
            />
          </label>
        </div>
        <div className="mt-6 flex items-center gap-3">
          <Button onClick={handleSave}>Guardar cambios</Button>
          {saved && <span className="text-sm font-medium text-[--color-ok-600]">Cambios guardados</span>}
        </div>
      </Card>

      <Card className="p-6 lg:p-8">
        <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">Integraciones</h2>
        <div className="mt-5 flex items-center justify-between rounded-lg border border-[--color-ink-100] p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-[--color-ink-50] text-[--color-ink-900]">
              <ShoppingBag size={22} />
            </div>
            <div>
              <p className="text-base font-medium text-[--color-ink-950]">Mercado Libre</p>
              <p className="text-sm text-[--color-neutral-600]">Desconectado</p>
            </div>
          </div>
          <Button variant="secondary" disabled>
            Conectar próximamente
          </Button>
        </div>
      </Card>
    </div>
  );
}
