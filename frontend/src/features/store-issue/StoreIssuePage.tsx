import { useCallback, useMemo, useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Package,
  Printer,
  RefreshCw,
  Search,
} from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError } from '@/lib/api/client';

import { storeIssueApi } from './api';
import type { StoreIssue, StoreIssueCandidateLot } from './types';

interface Props {
  onOpenPrint?: (issueId: string) => void;
  onPrint?: (issueId: string) => void;
}

export function StoreIssuePage({ onOpenPrint, onPrint }: Props) {
  const handlePrint = onOpenPrint || onPrint || (() => {});
  const [activeTab, setActiveTab] = useState<'candidate' | 'register'>('candidate');

  // Candidate lots query
  const candidateFetcher = useCallback(() => storeIssueApi.getCandidateLots(), []);
  const {
    data: candidateLots,
    loading: loadingCandidates,
    error: candidateError,
    reload: reloadCandidates,
  } = useApiQuery<StoreIssueCandidateLot[]>(candidateFetcher);

  // Issues register query
  const registerFetcher = useCallback(() => storeIssueApi.listStoreIssues(), []);
  const {
    data: issuesList,
    loading: loadingRegister,
    error: registerError,
    reload: reloadRegister,
  } = useApiQuery<StoreIssue[]>(registerFetcher);

  // Form state for creating store issue
  const [selectedLots, setSelectedLots] = useState<Record<string, number>>({});
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Filtering candidates
  const filteredCandidates = useMemo(() => {
    if (!candidateLots) return [];
    if (!searchQuery.trim()) return candidateLots;
    const q = searchQuery.toLowerCase();
    return candidateLots.filter(
      (c) =>
        c.product_code.toLowerCase().includes(q) ||
        c.product_name.toLowerCase().includes(q) ||
        (c.gs_no && c.gs_no.toLowerCase().includes(q)),
    );
  }, [candidateLots, searchQuery]);

  const toggleSelectLot = (lot: StoreIssueCandidateLot) => {
    setSelectedLots((prev) => {
      if (prev[lot.lot_id] !== undefined) {
        return Object.fromEntries(Object.entries(prev).filter(([id]) => id !== lot.lot_id));
      }
      return { ...prev, [lot.lot_id]: lot.available_qty };
    });
  };

  const updateLotQty = (lotId: string, maxQty: number, val: number) => {
    const safeQty = Math.max(1, Math.min(maxQty, val));
    setSelectedLots((prev) => ({
      ...prev,
      [lotId]: safeQty,
    }));
  };

  const selectedCount = Object.keys(selectedLots).length;
  const totalIssueQty = Object.values(selectedLots).reduce((sum, q) => sum + q, 0);

  const handleCreateIssue = async () => {
    if (selectedCount === 0) return;
    setSubmitting(true);
    setActionError(null);
    setActionSuccess(null);

    try {
      const lines = Object.entries(selectedLots).map(([lot_id, qty]) => ({
        lot_id,
        qty,
      }));

      const res = await storeIssueApi.createStoreIssue({
        issue_type_code: 'ISSUE_MAIN_STORE',
        notes: notes.trim() || undefined,
        lines,
      });

      setActionSuccess(
        `Store Issue ${res.issue_no} created successfully (${String(res.total_qty)} pcs).`,
      );
      setSelectedLots({});
      setNotes('');
      reloadCandidates();
      reloadRegister();
    } catch (err) {
      setActionError(toApiError(err).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 p-4 md:p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b pb-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Package className="w-6 h-6 text-primary" />
            Intermediate Store: Main Store Issue
          </h1>
          <p className="text-xs sm:text-sm text-muted-foreground mt-0.5">
            Sahil issues functional (Good / Repaired) returned stock to Main Store custody
          </p>
        </div>

        {/* Tab switchers */}
        <div className="flex items-center gap-2 bg-muted p-1 rounded-lg">
          <Button
            variant={activeTab === 'candidate' ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => {
              setActiveTab('candidate');
            }}
            className="text-xs sm:text-sm"
          >
            Issue Functional Stock
          </Button>
          <Button
            variant={activeTab === 'register' ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => {
              setActiveTab('register');
            }}
            className="text-xs sm:text-sm"
          >
            Issue Register ({issuesList?.length || 0})
          </Button>
        </div>
      </div>

      {/* Action alerts */}
      {actionSuccess && (
        <div className="p-4 rounded-lg bg-emerald-50/70 border border-emerald-200 text-emerald-900 dark:bg-emerald-950/20 dark:border-emerald-900/50 dark:text-emerald-300 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            <span className="text-sm font-medium">{actionSuccess}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setActionSuccess(null);
            }}
            className="h-7 text-xs"
          >
            Dismiss
          </Button>
        </div>
      )}

      {actionError && (
        <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-5 h-5" />
            <span className="text-sm font-medium">{actionError}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setActionError(null);
            }}
            className="h-7 text-xs"
          >
            Dismiss
          </Button>
        </div>
      )}

      {/* TAB 1: Candidate Lots for Issue */}
      {activeTab === 'candidate' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="relative w-full sm:w-72">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search product code, name, GS..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                }}
                className="w-full pl-9 pr-3 py-1.5 text-sm rounded-md border border-input bg-background"
              />
            </div>
            <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
              <Button
                variant="outline"
                size="sm"
                onClick={reloadCandidates}
                className="gap-1.5 text-xs"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Refresh
              </Button>
            </div>
          </div>

          {loadingCandidates ? (
            <LoadingState label="Loading available functional stock..." />
          ) : candidateError ? (
            <ErrorState
              title="Failed to load candidate lots"
              error={{ message: candidateError.message }}
              onRetry={reloadCandidates}
            />
          ) : filteredCandidates.length === 0 ? (
            <div className="p-12 text-center border rounded-lg bg-card text-muted-foreground space-y-2">
              <Package className="w-10 h-10 mx-auto stroke-1 text-muted-foreground" />
              <div className="font-semibold text-foreground">No Functional Stock Pending Issue</div>
              <p className="text-xs max-w-sm mx-auto">
                All functional stock in Intermediate Store has already been issued or dispatched.
              </p>
            </div>
          ) : (
            <div className="border rounded-lg overflow-hidden bg-card shadow-sm">
              <table className="w-full text-left text-xs sm:text-sm border-collapse">
                <thead>
                  <tr className="bg-muted/50 border-b">
                    <th className="p-3 w-10 text-center">
                      <input
                        type="checkbox"
                        checked={
                          filteredCandidates.length > 0 &&
                          filteredCandidates.every((c) => selectedLots[c.lot_id] !== undefined)
                        }
                        onChange={(e) => {
                          if (e.target.checked) {
                            const all: Record<string, number> = {};
                            filteredCandidates.forEach((c) => {
                              all[c.lot_id] = c.available_qty;
                            });
                            setSelectedLots(all);
                          } else {
                            setSelectedLots({});
                          }
                        }}
                        className="rounded border-input"
                      />
                    </th>
                    <th className="p-3 font-semibold text-muted-foreground">Product</th>
                    <th className="p-3 font-semibold text-muted-foreground">Condition</th>
                    <th className="p-3 font-semibold text-muted-foreground">Source GS</th>
                    <th className="p-3 font-semibold text-muted-foreground text-right">
                      Available
                    </th>
                    <th className="p-3 font-semibold text-muted-foreground text-right w-36">
                      Issue Qty
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filteredCandidates.map((lot) => {
                    const isSelected = selectedLots[lot.lot_id] !== undefined;
                    const issueQty = selectedLots[lot.lot_id] || lot.available_qty;

                    return (
                      <tr
                        key={lot.lot_id}
                        className={`transition-colors hover:bg-muted/20 ${
                          isSelected ? 'bg-primary/5 dark:bg-primary/10' : ''
                        }`}
                      >
                        <td className="p-3 text-center">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => {
                              toggleSelectLot(lot);
                            }}
                            className="rounded border-input"
                          />
                        </td>
                        <td className="p-3">
                          <div className="font-semibold text-foreground">{lot.product_name}</div>
                          <div className="font-mono text-xs text-muted-foreground">
                            {lot.product_code}
                          </div>
                        </td>
                        <td className="p-3">
                          <Badge
                            variant={
                              lot.condition_class === 'FUNCTIONAL_GOOD' ? 'success' : 'neutral'
                            }
                            className="text-xs"
                          >
                            {lot.condition_class === 'FUNCTIONAL_GOOD'
                              ? 'Good / Fresh'
                              : 'Repaired'}
                          </Badge>
                        </td>
                        <td className="p-3 font-mono text-xs text-muted-foreground">
                          {lot.gs_no || '—'}
                        </td>
                        <td className="p-3 text-right font-mono font-semibold">
                          {lot.available_qty}
                        </td>
                        <td className="p-3 text-right">
                          <input
                            type="number"
                            min={1}
                            max={lot.available_qty}
                            value={issueQty}
                            disabled={!isSelected}
                            onChange={(e) => {
                              updateLotQty(
                                lot.lot_id,
                                lot.available_qty,
                                parseInt(e.target.value) || 1,
                              );
                            }}
                            className="w-20 p-1 text-right text-xs rounded border border-input bg-background font-mono font-bold disabled:opacity-50"
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {/* Action Bar Footer */}
              <div className="p-4 bg-muted/40 border-t flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="text-xs sm:text-sm">
                    Selected: <strong className="text-foreground">{selectedCount}</strong> lot(s) •
                    Total: <strong className="text-foreground font-mono">{totalIssueQty}</strong>{' '}
                    pcs
                  </div>
                  <input
                    type="text"
                    placeholder="Issue notes / remarks (optional)..."
                    value={notes}
                    onChange={(e) => {
                      setNotes(e.target.value);
                    }}
                    className="text-xs p-1.5 rounded border border-input bg-background w-64"
                  />
                </div>

                <Button
                  size="sm"
                  disabled={selectedCount === 0 || submitting}
                  onClick={() => void handleCreateIssue()}
                  className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
                >
                  <ArrowRight className="w-4 h-4" />
                  {submitting ? 'Issuing...' : `Issue ${String(totalIssueQty)} Pcs to Main Store`}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: Issues Register */}
      {activeTab === 'register' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Past Store Issue Notes
            </h2>
            <Button
              variant="outline"
              size="sm"
              onClick={reloadRegister}
              className="gap-1.5 text-xs"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </Button>
          </div>

          {loadingRegister ? (
            <LoadingState label="Loading store issue register..." />
          ) : registerError ? (
            <ErrorState
              title="Failed to load register"
              error={{ message: registerError.message }}
              onRetry={reloadRegister}
            />
          ) : !issuesList || issuesList.length === 0 ? (
            <div className="p-12 text-center border rounded-lg bg-card text-muted-foreground">
              No store issues recorded yet.
            </div>
          ) : (
            <div className="border rounded-lg overflow-hidden bg-card shadow-sm">
              <table className="w-full text-left text-xs sm:text-sm border-collapse">
                <thead>
                  <tr className="bg-muted/50 border-b">
                    <th className="p-3 font-semibold text-muted-foreground">Issue No</th>
                    <th className="p-3 font-semibold text-muted-foreground">Date</th>
                    <th className="p-3 font-semibold text-muted-foreground">From → To</th>
                    <th className="p-3 font-semibold text-muted-foreground">Issued By</th>
                    <th className="p-3 font-semibold text-muted-foreground text-right">
                      Total Pcs
                    </th>
                    <th className="p-3 font-semibold text-muted-foreground">Status</th>
                    <th className="p-3 font-semibold text-muted-foreground text-right w-28">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {issuesList.map((iss) => (
                    <tr key={iss.id} className="hover:bg-muted/10 transition-colors">
                      <td className="p-3 font-mono font-bold text-foreground">{iss.issue_no}</td>
                      <td className="p-3 text-muted-foreground">
                        {new Date(iss.created_at).toLocaleDateString()}
                      </td>
                      <td className="p-3">
                        <span className="font-medium text-foreground">
                          {iss.from_location_name}
                        </span>{' '}
                        →{' '}
                        <span className="font-medium text-foreground">{iss.to_location_name}</span>
                      </td>
                      <td className="p-3 text-muted-foreground">{iss.created_by_name}</td>
                      <td className="p-3 text-right font-mono font-bold">{iss.total_qty}</td>
                      <td className="p-3">
                        <Badge
                          variant={iss.status === 'ACKNOWLEDGED' ? 'success' : 'warning'}
                          className="text-xs"
                        >
                          {iss.status}
                        </Badge>
                      </td>
                      <td className="p-3 text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            handlePrint(iss.id);
                          }}
                          className="gap-1.5 h-7 text-xs"
                        >
                          <Printer className="w-3.5 h-3.5" />
                          Print Note
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
