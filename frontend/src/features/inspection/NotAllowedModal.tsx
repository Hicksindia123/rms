import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui';
import type { ConditionOption } from './types';

interface NotAllowedModalProps {
  isOpen: boolean;
  option: ConditionOption | null;
  onConfirm: () => void;
  onCancel: () => void;
}

export const NotAllowedModal: React.FC<NotAllowedModalProps> = ({
  isOpen,
  option,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen || !option) return null;

  const isNo = option.allowed_status === 'NO';

  const getRoutingDescription = () => {
    if (option.system_behavior === 'HAZARD') {
      return 'This item contains hazardous mercury material and will be transferred to HAZARD_QUARANTINE. Safety alerts will be dispatched, and downstream flow is strictly blocked (G-05).';
    }
    if (option.system_behavior === 'REJECT_HOLD') {
      return `${option.label} (${option.code}) will be moved to REJECTED_HOLD for return to the sending party (HOLD_PARTY_RETURN).`;
    }
    if (option.system_behavior === 'TO_SPARE_PARTS') {
      return `${option.label} (${option.code}) will be moved to NON_FUNCTIONAL_STORE for spare parts harvesting (TO_SPARE_PARTS).`;
    }
    if (option.system_behavior === 'RECORDED_REJECT') {
      return `${option.label} (${option.code}) will be segregated to REJECTED_HOLD and documented as scrap (RECORDED_REJECT).`;
    }
    if (option.code === 'EO_INNER_CAPILLARY_BROKEN') {
      return `${option.label} requires technical evaluation by a technician (routing hint: EVALUATE).`;
    }
    return (
      option.rule_text ||
      option.next_action_text ||
      'This item will follow non-standard segregated routing.'
    );
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="not-allowed-title"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '1rem',
      }}
    >
      <div
        style={{
          backgroundColor: '#ffffff',
          borderRadius: '8px',
          maxWidth: '480px',
          width: '100%',
          padding: '1.5rem',
          boxShadow: '0 10px 25px rgba(0, 0, 0, 0.2)',
          display: 'flex',
          flexDirection: 'column',
          gap: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div
            style={{
              padding: '0.5rem',
              borderRadius: '50%',
              backgroundColor: isNo ? '#fef2f2' : '#fffbeb',
              color: isNo ? '#dc2626' : '#d97706',
            }}
          >
            <AlertTriangle size={24} aria-hidden="true" />
          </div>
          <div>
            <h3 id="not-allowed-title" style={{ margin: 0, fontSize: '1.125rem', fontWeight: 700 }}>
              {isNo ? 'Not Allowed Condition Selected' : 'Conditional Condition Selected'}
            </h3>
            <span style={{ fontSize: '0.85rem', color: '#64748b' }}>
              {option.label} ({option.code})
            </span>
          </div>
        </div>

        <div
          style={{
            fontSize: '0.9rem',
            lineHeight: 1.5,
            color: '#334155',
            backgroundColor: '#f8fafc',
            padding: '1rem',
            borderRadius: '6px',
            border: '1px solid #e2e8f0',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>
            Downstream Routing & Policy:
          </div>
          <div>{getRoutingDescription()}</div>
          {option.next_action_text && (
            <div style={{ marginTop: '0.5rem', fontSize: '0.8rem', color: '#64748b' }}>
              <strong>Next Action:</strong> {option.next_action_text}
            </div>
          )}
        </div>

        <p style={{ margin: 0, fontSize: '0.875rem', color: '#475569' }}>
          Are you sure you want to grade pieces into this condition?
        </p>

        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '0.5rem',
            marginTop: '0.5rem',
          }}
        >
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" variant={isNo ? 'danger' : 'primary'} onClick={onConfirm}>
            Confirm Allocation
          </Button>
        </div>
      </div>
    </div>
  );
};
