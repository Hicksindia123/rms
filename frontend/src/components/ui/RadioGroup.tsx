import React from 'react';
import { clsx } from 'clsx';
import { Badge } from './Badge';

export interface RadioOption {
  value: string;
  label: string;
  disabled?: boolean | undefined;
  allowed_status?: ('YES' | 'NO' | 'CONDITIONAL') | undefined;
  rule_text?: string | null | undefined;
}

export interface RadioGroupProps {
  name: string;
  options: RadioOption[];
  value?: string | undefined;
  onChange?: ((value: string) => void) | undefined;
  error?: string | undefined;
  helperText?: string | undefined;
  id?: string | undefined;
  disabled?: boolean | undefined;
}

export const RadioGroup: React.FC<RadioGroupProps> = ({
  name,
  options,
  value,
  onChange,
  error,
  helperText,
  id,
  disabled = false,
}) => {
  return (
    <div
      className="form-control-wrapper"
      id={id}
      role="radiogroup"
      aria-invalid={error ? 'true' : 'false'}
    >
      <div
        className="space-y-2"
        style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}
      >
        {options.map((opt) => {
          const isSelected = value === opt.value;
          const isOptDisabled = disabled || opt.disabled;

          return (
            <label
              key={opt.value}
              className={clsx(
                'radio-option',
                isSelected && 'radio-option--selected',
                isOptDisabled && 'radio-option--disabled',
              )}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '0.625rem',
                padding: '0.5rem 0.75rem',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-md)',
                backgroundColor: isSelected ? 'var(--color-bg-subtle)' : '#ffffff',
                cursor: isOptDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              <input
                type="radio"
                name={name}
                value={opt.value}
                checked={isSelected}
                disabled={isOptDisabled}
                onChange={() => onChange?.(opt.value)}
                style={{ marginTop: '0.2rem', minWidth: '1.25rem', minHeight: '1.25rem' }}
              />
              <div style={{ flex: 1 }}>
                <div
                  style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}
                >
                  <span style={{ fontWeight: 500, fontSize: '0.9375rem' }}>{opt.label}</span>
                  {opt.allowed_status === 'NO' && <Badge variant="danger">Not allowed</Badge>}
                  {opt.allowed_status === 'CONDITIONAL' && (
                    <Badge variant="warning">Conditional</Badge>
                  )}
                </div>
                {opt.rule_text ? (
                  <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.8125rem', color: '#b45309' }}>
                    ℹ️ {opt.rule_text}
                  </p>
                ) : null}
              </div>
            </label>
          );
        })}
      </div>

      {error ? (
        <p className="form-control__error" role="alert" style={{ marginTop: '0.375rem' }}>
          {error}
        </p>
      ) : helperText ? (
        <p className="form-control__helper" style={{ marginTop: '0.375rem' }}>
          {helperText}
        </p>
      ) : null}
    </div>
  );
};
