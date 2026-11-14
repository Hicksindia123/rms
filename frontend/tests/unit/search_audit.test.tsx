import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GlobalSearchBar } from '@/features/search/GlobalSearchBar';
import { GsActivityTab } from '@/features/goods-slips/GsActivityTab';
import { AuditExplorerPage } from '@/features/admin/audit/AuditExplorerPage';
import { searchApi } from '@/features/search/api';
import { auditApi } from '@/features/audit/api';

vi.mock('@/features/search/api', () => ({
  searchApi: {
    search: vi.fn(),
    globalSearch: vi.fn(),
  },
}));

vi.mock('@/features/audit/api', () => ({
  auditApi: {
    fetchAuditLog: vi.fn(),
    fetchAuditTables: vi.fn(),
    fetchGsActivity: vi.fn(),
    fetchUserActivity: vi.fn(),
    getAuditExportUrl: vi.fn(),
  },
}));

describe('GlobalSearchBar (P4-04)', () => {
  const onNavigate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders search input with shortcut hint', () => {
    render(<GlobalSearchBar onNavigate={onNavigate} />);
    expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
  });

  it('searches and shows grouped dropdown results on input', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({
      query: 'GS/2026',
      total: 1,
      is_qr_match: false,
      direct_route: null,
      groups: [
        {
          type: 'GOODS_SLIP',
          label: 'Goods Slips',
          count: 1,
          items: [
            {
              id: 'gs-1',
              type: 'GOODS_SLIP',
              title: 'GS/2026/00001',
              subtitle: 'ABC Electronics · DKT-100',
              badge: 'OPEN',
              route: '/gs/gs-1',
              details: {},
            },
          ],
        },
      ],
      took_ms: 12,
    });

    render(<GlobalSearchBar onNavigate={onNavigate} />);
    const input = screen.getByPlaceholderText(/search/i);
    fireEvent.change(input, { target: { value: 'GS/2026' } });

    await waitFor(() => {
      expect(screen.getByText('GS/2026/00001')).toBeInTheDocument();
      expect(screen.getByText(/ABC Electronics/)).toBeInTheDocument();
    });

    // Clicking item navigates
    fireEvent.click(screen.getByText('GS/2026/00001'));
    expect(onNavigate).toHaveBeenCalledWith('/gs/gs-1');
  });
});

describe('GsActivityTab (P4-04)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders merged activity timeline and toggles diff viewer', async () => {
    vi.mocked(auditApi.fetchGsActivity).mockResolvedValue({
      gs_id: 'gs-1',
      total: 2,
      items: [
        {
          id: 'act-1',
          category: 'STATUS',
          title: 'Status changed: GATE_INWARD → UNBOXING_PENDING',
          description: 'Inward verification completed',
          actor_id: 'user-1',
          actor_name: 'Anuj Kumar',
          at: '2026-11-06T10:00:00Z',
          step_code: 'STEP_1_INWARD',
          source_table: 'goods_slips',
          entity_id: 'gs-1',
          action: 'UPDATE',
          diffs: [
            {
              field: 'status',
              field_label: 'Status',
              old_value: 'GATE_INWARD',
              new_value: 'UNBOXING_PENDING',
            },
          ],
          metadata: {},
        },
      ],
    });

    render(<GsActivityTab gsId="gs-1" />);

    await waitFor(() => {
      expect(screen.getByText(/Status changed: GATE_INWARD/)).toBeInTheDocument();
      expect(screen.getByText('Anuj Kumar')).toBeInTheDocument();
    });

    // Expand field diffs
    const diffButton = screen.getByText(/View 1 changed field/);
    expect(diffButton).toBeInTheDocument();
    fireEvent.click(diffButton);

    expect(screen.getByText('GATE_INWARD')).toBeInTheDocument();
    expect(screen.getByText('UNBOXING_PENDING')).toBeInTheDocument();
  });
});

describe('AuditExplorerPage (P4-04)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(auditApi.fetchAuditTables).mockResolvedValue([
      'goods_slips',
      'parties',
      'credit_notes',
    ]);
    vi.mocked(auditApi.getAuditExportUrl).mockReturnValue(
      '/api/v1/audit/export?table_name=goods_slips',
    );
    vi.mocked(auditApi.fetchAuditLog).mockResolvedValue({
      total: 1,
      limit: 25,
      offset: 0,
      items: [
        {
          id: 'aud-1',
          table_name: 'goods_slips',
          row_id: 'gs-1',
          action: 'UPDATE',
          actor_id: 'u-1',
          actor_name: 'Super Admin',
          at: '2026-11-06T11:00:00Z',
          request_id: 'req-12345',
          diffs: [
            {
              field: 'status',
              field_label: 'Status',
              old_value: 'OPEN',
              new_value: 'CLOSED',
            },
          ],
          old_values: { status: 'OPEN' },
          new_values: { status: 'CLOSED' },
        },
      ],
    });
  });

  it('renders table filters and audit log entries', async () => {
    render(<AuditExplorerPage />);

    await waitFor(() => {
      expect(screen.getAllByText('goods_slips').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('UPDATE').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Super Admin')).toBeInTheDocument();
    });

    // Click view modal
    fireEvent.click(screen.getByRole('button', { name: /view/i }));
    expect(screen.getByText('Audit Entry: goods_slips (UPDATE)')).toBeInTheDocument();
    expect(screen.getByText('req-12345')).toBeInTheDocument();
  });
});
