import React from 'react';
import { clsx } from 'clsx';

export type BadgeVariant = 'default' | 'success' | 'danger' | 'warning' | 'info' | 'neutral';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export const Badge: React.FC<BadgeProps> = ({
  className,
  variant = 'default',
  children,
  ...props
}) => {
  return (
    <span className={clsx('badge', `badge--${variant}`, className)} {...props}>
      {children}
    </span>
  );
};
