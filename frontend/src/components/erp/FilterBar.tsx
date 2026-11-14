import React, { useEffect, useState } from 'react';
import { Filter } from 'lucide-react';

import { Button, Drawer, Input, Select } from '@/components/ui';

export interface FilterField {
  key: string;
  label: string;
  type: 'date' | 'text' | 'enum' | 'uuid' | 'bool';
  choices?: { value: string; label: string }[];
  required?: boolean;
}

export interface FilterBarProps {
  idPrefix: string;
  fields: FilterField[];
  values: Record<string, string>;
  onChange: (values: Record<string, string>) => void;
  onApply: () => void;
  onReset: () => void;
  /** Extra controls (e.g. saved filters) shown under the fields. */
  extra?: React.ReactNode;
  /** Number of filters currently applied (shown on the phone "Filters" button). */
  activeCount?: number;
}

const PHONE_QUERY = '(max-width: 767px)';

function useIsPhone(): boolean {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(PHONE_QUERY);
    const onChange = () => {
      setPhone(mq.matches);
    };
    mq.addEventListener('change', onChange);
    return () => {
      mq.removeEventListener('change', onChange);
    };
  }, []);
  return phone;
}

function Field({
  field,
  id,
  value,
  onChange,
}: {
  field: FilterField;
  id: string;
  value: string;
  onChange: (v: string) => void;
}) {
  let control: React.ReactNode;
  if (field.type === 'enum' || field.type === 'uuid' || field.type === 'bool') {
    const options =
      field.type === 'bool'
        ? [
            { value: 'true', label: 'Yes' },
            { value: 'false', label: 'No' },
          ]
        : (field.choices ?? []);
    control = (
      <Select
        id={id}
        value={value}
        options={options}
        placeholder={field.type === 'bool' ? 'Any' : 'All'}
        onChange={(e) => {
          onChange(e.target.value);
        }}
      />
    );
  } else {
    control = (
      <Input
        id={id}
        type={field.type === 'date' ? 'date' : 'search'}
        value={value}
        required={field.required}
        maxLength={field.type === 'text' ? 100 : undefined}
        onChange={(e) => {
          onChange(e.target.value);
        }}
      />
    );
  }
  return (
    <div className="filterbar__field">
      <label className="form-label" htmlFor={id}>
        {field.label}
      </label>
      {control}
    </div>
  );
}

/** Report / list filters: inline grid from 768px, a "Filters" drawer on phones (§11). */
export function FilterBar({
  idPrefix,
  fields,
  values,
  onChange,
  onApply,
  onReset,
  extra,
  activeCount = 0,
}: FilterBarProps) {
  const phone = useIsPhone();
  const [open, setOpen] = useState(false);

  const body = (
    <form
      className="filterbar__form"
      onSubmit={(e) => {
        e.preventDefault();
        onApply();
        setOpen(false);
      }}
    >
      <div className="filterbar__grid">
        {fields.map((f) => (
          <Field
            key={f.key}
            field={f}
            id={`${idPrefix}-${f.key}`}
            value={values[f.key] ?? ''}
            onChange={(v) => {
              onChange({ ...values, [f.key]: v });
            }}
          />
        ))}
      </div>
      <div className="filterbar__actions">
        <Button type="submit" variant="primary">
          Apply filters
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            onReset();
            setOpen(false);
          }}
        >
          Reset
        </Button>
      </div>
      {extra ? <div className="filterbar__extra">{extra}</div> : null}
    </form>
  );

  if (!phone)
    return (
      <section className="filterbar" aria-label="Filters">
        {body}
      </section>
    );
  return (
    <>
      <Button
        type="button"
        variant="secondary"
        className="filterbar__toggle"
        onClick={() => {
          setOpen(true);
        }}
      >
        <Filter size={16} aria-hidden="true" /> Filters
        {activeCount > 0 ? ` (${String(activeCount)})` : ''}
      </Button>
      <Drawer
        isOpen={open}
        onClose={() => {
          setOpen(false);
        }}
        title="Filters"
      >
        {body}
      </Drawer>
    </>
  );
}
