import { describe, it, expect, afterEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { alertsApi } from '../../src/api/alertsApi';
import { reportsApi } from '../../src/api/reportsApi';
import { ApiError, NetworkError } from '../../src/api/httpClient';
import { setToken } from '../../src/auth/tokenStore';

const BASE_URL = 'http://localhost:5000';

/**
 * Contrairement à tous les tests de composants précédents (qui mockent
 * alertsApi/reportsApi au niveau du module), ces tests appellent le VRAI
 * httpClient.ts contre un VRAI serveur HTTP simulé par MSW. Ce qu'ils
 * vérifient et que les autres tests NE PEUVENT PAS vérifier : la
 * construction réelle de l'URL et des query params, le header
 * Authorization réellement envoyé, le parsing réel du JSON d'erreur.
 */
describe('Intégration — alertsApi/reportsApi via httpClient réel', () => {
  afterEach(() => {
    setToken(null);
  });

  it('GET /alerts : construit la bonne URL avec les query params et parse la réponse réelle', async () => {
    let capturedUrl: URL | undefined;
    server.use(
      http.get(`${BASE_URL}/alerts`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({
          alerts: [],
          totalPending: 3,
          page: 2,
          pageSize: 10,
        });
      }),
    );

    const response = await alertsApi.getAlerts({ status: 'Pending', page: 2, pageSize: 10 });

    expect(capturedUrl?.searchParams.get('status')).toBe('Pending');
    expect(capturedUrl?.searchParams.get('page')).toBe('2');
    expect(capturedUrl?.searchParams.get('pageSize')).toBe('10');
    expect(response.totalPending).toBe(3);
  });

  it("envoie le header Authorization: Bearer <token> quand un token est présent dans tokenStore", async () => {
    let capturedAuth: string | null = null;
    server.use(
      http.get(`${BASE_URL}/alerts`, ({ request }) => {
        capturedAuth = request.headers.get('authorization');
        return HttpResponse.json({ alerts: [], totalPending: 0, page: 1, pageSize: 50 });
      }),
    );

    setToken('mon-vrai-jwt');
    await alertsApi.getAlerts();

    expect(capturedAuth).toBe('Bearer mon-vrai-jwt');
  });

  it("n'envoie AUCUN header Authorization quand tokenStore est vide", async () => {
    let capturedAuth: string | null = 'valeur-initiale-non-écrasée';
    server.use(
      http.get(`${BASE_URL}/alerts`, ({ request }) => {
        capturedAuth = request.headers.get('authorization');
        return HttpResponse.json({ alerts: [], totalPending: 0, page: 1, pageSize: 50 });
      }),
    );

    await alertsApi.getAlerts();

    expect(capturedAuth).toBeNull();
  });

  it('POST /alerts/{id}/validate : un vrai 409 devient une ApiError avec le bon code et les bons details', async () => {
    server.use(
      http.post(`${BASE_URL}/alerts/:alertId/validate`, () =>
        HttpResponse.json({ error: 'alert_already_processed', details: ['déjà traitée'] }, { status: 409 }),
      ),
    );

    await expect(alertsApi.validateAlert('ALT-1', { action: 'Confirm' })).rejects.toMatchObject({
      status: 409,
      code: 'alert_already_processed',
      details: ['déjà traitée'],
    });
  });

  it('un vrai 404 devient une ApiError avec code alert_not_found', async () => {
    server.use(
      http.post(`${BASE_URL}/alerts/:alertId/validate`, () =>
        HttpResponse.json({ error: 'alert_not_found', details: null }, { status: 404 }),
      ),
    );

    try {
      await alertsApi.validateAlert('ALT-INCONNU', { action: 'Dismiss' });
      throw new Error('aurait dû lever une ApiError');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).code).toBe('alert_not_found');
    }
  });

  it('une vraie coupure réseau lève NetworkError, pas une ApiError', async () => {
    server.use(http.get(`${BASE_URL}/alerts`, () => HttpResponse.error()));

    await expect(alertsApi.getAlerts()).rejects.toBeInstanceOf(NetworkError);
  });

  it('un 500 sans corps JSON valide retombe sur internal_server_error plutôt que de planter', async () => {
    server.use(
      http.get(`${BASE_URL}/alerts`, () => new HttpResponse('pas du json', { status: 500 })),
    );

    await expect(alertsApi.getAlerts()).rejects.toMatchObject({
      status: 500,
      code: 'internal_server_error',
    });
  });

  it('GET /reports : round-trip réel avec confirmedBy préservé tel quel', async () => {
    const response = await reportsApi.getReports({ page: 1, pageSize: 20 });
    expect(response.reports[0].confirmedBy).toBe('agent@bankily.mr');
    expect(response.reports[0].decision).toBe('BLOCK');
  });
});