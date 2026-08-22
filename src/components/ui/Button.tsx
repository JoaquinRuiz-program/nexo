import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';
type Size = 'md' | 'sm';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  fullWidth?: boolean;
}

const VARIANT_CLASSES: Record<Variant, string> = {
  primary: 'bg-[--color-ink-900] text-white hover:bg-[--color-ink-800]',
  secondary: 'bg-white text-[--color-ink-900] border border-[--color-ink-100] hover:bg-[--color-ink-50]',
  danger: 'bg-white text-[--color-err-600] border border-[--color-err-100] hover:bg-[--color-err-100]',
  ghost: 'text-[--color-ink-900] hover:bg-[--color-ink-50]',
};

const SIZE_CLASSES: Record<Size, string> = {
  md: 'px-5 py-3 text-base',
  sm: 'px-3.5 py-2 text-sm',
};

export function Button({ variant = 'primary', size = 'md', icon, fullWidth, className = '', children, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        VARIANT_CLASSES[variant]
      } ${SIZE_CLASSES[size]} ${fullWidth ? 'w-full' : ''} ${className}`}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}
