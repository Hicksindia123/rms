import { useCallback, useMemo, useState } from 'react';
import { CheckCircle2, RefreshCw, Search, Truck } from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';

import { dispatchApi } from './api';
import { DispatchModal } from './DispatchModal';
import type { DispatchQueueItem, ReplacementDispatch } from './types';

export function DispatchQueuePage() {
  const [activeTab, setActiveTab] = useState<'queue' | 'register'>('queue');
  const [typeFilter, setTypeFilter] = useState<'ALL' | 'SEND_NEW' | 'SEND_REPAIRED'>('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  // Queue query
  const queueFetcher = useCallback(() => dispatchApi.getQueue(), []);
  const {
    data: queueItems,
    loading: loadingQueue,
    error: queueError,
    reload: reloadQueue,
  } = useApiQuery<DispatchQueueItem[]>(queueFetcher);

  // Register query
  const registerFetcher = useCallback(() => dispatchApi.listDispatches(), []);
  const {
    data: dispatchRegister,
    loading: loadingRegister,
    error: registerError,
    reload: reloadRegister,
  } = useApiQuery<ReplacementDispatch[]>(registerFetcher);

  // Modal state
  const [selectedItem, setSelectedItem] = useState<DispatchQueueItem | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filtered queue items
  const filteredQueue = useMemo(() => {
    if (!queueItems) return [];
    return queueItems.filter((item) => {
      if (typeFilter !== 'ALL' && item.action_code !== typeFilter) return false;
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        item.gs_no.toLowerCase().includes(q) ||
        item.party_name.toLowerCase().includes(q) ||
        item.product_code.toLowerCase().includes(q) ||
        item.product_name.toLowerCase().includes(q)
      );
    });
  }, [queueItems, typeFilter, searchQuery]);

  const handleOpenDispatch = (item: DispatchQueueItem) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  const handleDispatchSuccess = (res: ReplacementDispatch) => {
    setSuccessMsg(
      `Replacement Dispatch ${res.dispatch_no} created successfully (${String(res.total_qty)} pcs via ${res.transporter})!`,
    );
    reloadQueue();
    reloadRegister();
  };

  return (
    <div className="space-y-6 p-4 md:p-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b pb-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Truck className="w-6 h-6 text-primary" />
            Replacement Dispatch Queue
          </h1>
          <p className="text-xs sm:text-sm text-muted-foreground mt-0.5">
            Dispatch fresh replacements (SEND_NEW) and serviced stock (SEND_REPAIRED) to dealers.
          </p>
        </div>

        {/* Tab switchers */}
        <div className="flex items-center gap-2 bg-muted p-1 rounded-lg">
          <Button
            variant={activeTab === 'queue' ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => {
              setActiveTab('queue');
            }}
            className="text-xs sm:text-sm"
          >
            Pending Queue ({queueItems?.length || 0})
          </Button>
          <Button
            variant={activeTab === 'register' ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => {
              setActiveTab('register');
            }}
            className="text-xs sm:text-sm"
          >
            Dispatch Register ({dispatchRegister?.length || 0})
          </Button>
        </div>
      </div>

      {/* Success banner */}
      {successMsg && (
        <div className="p-4 rounded-lg bg-emerald-50/70 border border-emerald-200 text-emerald-900 dark:bg-emerald-950/20 dark:border-emerald-900/50 dark:text-emerald-300 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            <span className="text-sm font-medium">{successMsg}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSuccessMsg(null);
            }}
            className="h-7 text-xs"
          >
            Dismiss
          </Button>
        </div>
      )}

      {/* TAB 1: Pending Queue */}
      {activeTab === 'queue' && (
        <div className="space-y-4">
          {/* Controls bar */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="flex items-center gap-2 w-full sm:w-auto">
              <div className="relative flex-1 sm:w-64">
                <Search className="w-4 h-4 absolute left-3 top-2.5 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Search GS, dealer, product..."
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                  }}
                  className="w-full pl-9 pr-3 py-1.5 text-xs sm:text-sm rounded-md border border-input bg-background"
                />
              </div>

              {/* Type filter */}
              <div className="flex items-center gap-1 bg-muted p-0.5 rounded-md">
                {(['ALL', 'SEND_NEW', 'SEND_REPAIRED'] as const).map((t) => (
                  <Button
                    key={t}
                    variant={typeFilter === t ? 'primary' : 'ghost'}
                    size="sm"
                    onClick={() => {
                      setTypeFilter(t);
                    }}
                    className="h-7 text-xs px-2"
                  >
                    {t === 'ALL' ? 'All' : t === 'SEND_NEW' ? 'Send New' : 'Send Repaired'}
                  </Button>
                ))}
              </div>
            </div>

            <Button variant="outline" size="sm" onClick={reloadQueue} className="gap-1.5 text-xs">
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </Button>
          </div>

          {loadingQueue ? (
            <LoadingState label="Loading pending dispatches..." />
          ) : queueError ? (
            <ErrorState
              title="Failed to load dispatch queue"
              error={{ message: queueError.message }}
              onRetry={reloadQueue}
            />
          ) : filteredQueue.length === 0 ? (
            <div className="p-12 text-center border rounded-lg bg-card text-muted-foreground space-y-2">
              <CheckCircle2 className="w-10 h-10 mx-auto text-emerald-500 stroke-1" />
              <div className="font-semibold text-foreground">No Pending Replacements in Queue</div>
              <p className="text-xs max-w-sm mx-auto">
                All planned replacement actions for open goods slips have been fully dispatched.
              </p>
            </div>
          ) : (
            <div className="border rounded-lg overflow-hidden bg-card shadow-sm">
              <table className="w-full text-left text-xs sm:text-sm border-collapse">
                <thead>
                  <tr className="bg-muted/50 border-b">
                    <th className="p-3 font-semibold text-muted-foreground">Goods Slip / Party</th>
                    <th className="p-3 font-semibold text-muted-foreground">Product</th>
                    <th className="p-3 font-semibold text-muted-foreground">Action Type</th>
                    <th className="p-3 font-semibold text-muted-foreground text-center">Planned</th>
                    <th className="p-3 font-semibold text-muted-foreground text-center">
                      Dispatched
                    </th>
                    <th className="p-3 font-semibold text-muted-foreground text-center">Pending</th>
                    <th className="p-3 font-semibold text-muted-foreground text-right w-28">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filteredQueue.map((item) => {
                    const isRepaired = item.action_code === 'SEND_REPAIRED';
                    return (
                      <tr
                        key={`${item.gs_item_id}:${item.action_code}`}
                        className="hover:bg-muted/10 transition-colors"
                      >
                        <td className="p-3">
                          <div className="font-mono font-bold text-foreground">{item.gs_no}</div>
                          <div className="text-xs text-muted-foreground">{item.party_name}</div>
                        </td>
                        <td className="p-3">
                          <div className="font-medium text-foreground">{item.product_name}</div>
                          <div className="font-mono text-xs text-muted-foreground">
                            {item.product_code}
                          </div>
                        </td>
                        <td className="p-3">
                          <Badge
                            variant={item.action_code === 'SEND_NEW' ? 'default' : 'neutral'}
                            className="text-xs"
                          >
                            {item.action_code}
                          </Badge>
                          {isRepaired && (
                            <div className="text-[10px] text-muted-foreground mt-0.5">
                              Repaired Stock:{' '}
                              <strong className="text-foreground">
                                {item.available_repaired_qty}
                              </strong>{' '}
                              pcs
                            </div>
                          )}
                        </td>
                        <td className="p-3 text-center font-mono">{item.planned_qty}</td>
                        <td className="p-3 text-center font-mono text-muted-foreground">
                          {item.dispatched_qty}
                        </td>
                        <td className="p-3 text-center font-mono font-bold text-primary">
                          {item.pending_qty}
                        </td>
                        <td className="p-3 text-right">
                          <Button
                            size="sm"
                            onClick={() => {
                              handleOpenDispatch(item);
                            }}
                            className="gap-1.5 h-7 text-xs bg-primary text-primary-foreground hover:bg-primary/90"
                          >
                            <Truck className="w-3.5 h-3.5" />
                            Dispatch
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: Dispatched Register */}
      {activeTab === 'register' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Dispatched Replacement Register
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
            <LoadingState label="Loading dispatch register..." />
          ) : registerError ? (
            <ErrorState
              title="Failed to load register"
              error={{ message: registerError.message }}
              onRetry={reloadRegister}
            />
          ) : !dispatchRegister || dispatchRegister.length === 0 ? (
            <div className="p-12 text-center border rounded-lg bg-card text-muted-foreground">
              No replacements dispatched yet.
            </div>
          ) : (
            <div className="border rounded-lg overflow-hidden bg-card shadow-sm">
              <table className="w-full text-left text-xs sm:text-sm border-collapse">
                <thead>
                  <tr className="bg-muted/50 border-b">
                    <th className="p-3 font-semibold text-muted-foreground">Dispatch No</th>
                    <th className="p-3 font-semibold text-muted-foreground">Date</th>
                    <th className="p-3 font-semibold text-muted-foreground">Goods Slip / Party</th>
                    <th className="p-3 font-semibold text-muted-foreground">Type</th>
                    <th className="p-3 font-semibold text-muted-foreground">
                      Transporter & Docket
                    </th>
                    <th className="p-3 font-semibold text-muted-foreground text-right">
                      Total Pcs
                    </th>
                    <th className="p-3 font-semibold text-muted-foreground">Dispatched By</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {dispatchRegister.map((d) => (
                    <tr key={d.id} className="hover:bg-muted/10 transition-colors">
                      <td className="p-3 font-mono font-bold text-foreground">{d.dispatch_no}</td>
                      <td className="p-3 text-muted-foreground">
                        {new Date(d.dispatched_at).toLocaleDateString()}
                      </td>
                      <td className="p-3">
                        <div className="font-mono text-foreground font-medium">{d.gs_no}</div>
                        <div className="text-xs text-muted-foreground">{d.party_name}</div>
                      </td>
                      <td className="p-3">
                        <Badge
                          variant={d.dispatch_type === 'SEND_NEW' ? 'default' : 'neutral'}
                          className="text-xs"
                        >
                          {d.dispatch_type}
                        </Badge>
                      </td>
                      <td className="p-3">
                        <div className="font-medium text-foreground">{d.transporter}</div>
                        {d.docket_no && (
                          <div className="text-xs font-mono text-muted-foreground">
                            Docket: {d.docket_no}
                          </div>
                        )}
                      </td>
                      <td className="p-3 text-right font-mono font-bold">{d.total_qty}</td>
                      <td className="p-3 text-muted-foreground text-xs">{d.dispatched_by_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Dispatch Modal */}
      {selectedItem && (
        <DispatchModal
          item={selectedItem}
          isOpen={isModalOpen}
          onClose={() => {
            setIsModalOpen(false);
            setSelectedItem(null);
          }}
          onSuccess={handleDispatchSuccess}
        />
      )}
    </div>
  );
}
