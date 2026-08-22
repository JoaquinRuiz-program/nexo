import type { HTMLAttributes } from 'react';

export function Card({ className = '', children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-[--radius-card] border border-[--color-ink-100] bg-white shadow-[0_1px_2px_rgba(15,36,56,0.04)] ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}
