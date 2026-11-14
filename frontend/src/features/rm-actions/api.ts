import { apiRequest } from '@/lib/api/client';
import type {
  ReplacementSlipResponse,
  ResolutionBoardResponse,
  RmActionsResponse,
  SaveRmActionsRequest,
} from './types';

export const rmActionsApi = {
  getActions: (gsId: string): Promise<RmActionsResponse> =>
    apiRequest<RmActionsResponse>(`/gs/${encodeURIComponent(gsId)}/rm-actions`),

  saveActions: (gsId: string, body: SaveRmActionsRequest): Promise<RmActionsResponse> =>
    apiRequest<RmActionsResponse>(`/gs/${encodeURIComponent(gsId)}/rm-actions`, {
      method: 'PUT',
      body,
    }),

  finaliseActions: (gsId: string): Promise<RmActionsResponse> =>
    apiRequest<RmActionsResponse>(`/gs/${encodeURIComponent(gsId)}/rm-actions/finalise`, {
      method: 'POST',
    }),

  getReplacementSlip: (gsId: string): Promise<ReplacementSlipResponse> =>
    apiRequest<ReplacementSlipResponse>(`/gs/${encodeURIComponent(gsId)}/replacement-slip`),

  getResolutionBoard: (gsId: string): Promise<ResolutionBoardResponse> =>
    apiRequest<ResolutionBoardResponse>(`/gs/${encodeURIComponent(gsId)}/resolution-board`),
};
