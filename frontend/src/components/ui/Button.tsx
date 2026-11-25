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
        'bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white border-transparent shadow-xs focus-visible:ring-blue-500/30',
      secondary:
        'bg-slate-100 hover:bg-slate-200 active:bg-slate-300 text-slate-800 border-slate-300 shadow-xs focus-visible:ring-slate-400/30',
      danger:
        'bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white border-transparent shadow-xs focus-visible:ring-rose-500/30',
      outline:
        'bg-white hover:bg-slate-50 active:bg-slate-100 text-slate-700 border-slate-300 shadow-xs focus-visible:ring-slate-400/30',
      ghost:
        'bg-transparent hover:bg-slate-100 active:bg-slate-200 text-slate-700 border-transparent focus-visible:ring-slate-400/30',
      link:
        'bg-transparent text-blue-600 hover:text-blue-700 underline-offset-4 hover:underline border-transparent p-0 min-h-0 h-auto',
    };

    const sizeStyles = {
      sm: 'px-2.5 py-1 text-xs min-h-[32px] sm:min-h-[36px] rounded-md gap-1.5',
      md: 'px-3.5 py-1.5 text-sm min-h-[40px] sm:min-h-[42px] rounded-lg gap-2',
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
          'inline-flex items-center justify-center font-medium transition-all duration-150 select-none cursor-pointer border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none',
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
