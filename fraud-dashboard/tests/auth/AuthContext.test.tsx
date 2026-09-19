import { describe, it, expect, vi } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import { makeFakeJwt } from '../testUtils/makeFakeJwt';

function nowSeconds(offsetSeconds: number): number {
  return Math.floor(Date.now() / 1000) + offsetSeconds;
}

function Probe() {
  const { isAuthenticated, hasReportsAccess, agentId, loginWithToken, logout } = useAuth();
  return (
    <div>
      <span data-testid="auth">{String(isAuthenticated)}</span>
      <span data-testid="reports">{String(hasReportsAccess)}</span>
      <span data-testid="agent">{agentId ?? 'none'}</span>
      <button
        onClick={() => loginWithToken(makeFakeJwt({ sub: 'agent@bankily.mr', role: 'supervisor', exp: nowSeconds(3600) }))}
      >
        login-valide-superviseur
      </button>
      <button onClick={() => loginWithToken(makeFakeJwt({ sub: 'agent@bankily.mr', exp: nowSeconds(3600) }))}>
        login-valide-sans-role
      </button>
      <button onClick={() => loginWithToken(makeFakeJwt({ sub: 'x', exp: nowSeconds(-10) }))}>
        login-expire
      </button>
      <button onClick={() => loginWithToken(makeFakeJwt({ sub: 'court@bankily.mr', exp: nowSeconds(2) }))}>
        login-courte-duree
      </button>
      <button onClick={() => loginWithToken('pas-un-jwt')}>login-invalide</button>
      <button onClick={logout}>logout</button>
    </div>
  );
}

function renderProbe() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

describe('AuthContext', () => {
  it('démarre toujours non authentifié (token en mémoire uniquement)', () => {
    renderProbe();
    expect(screen.getByTestId('auth')).toHaveTextContent('false');
  });

  it('authentifie avec un token valide et expose le claim sub comme agentId', async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByText('login-valide-superviseur'));

    expect(screen.getByTestId('auth')).toHaveTextContent('true');
    expect(screen.getByTestId('agent')).toHaveTextContent('agent@bankily.mr');
  });

  it('accorde hasReportsAccess pour le rôle supervisor, pas sans rôle', async () => {
    const user = userEvent.setup();
    renderProbe();

    await user.click(screen.getByText('login-valide-sans-role'));
    expect(screen.getByTestId('reports')).toHaveTextContent('false');

    await user.click(screen.getByText('logout'));
    await user.click(screen.getByText('login-valide-superviseur'));
    expect(screen.getByTestId('reports')).toHaveTextContent('true');
  });

  it('refuse un token expiré et reste non authentifié', async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByText('login-expire'));

    expect(screen.getByTestId('auth')).toHaveTextContent('false');
  });

  it('refuse un token structurellement invalide', async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByText('login-invalide'));

    expect(screen.getByTestId('auth')).toHaveTextContent('false');
  });

  it('logout ramène à l\'état non authentifié', async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByText('login-valide-superviseur'));
    expect(screen.getByTestId('auth')).toHaveTextContent('true');

    await user.click(screen.getByText('logout'));
    expect(screen.getByTestId('auth')).toHaveTextContent('false');
    expect(screen.getByTestId('agent')).toHaveTextContent('none');
  });

  it("déconnecte automatiquement à l'expiration exacte du token, SANS action de l'agent", () => {
    // Timers simulés : on ne veut pas attendre 2 vraies secondes dans la
    // suite de tests, et surtout on veut avancer le temps de façon
    // déterministe plutôt que d'espérer qu'un vrai setTimeout se déclenche
    // à temps dans l'environnement CI. fireEvent (pas userEvent) est
    // utilisé ici car userEvent dépend de vrais timers par défaut.
    vi.useFakeTimers();
    try {
      renderProbe();
      fireEvent.click(screen.getByText('login-courte-duree'));
      expect(screen.getByTestId('auth')).toHaveTextContent('true');

      act(() => {
        vi.advanceTimersByTime(2_500); // dépasse l'exp de 2s posée dans Probe
      });

      expect(screen.getByTestId('auth')).toHaveTextContent('false');
      expect(screen.getByTestId('agent')).toHaveTextContent('none');
    } finally {
      vi.useRealTimers();
    }
  });
});
