import React from 'react';
import { Minus, Plus } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface QtyStepperProps {
  value: number;
  max: number;
  min?: number;
  onChange: (value: number) => void;
  /** Accessible name of the number field (e.g. "Allowed pieces, item 1"). */
  label: string;
  disabled?: boolean;
  tone?: 'brand' | 'success' | 'danger' | 'warning';
  className?: string;
}

const TONE: Record<NonNullable<QtyStepperProps['tone']>, string> = {
  brand: 'focus-within:border-indigo-400 focus-within:ring-indigo-500/20',
  success: 'focus-within:border-emerald-400 focus-within:ring-emerald-500/20',
  danger: 'focus-within:border-rose-400 focus-within:ring-rose-500/20',
  warning: 'focus-within:border-amber-400 focus-within:ring-amber-500/20',
};

/** Touch-friendly quantity input: − / number / + with 44px targets, clamped to [min, max]. */
export const QtyStepper: React.FC<QtyStepperProps> = ({
  value,
  max,
  min = 0,
  onChange,
  label,
  disabled = false,
  tone = 'brand',
  className,
}) => {
  const clamp = (n: number) => Math.max(min, Math.min(max, n));
  const btn =
    'grid h-11 w-11 shrink-0 place-items-center text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 active:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-40';
  return (
    <div
      className={cn(
        'qty-stepper inline-flex items-center overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm ring-0 transition-shadow focus-within:ring-4',
        TONE[tone],
        disabled && 'opacity-60',
        className,
      )}
    >
      <button
        type="button"
        className={btn}
        aria-label={`Decrease ${label}`}
        disabled={disabled || value <= min}
        onClick={() => {
          onChange(clamp(value - 1));
        }}
      >
        <Minus className="h-4 w-4" aria-hidden="true" />
      </button>
      <input
        type="number"
        inputMode="numeric"
        aria-label={label}
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const n = parseInt(e.target.value, 10);
          onChange(clamp(isNaN(n) ? min : n));
        }}
        className="h-11 w-14 border-0 bg-transparent text-center font-mono text-base font-semibold tabular-nums text-slate-900 outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
      />
      <button
        type="button"
        className={btn}
        aria-label={`Increase ${label}`}
        disabled={disabled || value >= max}
        onClick={() => {
          onChange(clamp(value + 1));
        }}
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
};
