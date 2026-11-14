import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { rmActionsApi } from '@/features/rm-actions/api';
import { ResolutionBoardPage } from '@/features/rm-actions/ResolutionBoardPage';
import type { ResolutionBoardResponse } from '@/features/rm-actions/types';
import { storeIssueApi } from '@/features/store-issue/api';
import { StoreIssuePage } from '@/features/store-issue/StoreIssuePage';
import { StoreIssuePrintPage } from '@/features/store-issue/StoreIssuePrintPage';
import type {
  StoreIssue,
  StoreIssueCandidateLot,
  StoreIssuePrintResponse,
} from '@/features/store-issue/types';
import { dispatchApi } from '@/features/dispatch/api';
import { DispatchQueuePage } from '@/features/dispatch/DispatchQueuePage';
import type { DispatchCandidateLot, DispatchQueueItem } from '@/features/dispatch/types';

vi.mock('@/features/rm-actions/api');
vi.mock('@/features/store-issue/api');
vi.mock('@/features/dispatch/api');

const mockResolutionData: ResolutionBoardResponse = {
  gs_id: 'gs-1',
  gs_no: 'GS-2026-0001',
  status: 'IN_PROCESS',
  current_revision_no: 1,
  summary_notes: [
    'Line 1: Planned 3 SEND_REPAIRED pcs, but 0 were repaired. Suggestion: revise to SEND_NEW or CREDIT_NOTE.',
  ],
  lines: [
    {
      gs_item_id: 'item-1',
      line_no: 1,
      product_id: 'prod-1',
      product_code: 'FAN-01',
      product_name: 'Ceiling Fan',
      received_qty: 10,
      current_actions: [
        { action_code: 'SEND_REPAIRED', label: 'Send Repaired', qty: 3 },
        { action_code: 'SEND_NEW', label: 'Send New', qty: 4 },
        { action_code: 'NOT_ALLOWED', label: 'Not Allowed', qty: 3 },
      ],
      outcomes: {
        functional_good_qty: 4,
        functional_repaired_qty: 0,
        non_good_qty: 3,
        non_sellable_qty: 0,
        rejected_qty: 3,
      },
      dispatched: {
        dispatched_new_qty: 0,
        dispatched_repaired_qty: 0,
        issued_main_store_qty: 0,
      },
      has_mismatch: true,
      suggested_adjustments: [
        'Planned 3 SEND_REPAIRED pcs, but 0 repaired available. Suggestion: revise to SEND_NEW or CREDIT_NOTE.',
      ],
    },
  ],
};

const mockCandidateLots: StoreIssueCandidateLot[] = [
  {
    lot_id: 'lot-fg-1',
    stock_item_id: 'si-1',
    product_id: 'p-1',
    product_code: 'FAN-01',
    product_name: 'Ceiling Fan',
    condition_class: 'FUNCTIONAL_GOOD',
    available_qty: 4,
    gs_id: 'gs-1',
    gs_no: 'GS-2026-0001',
  },
  {
    lot_id: 'lot-fr-1',
    stock_item_id: 'si-2',
    product_id: 'p-2',
    product_code: 'ROD-01',
    product_name: 'Fan Rod',
    condition_class: 'FUNCTIONAL_REPAIRED',
    available_qty: 2,
    gs_id: 'gs-1',
    gs_no: 'GS-2026-0001',
  },
];

const mockStoreIssues: StoreIssue[] = [
  {
    id: 'issue-1',
    issue_no: 'SI/2026-27/00001',
    issue_type_code: 'ISSUE_MAIN_STORE',
    from_location_id: 'loc-1',
    from_location_name: 'Intermediate Store',
    to_location_id: 'loc-2',
    to_location_name: 'Main Store',
    status: 'ACKNOWLEDGED',
    total_qty: 6,
    created_at: '2026-11-05T10:00:00Z',
    created_by: 'user-1',
    created_by_name: 'Sahil',
    lines: [],
  },
];

