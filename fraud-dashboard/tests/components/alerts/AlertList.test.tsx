import type { ReactElement } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AlertList } from '../../../src/components/alerts/AlertList';
import { alertsApi } from '../../../src/api/alertsApi';
import { onReceiveAlert } from '../../../src/realtime/alertHubClient';
import type { AlertListItem, AlertsResponse } from '../../../src/types/alerts';

vi.mock('../../../src/api/alertsApi');
vi.mock('../../../src/realtime/alertHubClient');

function makeAlert(overrides: Partial<AlertListItem> = {}): AlertListItem {
  return {
    alertId: 'ALT-1',
    transactionId: 'TXN-1',
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

function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe('AlertList', () => {
  beforeEach(() => {
    vi.mocked(onReceiveAlert).mockReturnValue(() => {});
  });

  it('affiche les alertes en attente par défaut', async () => {
    const pendingResponse: AlertsResponse = {
      alerts: [makeAlert({ transactionId: 'TXN-2026-04821' })],
      totalPending: 1,
      page: 1,
      pageSize: 50,
    };
    vi.mocked(alertsApi.getAlerts).mockResolvedValue(pendingResponse);

    renderWithQueryClient(<AlertList onSelectAlert={vi.fn()} />);

    expect(await screen.findByText('TXN-2026-04821')).toBeInTheDocument();
    // vérifie que le filtre Pending a bien été demandé au backend
    expect(alertsApi.getAlerts).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'Pending' }),
    );
  });

  it("appelle onSelectAlert avec l'alerte cliquée", async () => {
    const user = userEvent.setup();
    const alert = makeAlert({ transactionId: 'TXN-CLIC' });
    vi.mocked(alertsApi.getAlerts).mockResolvedValue({
      alerts: [alert],
      totalPending: 1,
      page: 1,
      pageSize: 50,
    });
    const onSelectAlert = vi.fn();

    renderWithQueryClient(<AlertList onSelectAlert={onSelectAlert} />);
    await screen.findByText('TXN-CLIC');
    await user.click(screen.getByText('TXN-CLIC'));

    expect(onSelectAlert).toHaveBeenCalledWith(alert);
  });

  it('affiche l\'état vide quand aucune alerte ne correspond au filtre', async () => {
    vi.mocked(alertsApi.getAlerts).mockResolvedValue({ alerts: [], totalPending: 0, page: 1, pageSize: 50 });

    renderWithQueryClient(<AlertList onSelectAlert={vi.fn()} />);

    expect(await screen.findByText('Aucune alerte à afficher')).toBeInTheDocument();
  });

  it('incrémente le toast temps réel quand une alerte arrive via SignalR', async () => {
    vi.mocked(alertsApi.getAlerts).mockResolvedValue({ alerts: [], totalPending: 0, page: 1, pageSize: 50 });
    let capturedCallback: (() => void) | undefined;
    vi.mocked(onReceiveAlert).mockImplementation((cb) => {
      capturedCallback = () => cb({ alertId: 'X', transactionId: 'X', decision: 'Block', score: 1, fraudType: 'UNKNOWN' });
      return () => {};
    });

    renderWithQueryClient(<AlertList onSelectAlert={vi.fn()} />);
    await screen.findByText('Aucune alerte à afficher');

    act(() => {
      capturedCallback?.();
    });

    await waitFor(() => {
      expect(screen.getByText(/nouvelle alerte reçue en direct/)).toBeInTheDocument();
    });
  });
});
