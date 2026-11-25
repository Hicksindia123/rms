import React from 'react';
import { cn } from '@/lib/utils';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'outline' | 'link';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = 'secondary',
      size = 'md',
      isLoading = false,
      disabled,
      children,
      ...props
    },
    ref,
  ) => {
    const variantStyles = {
      primary:
        'bg-gradient-to-br from-brand-500 via-brand-600 to-[#5b3ff0] hover:brightness-110 active:brightness-95 text-white border-transparent shadow-glow focus-visible:ring-brand-500/30',
      secondary:
        'bg-brand-50 hover:bg-brand-100 active:bg-brand-200 text-brand-700 border-brand-100 focus-visible:ring-brand-400/30',
      danger:
        'bg-gradient-to-br from-rose-500 to-rose-600 hover:brightness-110 active:brightness-95 text-white border-transparent shadow-[0_8px_20px_-8px_rgba(225,29,72,0.6)] focus-visible:ring-rose-500/30',
      outline:
        'bg-white hover:bg-slate-50 hover:border-brand-200 hover:text-brand-700 active:bg-slate-100 text-slate-700 border-slate-200 shadow-[0_1px_2px_rgba(15,23,42,0.05)] focus-visible:ring-brand-400/30',
      ghost:
        'bg-transparent hover:bg-slate-100 active:bg-slate-200 text-slate-700 border-transparent focus-visible:ring-slate-400/30',
      link: 'bg-transparent text-blue-600 hover:text-blue-700 underline-offset-4 hover:underline border-transparent p-0 min-h-0 h-auto',
    };

    const sizeStyles = {
      sm: 'px-3 py-1 text-xs min-h-[32px] sm:min-h-[36px] rounded-lg gap-1.5',
      md: 'px-4 py-1.5 text-sm min-h-[40px] sm:min-h-[42px] rounded-xl gap-2',
      lg: 'px-5 py-2.5 text-base min-h-[44px] sm:min-h-[48px] rounded-xl gap-2.5',
    };

    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={cn(
          'btn',
          `btn--${variant}`,
          `btn--${size}`,
          isLoading && 'btn--loading',
          'inline-flex items-center justify-center font-semibold tracking-[-0.005em] transition-all duration-150 select-none cursor-pointer border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none',
          variantStyles[variant],
          variant !== 'link' && sizeStyles[size],
          className,
        )}
        {...props}
      >
        {isLoading ? (
          <span
            className="btn__spinner inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin flex-shrink-0"
            aria-hidden="true"
          />
        ) : null}
        {children}
      </button>
    );
  },
);

Button.displayName = 'Button';