const mockStoreIssuePrint: StoreIssuePrintResponse = {
  issue_no: 'SI/2026-27/00001',
  issue_type_code: 'ISSUE_MAIN_STORE',
  issue_date: '05/11/2026 10:00 AM',
  from_location: 'Intermediate Store',
  to_location: 'Main Store',
  status: 'ACKNOWLEDGED',
  notes: 'Issued post technician servicing',
  issued_by_name: 'Sahil',
  acknowledged_by_name: 'Main Store Keeper',
  total_qty: 6,
  signature_blocks: [
    {
      label: 'Issued By (Intermediate Store)',
      name: 'Sahil',
      role: 'Intermediate Store Manager',
    },
    {
      label: 'Acknowledged / Received By (Main Store)',
      name: 'Main Store Keeper',
      role: 'Main Store Keeper',
    },
  ],
  lines: [
    {
      line_no: 1,
      product_code: 'FAN-01',
      product_name: 'Ceiling Fan',
      condition_class: 'FUNCTIONAL_GOOD',
      gs_no: 'GS-2026-0001',
      qty: 4,
    },
    {
      line_no: 2,
      product_code: 'ROD-01',
      product_name: 'Fan Rod',
      condition_class: 'FUNCTIONAL_REPAIRED',
      gs_no: 'GS-2026-0001',
      qty: 2,
    },
  ],
};

const mockQueueItems: DispatchQueueItem[] = [
  {
    gs_id: 'gs-1',
    gs_no: 'GS-2026-0001',
    party_id: 'pty-1',
    party_name: 'Test Dealer',
    gs_item_id: 'item-1',
    line_no: 1,
    product_id: 'p-1',
    product_code: 'FAN-01',
    product_name: 'Ceiling Fan',
    action_code: 'SEND_NEW',
    planned_qty: 4,
    dispatched_qty: 0,
    pending_qty: 4,
    available_repaired_qty: 0,
  },
  {
    gs_id: 'gs-1',
    gs_no: 'GS-2026-0001',
    party_id: 'pty-1',
    party_name: 'Test Dealer',
    gs_item_id: 'item-1',
    line_no: 1,
    product_id: 'p-1',
    product_code: 'FAN-01',
    product_name: 'Ceiling Fan',
    action_code: 'SEND_REPAIRED',
    planned_qty: 3,
    dispatched_qty: 0,
    pending_qty: 3,
    available_repaired_qty: 3,
  },
];

const mockDispatchCandidateLots: DispatchCandidateLot[] = [
  {
    lot_id: 'lot-fr-1',
    stock_item_id: 'si-1',
    product_id: 'p-1',
    product_code: 'FAN-01',
    product_name: 'Ceiling Fan',
    location_id: 'loc-1',
    location_code: 'INTERMEDIATE_STORE',
    condition_class: 'FUNCTIONAL_REPAIRED',
    available_qty: 3,
    gs_id: 'gs-1',
    gs_no: 'GS-2026-0001',
  },
];

