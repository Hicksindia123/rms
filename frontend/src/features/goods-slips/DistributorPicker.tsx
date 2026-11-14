import { useCallback, useRef, useState } from 'react';
import { Plus } from 'lucide-react';

import { AsyncCombobox, Button, Input } from '@/components/ui';
import type { ComboboxOption } from '@/components/ui';

import { gsApi, type LookupItem, type PartyLookupPage } from './api';
import type { PartySelection } from './useStations';

interface Props {
  id: string;
  stateId: string;
  stationId: string;
  selection: PartySelection | null;
  error?: string | undefined;
  disabled?: boolean;
  onSelect: (selection: PartySelection | null) => void;
}

/** AMD-06: Distributor list filtered by the selected State + Station. When the station has no
 * parties the backend applies `gate.party_fallback` (DEC-35) and says so; a provisional party can
 * still be created for the selected state and station (DEC-02). */
export function DistributorPicker({
  id,
  stateId,
  stationId,
  selection,
  error,
  disabled,
  onSelect,
}: Props) {
  const known = useRef(new Map<string, LookupItem>());
  const [scope, setScope] = useState<PartyLookupPage['scope'] | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const ready = Boolean(stateId && stationId);

  const loadOptions = useCallback(
    async (q: string): Promise<ComboboxOption[]> => {
      if (!stateId || !stationId) return [];
      const page = await gsApi.partiesByLocation(stateId, stationId, q);
      setScope(page.fallback_applied ? page.scope : 'STATION');
      for (const r of page.items) known.current.set(r.id, r);
      return page.items.map((r) => ({
        value: r.id,
        label: r.name,
        sublabel: [r.code, r.station_name].filter(Boolean).join(' · ') || undefined,
      }));
    },
    [stateId, stationId],
  );

  if (selection?.kind === 'provisional') {
    return (
      <div className="gate-doc">
        <p style={{ margin: 0 }}>
          <strong>{selection.name}</strong>{' '}
          <span style={{ color: 'var(--color-muted)' }}>(provisional, admin review)</span>
        </p>
        <Button
          type="button"
          variant="secondary"
          disabled={disabled}
          onClick={() => {
            setCreating(false);
            onSelect(null);
          }}
        >
          Choose an existing distributor
        </Button>
      </div>
    );
  }

  if (creating) {
    return (
      <div className="gate-doc">
        <Input
          id={`${id}-new-name`}
          aria-label="New party name"
          placeholder="New party name"
          value={name}
          maxLength={200}
          error={nameError ?? undefined}
          disabled={disabled}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <Button
            type="button"
            variant="primary"
            disabled={disabled}
            onClick={() => {
              if (!name.trim()) {
                setNameError('Enter the party name');
                return;
              }
              setNameError(null);
              onSelect({ kind: 'provisional', name: name.trim(), stateId, stationId });
            }}
          >
            Use this party
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={disabled}
            onClick={() => {
              setCreating(false);
            }}
          >
            Back to the list
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
      <AsyncCombobox
        // Re-mount per station so the list reloads for the new filter.
        key={`${stateId}|${stationId}`}
        id={id}
        name="party"
        value={selection?.kind === 'existing' ? selection.id : ''}
        loadOptions={loadOptions}
        placeholder={ready ? 'Search distributor name or code…' : 'Select state and station first'}
        error={error}
        disabled={disabled || !ready}
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
      {ready && scope && scope !== 'STATION' ? (
        <p className="gate-hint" role="status" data-testid="party-fallback-hint">
          {scope === 'NONE'
            ? 'No distributors are linked to this station.'
            : scope === 'STATE'
              ? 'No distributors are linked to this station; showing the parties of the state.'
              : 'No distributors are linked to this station; showing all parties.'}
        </p>
      ) : null}
      {ready ? (
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
      ) : null}
    </div>
  );
}
