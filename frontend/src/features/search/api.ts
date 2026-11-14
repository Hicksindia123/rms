import { apiRequest } from '@/lib/api/client';

export interface SearchResultItem {
  id: string;
  type: string;
  title: string;
  subtitle: string | null;
  badge: string | null;
  badge_variant?: 'info' | 'success' | 'warning' | 'neutral';
  route: string;
  details: Record<string, unknown>;
}

export interface SearchResultGroup {
  type: string;
  label: string;
  count: number;
  items: SearchResultItem[];
}

export interface DirectMatchInfo {
  route: string;
  title: string;
  subtitle?: string | null;
}

export interface SearchResponse {
  query: string;
  total: number;
  is_qr_match: boolean;
  direct_route: string | null;
  direct_match?: DirectMatchInfo | null;
  groups: SearchResultGroup[];
  took_ms: number;
  search_time_ms?: number;
}

export const searchApi = {
  search: (query: string, limit = 5) =>
    apiRequest<SearchResponse>('/search', {
      query: { q: query, limit: String(limit) },
    }),
  globalSearch: async (query: string, limit = 20): Promise<SearchResponse> => {
    const res = await apiRequest<SearchResponse>('/search', {
      query: { q: query, limit: String(limit) },
    });
    // synthesize direct_match for UI banner if is_qr_match is true
    if (res.is_qr_match && res.direct_route) {
      const firstItem = res.groups[0]?.items[0];
      res.direct_match = {
        route: res.direct_route,
        title: firstItem ? firstItem.title : res.query,
        subtitle: firstItem ? firstItem.subtitle : 'Exact QR / Barcode Scan Match',
      };
    }
    res.search_time_ms = res.took_ms;
    return res;
  },
};
