import { useCallback } from 'react';
import { ArrowLeft, Printer } from 'lucide-react';

import { Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';

import { creditNotesApi } from './api';
import type { CreditNotePrint } from './types';

/** Decimal fields arrive as JSON strings (Pydantic v2 Decimal), so coerce at runtime. */
const toNum = (v: number | string): number => Number(v);

interface Props {
  cnId: string;
  onBack: () => void;
}

export function CreditNotePrintPage({ cnId, onBack }: Props) {
  const fetcher = useCallback(() => creditNotesApi.getPrint(cnId), [cnId]);
  const { data, loading, error, reload } = useApiQuery<CreditNotePrint>(fetcher);

  if (loading) {
    return <LoadingState label="Preparing Credit Note print view..." />;
  }

  if (error || !data) {
    return (
      <ErrorState
        title="Failed to load Credit Note print view"
        error={{ message: error?.message || 'Credit note data not found' }}
        onRetry={reload}
      />
    );
  }

  const handlePrint = () => {
    window.print();
  };

  const hasIgst = data.is_inter_state || toNum(data.igst_amount) > 0;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 p-4 md:p-8 print:p-0 print:bg-white text-slate-900">
      {/* Top action bar - hidden during print */}
      <div className="no-print max-w-4xl mx-auto mb-6 flex items-center justify-between">
        <Button variant="outline" size="sm" onClick={onBack} className="gap-2">
          <ArrowLeft className="w-4 h-4" />
          Back to Workspace
        </Button>
        <Button
          size="sm"
          onClick={handlePrint}
          className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
        >
          <Printer className="w-4 h-4" />
          Print / Save PDF
        </Button>
      </div>

      {/* Printable Sheet */}
      <div
        className="max-w-4xl mx-auto bg-white border border-slate-300 shadow-sm print:border-none print:shadow-none p-8 md:p-10 font-sans text-xs leading-relaxed"
        style={{ minHeight: '297mm' }}
      >
        {/* Header */}
        <div className="border-b-2 border-slate-800 pb-4 mb-6">
          <div className="flex justify-between items-start">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-slate-900 uppercase">
                REPLACEMENT MANAGEMENT SYSTEM
              </h1>
              <div className="text-slate-600 mt-1 space-y-0.5">
                <div>Central Commercial & Warehouse Facility</div>
                <div>New Delhi, India</div>
                <div className="font-mono font-semibold">GSTIN: 07AABCR1234F1Z5</div>
              </div>
            </div>

            <div className="text-right">
              <div className="inline-block px-3 py-1 bg-slate-900 text-white font-bold text-sm uppercase tracking-wider rounded">
                {data.voucher_type_name || data.cn_type_label}
              </div>
              <div className="mt-2 space-y-0.5 font-mono">
                <div>
                  <span className="text-slate-500 font-sans">Voucher No: </span>
                  <span className="font-bold text-slate-900">{data.voucher_no}</span>
                </div>
                <div>
                  <span className="text-slate-500 font-sans">Date: </span>
                  <span>{data.voucher_date}</span>
                </div>
                <div>
                  <span className="text-slate-500 font-sans">GS Ref: </span>
                  <span>{data.gs_no}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Party Details & Document References */}
        <div className="grid grid-cols-2 gap-6 mb-6">
          {/* Party Box */}
          <div className="border border-slate-300 rounded p-3 bg-slate-50/50">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">
              Customer / Party Details (Bill To)
            </div>
            <div className="font-bold text-sm text-slate-900">{data.party_name}</div>
            <div className="text-slate-600 mt-1 space-y-0.5">
              <div>Station: {data.party_station || 'N/A'}</div>
              <div>State: {data.party_state || 'N/A'}</div>
              <div className="font-mono font-semibold">
                GSTIN: {data.party_gstin || 'Unregistered / Not Provided'}
              </div>
            </div>
          </div>

          {/* Reference Box */}
          <div className="border border-slate-300 rounded p-3 bg-slate-50/50">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">
              Compliance & Verification References
            </div>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-slate-500">Party Document:</span>
                <span className="font-mono font-medium">
                  {data.party_doc_type
                    ? `${data.party_doc_type}: ${data.party_doc_no || 'N/A'}`
                    : 'None'}
                </span>
              </div>
              {data.party_doc_date && (
                <div className="flex justify-between">
                  <span className="text-slate-500">Party Doc Date:</span>
                  <span className="font-mono">{data.party_doc_date}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-slate-500">GST Portal Status:</span>
                <span className="font-semibold text-slate-800">
                  {data.gst_portal_status || 'N/A'}
                </span>
              </div>
              {data.gst_return_period && (
                <div className="flex justify-between">
                  <span className="text-slate-500">GST Return Period:</span>
                  <span className="font-mono">{data.gst_return_period}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Line Items Table */}
        <div className="mb-6">
          <table className="w-full border-collapse border border-slate-300 text-left">
            <thead>
              <tr className="bg-slate-100 text-[10px] uppercase tracking-wider text-slate-700">
                <th className="border border-slate-300 p-2 text-center w-8">#</th>
                <th className="border border-slate-300 p-2">Item Description / SKU</th>
                <th className="border border-slate-300 p-2 text-right w-16">Qty</th>
                <th className="border border-slate-300 p-2 text-right w-20">Rate</th>
                <th className="border border-slate-300 p-2 text-right w-24">Taxable Value</th>
                {hasIgst ? (
                  <th className="border border-slate-300 p-2 text-right w-20">IGST</th>
                ) : (
                  <>
                    <th className="border border-slate-300 p-2 text-right w-16">CGST</th>
                    <th className="border border-slate-300 p-2 text-right w-16">SGST</th>
                  </>
                )}
                <th className="border border-slate-300 p-2 text-right w-24">Total (₹)</th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((line, idx: number) => (
                <tr key={idx} className="border-b border-slate-200">
                  <td className="border border-slate-300 p-2 text-center font-mono">
                    {line.line_no}
                  </td>
                  <td className="border border-slate-300 p-2">
                    <div className="font-semibold text-slate-900">{line.product_name}</div>
                    <div className="text-[10px] text-slate-500 font-mono">
                      Code: {line.product_code}
                    </div>
                    {line.rate_verified_doc && (
                      <div className="text-[9px] text-slate-500">Ref: {line.rate_verified_doc}</div>
                    )}
                  </td>
                  <td className="border border-slate-300 p-2 text-right font-mono font-medium">
                    {line.qty}
                  </td>
                  <td className="border border-slate-300 p-2 text-right font-mono">
                    ₹{toNum(line.rate).toFixed(2)}
                  </td>
                  <td className="border border-slate-300 p-2 text-right font-mono font-medium">
                    ₹{toNum(line.taxable_amount).toFixed(2)}
                  </td>
                  {hasIgst ? (
                    <td className="border border-slate-300 p-2 text-right font-mono">
                      ₹{toNum(line.igst_amount).toFixed(2)}
                    </td>
                  ) : (
                    <>
                      <td className="border border-slate-300 p-2 text-right font-mono">
                        ₹{toNum(line.cgst_amount).toFixed(2)}
                      </td>
                      <td className="border border-slate-300 p-2 text-right font-mono">
                        ₹{toNum(line.sgst_amount).toFixed(2)}
                      </td>
                    </>
                  )}
                  <td className="border border-slate-300 p-2 text-right font-mono font-bold text-slate-900">
                    ₹{toNum(line.total_amount).toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Valuation & Totals Breakdown */}
        <div className="flex justify-end mb-8">
          <div className="w-72 border border-slate-300 rounded p-3 space-y-1.5 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-600">Taxable Value:</span>
              <span className="font-mono font-medium">₹{toNum(data.taxable_value).toFixed(2)}</span>
            </div>
            {hasIgst ? (
              <div className="flex justify-between">
                <span className="text-slate-600">IGST Amount:</span>
                <span className="font-mono">₹{toNum(data.igst_amount).toFixed(2)}</span>
              </div>
            ) : (
              <>
                <div className="flex justify-between">
                  <span className="text-slate-600">CGST Amount:</span>
                  <span className="font-mono">₹{toNum(data.cgst_amount).toFixed(2)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">SGST Amount:</span>
                  <span className="font-mono">₹{toNum(data.sgst_amount).toFixed(2)}</span>
                </div>
              </>
            )}
            <div className="border-t border-slate-300 pt-1.5 flex justify-between font-bold text-sm text-slate-900">
              <span>Total Value:</span>
              <span className="font-mono">₹{toNum(data.total_value).toFixed(2)}</span>
            </div>
          </div>
        </div>

        {/* Signatures */}
        <div className="pt-8 border-t border-slate-300 grid grid-cols-2 gap-8 text-center mt-auto">
          {data.signature_blocks.length >= 2 ? (
            data.signature_blocks.map((sig, sIdx) => (
              <div key={sIdx} className="space-y-12">
                <div className="text-slate-500 font-medium">{sig.label}</div>
                <div className="border-t border-dashed border-slate-400 pt-1">
                  <div className="font-bold text-slate-900">{sig.name}</div>
                  <div className="text-[10px] text-slate-500">{sig.role}</div>
                </div>
              </div>
            ))
          ) : (
            <>
              <div className="space-y-12">
                <div className="text-slate-500 font-medium">Prepared & Verified By</div>
                <div className="border-t border-dashed border-slate-400 pt-1">
                  <div className="font-bold text-slate-900">Accounts Department</div>
                  <div className="text-[10px] text-slate-500">Commercial / Accounts Signatory</div>
                </div>
              </div>
              <div className="space-y-12">
                <div className="text-slate-500 font-medium">Authorised Signatory</div>
                <div className="border-t border-dashed border-slate-400 pt-1">
                  <div className="font-bold text-slate-900">Commercial Authority</div>
                  <div className="text-[10px] text-slate-500">Replacement Management System</div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
