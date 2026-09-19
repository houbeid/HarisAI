import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement } from 'react';
import { ReportTable } from '../../../src/components/reports/ReportTable';
import { reportsApi } from '../../../src/api/reportsApi';
import type { StrReportItem, ReportsResponse } from '../../../src/types/reports';

vi.mock('../../../src/api/reportsApi');

function makeReport(overrides: Partial<StrReportItem> = {}): StrReportItem {
  return {
    reportId: 'STR-2026-0142',
    alertId: 'ALT-1',
    transactionId: 'TXN-2026-04816',
    operatorCode: 'BANKILY',
    fraudType: 'SIM_SWAPPING',
    riskScore: 95,
    decision: 'BLOCK',
    confirmedBy: 'agent@bankily.mr',
    agentNote: 'Confirmé — SIM swap avéré',
    generatedAt: new Date().toISOString(),
    ...overrides,
  };
}

function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe('ReportTable', () => {
  it('affiche confirmedBy tel quel (chaîne brute), pas un nom reconstruit', async () => {
    vi.mocked(reportsApi.getReports).mockResolvedValue({
      reports: [makeReport()],
      page: 1,
      pageSize: 20,
    });

    renderWithQueryClient(<ReportTable />);

    expect(await screen.findByText('agent@bankily.mr')).toBeInTheDocument();
  });

  it('affiche la décision telle que reçue (toujours majuscules sur cet endpoint)', async () => {
    vi.mocked(reportsApi.getReports).mockResolvedValue({
      reports: [makeReport({ decision: 'BLOCK' })],
      page: 1,
      pageSize: 20,
    });

    renderWithQueryClient(<ReportTable />);

    expect(await screen.findByText('Block')).toBeInTheDocument(); // normalisé à l'affichage par decisionLabel
  });

  it('désactive Précédent sur la première page, et Suivant si la page est incomplète', async () => {
    const shortPage: ReportsResponse = { reports: [makeReport()], page: 1, pageSize: 20 };
    vi.mocked(reportsApi.getReports).mockResolvedValue(shortPage);

    renderWithQueryClient(<ReportTable />);
    await screen.findByText('STR-2026-0142');

    expect(screen.getByRole('button', { name: /Précédent/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Suivant/ })).toBeDisabled();
  });

  it('active Suivant quand la page reçue est pleine (heuristique de pagination)', async () => {
    const user = userEvent.setup();
    const fullPage: StrReportItem[] = Array.from({ length: 20 }, (_, i) =>
      makeReport({ reportId: `STR-${i}` }),
    );
    vi.mocked(reportsApi.getReports).mockResolvedValue({ reports: fullPage, page: 1, pageSize: 20 });

    renderWithQueryClient(<ReportTable />);
    await screen.findByText('STR-0');

    const nextButton = screen.getByRole('button', { name: /Suivant/ });
    expect(nextButton).not.toBeDisabled();

    await user.click(nextButton);
    expect(reportsApi.getReports).toHaveBeenCalledWith({ page: 2, pageSize: 20 });
  });
});
