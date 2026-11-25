import { apiRequest } from '@/lib/api/client';

export interface SavedView {
  id: string;
  user_id: string;
  resource_code: string;
  name: string;
  description: string | null;
  filters: Record<string, unknown>;
  columns: string[] | null;
  sort: Record<string, unknown> | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface SavedViewIn {
  resource_code: string;
  name: string;
  description?: string | null;
  filters: Record<string, unknown>;
  columns?: string[] | null;
  sort?: Record<string, unknown> | null;
  is_default?: boolean;
}

export interface SavedViewUpdateIn {
  name?: string;
  description?: string | null;
  filters?: Record<string, unknown>;
  columns?: string[] | null;
  sort?: Record<string, unknown> | null;
  is_default?: boolean;
}

export const viewsApi = {
  fetchSavedViews: async (resourceCode: string): Promise<SavedView[]> => {
    return apiRequest<SavedView[]>(
      `/saved-views?resource_code=${encodeURIComponent(resourceCode)}`,
    );
  },

  createSavedView: async (data: SavedViewIn): Promise<SavedView> => {
    return apiRequest<SavedView>('/saved-views', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  updateSavedView: async (id: string, data: SavedViewUpdateIn): Promise<SavedView> => {
    return apiRequest<SavedView>(`/saved-views/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  deleteSavedView: async (id: string): Promise<undefined> => {
    return apiRequest<undefined>(`/saved-views/${id}`, {
      method: 'DELETE',
    });
  },
};
