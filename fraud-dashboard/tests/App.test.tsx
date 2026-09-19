import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../src/App';
import { makeFakeJwt } from './testUtils/makeFakeJwt';

/**
 * Contrairement à guards.test.tsx (qui teste RequireAuth/RequireReportsAccess
 * isolément avec un useAuth mocké), ce fichier fait tourner le VRAI
 * AuthProvider, le VRAI routage BrowserRouter, et les VRAIS appels réseau
 * (via les handlers MSW par défaut de tests/mocks/handlers.ts). Seul
 * alertHubClient est mocké — une vraie connexion SignalR/WebSocket n'a
 * aucun sens dans un test.
 */
vi.mock('../src/realtime/alertHubClient');

function validToken(overrides: Record<string, unknown> = {}) {
  return makeFakeJwt({
    sub: 'agent@bankily.mr',
    exp: Math.floor(Date.now() / 1000) + 3600,
    ...overrides,
  });
}

async function loginViaDevMode(token: string) {
  const user = userEvent.setup();
  await user.click(screen.getByText('Afficher le mode développeur'));
  await user.type(screen.getByLabelText(/Coller un token JWT/), token);
  await user.click(screen.getByRole('button', { name: 'Se connecter avec ce token' }));
}

describe('App — routage bout en bout', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/');
  });

  it('un visiteur non authentifié atterrit sur /login, quelle que soit la route demandée', () => {
    window.history.pushState({}, '', '/reports');
    render(<App />);
    expect(screen.getByText('Plateforme de conformité — accès agents')).toBeInTheDocument();
  });

  it('après connexion sans rôle privilégié : arrive sur Alertes, "Rapports STR" absent de la navigation', async () => {
    render(<App />);
    await loginViaDevMode(validToken());

    expect(await screen.findByText('Alertes de fraude')).toBeInTheDocument();
    expect(screen.queryByText('Rapports STR')).not.toBeInTheDocument();
  });

  it('après connexion avec le rôle supervisor : "Rapports STR" est accessible et affiche les vraies données réseau', async () => {
    render(<App />);
    // Email volontairement différent de celui du handler MSW pour
    // confirmedBy (agent@bankily.mr) : sinon "agent@bankily.mr" apparaît
    // deux fois à l'écran (identité Sidebar + colonne Agent du rapport),
    // et findByText échoue sur une correspondance ambiguë plutôt qu'absente.
    await loginViaDevMode(validToken({ sub: 'superviseur@harisai.mr', role: 'supervisor' }));
    await screen.findByText('Alertes de fraude');

    const user = userEvent.setup();
    await user.click(screen.getByText('Rapports STR'));

    // Donnée réelle renvoyée par le handler MSW par défaut (tests/mocks/handlers.ts),
    // pas une valeur codée en dur dans ce test.
    expect(await screen.findByText('agent@bankily.mr')).toBeInTheDocument();
  });

  // La redirection /reports -> /alerts pour un agent sans rôle privilégié
  // est déjà couverte de façon fiable et déterministe dans
  // tests/routes/guards.test.tsx (MemoryRouter) — pas dupliquée ici, où
  // simuler une navigation par URL directe avec BrowserRouter+jsdom serait
  // fragile (popstate ne se déclenche pas naturellement après pushState)
  // sans rien vérifier de plus que ce que guards.test.tsx prouve déjà.

  it('cycle complet connexion → déconnexion : ramène réellement à /login, pas juste un état interne', async () => {
    render(<App />);
    await loginViaDevMode(validToken());
    await screen.findByText('Alertes de fraude');

    const user = userEvent.setup();
    await user.click(screen.getByText('Se déconnecter'));

    // Vraie disparition du contenu protégé, pas juste apparition du login
    // à côté — la page Alertes ne doit plus être dans le DOM du tout.
    expect(await screen.findByText('Plateforme de conformité — accès agents')).toBeInTheDocument();
    expect(screen.queryByText('Alertes de fraude')).not.toBeInTheDocument();
  });
});
