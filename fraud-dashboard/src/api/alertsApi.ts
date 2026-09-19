import { httpClient } from './httpClient';
import type {
  AlertListItem,
  AlertsResponse,
  GetAlertsParams,
  ValidateAlertRequest,
  ValidateAlertResponse,
} from '../types/alerts';

/**
 * Toute la surface d'accès à GET /alerts, GET /alerts/{id} et
 * POST /alerts/{id}/validate. Aucun composant ne doit connaître le chemin
 * exact de ces endpoints — seulement ce module.
 */
export const alertsApi = {
  getAlerts: (params?: GetAlertsParams) =>
    httpClient.get<AlertsResponse>('/alerts', {
      status: params?.status,
      page: params?.page,
      pageSize: params?.pageSize,
    }),

  // Comble le point ouvert 4 (Session 2) — utilisé notamment par
  // AlertDetailPanel après un 409 pour relire l'état exact d'une alerte,
  // sans dépendre de la fenêtre de pagination de getAlerts().
  getAlertById: (alertId: string) => httpClient.get<AlertListItem>(`/alerts/${alertId}`),

  validateAlert: (alertId: string, payload: ValidateAlertRequest) =>
    httpClient.post<ValidateAlertResponse>(`/alerts/${alertId}/validate`, payload),
};