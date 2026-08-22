import { useRef, useState } from 'react';
import { UploadCloud, FileSpreadsheet } from 'lucide-react';
import { Button } from '@/components/ui/Button';

const ACCEPTED = '.xlsx,.xls,.csv';

export function UploadDropzone({ onFile }: { onFile: (file: File) => void }) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    onFile(file);
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        handleFiles(e.dataTransfer.files);
      }}
      className={`flex flex-col items-center justify-center gap-4 rounded-[--radius-card] border-2 border-dashed p-10 text-center transition-colors ${
        dragOver ? 'border-[--color-gold-500] bg-[--color-gold-100]/40' : 'border-[--color-ink-100] bg-[--color-ink-50]'
      }`}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-white text-[--color-ink-800] shadow-sm">
        <UploadCloud size={28} />
      </div>
      <div>
        <p className="text-lg font-medium text-[--color-ink-950]">Arrastra tu archivo Excel aquí</p>
        <p className="mt-1 text-sm text-[--color-neutral-600]">Formatos permitidos: .xlsx, .xls, .csv</p>
      </div>
      <p className="text-sm text-[--color-neutral-600]">o</p>
      <Button type="button" variant="secondary" icon={<FileSpreadsheet size={18} />} onClick={() => inputRef.current?.click()}>
        Seleccionar archivo
      </Button>
      <input ref={inputRef} type="file" accept={ACCEPTED} className="hidden" onChange={(e) => handleFiles(e.target.files)} />
    </div>
  );
}
