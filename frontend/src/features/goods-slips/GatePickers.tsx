import { useCallback, useEffect, useRef, useState } from 'react';
import { Plus } from 'lucide-react';

import { AsyncCombobox, Button, Input, Select } from '@/components/ui';
import type { ComboboxOption } from '@/components/ui';

import { gsApi, type LookupItem } from './api';
import type { PartySelection, StationCache } from './useStations';

interface PartyPickerProps {
  id: string;
  selection: PartySelection | null;
  states: LookupItem[];
  stations: StationCache;
  error?: string | undefined;
  disabled?: boolean;
  onSelect: (selection: PartySelection | null) => void;
}

/** DEC-02: pick a party from the master, or create a provisional one inline at the gate. */
export function PartyPicker({
  id,
  selection,
  states,
  stations,
  error,
  disabled,
  onSelect,
}: PartyPickerProps) {
  const known = useRef(new Map<string, LookupItem>());
  const [creating, setCreating] = useState(selection?.kind === 'provisional');
  const [draft, setDraft] = useState({ name: '', stateId: '', stationId: '' });
  const [draftError, setDraftError] = useState<string | null>(null);

  useEffect(() => {
    if (draft.stateId) stations.load(draft.stateId);
  }, [draft.stateId, stations]);

  const loadOptions = useCallback(async (q: string): Promise<ComboboxOption[]> => {
    const rows = await gsApi.parties(q);
    for (const r of rows) known.current.set(r.id, r);
    return rows.map((r) => ({
      value: r.id,
      label: r.name,
      sublabel: [r.station_name, r.state_name].filter(Boolean).join(', ') || undefined,
    }));
  }, []);

  if (creating) {
    const stationOptions = stations.get(draft.stateId).map((s) => ({ value: s.id, label: s.name }));
    return (
      <div
        style={{
          border: '1px solid var(--color-border)',
          borderRadius: '0.5rem',
          padding: '0.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
        }}
      >
        {selection?.kind === 'provisional' ? (
          <p style={{ margin: 0 }}>
            <strong>{selection.name}</strong>{' '}
            <span style={{ color: 'var(--color-muted)' }}>(provisional, admin review)</span>
          </p>
        ) : (
          <>
            <Input
              id={`${id}-new-name`}
              aria-label="New party name"
              placeholder="New party name"
              value={draft.name}
              disabled={disabled}
              onChange={(e) => {
                setDraft({ ...draft, name: e.target.value });
              }}
            />
            <Select
              id={`${id}-new-state`}
              aria-label="New party state"
              placeholder="-- Select State / UT --"
              options={states.map((s) => ({ value: s.id, label: s.name }))}
              value={draft.stateId}
              disabled={disabled}
              onChange={(e) => {
                setDraft({ ...draft, stateId: e.target.value, stationId: '' });
              }}
            />
            <Select
              id={`${id}-new-station`}
              aria-label="New party station"
              placeholder={
                draft.stateId
                  ? '-- Select Station (City / District) --'
                  : '-- Select State First --'
              }
              options={stationOptions}
              value={draft.stationId}
              disabled={disabled || !draft.stateId}
              onChange={(e) => {
                setDraft({ ...draft, stationId: e.target.value });
              }}
            />
            {draftError ? (
              <p className="form-control__error" role="alert">
                {draftError}
              </p>
            ) : null}
          </>
        )}
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {selection?.kind !== 'provisional' ? (
            <Button
              type="button"
              variant="primary"
              disabled={disabled}
              onClick={() => {
                if (!draft.name.trim() || !draft.stateId || !draft.stationId) {
                  setDraftError('Enter the party name, state and station');
                  return;
                }
                setDraftError(null);
                onSelect({
                  kind: 'provisional',
                  name: draft.name.trim(),
                  stateId: draft.stateId,
                  stationId: draft.stationId,
                });
              }}
            >
              Use this party
            </Button>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            disabled={disabled}
            onClick={() => {
              setCreating(false);
              onSelect(null);
            }}
          >
            Search existing parties
          </Button>
        </div>
        {error ? (
          <p className="form-control__error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      <AsyncCombobox
        id={id}
        name="party"
        value={selection?.kind === 'existing' ? selection.id : ''}
        loadOptions={loadOptions}
        placeholder="Search party name or code…"
        error={error}
        disabled={disabled}
        onChange={(value) => {
          const party = value ? known.current.get(value) : undefined;
          onSelect(
            party
              ? {
                  kind: 'existing',
                  id: party.id,
                  name: party.name,
                  stateId: party.state_id ?? null,
                  stationId: party.station_id ?? null,
                }
              : null,
          );
        }}
      />
      <Button
        type="button"
        variant="ghost"
        disabled={disabled}
        onClick={() => {
          setCreating(true);
          onSelect(null);
        }}
        style={{ alignSelf: 'flex-start' }}
      >
        <Plus size={16} aria-hidden="true" /> Party not found? Create provisional party
      </Button>
    </div>
  );
}

interface TransporterInputProps {
  id: string;
  value: string;
  error?: string | undefined;
  disabled?: boolean;
  onChange: (name: string, transporterId: string | null) => void;
}

/** DD r3: transporter from the master (suggestions) or a new free-text name. */
export function TransporterInput({ id, value, error, disabled, onChange }: TransporterInputProps) {
  const [options, setOptions] = useState<LookupItem[]>([]);

  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => {
      gsApi
        .transporters(value)
        .then((rows) => {
          if (current) setOptions(rows);
        })
        .catch((err: unknown) => {
          console.warn('Transporter lookup failed', err);
        });
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [value]);

  const listId = `${id}-list`;
  return (
    <>
      <Input
        id={id}
        list={listId}
        value={value}
        error={error}
        disabled={disabled}
        autoComplete="off"
        helperText="Pick from the transporter master or type a new name"
        onChange={(e) => {
          const name = e.target.value;
          const match = options.find((o) => o.name.toLowerCase() === name.trim().toLowerCase());
          onChange(name, match ? match.id : null);
        }}
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o.id} value={o.name} />
        ))}
      </datalist>
    </>
  );
}
