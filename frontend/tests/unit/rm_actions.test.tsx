import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { RmSegregationPage } from '@/features/rm-actions/RmSegregationPage';
import { ReplacementSlipPrintPage } from '@/features/rm-actions/ReplacementSlipPrintPage';
import { PendencyRegisterPage } from '@/features/pendency/PendencyRegisterPage';
import { PendencyTab } from '@/features/pendency/PendencyTab';
import { rmActionsApi } from '@/features/rm-actions/api';
import { pendencyApi } from '@/features/pendency/api';
import type { RmActionsResponse, ReplacementSlipResponse } from '@/features/rm-actions/types';
import type { PendencyItem } from '@/features/pendency/types';

vi.mock('@/features/rm-actions/api');
vi.mock('@/features/pendency/api');
vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({
    status: 'signed-in',
    me: {
      profile: {
        id: '11111111-1111-1111-1111-111111111111',
        email: 'pratham@hicks.co.in',
        full_name: 'Pratham Saxena',
        is_super_admin: false,
      },
      roles: [{ code: 'REPLACEMENT_MANAGER', name: 'Replacement Manager' }],
      permissions: [],
      step_codes: ['S1A_RM_ACTION'],
    },
    hasRole: (r: string) => r === 'REPLACEMENT_MANAGER',
    can: () => true,
    signIn: vi.fn(),
    signOut: vi.fn(),
    reloadMe: vi.fn(),
  }),
}));

const mockRmActionsData: RmActionsResponse = {
  gs_id: 'gs-1234',
  gs_no: 'GS-202611-001',
  status: 'RM_REVIEW',
  current_step_code: 'S1A_RM_ACTION',
  current_revision_no: 1,
  has_open_pendency: false,
  can_revise: true,
  requires_reason_for_revision: false,
  lines: [
    {
      gs_item_id: 'item-1',
      line_no: 1,
      product_id: 'prod-1',
      product_code: 'DMT-01',
      product_name: 'Digital Clinical Thermometer',
      received_qty: 10,
      allowed_qty: 8,
      not_allowed_qty: 2,
      allocations: [
        {
          condition_code: 'DMT_GOOD',
          condition_label: 'Good Condition',
          qty: 8,
          allowed_status: 'ALLOWED',
        },
        {
          condition_code: 'DMT_BROKEN_BODY',
          condition_label: 'Broken Body',
          qty: 2,
          allowed_status: 'NOT_ALLOWED',
        },
      ],
      rejections: [
        {
          condition_code: 'DMT_BROKEN_BODY',
          condition_label: 'Broken Body',
          qty: 2,
          reason: 'Damage during transit',
        },
      ],
      current_actions: [
        { action_code: 'NOT_ALLOWED', label: 'Not Allowed', qty: 2 },
        { action_code: 'SEND_NEW', label: 'Send New', qty: 8 },
      ],
      pending_qty: 0,
    },
  ],
  revision_history: [
    {
      revision_no: 1,
      decided_by: '11111111-1111-1111-1111-111111111111',
      decided_by_name: 'Pratham Saxena',
      decided_at: '2026-11-03T10:00:00Z',
      reason: null,
      lines: [],
    },
  ],
  options: [
    { code: 'SEND_NEW', label: 'Send New', allowed_status: 'ALLOWED', sort_order: 10 },
    { code: 'SEND_REPAIRED', label: 'Send Repaired', allowed_status: 'ALLOWED', sort_order: 20 },
    { code: 'ISSUE_CN', label: 'Issue CN', allowed_status: 'ALLOWED', sort_order: 30 },
    { code: 'NOT_ALLOWED', label: 'Not Allowed', allowed_status: 'NOT_ALLOWED', sort_order: 40 },
    { code: 'PENDING_BP', label: 'Pending (BP)', allowed_status: 'ALLOWED', sort_order: 50 },
  ],
};

