import '@testing-library/jest-dom/vitest';
import { beforeAll, afterEach, afterAll } from 'vitest';
import { server } from './mocks/server';

// env.ts valide au chargement du module (fail-fast voulu en production —
// voir config/env.ts). Les tests unitaires qui importent des modules
// dépendant transitivement de httpClient (même mockés) ont donc besoin
// de ces variables présentes, sinon l'import du VRAI module échoue avant
// que vi.mock() ne prenne effet. Valeurs factices, jamais lues réellement
// puisque alertsApi/httpClient sont mockés dans les tests concernés.
import.meta.env.VITE_API_BASE_URL = 'http://localhost:5000';
import.meta.env.VITE_SIGNALR_URL = 'http://localhost:5000';

// Serveur MSW démarré pour TOUTE la suite. Sans effet sur les tests qui
// mockent alertsApi/reportsApi au niveau du module (fetch n'est jamais
// appelé dans ce cas) — actif uniquement pour tests/integration/, où le
// vrai httpClient tourne contre ce faux réseau.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());