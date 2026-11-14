import React from 'react';
import { Badge } from './Badge';

export interface MultiSelectOption {
  value: string;
  label: string;
  disabled?: boolean | undefined;
  allowed_status?: ('YES' | 'NO' | 'CONDITIONAL') | undefined;
  rule_text?: string | null | undefined;
}

export interface MultiSelectProps {
  name: string;
  options: MultiSelectOption[];
  value?: string[] | undefined;
  onChange?: ((value: string[]) => void) | undefined;
  error?: string | undefined;
  helperText?: string | undefined;
  id?: string | undefined;
  disabled?: boolean | undefined;
}

export const MultiSelect: React.FC<MultiSelectProps> = ({
  name,
  options,
  value = [],
  onChange,
  error,
  helperText,
  id,
  disabled = false,
}) => {
  const handleToggle = (optValue: string) => {
    if (disabled) return;
    const current = new Set(value);
    if (current.has(optValue)) {
      current.delete(optValue);
    } else {
      current.add(optValue);
    }
    onChange?.(Array.from(current));
  };

  return (
    <div className="form-control-wrapper" id={id}>
      <div
        className="multiselect-list"
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '0.375rem',
          maxHeight: '220px',
          overflowY: 'auto',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          padding: '0.5rem',
          backgroundColor: '#fff',
        }}
      >
        {options.map((opt) => {
          const isChecked = value.includes(opt.value);
          const isOptDisabled = disabled || opt.disabled;

          return (
            <label
              key={opt.value}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.375rem 0.5rem',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: isChecked ? 'var(--color-bg-subtle)' : 'transparent',
                cursor: isOptDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              <input
                type="checkbox"
                name={name}
                value={opt.value}
                checked={isChecked}
                disabled={isOptDisabled}
                onChange={() => {
                  handleToggle(opt.value);
                }}
                style={{ minWidth: '1.125rem', minHeight: '1.125rem' }}
              />
              <span style={{ fontSize: '0.875rem', flex: 1 }}>{opt.label}</span>
              {opt.allowed_status === 'NO' && <Badge variant="danger">Not allowed</Badge>}
              {opt.allowed_status === 'CONDITIONAL' && <Badge variant="warning">Conditional</Badge>}
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
