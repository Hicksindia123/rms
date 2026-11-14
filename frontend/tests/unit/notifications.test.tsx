import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { NotificationAdminPage } from '@/features/admin/notifications/NotificationAdminPage';
import {
  notificationAdminApi,
  notificationsApi,
  type AppNotification,
  type EmailStatus,
  type Lookups,
  type NotificationList,
  type Preferences,
} from '@/features/notifications/api';
import { NotificationBell } from '@/features/notifications/NotificationBell';
import { NotificationCentrePage } from '@/features/notifications/NotificationCentrePage';
import { NotificationPreferencesPage } from '@/features/notifications/NotificationPreferencesPage';

vi.mock('@/features/notifications/api', () => ({
  notificationsApi: {
    mine: vi.fn(),
    read: vi.fn(),
    readAll: vi.fn(),
    preferences: vi.fn(),
    savePreferences: vi.fn(),
  },
  notificationAdminApi: {
    emailStatus: vi.fn(),
    lookups: vi.fn(),
    eventTypes: vi.fn(),
    updateEventType: vi.fn(),
    rules: vi.fn(),
    createRule: vi.fn(),
    updateRule: vi.fn(),
    deleteRule: vi.fn(),
    templates: vi.fn(),
    templateVersions: vi.fn(),
    saveTemplate: vi.fn(),
    preview: vi.fn(),
    escalationRules: vi.fn(),
    createEscalationRule: vi.fn(),
    updateEscalationRule: vi.fn(),
    deleteEscalationRule: vi.fn(),
    deliveries: vi.fn(),
  },
}));

vi.mock('@/lib/supabase', () => ({
  isSupabaseConfigured: () => false,
  getSupabase: () => ({
    channel: () => ({
      on: () => ({ subscribe: () => {} }),
    }),
    removeChannel: () => {},
  }),
}));

const mockNotification: AppNotification = {
  id: 'notif-1',
  event_type: 'GS_CREATED',
  type: 'workflow',
  title: 'Goods slip GS-2026-0001 created',
  body: 'A consignment arrived and GS was created.',
  entity_type: 'goods_slip',
  entity_id: 'gs-1',
  priority: 'NORMAL',
  read_at: null,
  created_at: '2026-11-06T10:00:00Z',
};

const mockList: NotificationList = {
  items: [mockNotification],
  unread_count: 1,
  total: 1,
};

const mockPreferences: Preferences = {
  email_channel: {
    enabled: true,
    host: 'localhost',
    port: 54325,
    sender: 'rms@example.local',
    security: 'PLAIN',
    reason: null,
  },
  email_address: 'anuj@rms.local',
  email_mode: 'IMMEDIATE',
  items: [
    {
      event_type: 'GS_CREATED',
      label: 'Goods slip created',
      description: 'A goods slip was created at the gate.',
      category: 'WORKFLOW',
      is_mandatory: false,
      email_enabled: true,
      email_rule_active: true,
    },
    {
      event_type: 'HAZARD_DETECTED',
      label: 'Hazard detected',
      description: 'A mercury hazard was recorded at inspection.',
      category: 'COMPLIANCE',
      is_mandatory: true,
      email_enabled: true,
      email_rule_active: true,
    },
  ],
};

const mockEmailStatus: EmailStatus = {
  enabled: true,
  host: 'localhost',
  port: 54325,
  sender: 'rms@example.local',
  security: 'PLAIN',
  reason: null,
};

const mockLookups: Lookups = {
  roles: [{ code: 'INWARD_VERIFIER', name: 'Inward Verifier' }],
  users: [{ id: 'user-1', full_name: 'Anuj Kumar', email: 'anuj@rms.local' }],
  steps: [
    {
      id: 'step-1',
      code: 'STEP_1_INWARD',
      label: 'Gate Inward',
      sla_hours: 2,
      workflow_code: 'RMS_MAIN',
      version_no: 1,
      version_status: 'ACTIVE',
    },
  ],
};