const mockReplacementSlipData: ReplacementSlipResponse = {
  gs_id: 'gs-1234',
  gs_no: 'GS-202611-001',
  party_name: 'Apollo Pharmacy Ltd',
  party_code: 'APOLLO-DEL',
  station_name: 'New Delhi',
  state_name: 'Delhi',
  date: '2026-11-03',
  revision_no: 1,
  rm_name: 'Pratham Saxena',
  prepared_by: 'Aman Inward',
  print_count: 1,
  is_reprint: false,
  watermark: null,
  signature_blocks: [
    { label: 'Prepared By', role: 'Inward Verifier', name: 'Aman Inward' },
    { label: 'Replacement Manager', role: 'Replacement Manager', name: 'Pratham Saxena' },
    { label: 'Store Incharge / Dispatch', role: 'Store Incharge', name: '' },
  ],
  lines: [
    {
      line_no: 1,
      product_code: 'DMT-01',
      product_name: 'Digital Clinical Thermometer',
      received_qty: 10,
      send_new_qty: 8,
      send_repaired_qty: 0,
      issue_cn_qty: 0,
      not_allowed_qty: 2,
      pending_bp_qty: 0,
      rejected_qty: 2,
      rejection_reasons: ['Damage during transit'],
      pending_qty: 0,
      remarks: null,
    },
  ],
  totals: {
    received_qty: 10,
    send_new_qty: 8,
    send_repaired_qty: 0,
    issue_cn_qty: 0,
    not_allowed_qty: 2,
    pending_bp_qty: 0,
  },
  layout: { header_title: 'Template Header Title', header_subtitle: 'Template Slip Subtitle' },
};

const mockPendencyItems: PendencyItem[] = [
  {
    id: 'pend-1',
    gs_id: 'gs-1234',
    gs_no: 'GS-202611-001',
    party_name: 'Apollo Pharmacy Ltd',
    gs_item_id: 'item-1',
    line_no: 1,
    product_name: 'Digital Clinical Thermometer',
    qty: 3,
    reason: 'Sent to technical repair team for diagnosis',
    sent_to: 'Repair Team',
    blocks_gs: false,
    status: 'OPEN',
    opened_by: '11111111-1111-1111-1111-111111111111',
    opened_by_name: 'Pratham Saxena',
    opened_at: '2026-11-03T09:00:00Z',
    age_days: 0,
    age_hours: 2,
  },
];

