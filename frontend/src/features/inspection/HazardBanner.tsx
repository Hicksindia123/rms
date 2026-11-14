import React from 'react';
import { AlertOctagon, ShieldAlert } from 'lucide-react';

interface HazardBannerProps {
  hazardQty?: number;
  message?: string;
  className?: string;
}

export const HazardBanner: React.FC<HazardBannerProps> = ({ hazardQty, message, className }) => {
  return (
    <div
      role="alert"
      className={className}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '0.75rem',
        padding: '1rem',
        backgroundColor: '#fef2f2',
        border: '2px solid #ef4444',
        borderRadius: '8px',
        color: '#991b1b',
        boxShadow: '0 2px 4px rgba(239, 68, 68, 0.1)',
      }}
    >
      <AlertOctagon
        size={28}
        color="#dc2626"
        style={{ flexShrink: 0, marginTop: '2px' }}
        aria-hidden="true"
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontWeight: 800, fontSize: '0.95rem', letterSpacing: '0.025em' }}>
            MERCURY HAZARD — QUARANTINE PROTOCOL ACTIVATED
          </span>
          {hazardQty !== undefined && hazardQty > 0 && (
            <span
              style={{
                backgroundColor: '#dc2626',
                color: '#ffffff',
                fontWeight: 700,
                fontSize: '0.75rem',
                padding: '2px 8px',
                borderRadius: '12px',
              }}
            >
              {hazardQty} {hazardQty === 1 ? 'piece' : 'pieces'}
            </span>
          )}
        </div>
        <div style={{ fontSize: '0.85rem', lineHeight: 1.4 }}>
          {message ||
            'Item will be segregated and locked into HAZARD_QUARANTINE. Safety team & RM will be alerted immediately. Downstream operational flow to functional stores is strictly blocked (G-04/G-05).'}
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            marginTop: '0.25rem',
            fontSize: '0.75rem',
            fontWeight: 600,
            color: '#b91c1c',
          }}
        >
          <ShieldAlert size={14} aria-hidden="true" />
          <span>Non-bypassable Safety Guard Active</span>
        </div>
      </div>
    </div>
  );
};
