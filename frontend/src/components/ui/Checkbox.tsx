import React from 'react';
import { clsx } from 'clsx';

export interface CheckboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: React.ReactNode;
  error?: string | undefined;
  helperText?: string | undefined;
}

export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, error, helperText, id, ...props }, ref) => {
    return (
      <div className="form-control-wrapper">
        <label
          htmlFor={id}
          className={clsx('checkbox-label', className)}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '0.625rem',
            cursor: props.disabled ? 'not-allowed' : 'pointer',
          }}
        >
          <input
            ref={ref}
            type="checkbox"
            id={id}
            className="checkbox-input"
            aria-invalid={error ? 'true' : 'false'}
            style={{
              marginTop: '0.15rem',
              minWidth: '1.25rem',
              minHeight: '1.25rem',
              cursor: props.disabled ? 'not-allowed' : 'pointer',
            }}
            {...props}
          />
          <span style={{ fontSize: '0.9375rem', color: 'var(--color-fg)' }}>{label}</span>
        </label>
        {error ? (
          <p className="form-control__error" role="alert" style={{ marginTop: '0.25rem' }}>
            {error}
          </p>
        ) : helperText ? (
          <p className="form-control__helper" style={{ marginTop: '0.25rem' }}>
            {helperText}
          </p>
        ) : null}
      </div>
    );
  },
);

Checkbox.displayName = 'Checkbox';
