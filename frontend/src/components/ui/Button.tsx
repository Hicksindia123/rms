import React from 'react';
import { clsx } from 'clsx';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'outline';
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
    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={clsx(
          'btn',
          `btn--${variant}`,
          `btn--${size}`,
          isLoading && 'btn--loading',
          className,
        )}
        {...props}
      >
        {isLoading ? <span className="btn__spinner" aria-hidden="true" /> : null}
        {children}
      </button>
    );
  },
);

Button.displayName = 'Button';
