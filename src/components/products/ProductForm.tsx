import { useRef, useState, type FormEvent } from 'react';
import { UploadCloud, ImageUp } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { CATEGORIAS, type ProductCategory, type ProductFormInput } from '@/types/product';

interface ProductFormProps {
  initial?: Partial<ProductFormInput>;
  submitLabel: string;
  onSubmit: (input: ProductFormInput) => void;
  onCancel?: () => void;
}

const EMPTY: ProductFormInput = {
  sku: '',
  nombre: '',
  marca: '',
  categoria: 'Cuadernos',
  precio: 0,
  stock: 0,
  descripcion: '',
  imagenUrl: null,
  publicar: false,
};

export function ProductForm({ initial, submitLabel, onSubmit, onCancel }: ProductFormProps) {
  const [form, setForm] = useState<ProductFormInput>({ ...EMPTY, ...initial });
  const [errors, setErrors] = useState<Partial<Record<keyof ProductFormInput, string>>>({});
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function set<K extends keyof ProductFormInput>(key: K, value: ProductFormInput[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function readImageFile(file: File | undefined) {
    if (!file) return;
    if (!file.type.startsWith('image/')) return;
    const reader = new FileReader();
    reader.onload = () => set('imagenUrl', reader.result as string);
    reader.readAsDataURL(file);
  }

  function validate(): boolean {
    const next: Partial<Record<keyof ProductFormInput, string>> = {};
    if (!form.sku.trim()) next.sku = 'Ingresa un SKU.';
    if (!form.nombre.trim()) next.nombre = 'Ingresa el nombre del producto.';
    if (!form.marca.trim()) next.marca = 'Ingresa la marca.';
    if (form.precio < 0) next.precio = 'El precio no puede ser negativo.';
    if (form.stock < 0) next.stock = 'El stock no puede ser negativo.';
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    onSubmit(form);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-8">
      <section>
        <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">Información del producto</h2>
        <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2">
          <Field label="SKU" error={errors.sku}>
            <input
              value={form.sku}
              onChange={(e) => set('sku', e.target.value)}
              className={inputClass(!!errors.sku)}
              placeholder="Ej: 018"
            />
          </Field>
          <Field label="Nombre" error={errors.nombre}>
            <input
              value={form.nombre}
              onChange={(e) => set('nombre', e.target.value)}
              className={inputClass(!!errors.nombre)}
              placeholder="Ej: Cuaderno Universitario 100 hojas"
            />
          </Field>
          <Field label="Marca" error={errors.marca}>
            <input
              value={form.marca}
              onChange={(e) => set('marca', e.target.value)}
              className={inputClass(!!errors.marca)}
              placeholder="Ej: Torre"
            />
          </Field>
          <Field label="Categoría">
            <select
              value={form.categoria}
              onChange={(e) => set('categoria', e.target.value as ProductCategory)}
              className={inputClass(false)}
            >
              {CATEGORIAS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Precio (CLP)" error={errors.precio}>
            <input
              type="number"
              min={0}
              value={form.precio}
              onChange={(e) => set('precio', Number(e.target.value))}
              className={inputClass(!!errors.precio)}
            />
          </Field>
          <Field label="Stock" error={errors.stock}>
            <input
              type="number"
              min={0}
              value={form.stock}
              onChange={(e) => set('stock', Number(e.target.value))}
              className={inputClass(!!errors.stock)}
            />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Descripción">
              <textarea
                value={form.descripcion}
                onChange={(e) => set('descripcion', e.target.value)}
                rows={4}
                className={inputClass(false)}
                placeholder="Describe el producto: material, tamaño, uso recomendado…"
              />
            </Field>
          </div>
        </div>
      </section>

      <section>
        <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">Imagen</h2>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            readImageFile(e.dataTransfer.files?.[0]);
          }}
          className={`mt-4 flex flex-col items-center justify-center gap-3 rounded-[--radius-card] border-2 border-dashed p-8 text-center transition-colors ${
            dragOver ? 'border-[--color-gold-500] bg-[--color-gold-100]/40' : 'border-[--color-ink-100] bg-[--color-ink-50]'
          }`}
        >
          {form.imagenUrl ? (
            <>
              <img src={form.imagenUrl} alt="Previsualización" className="h-32 w-32 rounded-lg object-cover" />
              <button type="button" onClick={() => set('imagenUrl', null)} className="text-sm font-semibold text-[--color-err-600] hover:underline">
                Quitar imagen
              </button>
            </>
          ) : (
            <>
              <UploadCloud size={32} className="text-[--color-neutral-600]" />
              <p className="text-base font-medium text-[--color-ink-950]">Arrastra una imagen aquí</p>
              <p className="text-sm text-[--color-neutral-600]">o</p>
              <Button type="button" variant="secondary" icon={<ImageUp size={18} />} onClick={() => fileInputRef.current?.click()}>
                Seleccionar imagen
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => readImageFile(e.target.files?.[0])}
              />
            </>
          )}
        </div>
      </section>

      <section>
        <h2 className="font-display text-xl font-semibold text-[--color-ink-950]">Publicación</h2>
        <div className="mt-4 flex flex-col gap-3">
          <p className="text-base text-[--color-ink-900]">¿Publicar producto?</p>
          <div className="flex gap-3">
            <ToggleOption label="Sí" selected={form.publicar} onClick={() => set('publicar', true)} />
            <ToggleOption label="No" selected={!form.publicar} onClick={() => set('publicar', false)} />
          </div>
        </div>
      </section>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button type="submit">{submitLabel}</Button>
        {onCancel && (
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancelar
          </Button>
        )}
      </div>
    </form>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-[--color-ink-900]">{label}</span>
      {children}
      {error && <span className="text-sm text-[--color-err-600]">{error}</span>}
    </label>
  );
}

function inputClass(hasError: boolean) {
  return `w-full rounded-lg border bg-white px-4 py-3 text-base text-[--color-ink-950] focus:border-[--color-ink-800] ${
    hasError ? 'border-[--color-err-600]' : 'border-[--color-ink-100]'
  }`;
}

function ToggleOption({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border px-6 py-3 text-base font-semibold transition-colors ${
        selected
          ? 'border-[--color-ink-900] bg-[--color-ink-900] text-white'
          : 'border-[--color-ink-100] bg-white text-[--color-ink-900] hover:bg-[--color-ink-50]'
      }`}
    >
      {label}
    </button>
  );
}
