import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { AuditBanner } from '@/features/container-audit/AuditBanner';
import { ComplianceCalendar } from '@/features/container-audit/ComplianceCalendar';
import * as authHook from '@/features/auth/useAuth';
import * as apiHook from '@/hooks/useApiQuery';

describe('Container Audit Components (P2-06, BR-18, DEC-08)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('AuditBanner', () => {
    it('renders alert banner when today audit is pending for Inward Verifier', () => {
      vi.spyOn(authHook, 'useAuth').mockReturnValue({
        status: 'signed-in',
        session: null,
        me: {
          profile: {
            id: 'user-1',
            email: 'aman@example.com',
            full_name: 'Aman',
            is_super_admin: false,
          },
          roles: [{ code: 'INWARD_VERIFIER', name: 'Inward Verifier' }],
          permissions: [],
          step_codes: ['S1_INSPECT'],
        },
        error: null,
        signIn: vi.fn(),
        signOut: vi.fn(),
        reloadMe: vi.fn(),
        can: vi.fn().mockReturnValue(true),
      });

      vi.spyOn(apiHook, 'useApiQuery').mockReturnValue({
        data: {
          day: {
            id: 'day-1',
            audit_date: '2026-11-03',
            status: 'PENDING',
            is_late: false,
            late_reason: null,
            confirmed: false,
            confirmed_by: null,
            confirmed_by_name: null,
            confirmed_at: null,
            remarks: null,
            created_at: '2026-11-03T00:00:00Z',
          },
          containers: [],
          checkbox_label: 'Containers Checked & Counted Daily',
          can_edit: true,
          can_confirm: true,
        },
        loading: false,
        error: null,
        reload: vi.fn(),
        setData: vi.fn(),
      });

      const onOpenAudit = vi.fn();
      render(<AuditBanner onOpenAudit={onOpenAudit} />);

      expect(screen.getByText(/Daily DMT Container Audit Pending/i)).toBeInTheDocument();
      expect(screen.getByText(/All active DMT containers must be counted/i)).toBeInTheDocument();

      const btn = screen.getByRole('button', { name: /Open Daily Register/i });
      fireEvent.click(btn);
      expect(onOpenAudit).toHaveBeenCalledTimes(1);
    });

    it('does not render banner when audit is already confirmed', () => {
      vi.spyOn(authHook, 'useAuth').mockReturnValue({
        status: 'signed-in',
        session: null,
        me: {
          profile: {
            id: 'user-1',
            email: 'aman@example.com',
            full_name: 'Aman',
            is_super_admin: false,
          },
          roles: [{ code: 'INWARD_VERIFIER', name: 'Inward Verifier' }],
          permissions: [],
          step_codes: ['S1_INSPECT'],
        },
        error: null,
        signIn: vi.fn(),
        signOut: vi.fn(),
        reloadMe: vi.fn(),
        can: vi.fn().mockReturnValue(true),
      });

      vi.spyOn(apiHook, 'useApiQuery').mockReturnValue({
        data: {
          day: {
            id: 'day-1',
            audit_date: '2026-11-03',
            status: 'CONFIRMED',
            is_late: false,
            late_reason: null,
            confirmed: true,
            confirmed_by: 'user-1',
            confirmed_by_name: 'Aman',
            confirmed_at: '2026-11-03T10:00:00Z',
            remarks: null,
            created_at: '2026-11-03T00:00:00Z',
          },
          containers: [],
          checkbox_label: 'Containers Checked & Counted Daily',
          can_edit: false,
          can_confirm: false,
        },
        loading: false,
        error: null,
        reload: vi.fn(),
        setData: vi.fn(),
      });

      const { container } = render(<AuditBanner />);
      expect(container.firstChild).toBeNull();
    });
  });

  describe('ComplianceCalendar', () => {
    it('renders month header, status legend, and responds to day click', () => {
      vi.spyOn(apiHook, 'useApiQuery').mockReturnValue({
        data: {
          from_date: '2026-11-01',
          to_date: '2026-11-30',
          days: [
            {
              audit_date: '2026-11-01',
              status: 'CONFIRMED',
              is_late: false,
              confirmed: true,
              confirmed_at: '2026-11-01T16:00:00Z',
              total_containers_counted: 40,
              total_sellable_packaging_qty: 8,
              remarks: 'All clean',
            },
            {
              audit_date: '2026-11-02',
              status: 'LATE',
              is_late: true,
              confirmed: true,
              confirmed_at: '2026-11-03T09:30:00Z',
              total_containers_counted: 35,
              total_sellable_packaging_qty: 6,
              remarks: 'Late entry entered',
            },
          ],
          today_status: 'PENDING',
        },
        loading: false,
        error: null,
        reload: vi.fn(),
        setData: vi.fn(),
      });

      render(<ComplianceCalendar />);

      // Status legend check
      expect(screen.getByText(/Confirmed On-Time/i)).toBeInTheDocument();
      expect(screen.getByText(/Late Confirmation/i)).toBeInTheDocument();
      expect(screen.getByText(/Missed Day/i)).toBeInTheDocument();

      // Click on day 1 to view details
      const day1Btn = screen.getByText('1');
      fireEvent.click(day1Btn);

      expect(screen.getByText(/Audit Details for 2026-11-01/i)).toBeInTheDocument();
      expect(screen.getAllByText(/40 pcs/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/8/i).length).toBeGreaterThanOrEqual(1);
    });
  });
});
