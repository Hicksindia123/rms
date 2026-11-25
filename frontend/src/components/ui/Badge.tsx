import React from 'react';
import { cn } from '@/lib/utils';

export type BadgeVariant =
  | 'default'
  | 'success'
  | 'danger'
  | 'warning'
  | 'info'
  | 'neutral'
  | 'purple';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  dot?: boolean;
}

export const Badge: React.FC<BadgeProps> = ({
  className,
  variant = 'default',
  dot = false,
  children,
  ...props
}) => {
  const variantStyles = {
    default: 'bg-slate-100 text-slate-700 border-slate-200/80',
    neutral: 'bg-slate-100 text-slate-700 border-slate-200/80',
    success: 'bg-emerald-50 text-emerald-800 border-emerald-200/80',
    danger: 'bg-rose-50 text-rose-800 border-rose-200/80',
    warning: 'bg-amber-50 text-amber-900 border-amber-200/80',
    info: 'bg-sky-50 text-sky-800 border-sky-200/80',
    purple: 'bg-purple-50 text-purple-800 border-purple-200/80',
  };

  const dotColors = {
    default: 'bg-slate-500',
    neutral: 'bg-slate-500',
    success: 'bg-emerald-500',
    danger: 'bg-rose-500',
    warning: 'bg-amber-500',
    info: 'bg-sky-500',
    purple: 'bg-purple-500',
  };

  return (
    <span
      className={cn(
        'badge',
        `badge--${variant}`,
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold tracking-wide border transition-colors',
        variantStyles[variant] || variantStyles.default,
        className,
      )}
      {...props}
    >
      {dot && (
        <span
          className={cn(
            'w-1.5 h-1.5 rounded-full flex-shrink-0',
            dotColors[variant] || dotColors.default,
          )}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
};
