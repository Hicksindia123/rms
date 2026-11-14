import { useCallback } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Edit3,
  Package,
  Send,
  Truck,
  Wrench,
} from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';

import { rmActionsApi } from './api';
import type { ResolutionBoardResponse } from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onReviseActions?: (gsId: string) => void;
  onRevise?: () => void;
  onGoToDispatch?: () => void;
  onGoToStoreIssue?: () => void;
  onOpenCnDecision?: () => void;
}

export function ResolutionBoardPage({
  gsId,
  onBack,
  onReviseActions,
  onRevise,
  onGoToDispatch,
  onGoToStoreIssue,
  onOpenCnDecision,
}: Props) {
  const fetcher = useCallback(() => rmActionsApi.getResolutionBoard(gsId), [gsId]);
  const { data, loading, error, reload } = useApiQuery<ResolutionBoardResponse>(fetcher);

  const handleRevise = () => {
    if (onReviseActions) onReviseActions(gsId);
    else if (onRevise) onRevise();
  };

  if (loading) {
    return <LoadingState label="Loading resolution board data..." />;
  }

  if (error || !data) {
    return (
      <ErrorState
        title="Failed to load resolution board"
        error={{ message: error?.message || 'Resolution board not available' }}
        onRetry={reload}
      />
    );
  }

  const mismatchCount = data.lines.filter((l) => l.has_mismatch).length;

  return (
    <div className="space-y-6 p-4 md:p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b pb-4">
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={onBack} className="gap-2">
            <ArrowLeft className="w-4 h-4" />
            Back
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground">
                RM Resolution Board
              </h1>
              <Badge variant="neutral" className="font-mono text-xs">
                {data.gs_no}
              </Badge>
              <Badge variant="default" className="text-xs">
                Rev {data.current_revision_no}
              </Badge>
            </div>
            <p className="text-xs sm:text-sm text-muted-foreground mt-0.5">
              Compare planned RM allocations against technical servicing outcomes and actual
              dispatches
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {onGoToStoreIssue && (
            <Button variant="outline" size="sm" onClick={onGoToStoreIssue} className="gap-1.5">
              <Package className="w-4 h-4" />
              Store Issues
            </Button>
          )}
          {onGoToDispatch && (
            <Button variant="outline" size="sm" onClick={onGoToDispatch} className="gap-1.5">
              <Truck className="w-4 h-4" />
              Dispatch Queue
            </Button>
          )}
          {onOpenCnDecision && (
            <Button
              variant="outline"
              size="sm"
              onClick={onOpenCnDecision}
              className="gap-1.5 border-emerald-500 text-emerald-700 hover:bg-emerald-50 dark:text-emerald-300 dark:hover:bg-emerald-950/30"
            >
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              Step-7 CN Decision
            </Button>
          )}
          <Button
            size="sm"
            onClick={handleRevise}
            className="gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <Edit3 className="w-4 h-4" />
            Revise RM Actions
          </Button>
        </div>
      </div>

      {/* Summary Notes / Alerts */}
      {data.summary_notes.length > 0 && (
        <div
          className={`p-4 rounded-lg border ${
            mismatchCount > 0
              ? 'bg-amber-50/70 border-amber-200 text-amber-900 dark:bg-amber-950/20 dark:border-amber-900/50 dark:text-amber-300'
              : 'bg-emerald-50/70 border-emerald-200 text-emerald-900 dark:bg-emerald-950/20 dark:border-emerald-900/50 dark:text-emerald-300'
          }`}
        >
          <div className="flex items-start gap-3">
            {mismatchCount > 0 ? (
              <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
            ) : (
              <CheckCircle2 className="w-5 h-5 mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            )}
            <div className="space-y-1">
              <div className="font-semibold text-sm">
                {mismatchCount > 0
                  ? `${String(mismatchCount)} Line(s) Require RM Revision Attention`
                  : 'All Line Allocations Aligned'}
              </div>
              {data.summary_notes.map((note, idx) => (
                <div key={idx} className="text-xs sm:text-sm">
                  {note}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Lines Listing */}
      <div className="space-y-4">
        {data.lines.map((line) => {
          return (
            <div
              key={line.gs_item_id}
              className={`rounded-lg border bg-card text-card-foreground shadow-sm transition-all overflow-hidden ${
                line.has_mismatch
                  ? 'border-amber-300 ring-1 ring-amber-300/50 dark:border-amber-800'
                  : 'border-border'
              }`}
            >
              {/* Line Header */}
              <div className="p-4 bg-muted/40 border-b flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-3">
                  <span className="flex items-center justify-center w-7 h-7 rounded-full bg-primary/10 text-primary font-bold text-xs">
                    #{line.line_no}
                  </span>
                  <div>
                    <div className="font-semibold text-sm sm:text-base">
                      {line.product_name}{' '}
                      <span className="font-mono text-xs text-muted-foreground font-normal">
                        ({line.product_code})
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Received Total:{' '}
                      <strong className="text-foreground">{line.received_qty}</strong> pcs
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {line.has_mismatch ? (
                    <Badge variant="warning" className="gap-1 text-xs">
                      <AlertTriangle className="w-3.5 h-3.5" />
                      Outcome Mismatch
                    </Badge>
                  ) : (
                    <Badge variant="success" className="gap-1 text-xs">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Balanced
                    </Badge>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRevise}
                    className="text-xs h-7 px-2"
                  >
                    Revise
                  </Button>
                </div>
              </div>

              {/* Line Content Grid */}
              <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-4 text-xs sm:text-sm">
                {/* Column 1: Planned RM Actions */}
                <div className="space-y-2 border-b md:border-b-0 md:border-r pb-4 md:pb-0 md:pr-4">
                  <div className="font-semibold text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <Send className="w-3.5 h-3.5 text-blue-500" />
                    Current RM Plan
                  </div>
                  <div className="space-y-1.5">
                    {line.current_actions.length > 0 ? (
                      line.current_actions.map((act) => (
                        <div
                          key={act.action_code}
                          className="flex items-center justify-between p-2 rounded bg-muted/30"
                        >
                          <span className="font-medium text-foreground">
                            {act.label || act.action_code}
                          </span>
                          <span className="font-bold text-foreground font-mono">{act.qty} pcs</span>
                        </div>
                      ))
                    ) : (
                      <div className="text-muted-foreground italic text-xs">
                        No allocations recorded
                      </div>
                    )}
                  </div>
                </div>

                {/* Column 2: Actual Technical Outcomes */}
                <div className="space-y-2 border-b md:border-b-0 md:border-r pb-4 md:pb-0 md:pr-4">
                  <div className="font-semibold text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <Wrench className="w-3.5 h-3.5 text-amber-500" />
                    Actual Outcomes
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between p-1.5 rounded bg-muted/20">
                      <span className="text-emerald-700 dark:text-emerald-400 font-medium">
                        Functional Good
                      </span>
                      <span className="font-mono font-semibold">
                        {line.outcomes.functional_good_qty}
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-1.5 rounded bg-muted/20">
                      <span className="text-teal-700 dark:text-teal-400 font-medium">
                        Functional Repaired
                      </span>
                      <span className="font-mono font-semibold">
                        {line.outcomes.functional_repaired_qty}
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-1.5 rounded bg-muted/20">
                      <span className="text-rose-700 dark:text-rose-400 font-medium">
                        Non-Good (Dismantle)
                      </span>
                      <span className="font-mono font-semibold">{line.outcomes.non_good_qty}</span>
                    </div>
                    <div className="flex items-center justify-between p-1.5 rounded bg-muted/20">
                      <span className="text-orange-700 dark:text-orange-400 font-medium">
                        Non-Sellable (Scratched)
                      </span>
                      <span className="font-mono font-semibold">
                        {line.outcomes.non_sellable_qty}
                      </span>
                    </div>
                    {line.outcomes.rejected_qty > 0 && (
                      <div className="flex items-center justify-between p-1.5 rounded bg-muted/20">
                        <span className="text-red-700 dark:text-red-400 font-medium">
                          Inspection Rejected
                        </span>
                        <span className="font-mono font-semibold">
                          {line.outcomes.rejected_qty}
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Column 3: Dispatched & Issued Status */}
                <div className="space-y-2">
                  <div className="font-semibold text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <Truck className="w-3.5 h-3.5 text-indigo-500" />
                    Dispatches & Store Issues
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between p-1.5 rounded bg-muted/20">
                      <span className="text-foreground">Dispatched New (Main Store)</span>
                      <span className="font-mono font-semibold text-foreground">
                        {line.dispatched.dispatched_new_qty} pcs
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-1.5 rounded bg-muted/20">
                      <span className="text-foreground">Dispatched Repaired</span>
                      <span className="font-mono font-semibold text-foreground">
                        {line.dispatched.dispatched_repaired_qty} pcs
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-1.5 rounded bg-muted/20">
                      <span className="text-foreground">Issued to Main Store</span>
                      <span className="font-mono font-semibold text-foreground">
                        {line.dispatched.issued_main_store_qty} pcs
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Suggestions Section */}
              {line.suggested_adjustments.length > 0 && (
                <div className="p-3 bg-muted/20 border-t space-y-1">
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1">
                    <AlertCircle className="w-3 h-3 text-primary" />
                    Resolution Advisory
                  </div>
                  {line.suggested_adjustments.map((sug, sIdx) => (
                    <div
                      key={sIdx}
                      className={`text-xs ${
                        line.has_mismatch
                          ? 'text-amber-800 dark:text-amber-300 font-medium'
                          : 'text-muted-foreground'
                      }`}
                    >
                      • {sug}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
