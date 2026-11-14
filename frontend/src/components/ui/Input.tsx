import React from 'react';
import { clsx } from 'clsx';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: string | undefined;
  helperText?: string | undefined;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, helperText, id, ...props }, ref) => {
    return (
      <div className="form-control-wrapper">
        <input
          ref={ref}
          id={id}
          className={clsx('input', error && 'input--error', className)}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={
            error ? `${id ?? 'input'}-error` : helperText ? `${id ?? 'input'}-helper` : undefined
          }
          {...props}
        />
        {error ? (
          <p id={`${id ?? 'input'}-error`} className="form-control__error" role="alert">
            {error}
          </p>
        ) : helperText ? (
          <p id={`${id ?? 'input'}-helper`} className="form-control__helper">
            {helperText}
          </p>
        ) : null}
      </div>
    );
  },
);

Input.displayName = 'Input';