describe('NotificationCentrePage (P4-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(notificationsApi.mine).mockResolvedValue(mockList);
    vi.mocked(notificationsApi.preferences).mockResolvedValue(mockPreferences);
  });

  it('renders notification list and handles mark all read', async () => {
    vi.mocked(notificationsApi.readAll).mockResolvedValue({ updated: 1 });
    const onOpen = vi.fn().mockReturnValue(true);
    const onPreferences = vi.fn();

    render(
      <NotificationCentrePage userId="user-1" onOpen={onOpen} onPreferences={onPreferences} />,
    );

    await waitFor(() => {
      expect(screen.getByText('Goods slip GS-2026-0001 created')).toBeInTheDocument();
    });

    const markAllBtn = screen.getByText('Mark all read');
    fireEvent.click(markAllBtn);

    await waitFor(() => {
      expect(notificationsApi.readAll).toHaveBeenCalled();
    });
  });

  it('handles item click and calls onOpen', async () => {
    vi.mocked(notificationsApi.read).mockResolvedValue({ updated: 1 });
    const onOpen = vi.fn().mockReturnValue(true);
    const onPreferences = vi.fn();

    render(
      <NotificationCentrePage userId="user-1" onOpen={onOpen} onPreferences={onPreferences} />,
    );

    await waitFor(() => {
      expect(screen.getByText('Goods slip GS-2026-0001 created')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Goods slip GS-2026-0001 created'));
    expect(onOpen).toHaveBeenCalledWith(mockNotification);
  });
});

describe('NotificationPreferencesPage (P4-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(notificationsApi.preferences).mockResolvedValue(mockPreferences);
    vi.mocked(notificationsApi.savePreferences).mockResolvedValue(mockPreferences);
  });

  it('renders preferences and locks mandatory events', async () => {
    render(<NotificationPreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText('Goods slip created')).toBeInTheDocument();
      expect(screen.getByText('Hazard detected')).toBeInTheDocument();
    });

    // Mandatory event switch should be disabled
    const hazardCheckbox = screen.getByRole('checkbox', { name: /Hazard detected/i });
    expect(hazardCheckbox).toBeDisabled();

    // Non-mandatory event switch should be enabled
    const gsCheckbox = screen.getByRole('checkbox', { name: /Goods slip created/i });
    expect(gsCheckbox).not.toBeDisabled();
  });
});

describe('NotificationBell (P4-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(notificationsApi.mine).mockResolvedValue(mockList);
  });

  it('renders bell and opens dropdown with notifications', async () => {
    const onOpen = vi.fn();
    const onViewAll = vi.fn();

    render(<NotificationBell userId="user-1" onOpen={onOpen} onViewAll={onViewAll} />);

    await waitFor(() => {
      expect(screen.getByText('1')).toBeInTheDocument(); // Unread badge
    });

    const bellBtn = screen.getByRole('button', { name: /notifications/i });
    fireEvent.click(bellBtn);

    await waitFor(() => {
      expect(screen.getByText('Goods slip GS-2026-0001 created')).toBeInTheDocument();
    });
  });
});

describe('NotificationAdminPage (P4-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(notificationAdminApi.emailStatus).mockResolvedValue(mockEmailStatus);
    vi.mocked(notificationAdminApi.lookups).mockResolvedValue(mockLookups);
    vi.mocked(notificationAdminApi.eventTypes).mockResolvedValue([
      {
        code: 'GS_CREATED',
        label: 'Goods slip created',
        description: 'Gate created',
        category: 'WORKFLOW',
        default_priority: 'NORMAL',
        is_mandatory: false,
        source_ref: 'WF r2',
        sort_order: 10,
      },
    ]);
    vi.mocked(notificationAdminApi.rules).mockResolvedValue([
      {
        id: 'rule-1',
        event_type: 'GS_CREATED',
        event_label: 'Goods slip created',
        name: 'Gate created rule',
        include_context_recipients: true,
        include_step_assignees: false,
        recipient_role_codes: ['INWARD_VERIFIER'],
        recipient_user_ids: [],
        channels: ['IN_APP', 'EMAIL'],
        priority: 'NORMAL',
        is_mandatory: false,
        is_active: true,
        created_at: '2026-11-06T10:00:00Z',
        updated_at: '2026-11-06T10:00:00Z',
      },
    ]);
  });

  it('renders rules tab and SMTP status banner', async () => {
    render(<NotificationAdminPage />);

    await waitFor(() => {
      expect(screen.getByText(/Gate created rule/i)).toBeInTheDocument();
      expect(screen.getByText(/localhost:54325/i)).toBeInTheDocument();
    });
  });
});
