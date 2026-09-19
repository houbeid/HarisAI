import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Sidebar } from '../../../src/components/layout/Sidebar';
import { useAuth } from '../../../src/auth/AuthContext';
import { alertsApi } from '../../../src/api/alertsApi';

vi.mock('../../../src/auth/AuthContext');
vi.mock('../../../src/api/alertsApi');

function mockAuth(overrides: Partial<ReturnType<typeof useAuth>> = {}) {
  vi.mocked(useAuth).mockReturnValue({
    token: 'x',
    agentId: 'sidi@bankily.mr',
    roles: [],
    isAuthenticated: true,
    hasReportsAccess: false,
    loginWithToken: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  });
}

function renderSidebar() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={['/alerts']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/alerts" element={<Sidebar />} />
          <Route path="/login" element={<p>Page de connexion</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Sidebar', () => {
  beforeEach(() => {
    vi.mocked(alertsApi.getAlerts).mockResolvedValue({
      alerts: [],
      totalPending: 5,
      page: 1,
      pageSize: 1,
    });
  });

  it('affiche "Rapports STR" seulement quand hasReportsAccess est vrai', async () => {
    mockAuth({ hasReportsAccess: false });
    renderSidebar();
    expect(screen.queryByText('Rapports STR')).not.toBeInTheDocument();
  });

  it('affiche "Rapports STR" quand hasReportsAccess est vrai', () => {
    mockAuth({ hasReportsAccess: true, roles: ['supervisor'] });
    renderSidebar();
    expect(screen.getByText('Rapports STR')).toBeInTheDocument();
  });

  it('affiche le badge de compteur avec la valeur réelle de totalPending', async () => {
    mockAuth();
    renderSidebar();
    expect(await screen.findByText('5')).toBeInTheDocument();
  });

  it.each([
    [['supervisor'], 'Superviseur'],
    [['compliance_officer'], 'Compliance officer'],
    [[], 'Agent de conformité'],
  ] as const)('affiche le bon libellé de rôle pour %s', (roles, expectedLabel) => {
    mockAuth({ roles: [...roles], hasReportsAccess: roles.length > 0 });
    renderSidebar();
    expect(screen.getByText(expectedLabel)).toBeInTheDocument();
  });

  it("affiche l'identifiant de l'agent connecté", () => {
    mockAuth({ agentId: 'aicha@bankily.mr' });
    renderSidebar();
    expect(screen.getByText('aicha@bankily.mr')).toBeInTheDocument();
  });

  it('appelle logout() ET navigue réellement vers /login au clic sur "Se déconnecter"', async () => {
    const user = userEvent.setup();
    const logout = vi.fn();
    mockAuth({ logout });
    renderSidebar();

    await user.click(screen.getByText('Se déconnecter'));

    expect(logout).toHaveBeenCalledOnce();
    expect(await screen.findByText('Page de connexion')).toBeInTheDocument();
  });
});
