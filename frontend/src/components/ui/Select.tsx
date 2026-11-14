import React from 'react';
import { clsx } from 'clsx';
import { Badge } from './Badge';

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean | undefined;
  allowed_status?: ('YES' | 'NO' | 'CONDITIONAL') | undefined;
  rule_text?: string | null | undefined;
}

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  options: SelectOption[];
  error?: string | undefined;
  helperText?: string | undefined;
  placeholder?: string | undefined;
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      className,
      options,
      error,
      helperText,
      placeholder = '-- Select an option --',
      id,
      value,
      ...props
    },
    ref,
  ) => {
    const selectedOption = options.find((opt) => opt.value === String(value));

    return (
      <div className="form-control-wrapper">
        <select
          ref={ref}
          id={id}
          value={value}
          className={clsx('select', error && 'select--error', className)}
          aria-invalid={error ? 'true' : 'false'}
          {...props}
        >
          {placeholder ? <option value="">{placeholder}</option> : null}
          {options.map((opt) => {
            const statusLabel =
              opt.allowed_status === 'NO'
                ? ' [Not Allowed]'
                : opt.allowed_status === 'CONDITIONAL'
                  ? ' [Conditional]'
                  : '';
            return (
              <option key={opt.value} value={opt.value} disabled={opt.disabled}>
                {opt.label}
                {statusLabel}
              </option>
            );
          })}
        </select>

        {/* Dynamic metadata display for the selected option */}
        {selectedOption?.allowed_status && selectedOption.allowed_status !== 'YES' ? (
          <div className="mt-1 flex items-center gap-2" style={{ marginTop: '0.25rem' }}>
            {selectedOption.allowed_status === 'NO' && <Badge variant="danger">Not allowed</Badge>}
            {selectedOption.allowed_status === 'CONDITIONAL' && (
              <Badge variant="warning">Conditional</Badge>
            )}
          </div>
        ) : null}

        {selectedOption?.rule_text ? (
          <p
            className="form-control__helper form-control__helper--rule"
            style={{ marginTop: '0.25rem', color: '#b45309' }}
          >
            ℹ️ {selectedOption.rule_text}
          </p>
        ) : null}

        {error ? (
          <p id={`${id ?? 'select'}-error`} className="form-control__error" role="alert">
            {error}
          </p>
        ) : helperText ? (
          <p id={`${id ?? 'select'}-helper`} className="form-control__helper">
            {helperText}
          </p>
        ) : null}
      </div>
    );
  },
);

Select.displayName = 'Select';
