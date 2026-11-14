import type {
  FormSnapshot,
  FormDefinitionSummary,
  FormVersionSummary,
  FormFieldSnapshot,
  VersionDiffResult,
} from '@/features/config/forms/types';
import type {
  OptionSet,
  OptionItem,
  AllowedStatus,
  SystemBehavior,
} from '@/features/config/options/types';

const BASE_URL: string = String(import.meta.env.VITE_API_URL ?? 'http://localhost:8000');

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const headersInit: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (options?.headers) {
    Object.assign(headersInit, options.headers);
  }

  const res = await fetch(`${BASE_URL}${url}`, {
    ...options,
    headers: headersInit,
  });

  if (!res.ok) {
    const errorBody = (await res.json().catch(() => ({}))) as { detail?: string };
    const message = errorBody.detail ?? `HTTP ${String(res.status)} ${res.statusText}`;
    throw new Error(message);
  }

  return (await res.json()) as T;
}

export const optionsApi = {
  listSets: async (): Promise<OptionSet[]> => {
    return fetchJson<OptionSet[]>('/api/v1/config/options/sets');
  },

  getSet: async (id: string): Promise<OptionSet> => {
    return fetchJson<OptionSet>(`/api/v1/config/options/sets/${id}`);
  },

  getSetByCode: async (code: string): Promise<OptionSet> => {
    return fetchJson<OptionSet>(`/api/v1/config/options/sets/by-code/${code}`);
  },

  createItem: async (
    setId: string,
    payload: {
      code: string;
      label: string;
      sort_order?: number | undefined;
      is_active?: boolean | undefined;
      allowed_status?: AllowedStatus | undefined;
      rule_text?: string | null | undefined;
      next_action_text?: string | null | undefined;
      remarks?: string | null | undefined;
      system_behavior?: SystemBehavior | undefined;
    },
  ): Promise<OptionItem> => {
    return fetchJson<OptionItem>('/api/v1/config/options/items', {
      method: 'POST',
      body: JSON.stringify({
        option_set_id: setId,
        ...payload,
      }),
    });
  },

  updateItem: async (
    itemId: string,
    payload: {
      label?: string | undefined;
      sort_order?: number | undefined;
      is_active?: boolean | undefined;
      allowed_status?: AllowedStatus | undefined;
      rule_text?: string | null | undefined;
      next_action_text?: string | null | undefined;
      remarks?: string | null | undefined;
      system_behavior?: SystemBehavior | undefined;
      reason?: string | null | undefined;
    },
  ): Promise<OptionItem> => {
    return fetchJson<OptionItem>(`/api/v1/config/options/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  getItemUsage: async (itemId: string): Promise<{ usage_count: number }> => {
    return fetchJson<{ usage_count: number }>(`/api/v1/config/options/items/${itemId}/usage`);
  },
};

export const formsApi = {
  listForms: async (): Promise<FormDefinitionSummary[]> => {
    return fetchJson<FormDefinitionSummary[]>('/api/v1/config/forms');
  },

  listVersions: async (formCode: string): Promise<FormVersionSummary[]> => {
    return fetchJson<FormVersionSummary[]>(`/api/v1/config/forms/${formCode}/versions`);
  },

  getPublished: async (formCode: string): Promise<FormSnapshot> => {
    return fetchJson<FormSnapshot>(`/api/v1/config/forms/${formCode}/published`);
  },

  getVersion: async (formCode: string, version: number): Promise<FormSnapshot> => {
    return fetchJson<FormSnapshot>(`/api/v1/config/forms/${formCode}/versions/${String(version)}`);
  },

  createDraft: async (formCode: string): Promise<FormSnapshot> => {
    return fetchJson<FormSnapshot>(`/api/v1/config/forms/${formCode}/draft`, {
      method: 'POST',
    });
  },

  updateDraftFields: async (
    formCode: string,
    version: number,
    fields: FormFieldSnapshot[],
  ): Promise<FormSnapshot> => {
    return fetchJson<FormSnapshot>(
      `/api/v1/config/forms/${formCode}/versions/${String(version)}/fields`,
      {
        method: 'PUT',
        body: JSON.stringify({ fields }),
      },
    );
  },

  validateDraft: async (
    formCode: string,
    version: number,
  ): Promise<{ valid: boolean; errors: string[] }> => {
    return fetchJson<{ valid: boolean; errors: string[] }>(
      `/api/v1/config/forms/${formCode}/versions/${String(version)}/validate`,
      {
        method: 'POST',
      },
    );
  },

  publishVersion: async (
    formCode: string,
    version: number,
    changeNotes: string,
  ): Promise<FormSnapshot> => {
    return fetchJson<FormSnapshot>(
      `/api/v1/config/forms/${formCode}/versions/${String(version)}/publish`,
      {
        method: 'POST',
        body: JSON.stringify({ change_notes: changeNotes }),
      },
    );
  },

  diffVersions: async (formCode: string, v1: number, v2: number): Promise<VersionDiffResult> => {
    return fetchJson<VersionDiffResult>(
      `/api/v1/config/forms/${formCode}/diff?v1=${String(v1)}&v2=${String(v2)}`,
    );
  },
};
