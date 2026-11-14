import { useState } from 'react';

import { Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { AdjustmentRequestModal } from './AdjustmentRequestModal';
import { AdjustmentsPanel } from './AdjustmentsPanel';
import { CustodyAssignModal } from './CustodyAssignModal';
import { SegregationCheckPanel } from './SegregationCheckPanel';
import { StockCardDrawer } from './StockCardDrawer';
import { StockViewPanel } from './StockViewPanel';
import { inventoryApi } from './api';
import { HOLD_VIEWS, VIEW_LABELS, type InventoryTab } from './rules';
import type { Balance, InventoryLookups, StockCard, StockRow, StockView } from './types';

const TAB_VIEW: Partial<Record<InventoryTab, StockView>> = {
  functional: 'FUNCTIONAL',
  'non-functional': 'NON_FUNCTIONAL',
  'spare-parts': 'SPARE_PARTS',
  batteries: 'BATTERIES',
};

interface Props {
  tab: InventoryTab;
  onTab: (tab: InventoryTab) => void;
  onOpenTransfer: (transferId: string) => void;
}

/** Step-6 custody segregation (BR-30): each custodian's segregated stock, adjustments, check. */
export function InventoryPage({ tab, onTab, onOpenTransfer }: Props) {
  const {
    data: lookups,
    error,
    loading,
    reload,
  } = useApiQuery<InventoryLookups>(inventoryApi.lookups);
  const [holdView, setHoldView] = useState<StockView>('REJECTED_HOLD');
  const [openRow, setOpenRow] = useState<StockRow | null>(null);
  const [assignRow, setAssignRow] = useState<StockRow | null>(null);
  const [adjust, setAdjust] = useState<{ card: StockCard; balance: Balance } | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const bump = () => {
    setReloadToken((n) => n + 1);
  };

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !lookups) return <LoadingState label="Loading inventory…" />;

  const tabs: Array<{ id: InventoryTab; label: string }> = [
    { id: 'functional', label: VIEW_LABELS.FUNCTIONAL },
    { id: 'non-functional', label: VIEW_LABELS.NON_FUNCTIONAL },
    ...(lookups.views.includes('SPARE_PARTS')
      ? [{ id: 'spare-parts' as const, label: VIEW_LABELS.SPARE_PARTS }]
      : []),
    { id: 'batteries', label: VIEW_LABELS.BATTERIES },
    { id: 'holds', label: 'Hold & Quarantine' },
    { id: 'adjustments', label: 'Adjustments' },
    { id: 'segregation', label: 'Segregation check' },
  ];
  const active = tabs.some((t) => t.id === tab) ? tab : 'functional';
  const view = active === 'holds' ? holdView : TAB_VIEW[active];

  return (
    <div className="page">
      <h1 className="page__title">Inventory</h1>
      <p className="page__subtitle">
        Functional stock stays with the Intermediate Store; non-functional, non-sellable stock and
        salvaged parts with the Spare Parts Manager.
      </p>
      <div className="tabs tabs--wrap" role="tablist" aria-label="Inventory views">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            className="tabs__tab"
            aria-selected={active === t.id}
            onClick={() => {
              onTab(t.id);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {active === 'holds' ? (
        <div
          role="group"
          aria-label="Hold location"
          style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '1rem' }}
        >
          {HOLD_VIEWS.map((v) => (
            <Button
              key={v}
              type="button"
              size="sm"
              variant={holdView === v ? 'primary' : 'secondary'}
              aria-pressed={holdView === v}
              style={{ minHeight: 44 }}
              onClick={() => {
                setHoldView(v);
              }}
            >
              {VIEW_LABELS[v]}
            </Button>
          ))}
        </div>
      ) : null}

      {view ? (
        <StockViewPanel
          key={view}
          view={view}
          lookups={lookups}
          reloadToken={reloadToken}
          onOpen={setOpenRow}
          onAssign={setAssignRow}
        />
      ) : active === 'adjustments' ? (
        <AdjustmentsPanel reloadToken={reloadToken} />
      ) : (
        <SegregationCheckPanel />
      )}

      {/* One dialog at a time: the drawer returns when the assignment / count modal closes. */}
      {openRow && !assignRow && !adjust ? (
        <StockCardDrawer
          row={openRow}
          canAssign={lookups.can_assign}
          canRequestAdjustment={lookups.can_request_adjustment}
          reloadToken={reloadToken}
          onClose={() => {
            setOpenRow(null);
          }}
          onAssign={setAssignRow}
          onRequestAdjustment={(card, balance) => {
            setAdjust({ card, balance });
          }}
          onOpenTransfer={onOpenTransfer}
        />
      ) : null}
      {assignRow ? (
        <CustodyAssignModal
          key={`${assignRow.lot_id}:${assignRow.location_id}`}
          row={assignRow}
          options={lookups.assignment_options}
          onClose={() => {
            setAssignRow(null);
          }}
          onDone={bump}
          onOpenTransfer={onOpenTransfer}
        />
      ) : null}
      {adjust ? (
        <AdjustmentRequestModal
          card={adjust.card}
          balance={adjust.balance}
          onClose={() => {
            setAdjust(null);
          }}
          onDone={bump}
        />
      ) : null}
    </div>
  );
}
