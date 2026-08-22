import { ImageIcon } from 'lucide-react';

export function ProductImage({ src, alt, size = 'md' }: { src: string | null; alt: string; size?: 'sm' | 'md' | 'lg' }) {
  const dims = size === 'sm' ? 'h-12 w-12' : size === 'lg' ? 'h-56 w-56' : 'h-20 w-20';
  const iconSize = size === 'sm' ? 18 : size === 'lg' ? 48 : 24;

  if (src) {
    return <img src={src} alt={alt} className={`${dims} rounded-lg object-cover`} />;
  }

  return (
    <div className={`flex ${dims} shrink-0 items-center justify-center rounded-lg bg-[--color-paper-dim] text-[--color-neutral-600]`}>
      <ImageIcon size={iconSize} strokeWidth={1.5} />
    </div>
  );
}
