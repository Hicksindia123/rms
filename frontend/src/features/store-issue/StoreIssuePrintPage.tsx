import { useCallback } from 'react';
import { ArrowLeft, Printer } from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';

import { storeIssueApi } from './api';
import type { StoreIssuePrintResponse } from './types';

interface Props {
  issueId: string;
  onBack: () => void;
}

export function StoreIssuePrintPage({ issueId, onBack }: Props) {
  const fetcher = useCallback(() => storeIssueApi.getStoreIssuePrint(issueId), [issueId]);
  const { data, loading, error, reload } = useApiQuery<StoreIssuePrintResponse>(fetcher);

  const handlePrint = () => {
    window.print();
  };

  if (loading) {
    return <LoadingState label="Loading store issue print data..." />;
  }

  if (error || !data) {
    return (
      <ErrorState
        title="Failed to load store issue note"
        error={{ message: error?.message || 'Store issue not found' }}
        onRetry={reload}
      />
    );
  }

  return (
    <div className="space-y-6 p-4 md:p-8 max-w-4xl mx-auto">
      {/* Top action bar - hidden during print */}
      <div className="flex items-center justify-between print:hidden border-b pb-4">
        <Button variant="outline" size="sm" onClick={onBack} className="gap-2">
          <ArrowLeft className="w-4 h-4" />
          Back to Store Issues
        </Button>
        <Button
          size="sm"
          onClick={handlePrint}
          className="gap-2 bg-primary text-primary-foreground"
        >
          <Printer className="w-4 h-4" />
          Print Note
        </Button>
      </div>

      {/* Printable Document Sheet */}
      <div className="bg-card text-card-foreground border rounded-lg p-6 sm:p-8 shadow-sm print:border-none print:shadow-none print:p-0">
        {/* Header */}
        <div className="border-b pb-4 mb-6 text-center space-y-1">
          <h1 className="text-2xl font-bold tracking-tight uppercase">Store Issue Note</h1>
          <p className="text-xs text-muted-foreground uppercase tracking-widest font-mono">
            Replacement Management System • Step-6 Store Return
          </p>
        </div>

        {/* Issue Details Box */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-4 rounded-lg bg-muted/30 border mb-6 text-xs sm:text-sm">
          <div>
            <div className="text-muted-foreground text-xs uppercase font-medium">Issue No</div>
            <div className="font-mono font-bold text-foreground text-sm sm:text-base">
              {data.issue_no}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground text-xs uppercase font-medium">Date & Time</div>
            <div className="font-medium text-foreground">{data.issue_date}</div>
          </div>
          <div>
            <div className="text-muted-foreground text-xs uppercase font-medium">From Location</div>
            <div className="font-medium text-foreground">{data.from_location}</div>
          </div>
          <div>
            <div className="text-muted-foreground text-xs uppercase font-medium">To Location</div>
            <div className="font-medium text-foreground">{data.to_location}</div>
          </div>
        </div>

        {/* Line Items Table */}
        <div className="border rounded-lg overflow-hidden mb-6">
          <table className="w-full text-left text-xs sm:text-sm border-collapse">
            <thead>
              <tr className="bg-muted/50 border-b">
                <th className="p-3 font-semibold text-muted-foreground w-12 text-center">#</th>
                <th className="p-3 font-semibold text-muted-foreground">Product Code</th>
                <th className="p-3 font-semibold text-muted-foreground">Product Description</th>
                <th className="p-3 font-semibold text-muted-foreground">Condition</th>
                <th className="p-3 font-semibold text-muted-foreground">Source GS</th>
                <th className="p-3 font-semibold text-muted-foreground text-right w-24">
                  Qty (Pcs)
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.lines.map((line) => (
                <tr key={line.line_no} className="hover:bg-muted/10">
                  <td className="p-3 text-center text-muted-foreground">{line.line_no}</td>
                  <td className="p-3 font-mono font-medium">{line.product_code}</td>
                  <td className="p-3 font-medium">{line.product_name}</td>
                  <td className="p-3">
                    <Badge variant="neutral" className="text-xs">
                      {line.condition_class}
                    </Badge>
                  </td>
                  <td className="p-3 font-mono text-xs text-muted-foreground">
                    {line.gs_no || '—'}
                  </td>
                  <td className="p-3 text-right font-bold font-mono">{line.qty}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-muted/30 border-t font-semibold">
                <td colSpan={5} className="p-3 text-right uppercase text-xs tracking-wider">
                  Total Issued Quantity:
                </td>
                <td className="p-3 text-right font-mono font-bold text-sm text-foreground">
                  {data.total_qty} pcs
                </td>
              </tr>
            </tfoot>
          </table>
        </div>

        {/* Notes */}
        {data.notes && (
          <div className="mb-8 p-3 rounded bg-muted/20 border text-xs text-muted-foreground">
            <strong className="text-foreground">Remarks:</strong> {data.notes}
          </div>
        )}

        {/* Signatures */}
        <div className="grid grid-cols-2 gap-8 pt-12 border-t mt-12 text-xs sm:text-sm">
          {data.signature_blocks.map((sig, idx) => (
            <div key={idx} className="space-y-4">
              <div className="border-b border-dashed pb-2 font-semibold text-foreground">
                {sig.name}
              </div>
              <div className="space-y-0.5 text-xs text-muted-foreground">
                <div className="font-medium text-foreground">{sig.label}</div>
                <div>{sig.role}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
