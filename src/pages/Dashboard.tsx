import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CirclePlus, ClipboardList, Package, CheckCircle2, Clock, AlertTriangle, FileUp, Sparkles, RefreshCw, ShoppingBag, Link2 } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useProducts } from '@/context/ProductContext';
import { formatRelative, isOutOfSync } from '@/services/productService';
import { connectMercadoLibre } from '@/services/mercadoLibreService';

export function Dashboard() {
  const { products, activity, automation } = useProducts();
  const navigate = useNavigate();
  const [connectMsg, setConnectMsg] = useState<string | null>(null);

  const stats = useMemo(() => {
    const total = products.length;
    const publicados = products.filter((p) => p.estado === 'publicado').length;
    const listos = products.filter((p) => p.estado === 'listo').length;
    const pendientes = products.filter((p) => p.estado === 'pendiente').length;
    const errores = products.filter((p) => p.estado === 'error').length;
    const desactualizados = products.filter((p) => p.estado === 'publicado' && isOutOfSync(p)).length;
    return { total, publicados, listos, pendientes, errores, desactualizados };
  }, [products]);

  const cards = [
    { label: 'Catálogo', value: stats.total, icon: Package, tone: 'ink' },
    { label: 'Publicados', value: stats.publicados, icon: CheckCircle2, tone: 'ink2' },
    { label: 'Listos para publicar', value: stats.listos, icon: CheckCircle2, tone: 'ok' },
    { label: 'Pendientes', value: stats.pendientes, icon: Clock, tone: 'warn' },
    { label: 'Errores', value: stats.errores, icon: AlertTriangle, tone: 'err' },
    { label: 'Desactualizados', value: stats.desactualizados, icon: RefreshCw, tone: 'warn' },
  ] as const;

  const toneClasses: Record<string, string> = {
    ink: 'bg-[--color-ink-50] text-[--color-ink-900]',
    ink2: 'bg-[--color-ink-100] text-[--color-ink-700]',
    ok: 'bg-[--color-ok-100] text-[--color-ok-600]',
    warn: 'bg-[--color-warn-100] text-[--color-warn-600]',
    err: 'bg-[--color-err-100] text-[--color-err-600]',
  };

  async function handleConnect() {
    const result = await connectMercadoLibre();
    setConnectMsg(result.mensaje);
    setTimeout(() => setConnectMsg(null), 3500);
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8">
      <div>
        <p className="text-lg text-[--color-neutral-600]">Bienvenido de vuelta. Aquí tienes un resumen de tu catálogo.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        {cards.map(({ label, value, icon: Icon, tone }) => (
          <Card key={label} className="p-6">
            <div className={`mb-4 inline-flex h-11 w-11 items-center justify-center rounded-lg ${toneClasses[tone]}`}>
              <Icon size={22} strokeWidth={2} />
            </div>
            <p className="font-display text-4xl font-semibold text-[--color-ink-950]">{value.toLocaleString('es-CL')}</p>
            <p className="mt-1 text-base text-[--color-neutral-600]">{label}</p>
          </Card>
        ))}
      </div>

      <Card className="p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-[--color-gold-100] text-[--color-gold-600]">
              <Sparkles size={22} strokeWidth={2} />
            </div>
            <div>
              <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">Automatización</h2>
              <p className="mt-0.5 flex items-center gap-2 text-base text-[--color-ok-600]">
                <span className="h-2.5 w-2.5 rounded-full bg-[--color-ok-600]" />
                {automation.systemActive ? 'Sistema activo' : 'Sistema inactivo'}
              </p>
            </div>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <p className="text-sm text-[--color-neutral-600]">Última sincronización</p>
            <p className="mt-1 text-base font-medium text-[--color-ink-950]">
              {automation.lastSync ? formatRelative(automation.lastSync) : 'Todavía no hay sincronizaciones'}
            </p>
          </div>
          <div>
            <p className="text-sm text-[--color-neutral-600]">Última importación</p>
            <p className="mt-1 text-base font-medium text-[--color-ink-950]">
              {automation.lastImport ? formatRelative(automation.lastImport) : 'Todavía no se ha importado un catálogo'}
            </p>
          </div>
          <div>
            <p className="text-sm text-[--color-neutral-600]">Productos procesados</p>
            <p className="mt-1 text-base font-medium text-[--color-ink-950]">{automation.processedCount.toLocaleString('es-CL')}</p>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap gap-3">
          <Button icon={<FileUp size={18} />} onClick={() => navigate('/productos/importar')}>
            Importar productos
          </Button>
          <Button variant="secondary" icon={<RefreshCw size={18} />} onClick={() => navigate('/productos/importar')}>
            Procesar catálogo
          </Button>
          <Button variant="secondary" icon={<ClipboardList size={18} />} onClick={() => navigate('/pendientes')}>
            Ver pendientes
          </Button>
        </div>
      </Card>

      <Card className="p-6">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-[--color-warn-100] text-[--color-warn-600]">
            <ShoppingBag size={22} strokeWidth={2} />
          </div>
          <div>
            <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">Mercado Libre</h2>
            <p className="mt-0.5 flex items-center gap-2 text-base text-[--color-warn-600]">
              <span className="h-2.5 w-2.5 rounded-full bg-[--color-warn-600]" />
              Modo simulación
            </p>
          </div>
        </div>
        <p className="mt-4 text-base text-[--color-neutral-600]">
          Mercado Libre todavía no está conectado. Las publicaciones actuales son simuladas.
        </p>
        <div className="mt-4 flex items-center gap-3">
          <Button variant="secondary" icon={<Link2 size={18} />} onClick={handleConnect}>
            Conectar Mercado Libre
          </Button>
          {connectMsg && <span className="text-sm text-[--color-neutral-600]">{connectMsg}</span>}
        </div>
      </Card>

      <div className="flex flex-col gap-4 sm:flex-row">
        <Button icon={<CirclePlus size={20} />} onClick={() => navigate('/agregar-producto')}>
          Agregar producto
        </Button>
        <Button variant="secondary" icon={<ClipboardList size={20} />} onClick={() => navigate('/pendientes')}>
          Ver productos pendientes
        </Button>
      </div>

      <Card className="p-6">
        <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">Actividad reciente</h2>
        <ul className="mt-4 divide-y divide-[--color-ink-100]">
          {activity.slice(0, 8).map((entry) => (
            <li key={entry.id} className="flex items-center justify-between gap-4 py-3">
              <p className="text-base text-[--color-ink-900]">{entry.mensaje}</p>
              <p className="shrink-0 text-sm text-[--color-neutral-600]">{formatRelative(entry.fecha)}</p>
            </li>
          ))}
          {activity.length === 0 && <p className="py-4 text-base text-[--color-neutral-600]">Todavía no hay actividad registrada.</p>}
        </ul>
      </Card>
    </div>
  );
}
