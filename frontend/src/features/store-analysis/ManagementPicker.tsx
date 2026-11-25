/**
 * DEC-75: choose pieces to send for Management approval — per item + condition + current decision
 * ("previous action"), a quantity and a proposal (labels and options come from configuration:
 * setting store_analysis.management_proposals). Used inside the analysis (with the submission) and
 * afterwards (any time until Accounts completes the goods slip).
 */
import React from 'react';
import { ArrowRight } from 'lucide-react';

import { QtyStepper } from '@/components/ui';
import { cn } from '@/lib/utils';

import type { Pick, PickRow, Picks } from './picks';
import type { ProposalOption } from './types';

interface Props {
  rows: PickRow[];
  proposals: ProposalOption[];
  picks: Picks;
  onChange: (next: Picks) => void;
}

export const ManagementPicker: React.FC<Props> = ({ rows, proposals, picks, onChange }) => {
  const set = (key: string, patch: Partial<Pick>) => {
    const cur = picks[key] ?? { qty: 0, proposal: null };
    onChange({ ...picks, [key]: { ...cur, ...patch } });
  };

  if (rows.length === 0) {
    return (
      <p className="m-0 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">
        No pieces are free to send right now.
      </p>
    );
  }

  return (
    <ul className="m-0 list-none space-y-2.5 p-0" aria-label="Pieces to send to Management">
      {rows.map((r) => {
        const p = picks[r.key] ?? { qty: 0, proposal: null };
        const choices = proposals.filter((o) => o.code !== r.from_code);
        const active = p.qty > 0;
        return (
          <li
            key={r.key}
            className={cn(
              'rounded-2xl border p-3 transition-colors sm:p-4',
              active ? 'border-indigo-200 bg-indigo-50/50 shadow-sm' : 'border-slate-200 bg-white',
            )}
            data-testid={`mgmt-pick-${r.key}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="m-0 break-words text-sm font-semibold text-slate-900">
                  <span className="text-slate-400">#{r.line_no}</span> {r.product_name}
                </p>
                <p className="m-0 mt-0.5 text-xs text-slate-500">
                  {r.condition_label ? `${r.condition_label} · ` : ''}
                  Currently <span className="font-semibold text-slate-700">{r.from_label}</span> ·
                  up to {r.max} pcs
                </p>
              </div>
              <QtyStepper
                value={Math.min(p.qty, r.max)}
                max={r.max}
                label={`Pieces to send, item ${String(r.line_no)}${
                  r.condition_label ? `, ${r.condition_label}` : ''
                }, ${r.from_label}`}
                onChange={(qty) => {
                  set(r.key, { qty });
                }}
              />
            </div>
            {active ? (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-500">
                  Propose <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Proposal">
                  {choices.map((o) => {
                    const on = p.proposal === o.code;
                    return (
                      <button
                        key={o.code}
                        type="button"
                        role="radio"
                        aria-checked={on}
                        onClick={() => {
                          set(r.key, { proposal: o.code });
                        }}
                        className={cn(
                          'min-h-[44px] rounded-xl border px-4 text-sm font-semibold transition-all',
                          on
                            ? 'border-indigo-600 bg-indigo-600 text-white shadow-md shadow-indigo-600/20'
                            : 'border-slate-200 bg-white text-slate-700 hover:border-indigo-300 hover:text-indigo-700',
                        )}
                      >
                        {o.label}
                      </button>
                    );
                  })}
                </div>
                {!p.proposal ? (
                  <span className="text-xs font-medium text-amber-700">Choose a proposal</span>
                ) : null}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
};
