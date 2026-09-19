import { http, HttpResponse } from 'msw';

/**
 * Base URL identique à celle stubbée dans tests/setup.ts
 * (VITE_API_BASE_URL='http://localhost:5000'). MSW intercepte au niveau
 * de fetch() lui-même — ces tests passent par le VRAI httpClient.ts,
 * pas par un mock du module alertsApi/reportsApi. C'est la différence
 * avec tous les tests de composants précédents : ici on vérifie que
 * httpClient construit vraiment la bonne URL, envoie vraiment le bon
 * header, parse vraiment le JSON reçu.
 */
const BASE_URL = 'http://localhost:5000';

export const handlers = [
  http.get(`${BASE_URL}/alerts`, ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get('status');

    return HttpResponse.json({
      alerts: [
        {
          alertId: 'ALT-1',
          transactionId: 'TXN-1',
          operator: 'BANKILY',
          decision: 'Block',
          score: 92,
          fraudType: 'SIM_SWAPPING',
          status: status ?? 'Pending',
          createdAt: new Date().toISOString(),
          reviewedAt: null,
          reviewedBy: null,
        },
      ],
      totalPending: 1,
      page: 1,
      pageSize: 50,
    });
  }),

  http.post(`${BASE_URL}/alerts/:alertId/validate`, async ({ params }) => {
    return HttpResponse.json({
      alertId: params.alertId as string,
      action: 'Confirm',
      strReportTriggered: true,
    });
  }),

  http.get(`${BASE_URL}/reports`, () => {
    return HttpResponse.json({
      reports: [
        {
          reportId: 'STR-1',
          alertId: 'ALT-1',
          transactionId: 'TXN-1',
          operatorCode: 'BANKILY',
          fraudType: 'SIM_SWAPPING',
          riskScore: 95,
          decision: 'BLOCK',
          confirmedBy: 'agent@bankily.mr',
          agentNote: null,
          generatedAt: new Date().toISOString(),
        },
      ],
      page: 1,
      pageSize: 20,
    });
  }),
];