import type { ReactElement } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RequireAuth, RequireReportsAccess } from '../../src/routes/guards';
import { useAuth } from '../../src/auth/AuthContext';
import { alertsApi } from '../../src/api/alertsApi';
import { connectAlertHub, disconnectAlertHub } from '../../src/realtime/alertHubClient';

vi.mock('../../src/auth/AuthContext');
vi.mock('../../src/api/alertsApi');
vi.mock('../../src/realtime/alertHubClient');

const routerFuture = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

function mockAuth(overrides: Partial<ReturnType<typeof useAuth>> = {}) {
  vi.mocked(useAuth).mockReturnValue({
    token: null,
    agentId: null,
    roles: [],
    isAuthenticated: false,
    hasReportsAccess: false,
    loginWithToken: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  });
}

function renderWithProviders(ui: ReactElement, initialEntry: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]} future={routerFuture}>
        {ui}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('RequireAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(alertsApi.getAlerts).mockResolvedValue({ alerts: [], totalPending: 0, page: 1, pageSize: 1 });
  });

  it('redirige vers /login quand isAuthenticated est faux — jamais de fuite de contenu protégé', () => {
    mockAuth({ isAuthenticated: false });

    renderWithProviders(
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/alerts" element={<p>Contenu secret des alertes</p>} />
        </Route>
        <Route path="/login" element={<p>Page de connexion</p>} />
      </Routes>,
      '/alerts',
    );

    expect(screen.getByText('Page de connexion')).toBeInTheDocument();
    expect(screen.queryByText('Contenu secret des alertes')).not.toBeInTheDocument();
  });

  it('rend la page demandée (Outlet) quand isAuthenticated est vrai', () => {
    mockAuth({ isAuthenticated: true });

    renderWithProviders(
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/alerts" element={<p>Contenu des alertes</p>} />
        </Route>
        <Route path="/login" element={<p>Page de connexion</p>} />
      </Routes>,
      '/alerts',
    );

    expect(screen.getByText('Contenu des alertes')).toBeInTheDocument();
  });

  it('connecte le hub SignalR quand authentifié, et le déconnecte au démontage', () => {
    mockAuth({ isAuthenticated: true });

    const { unmount } = renderWithProviders(
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/alerts" element={<p>Contenu</p>} />
        </Route>
      </Routes>,
      '/alerts',
    );

    expect(connectAlertHub).toHaveBeenCalledOnce();
    expect(disconnectAlertHub).not.toHaveBeenCalled();

    unmount();
    expect(disconnectAlertHub).toHaveBeenCalledOnce();
  });

  it('ne connecte JAMAIS le hub quand non authentifié', () => {
    mockAuth({ isAuthenticated: false });

    renderWithProviders(
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/alerts" element={<p>Contenu</p>} />
        </Route>
        <Route path="/login" element={<p>Login</p>} />
      </Routes>,
      '/alerts',
    );

    expect(connectAlertHub).not.toHaveBeenCalled();
  });
});

describe('RequireReportsAccess', () => {
  it('redirige vers /alerts quand hasReportsAccess est faux — accès direct par URL bloqué comme le lien masqué', () => {
    mockAuth({ isAuthenticated: true, hasReportsAccess: false });

    renderWithProviders(
      <Routes>
        <Route element={<RequireReportsAccess />}>
          <Route path="/reports" element={<p>Rapports STR confidentiels</p>} />
        </Route>
        <Route path="/alerts" element={<p>Page Alertes</p>} />
      </Routes>,
      '/reports',
    );

    expect(screen.getByText('Page Alertes')).toBeInTheDocument();
    expect(screen.queryByText('Rapports STR confidentiels')).not.toBeInTheDocument();
  });

  it('rend la page quand hasReportsAccess est vrai', () => {
    mockAuth({ isAuthenticated: true, hasReportsAccess: true });

    renderWithProviders(
      <Routes>
        <Route element={<RequireReportsAccess />}>
          <Route path="/reports" element={<p>Rapports STR</p>} />
        </Route>
      </Routes>,
      '/reports',
    );

    expect(screen.getByText('Rapports STR')).toBeInTheDocument();
  });
});