describe('Step-3 a) RM Actions & Replacement Slip (P2-07)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('RmSegregationPage', () => {
    it('renders segregation page with reconciliation and pre-filled quantities', async () => {
      vi.mocked(rmActionsApi.getActions).mockResolvedValue(mockRmActionsData);

      render(<RmSegregationPage gsId="gs-1234" onBack={vi.fn()} onOpenSlip={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText('RM Item Segregation')).toBeInTheDocument();
      });

      expect(screen.getByText(/GS-202611-001/)).toBeInTheDocument();
      expect(screen.getByText('Digital Clinical Thermometer')).toBeInTheDocument();
      expect(screen.getByText(/Line total:/)).toBeInTheDocument();
      expect(screen.getByText(/Locked: 2 rejected at inspection/)).toBeInTheDocument();
    });

    it('enables finalisation when fully reconciled', async () => {
      vi.mocked(rmActionsApi.getActions).mockResolvedValue(mockRmActionsData);

      render(<RmSegregationPage gsId="gs-1234" onBack={vi.fn()} onOpenSlip={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText('RM Item Segregation')).toBeInTheDocument();
      });

      const finaliseBtn = screen.getByRole('button', { name: /Finalise & Advance/i });
      expect(finaliseBtn).toBeEnabled();
    });

    it('shows unlock override modal for not allowed reallocations (DEC-33)', async () => {
      vi.mocked(rmActionsApi.getActions).mockResolvedValue(mockRmActionsData);

      render(<RmSegregationPage gsId="gs-1234" onBack={vi.fn()} onOpenSlip={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText('RM Item Segregation')).toBeInTheDocument();
      });

      const unlockBtn = screen.getByRole('button', { name: /Unlock with RM Override/i });
      fireEvent.click(unlockBtn);

      expect(screen.getByText('Override Inspection Rejections (DEC-33)')).toBeInTheDocument();
      expect(
        screen.getByPlaceholderText(/e\.g\. Verified commercial goodwill approval/i),
      ).toBeInTheDocument();
    });
  });

  describe('ReplacementSlipPrintPage', () => {
    it('renders A4 replacement slip with company header and totals', async () => {
      vi.mocked(rmActionsApi.getReplacementSlip).mockResolvedValue(mockReplacementSlipData);

      render(<ReplacementSlipPrintPage gsId="gs-1234" onBack={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText('Template Header Title')).toBeInTheDocument();
      });

      expect(screen.getByText('Template Slip Subtitle')).toBeInTheDocument();
      expect(screen.getByText(/Apollo Pharmacy Ltd/)).toBeInTheDocument();
      expect(screen.getByText('DMT-01')).toBeInTheDocument();
      expect(screen.getByText('Print / Save as PDF')).toBeInTheDocument();
      expect(screen.getByText('Original')).toBeInTheDocument();
    });

    it('renders watermark on re-print', async () => {
      vi.mocked(rmActionsApi.getReplacementSlip).mockResolvedValue({
        ...mockReplacementSlipData,
        print_count: 2,
        is_reprint: true,
        watermark: 'REPRINT #2',
      });

      render(<ReplacementSlipPrintPage gsId="gs-1234" onBack={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText('REPRINT #2')).toBeInTheDocument();
      });

      expect(screen.getByText('Reprint #2')).toBeInTheDocument();
    });
  });

  describe('Pendency Register & Tab', () => {
    it('renders PendencyTab with open pendency and clear button', async () => {
      vi.mocked(pendencyApi.listPendencies).mockResolvedValue(mockPendencyItems);

      render(<PendencyTab gsId="gs-1234" />);

      await waitFor(() => {
        expect(screen.getByText('1 Open Pendency (BP)')).toBeInTheDocument();
      });

      expect(screen.getByText('Sent to technical repair team for diagnosis')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Clear Pendency/i })).toBeInTheDocument();
    });

    it('opens clear modal and calls clearPendency API', async () => {
      vi.mocked(pendencyApi.listPendencies).mockResolvedValue(mockPendencyItems);
      const firstItem = mockPendencyItems[0];
      if (!firstItem) throw new Error('mockPendencyItems must not be empty');
      vi.mocked(pendencyApi.clearPendency).mockResolvedValue({
        ...firstItem,
        status: 'CLEARED',
        resolution_action: 'SEND_REPAIRED',
        clearance_notes: 'Repaired by factory team',
      });
      vi.mocked(rmActionsApi.getActions).mockResolvedValue(mockRmActionsData);

      render(<PendencyRegisterPage onOpenGs={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText('Pendency (BP) Register')).toBeInTheDocument();
      });

      const clearBtn = screen.getByRole('button', { name: /Clear Pendency/i });
      fireEvent.click(clearBtn);

      // Resolution choices come from the RM_ITEM_ACTION option set, without Pending (BP) (rule e).
      const select = await screen.findByLabelText(/Resolution Action/i);
      const offered = Array.from((select as HTMLSelectElement).options)
        .map((o) => o.value)
        .filter(Boolean); // the Select primitive's empty placeholder
      expect(offered).not.toContain('PENDING_BP');
      expect(offered).toEqual(
        mockRmActionsData.options.filter((o) => o.code !== 'PENDING_BP').map((o) => o.code),
      );
      const notesInput = screen.getByPlaceholderText(/e\.g\. Technical review complete/i);
      fireEvent.change(notesInput, { target: { value: 'Repaired by factory team' } });

      const confirmBtn = screen.getByRole('button', { name: /Confirm Clearance/i });
      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(pendencyApi.clearPendency).toHaveBeenCalledWith('pend-1', {
          resolution_action: 'SEND_REPAIRED',
          notes: 'Repaired by factory team',
        });
      });
    });
  });
});
