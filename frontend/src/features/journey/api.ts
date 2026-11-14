import { apiRequest } from '@/lib/api/client';

/** Change plan Phase 10 (AMD-22): the signed-in user's menu, from DB config (GET /me/journey). */
export interface JourneyNext {
  gs_id: string;
  gs_no: string;
  party_name: string | null;
  station_name: string | null;
  target_id: string;
  since: string | null;
}

export interface JourneyEntry {
  code: string;
  label: string;
  hint: string | null;
  kind: 'STEP' | 'TOOL';
  screen_key: string;
  item_screen_key: string | null;
  queue_code: string | null;
  count: number | null;
  next: JourneyNext | null;
}

export interface MyJourney {
  entries: JourneyEntry[];
  hidden_features: string[];
}

export type JourneyQueueItem = JourneyNext;

export interface JourneyQueue {
  code: string;
  label: string;
  hint: string | null;
  item_screen_key: string | null;
  items: JourneyQueueItem[];
  total: number;
}

export function fetchMyJourney(): Promise<MyJourney> {
  return apiRequest<MyJourney>('/me/journey');
}

export function fetchJourneyQueue(code: string): Promise<JourneyQueue> {
  return apiRequest<JourneyQueue>(`/me/journey/${encodeURIComponent(code)}`);
}

// --- admin (Admin -> Role Journeys) ------------------------------------------------------------

export interface JourneyStep {
  code: string;
  label: string;
  hint: string | null;
  kind: 'STEP' | 'TOOL';
  screen_key: string;
  item_screen_key: string | null;
  queue_code: string | null;
  feature_code: string | null;
  perm_module: string;
  perm_action: string;
  sort_order: number;
  is_active: boolean;
}

export interface RoleJourney {
  role_code: string;
  role_name: string;
  step_codes: string[];
}

export interface JourneyConfig {
  steps: JourneyStep[];
  roles: RoleJourney[];
  on_hold: string[];
}

export function fetchJourneyConfig(): Promise<JourneyConfig> {
  return apiRequest<JourneyConfig>('/config/journeys');
}

export function saveRoleJourney(
  roleCode: string,
  stepCodes: string[],
  reason: string,
): Promise<RoleJourney> {
  return apiRequest<RoleJourney>(`/config/journeys/roles/${encodeURIComponent(roleCode)}`, {
    method: 'PUT',
    body: { step_codes: stepCodes, reason },
  });
}

export function saveJourneyStep(
  code: string,
  body: { label: string; hint: string | null; is_active: boolean; reason: string },
): Promise<JourneyStep> {
  return apiRequest<JourneyStep>(`/config/journeys/steps/${encodeURIComponent(code)}`, {
    method: 'PUT',
    body,
  });
}
