import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AlertsPage } from '../../src/pages/AlertsPage';
import { alertsApi } from '../../src/api/alertsApi';
import { onReceiveAlert } from '../../src/realtime/alertHubClient';
import type { AlertListItem } from '../../src/types/alerts';

vi.mock('../../src/api/alertsApi');
vi.mock('../../src/realtime/alertHubClient');

function makeAlert(overrides: Partial<AlertListItem> = {}): AlertListItem {
  return {
    alertId: 'ALT-42',
    transactionId: 'TXN-2026-04821',
    operator: 'BANKILY',
    decision: 'Block',
    score: 92,
    fraudType: 'SIM_SWAPPING',
    status: 'Pending',
    createdAt: new Date().toISOString(),
    reviewedAt: null,
    reviewedBy: null,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AlertsPage />
    </QueryClientProvider>,
  );
}

describe('AlertsPage — intégration AlertList + AlertDetailPanel', () => {
  beforeEach(() => {
    vi.mocked(onReceiveAlert).mockReturnValue(() => {});
    vi.mocked(alertsApi.getAlerts).mockResolvedValue({
      alerts: [makeAlert()],
      totalPending: 1,
      page: 1,
      pageSize: 50,
    });
  });

  it("le clic sur une ligne d'AlertList ouvre réellement AlertDetailPanel avec la bonne alerte", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('TXN-2026-04821');
    // Avant clic : pas de drawer ouvert.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(screen.getByText('TXN-2026-04821'));

    const dialog = screen.getByRole('dialog', { name: "Détail de l'alerte" });
    expect(dialog).toBeInTheDocument();
    // Le contenu du drawer reflète bien l'alerte cliquée, pas une autre.
    expect(screen.getAllByText('TXN-2026-04821')).toHaveLength(2); // ligne du tableau + titre du drawer
  });

  it('valider une alerte invalide le cache — la liste est réellement re-questionnée, pas juste fermée visuellement', async () => {
    const user = userEvent.setup();
    vi.mocked(alertsApi.validateAlert).mockResolvedValue({
      alertId: 'ALT-42',
      action: 'Confirm',
      strReportTriggered: true,
    });

    renderPage();
    await screen.findByText('TXN-2026-04821');

    const callsBeforeValidation = vi.mocked(alertsApi.getAlerts).mock.calls.length;

    await user.click(screen.getByText('TXN-2026-04821'));
    await user.click(screen.getByRole('button', { name: /Confirmer la fraude/ }));
    await user.click(screen.getByRole('button', { name: 'Valider la décision' }));

    // Le drawer se ferme après succès.
    await vi.waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    // ET la liste a été réellement re-questionnée (invalidateQueries a
    // fonctionné), pas seulement le drawer fermé visuellement.
    await vi.waitFor(() => {
      expect(vi.mocked(alertsApi.getAlerts).mock.calls.length).toBeGreaterThan(callsBeforeValidation);
    });
  });
});
