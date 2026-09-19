import { useState } from 'react';
import { useAuth } from '../../auth/AuthContext';
import { Button } from '../ui/Button';

/**
 * POINT OUVERT MAJEUR (voir auth/AuthContext.tsx) : aucun endpoint
 * d'émission de token JWT n'existe côté backend. Le formulaire
 * email/mot de passe ci-dessous est fidèle à la maquette validée, mais
 * VOLONTAIREMENT désactivé — il ne fait rien tant que l'endpoint
 * n'existe pas. Le "Mode développeur" est le seul chemin réellement
 * fonctionnel aujourd'hui, à retirer (ou masquer en production via une
 * variable d'env) une fois le vrai login implémenté.
 */
export function LoginForm({ onLoginSuccess }: { onLoginSuccess: () => void }) {
  const { loginWithToken } = useAuth();
  const [devMode, setDevMode] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [tokenError, setTokenError] = useState<string | null>(null);

  function handleTokenSubmit() {
    const ok = loginWithToken(tokenInput.trim());
    if (ok) {
      onLoginSuccess();
    } else {
      setTokenError('Token invalide ou expiré.');
    }
  }

  return (
    <div className="mx-auto mt-24 max-w-sm rounded-lg border border-gray-200 bg-white p-8">
      <div className="mb-1 flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded bg-blue-600 font-bold text-white">
          H
        </div>
        <span className="text-lg font-bold text-gray-900">HarisAI</span>
      </div>
      <p className="mb-6 text-sm text-gray-500">Plateforme de conformité — accès agents</p>

      <form
        onSubmit={(e) => e.preventDefault()}
        aria-disabled="true"
        className="space-y-4"
      >
        <div>
          <label htmlFor="login-email" className="mb-1 block text-sm font-medium text-gray-700">
            Identifiant
          </label>
          <input
            id="login-email"
            type="email"
            placeholder="agent@harisai.mr"
            disabled
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-50 disabled:text-gray-400"
          />
        </div>
        <div>
          <label htmlFor="login-password" className="mb-1 block text-sm font-medium text-gray-700">
            Mot de passe
          </label>
          <input
            id="login-password"
            type="password"
            disabled
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-50 disabled:text-gray-400"
          />
        </div>
        <Button type="submit" disabled className="w-full">
          Se connecter
        </Button>
        <p className="text-center text-xs text-gray-400">
          Authentification pas encore disponible — l'émission de token n'existe pas encore côté
          backend.
        </p>
      </form>

      <div className="mt-6 border-t border-dashed border-gray-200 pt-4">
        <button
          type="button"
          onClick={() => setDevMode((v) => !v)}
          className="text-xs font-medium text-gray-500 underline"
        >
          {devMode ? 'Masquer' : 'Afficher'} le mode développeur
        </button>

        {devMode && (
          <div className="mt-3 space-y-2">
            <label htmlFor="dev-token" className="block text-xs font-medium text-gray-700">
              Coller un token JWT (voir BuildJwt des tests backend pour le format)
            </label>
            <textarea
              id="dev-token"
              value={tokenInput}
              onChange={(e) => {
                setTokenInput(e.target.value);
                setTokenError(null);
              }}
              rows={3}
              className="w-full rounded-md border border-gray-300 px-2 py-1 font-mono text-xs"
            />
            {tokenError && <p className="text-xs text-red-600">{tokenError}</p>}
            <Button variant="secondary" onClick={handleTokenSubmit} className="w-full">
              Se connecter avec ce token
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
