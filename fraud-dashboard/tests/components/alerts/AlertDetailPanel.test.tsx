import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AlertDetailPanel } from '../../../src/components/alerts/AlertDetailPanel';
import { alertsApi } from '../../../src/api/alertsApi';
import { ApiError } from '../../../src/api/httpClient';
import type { AlertListItem } from '../../../src/types/alerts';

vi.mock('../../../src/api/alertsApi');

function makeAlert(overrides: Partial<AlertListItem> = {}): AlertListItem {
  return {
    alertId: 'ALT-1',
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

describe('AlertDetailPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('ne rend rien quand alert est null', () => {
    render(<AlertDetailPanel alert={null} onClose={vi.fn()} onValidated={vi.fn()} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('désactive "Valider la décision" tant qu\'aucune action n\'est choisie', () => {
    render(<AlertDetailPanel alert={makeAlert()} onClose={vi.fn()} onValidated={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Valider la décision' })).toBeDisabled();
  });

  it('active le bouton après avoir choisi une action, et envoie "Confirm" (jamais le libellé du bouton)', async () => {
    const user = userEvent.setup();
    const onValidated = vi.fn();
    vi.mocked(alertsApi.validateAlert).mockResolvedValue({
      alertId: 'ALT-1',
      action: 'Confirm',
      strReportTriggered: true,
    });

    render(<AlertDetailPanel alert={makeAlert()} onClose={vi.fn()} onValidated={onValidated} />);

    await user.click(screen.getByRole('button', { name: /Confirmer la fraude/ }));
    await user.click(screen.getByRole('button', { name: 'Valider la décision' }));

    await waitFor(() => expect(onValidated).toHaveBeenCalled());
    expect(alertsApi.validateAlert).toHaveBeenCalledWith('ALT-1', {
      action: 'Confirm',
      note: undefined,
    });
  });

  it('affiche le bandeau de conflit avec les infos réelles sur 409', async () => {
    const user = userEvent.setup();
    vi.mocked(alertsApi.validateAlert).mockRejectedValue(
      new ApiError(409, 'alert_already_processed', ['Alerte déjà traitée']),
    );
    vi.mocked(alertsApi.getAlerts).mockResolvedValue({
      alerts: [makeAlert({ status: 'Confirmed', reviewedBy: 'aicha@bankily.mr', reviewedAt: new Date().toISOString() })],
      totalPending: 0,
      page: 1,
      pageSize: 100,
    });

    render(<AlertDetailPanel alert={makeAlert()} onClose={vi.fn()} onValidated={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Confirmer la fraude/ }));
    await user.click(screen.getByRole('button', { name: 'Valider la décision' }));

    expect(await screen.findByText(/Alerte déjà traitée/)).toBeInTheDocument();
    expect(screen.getByText(/aicha@bankily\.mr/)).toBeInTheDocument();
  });

  it('dégrade honnêtement le bandeau de conflit si le lookup ne retrouve pas l\'alerte', async () => {
    const user = userEvent.setup();
    vi.mocked(alertsApi.validateAlert).mockRejectedValue(
      new ApiError(409, 'alert_already_processed', []),
    );
    vi.mocked(alertsApi.getAlerts).mockResolvedValue({ alerts: [], totalPending: 0, page: 1, pageSize: 100 });

    render(<AlertDetailPanel alert={makeAlert()} onClose={vi.fn()} onValidated={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Confirmer la fraude/ }));
    await user.click(screen.getByRole('button', { name: 'Valider la décision' }));

    expect(await screen.findByText(/traitée par un autre agent entre-temps/)).toBeInTheDocument();
  });

  it('affiche "Alerte introuvable" sur 404, avec retour à la liste', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    vi.mocked(alertsApi.validateAlert).mockRejectedValue(new ApiError(404, 'alert_not_found', []));

    render(<AlertDetailPanel alert={makeAlert()} onClose={onClose} onValidated={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Écarter l'alerte/ }));
    await user.click(screen.getByRole('button', { name: 'Valider la décision' }));

    expect(await screen.findByText('Alerte introuvable')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retour à la liste' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('affiche un état lecture seule (pas de formulaire) pour une alerte déjà traitée à l\'ouverture', () => {
    render(
      <AlertDetailPanel
        alert={makeAlert({ status: 'Confirmed', reviewedBy: 'sidi@bankily.mr' })}
        onClose={vi.fn()}
        onValidated={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: /Confirmer la fraude/ })).not.toBeInTheDocument();
    expect(screen.getByText(/sidi@bankily\.mr/)).toBeInTheDocument();
  });
});
