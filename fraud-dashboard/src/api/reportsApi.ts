import { httpClient } from './httpClient';
import type { GetReportsParams, ReportsResponse } from '../types/reports';

/**
 * Accès à GET /reports. Réservé compliance_officer/supervisor côté backend
 * (JWT) — ce module ne fait AUCUNE vérification de rôle lui-même, il fait
 * confiance au 401/403 du backend en dernier recours. La vérification de
 * rôle côté UI (masquer la navigation) est une couche de confort, pas une
 * frontière de sécurité — voir auth/AuthContext.tsx.
 */
export const reportsApi = {
  getReports: (params?: GetReportsParams) =>
    httpClient.get<ReportsResponse>('/reports', {
      page: params?.page,
      pageSize: params?.pageSize,
    }),
};