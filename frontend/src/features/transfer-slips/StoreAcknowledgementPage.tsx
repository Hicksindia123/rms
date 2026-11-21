/**
 * Phase P6 (DEC-66): "Acknowledge Transfer Slips" for the Intermediate Store users. The API returns
 * only the slips of the store(s) whose role the user holds; the list opens on the slips still
 * waiting for acknowledgement. A slip opens the slip view, where the store acknowledges it in full
 * or reports a discrepancy.
 */
import React, { useState } from 'react';
import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui';
import { PageHeader } from '@/components/erp';

import { SlipsTab } from './TransferSlipsPage';

interface Props {
  onOpenSlip: (id: string) => void;
}

export const StoreAcknowledgementPage: React.FC<Props> = ({ onOpenSlip }) => {
  const [key, setKey] = useState(0);
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="store-ack-page">
      <PageHeader
        title="Acknowledge Transfer Slips"
        subtitle="Transfer slips sent to your Intermediate Store. Open one, check the goods and acknowledge receipt."
        actions={
          <Button
            type="button"
            variant="outline"
            className="min-h-[44px]"
            onClick={() => {
              setKey((k) => k + 1);
            }}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />
      <SlipsTab key={key} onOpenSlip={onOpenSlip} initialStatus="GENERATED" />
    </div>
  );
};
