import React, { useState, useEffect, useRef, useMemo } from 'react';
import { clsx } from 'clsx';

export interface ComboboxOption {
  value: string;
  label: string;
  sublabel?: string | undefined;
}

export interface AsyncComboboxProps {
  id?: string | undefined;
  name: string;
  value?: string | undefined;
  onChange?: ((value: string) => void) | undefined;
  loadOptions?: ((query: string) => Promise<ComboboxOption[]>) | undefined;
  staticOptions?: ComboboxOption[] | undefined;
  placeholder?: string | undefined;
  error?: string | undefined;
  helperText?: string | undefined;
  disabled?: boolean | undefined;
  /** Accessible name of the text input (the `id` sits on the wrapper, so `htmlFor` cannot reach it). */
  ariaLabel?: string | undefined;
}

export const AsyncCombobox: React.FC<AsyncComboboxProps> = ({
  id,
  value,
  onChange,
  loadOptions,
  staticOptions,
  placeholder = 'Search...',
  error,
  helperText,
  disabled = false,
  ariaLabel,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [asyncOptions, setAsyncOptions] = useState<ComboboxOption[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const filteredStatic = useMemo(() => {
    if (!staticOptions) return [];
    return staticOptions.filter((opt) => opt.label.toLowerCase().includes(query.toLowerCase()));
  }, [staticOptions, query]);

  const options = loadOptions ? asyncOptions : filteredStatic;
  const selectedOption = options.find((o) => o.value === value);
  const displayValue = isOpen ? query : (selectedOption?.label ?? value ?? '');

  // Load options when search term changes
  useEffect(() => {
    if (!loadOptions) return;

    let isCurrent = true;
    const timer = setTimeout(() => {
      setIsLoading(true);
      loadOptions(query)
        .then((res) => {
          if (isCurrent) {
            setAsyncOptions(res);
            setIsLoading(false);
          }
        })
        .catch(() => {
          if (isCurrent) setIsLoading(false);
        });
    }, 250);

    return () => {
      isCurrent = false;
      clearTimeout(timer);
    };
  }, [query, loadOptions]);

  // Close dropdown on outside click
  useEffect(() => {
    const handleOutsideClick = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
    };
  }, []);

  const handleSelect = (option: ComboboxOption) => {
    onChange?.(option.value);
    setQuery('');
    setIsOpen(false);
  };

  return (
    <div ref={wrapperRef} className="form-control-wrapper" style={{ position: 'relative' }} id={id}>
      <div style={{ display: 'flex', gap: '0.25rem' }}>
        <input
          type="text"
          className={clsx('input', error && 'input--error')}
          placeholder={placeholder}
          value={displayValue}
          disabled={disabled}
          onFocus={() => {
            setIsOpen(true);
            setQuery(selectedOption?.label ?? '');
          }}
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
            if (e.target.value === '') {
              onChange?.('');
            }
          }}
          aria-invalid={error ? 'true' : 'false'}
          aria-label={ariaLabel}
          style={{ width: '100%' }}
        />
        {value && !disabled ? (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => {
              setQuery('');
              onChange?.('');
            }}
            title="Clear selection"
            style={{ padding: '0 0.5rem' }}
          >
            ×
          </button>
        ) : null}
      </div>

      {isOpen && (
        <div
          className="combobox-dropdown"
          role="listbox"
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 50,
            marginTop: '0.25rem',
            maxHeight: '200px',
            overflowY: 'auto',
            background: '#ffffff',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
          }}
        >
          {isLoading ? (
            <div
              style={{ padding: '0.5rem', color: 'var(--color-fg-muted)', fontSize: '0.875rem' }}
            >
              Loading...
            </div>
          ) : options.length === 0 ? (
            <div
              style={{ padding: '0.5rem', color: 'var(--color-fg-muted)', fontSize: '0.875rem' }}
            >
              No matches found
            </div>
          ) : (
            options.map((opt) => (
              <button
                type="button"
                role="option"
                aria-selected={value === opt.value}
                key={opt.value}
                onClick={() => {
                  handleSelect(opt);
                }}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  font: 'inherit',
                  color: 'inherit',
                  border: 'none',
                  minHeight: '44px',
                  padding: '0.5rem 0.75rem',
                  cursor: 'pointer',
                  borderBottom: '1px solid var(--color-bg-subtle)',
                  backgroundColor: value === opt.value ? 'var(--color-bg-subtle)' : '#ffffff',
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--color-bg-subtle)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor =
                    value === opt.value ? 'var(--color-bg-subtle)' : '#ffffff';
                }}
              >
                <div style={{ fontSize: '0.875rem', fontWeight: 500 }}>{opt.label}</div>
                {opt.sublabel ? (
                  <div style={{ fontSize: '0.75rem', color: 'var(--color-fg-muted)' }}>
                    {opt.sublabel}
                  </div>
                ) : null}
              </button>
            ))
          )}
        </div>
      )}

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
};
