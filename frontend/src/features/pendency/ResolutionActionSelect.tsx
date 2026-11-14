import { useCallback } from 'react';

import { ErrorState, LoadingState, Select } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { rmActionsApi } from '@/features/rm-actions/api';
import type { RmActionsResponse } from '@/features/rm-actions/types';

interface Props {
  id: string;
  gsId: string;
  value: string;
  onChange: (code: string) => void;
}

/**
 * Resolution choices for clearing a pendency: the RM item actions (WF r6) with their DB labels,
 * minus Pending (BP) itself. Codes and labels come from the RM_ITEM_ACTION option set (rule e).
 */
export function ResolutionActionSelect({ id, gsId, value, onChange }: Props) {
  const fetcher = useCallback(() => rmActionsApi.getActions(gsId), [gsId]);
  const { data, error, loading, reload } = useApiQuery<RmActionsResponse>(fetcher);

  if (error) {
    return <ErrorState title="Could not load resolution actions" error={error} onRetry={reload} />;
  }
  if (loading || !data) {
    return <LoadingState label="Loading resolution actions…" />;
  }
  const options = data.options
    .filter((o) => o.code !== 'PENDING_BP')
    .map((o) => ({ value: o.code, label: o.label }));
  return (
    <Select
      id={id}
      value={value}
      onChange={(e) => {
        onChange(e.target.value);
      }}
      options={options}
    />
  );
}
