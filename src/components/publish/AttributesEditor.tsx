import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';

interface AttributesEditorProps {
  atributos: { etiqueta: string; valor: string }[];
  onChange: (atributos: { etiqueta: string; valor: string }[]) => void;
}

export function AttributesEditor({ atributos, onChange }: AttributesEditorProps) {
  const [nuevaEtiqueta, setNuevaEtiqueta] = useState('');
  const [nuevoValor, setNuevoValor] = useState('');

  function updateItem(index: number, field: 'etiqueta' | 'valor', value: string) {
    const next = atributos.map((a, i) => (i === index ? { ...a, [field]: value } : a));
    onChange(next);
  }

  function removeItem(index: number) {
    onChange(atributos.filter((_, i) => i !== index));
  }

  function addItem() {
    if (!nuevaEtiqueta.trim() || !nuevoValor.trim()) return;
    onChange([...atributos, { etiqueta: nuevaEtiqueta.trim(), valor: nuevoValor.trim() }]);
    setNuevaEtiqueta('');
    setNuevoValor('');
  }

  return (
    <div className="flex flex-col gap-3">
      {atributos.length === 0 && <p className="text-base text-[--color-neutral-600]">Todavía no hay características cargadas.</p>}
      {atributos.map((a, i) => (
        <div key={`${a.etiqueta}-${i}`} className="flex flex-wrap items-center gap-2">
          <input
            value={a.etiqueta}
            onChange={(e) => updateItem(i, 'etiqueta', e.target.value)}
            className="w-36 rounded-lg border border-[--color-ink-100] bg-white px-3 py-2 text-sm text-[--color-ink-950]"
            placeholder="Característica"
          />
          <input
            value={a.valor}
            onChange={(e) => updateItem(i, 'valor', e.target.value)}
            className="flex-1 rounded-lg border border-[--color-ink-100] bg-white px-3 py-2 text-sm text-[--color-ink-950]"
            placeholder="Valor"
          />
          <button
            type="button"
            onClick={() => removeItem(i)}
            className="rounded-lg p-2 text-[--color-err-600] hover:bg-[--color-err-100]"
            aria-label="Eliminar característica"
          >
            <Trash2 size={16} />
          </button>
        </div>
      ))}

      <div className="flex flex-wrap items-center gap-2 border-t border-dashed border-[--color-ink-100] pt-3">
        <input
          value={nuevaEtiqueta}
          onChange={(e) => setNuevaEtiqueta(e.target.value)}
          className="w-36 rounded-lg border border-[--color-ink-100] bg-white px-3 py-2 text-sm text-[--color-ink-950]"
          placeholder="Ej: Material"
        />
        <input
          value={nuevoValor}
          onChange={(e) => setNuevoValor(e.target.value)}
          className="flex-1 rounded-lg border border-[--color-ink-100] bg-white px-3 py-2 text-sm text-[--color-ink-950]"
          placeholder="Ej: Papel"
        />
        <Button type="button" variant="secondary" icon={<Plus size={16} />} onClick={addItem}>
          Agregar característica
        </Button>
      </div>
    </div>
  );
}