describe('P3-05 Store Issue, Replacement Dispatch, and Resolution Board', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('ResolutionBoardPage', () => {
    it('renders planned RM allocations vs servicing outcomes and mismatch alert', async () => {
      vi.mocked(rmActionsApi.getResolutionBoard).mockResolvedValue(mockResolutionData);
      const onBack = vi.fn();
      const onRevise = vi.fn();

      render(<ResolutionBoardPage gsId="gs-1" onBack={onBack} onRevise={onRevise} />);

      await waitFor(() => {
        expect(screen.getByText('RM Resolution Board')).toBeInTheDocument();
      });

      expect(screen.getByText('GS-2026-0001')).toBeInTheDocument();
      expect(screen.getByText(/1 Line\(s\) Require RM Revision Attention/i)).toBeInTheDocument();
      expect(
        screen.getByText(/Planned 3 SEND_REPAIRED pcs, but 0 were repaired/i),
      ).toBeInTheDocument();

      const [firstReviseBtn] = screen.getAllByRole('button', { name: /Revise/i });
      if (!firstReviseBtn) throw new Error('Revise button not rendered');
      fireEvent.click(firstReviseBtn);
      expect(onRevise).toHaveBeenCalled();
    });
  });

  describe('StoreIssuePage', () => {
    it('renders candidate functional lots and allows creating store issue to Main Store', async () => {
      vi.mocked(storeIssueApi.getCandidateLots).mockResolvedValue(mockCandidateLots);
      vi.mocked(storeIssueApi.listStoreIssues).mockResolvedValue(mockStoreIssues);
      vi.mocked(storeIssueApi.createStoreIssue).mockResolvedValue({
        id: 'issue-new',
        issue_no: 'SI/2026-27/00002',
        issue_type_code: 'ISSUE_MAIN_STORE',
        from_location_id: 'loc-1',
        from_location_name: 'Intermediate Store',
        to_location_id: 'loc-2',
        to_location_name: 'Main Store',
        status: 'ACKNOWLEDGED',
        total_qty: 4,
        created_at: '2026-11-05T10:10:00Z',
        created_by: 'user-1',
        created_by_name: 'Sahil',
        lines: [],
      });

      const onPrint = vi.fn();
      render(<StoreIssuePage onPrint={onPrint} />);

      await waitFor(() => {
        expect(screen.getByText('Intermediate Store: Main Store Issue')).toBeInTheDocument();
      });

      expect(screen.getByText('Ceiling Fan')).toBeInTheDocument();
      expect(screen.getByText('Fan Rod')).toBeInTheDocument();

      // Check the first lot checkbox
      const checkboxes = screen.getAllByRole('checkbox');
      const firstRowCheckbox = checkboxes[1]; // first item row checkbox
      if (!firstRowCheckbox) throw new Error('Lot row checkbox not rendered');
      fireEvent.click(firstRowCheckbox);

      const issueBtn = screen.getByRole('button', { name: /Issue 4 Pcs to Main Store/i });
      expect(issueBtn).not.toBeDisabled();
      fireEvent.click(issueBtn);

      await waitFor(() => {
        expect(storeIssueApi.createStoreIssue).toHaveBeenCalledWith(
          expect.objectContaining({
            issue_type_code: 'ISSUE_MAIN_STORE',
            lines: [{ lot_id: 'lot-fg-1', qty: 4 }],
          }),
        );
      });
    });
  });

  describe('StoreIssuePrintPage', () => {
    it('renders printable note with signature blocks and line details', async () => {
      vi.mocked(storeIssueApi.getStoreIssuePrint).mockResolvedValue(mockStoreIssuePrint);
      const onBack = vi.fn();

      render(<StoreIssuePrintPage issueId="issue-1" onBack={onBack} />);

      await waitFor(() => {
        expect(screen.getByText('Store Issue Note')).toBeInTheDocument();
      });

      expect(screen.getByText('SI/2026-27/00001')).toBeInTheDocument();
      expect(screen.getByText('Intermediate Store')).toBeInTheDocument();
      expect(screen.getByText('Main Store')).toBeInTheDocument();
      expect(screen.getByText('Issued By (Intermediate Store)')).toBeInTheDocument();
      expect(screen.getByText('Acknowledged / Received By (Main Store)')).toBeInTheDocument();
    });
  });

  describe('DispatchQueuePage', () => {
    it('renders replacement queue with SEND_NEW and SEND_REPAIRED items', async () => {
      vi.mocked(dispatchApi.getQueue).mockResolvedValue(mockQueueItems);
      vi.mocked(dispatchApi.listDispatches).mockResolvedValue([]);
      vi.mocked(dispatchApi.getCandidateLots).mockResolvedValue(mockDispatchCandidateLots);

      render(<DispatchQueuePage />);

      await waitFor(() => {
        expect(screen.getByText('Replacement Dispatch Queue')).toBeInTheDocument();
      });

      expect(screen.getAllByText('Test Dealer').length).toBeGreaterThan(0);
      expect(screen.getByText('SEND_NEW')).toBeInTheDocument();
      expect(screen.getByText('SEND_REPAIRED')).toBeInTheDocument();

      // Open dispatch modal for SEND_NEW (use exact button name "Dispatch" to not match "Dispatch Register")
      const [firstDispatchBtn] = screen.getAllByRole('button', { name: /^Dispatch$/i });
      if (!firstDispatchBtn) throw new Error('Dispatch button not rendered');
      fireEvent.click(firstDispatchBtn);

      await waitFor(() => {
        expect(screen.getByText(/Dispatch Replacement \(SEND_NEW\)/i)).toBeInTheDocument();
      });

      expect(screen.getByText(/Transporter \/ Courier/i)).toBeInTheDocument();
      expect(
        screen.getByText(/Dispatched from fresh Main Store stock outside the RMS/i),
      ).toBeInTheDocument();
    });
  });
});
