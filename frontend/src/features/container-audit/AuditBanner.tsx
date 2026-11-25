import { ArrowRight, ShieldAlert } from 'lucide-react';
import { useCallback } from 'react';

import { Button } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { useApiQuery } from '@/hooks/useApiQuery';
import { apiRequest } from '@/lib/api/client';
import type { TodayAuditData } from './types';

interface BannerProps {
  onOpenAudit?: (() => void) | undefined;
}

export function AuditBanner({ onOpenAudit }: BannerProps) {
  const { status, me, can } = useAuth();
  const signedIn = status === 'signed-in';

  const isVerifier =
    Boolean(me?.profile.is_super_admin) ||
    Boolean(
      me?.roles.some((r) => r.code === 'INWARD_VERIFIER' || r.code === 'REPLACEMENT_MANAGER'),
    ) ||
    can('container_audit', 'edit');

  // Only query when the API will allow it (GET /container-audits/today needs container_audit.view);
  // otherwise every other role gets a 403 on My Work (P2-08 fix).
  if (!signedIn || !isVerifier || !can('container_audit', 'view')) {
    return null;
  }
  return <TodayAuditBanner onOpenAudit={onOpenAudit} />;
}

function TodayAuditBanner({ onOpenAudit }: BannerProps) {
  const fetcher = useCallback(() => {
    return apiRequest<TodayAuditData>('/container-audits/today');
  }, []);

  const { data } = useApiQuery<TodayAuditData>(fetcher);

  // Data not loaded, or already confirmed -> do not show banner
  if (!data || data.day.confirmed) {
    return null;
  }

  return (
    <div
      role="alert"
      className="bg-amber-500/10 border-2 border-amber-500/40 rounded-xl p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-sm"
    >
      <div className="flex items-start gap-3.5">
        <div className="w-10 h-10 rounded-lg bg-amber-500/20 text-amber-500 flex items-center justify-center shrink-0 mt-0.5">
          <ShieldAlert className="w-5 h-5" />
        </div>
        <div>
          <h3 className="font-bold text-amber-500 text-sm sm:text-base flex items-center gap-2">
            Daily DMT Container Audit Pending
          </h3>
          <p className="text-xs sm:text-sm text-foreground/80 mt-1 max-w-2xl">
            All active DMT containers must be counted and checked on a daily basis, with sellable
            packaging separated. Today's audit has not been confirmed yet.
          </p>
        </div>
      </div>

      <Button
        variant="primary"
        size="sm"
        onClick={onOpenAudit}
        className="shrink-0 font-semibold self-start sm:self-auto bg-amber-600 hover:bg-amber-500 text-white border-none"
      >
        <span>Open Daily Register</span>
        <ArrowRight className="w-4 h-4 ml-1.5" />
      </Button>
    </div>
  );
}
