import { useRef } from 'react';
import { UploadCloud, Star, Trash2, ArrowLeft, ArrowRight } from 'lucide-react';
import { ProductImage } from '@/components/products/ProductImage';

interface ImagesManagerProps {
  imagenUrl: string | null;
  imagenesSecundarias: string[];
  onChangeMain: (url: string | null) => void;
  onChangeSecondary: (urls: string[]) => void;
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error('No se pudo leer la imagen.'));
    reader.readAsDataURL(file);
  });
}

export function ImagesManager({ imagenUrl, imagenesSecundarias, onChangeMain, onChangeSecondary }: ImagesManagerProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleAddFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const urls = await Promise.all(Array.from(files).map(readAsDataUrl));
    if (!imagenUrl) {
      onChangeMain(urls[0]);
      onChangeSecondary([...imagenesSecundarias, ...urls.slice(1)]);
    } else {
      onChangeSecondary([...imagenesSecundarias, ...urls]);
    }
  }

  function makeMain(index: number) {
    const chosen = imagenesSecundarias[index];
    const restWithOldMain = imagenUrl ? [imagenUrl, ...imagenesSecundarias.filter((_, i) => i !== index)] : imagenesSecundarias.filter((_, i) => i !== index);
    onChangeMain(chosen);
    onChangeSecondary(restWithOldMain);
  }

  function removeSecondary(index: number) {
    onChangeSecondary(imagenesSecundarias.filter((_, i) => i !== index));
  }

  function move(index: number, dir: -1 | 1) {
    const next = [...imagenesSecundarias];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChangeSecondary(next);
  }

  const status: { label: string; tone: 'ok' | 'warn' | 'error' } = !imagenUrl
    ? { label: 'Falta imagen', tone: 'error' }
    : imagenesSecundarias.length === 0
      ? { label: 'Imagen insuficiente — agrega al menos una foto adicional', tone: 'warn' }
      : { label: 'Imágenes válidas', tone: 'ok' };

  const toneClass = status.tone === 'ok' ? 'text-[--color-ok-600]' : status.tone === 'warn' ? 'text-[--color-warn-600]' : 'text-[--color-err-600]';

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex flex-col items-center gap-1.5">
          <ProductImage src={imagenUrl} alt="Imagen principal" size="lg" />
          <span className="text-xs font-medium text-[--color-neutral-600]">Principal</span>
        </div>

        {imagenesSecundarias.map((url, i) => (
          <div key={`${url.slice(0, 20)}-${i}`} className="flex flex-col items-center gap-1.5">
            <div className="relative">
              <ProductImage src={url} alt={`Imagen secundaria ${i + 1}`} />
              <div className="absolute -bottom-2 left-1/2 flex -translate-x-1/2 gap-1 rounded-full bg-white p-1 shadow">
                <button type="button" onClick={() => move(i, -1)} className="rounded p-1 text-[--color-ink-900] hover:bg-[--color-ink-50]" aria-label="Mover antes">
                  <ArrowLeft size={12} />
                </button>
                <button type="button" onClick={() => makeMain(i)} className="rounded p-1 text-[--color-gold-600] hover:bg-[--color-gold-100]" aria-label="Usar como principal">
                  <Star size={12} />
                </button>
                <button type="button" onClick={() => removeSecondary(i)} className="rounded p-1 text-[--color-err-600] hover:bg-[--color-err-100]" aria-label="Eliminar">
                  <Trash2 size={12} />
                </button>
                <button type="button" onClick={() => move(i, 1)} className="rounded p-1 text-[--color-ink-900] hover:bg-[--color-ink-50]" aria-label="Mover después">
                  <ArrowRight size={12} />
                </button>
              </div>
            </div>
          </div>
        ))}

        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-[--color-ink-100] text-[--color-neutral-600] hover:border-[--color-gold-500] hover:text-[--color-gold-600]"
        >
          <UploadCloud size={20} />
          <span className="text-xs">Subir</span>
        </button>
        <input ref={inputRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => handleAddFiles(e.target.files)} />
      </div>

      <p className={`text-sm font-medium ${toneClass}`}>{status.label}</p>
    </div>
  );
}
