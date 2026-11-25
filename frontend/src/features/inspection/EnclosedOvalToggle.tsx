import React from 'react';
import { Lock, Unlock } from 'lucide-react';

interface EnclosedOvalToggleProps {
  /** Unique per line card so the label binds to its own checkbox. */
  idPrefix: string;
  confirmed: boolean;
  disabled?: boolean;
  onChange: (confirmed: boolean) => void;
}

export const EnclosedOvalToggle: React.FC<EnclosedOvalToggleProps> = ({
  idPrefix,
  confirmed,
  disabled = false,
  onChange,
}) => {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0.75rem 1rem',
        borderRadius: '6px',
        backgroundColor: confirmed ? '#f0fdf4' : '#fffbeb',
        border: `1px solid ${confirmed ? '#86efac' : '#fcd34d'}`,
        transition: 'all 0.2s ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        {confirmed ? (
          <Unlock size={20} color="#16a34a" aria-hidden="true" />
        ) : (
          <Lock size={20} color="#d97706" aria-hidden="true" />
        )}
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <label
            htmlFor={`${idPrefix}-eo-full-opening`}
            style={{
              fontWeight: 600,
              fontSize: '0.875rem',
              color: confirmed ? '#166534' : '#92400e',
              cursor: disabled ? 'not-allowed' : 'pointer',
            }}
          >
            Enclosed Oval Protocol: Full Opening Confirmation
          </label>
          <span style={{ fontSize: '0.75rem', color: confirmed ? '#15803d' : '#b45309' }}>
            {confirmed
              ? 'Complete unboxing and visual verification confirmed. Condition grading unlocked.'
              : 'Protocol requirement: You must confirm full opening of the enclosed oval thermometer casing before grading.'}
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center' }}>
        <input
          id={`${idPrefix}-eo-full-opening`}
          type="checkbox"
          checked={confirmed}
          disabled={disabled}
          onChange={(e) => {
            onChange(e.target.checked);
          }}
          style={{
            width: '18px',
            height: '18px',
            cursor: disabled ? 'not-allowed' : 'pointer',
            accentColor: 'var(--color-primary, #2a47f0)',
          }}
          aria-label="Confirm Enclosed Oval full opening"
        />
      </div>
    </div>
  );
};
