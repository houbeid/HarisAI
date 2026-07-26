import { httpClient } from './httpClient';
import type {
  AlertsResponse,
  GetAlertsParams,
  ValidateAlertRequest,
  ValidateAlertResponse,
} from '../types/alerts';

/**
 * Toute la surface d'accès à GET /alerts et POST /alerts/{id}/validate.
 * Aucun composant ne doit connaître le chemin exact de ces endpoints —
 * seulement ce module.
 */
export const alertsApi = {
  getAlerts: (params?: GetAlertsParams) =>
    httpClient.get<AlertsResponse>('/alerts', {
      status: params?.status,
      page: params?.page,
      pageSize: params?.pageSize,
    }),

  validateAlert: (alertId: string, payload: ValidateAlertRequest) =>
    httpClient.post<ValidateAlertResponse>(`/alerts/${alertId}/validate`, payload),
};