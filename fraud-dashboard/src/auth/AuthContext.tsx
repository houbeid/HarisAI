import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { jwtDecode } from 'jwt-decode';
import { setToken as setStoredToken } from './tokenStore';

/**
 * Couche React au-dessus de tokenStore.ts. Ne dépend PAS de
 * realtime/alertHubClient — connecter/déconnecter le Hub SignalR est une
 * responsabilité des pages/composants métier qui observent isAuthenticated,
 * pas de ce contexte (Auth et Realtime sont deux couches sœurs, voir
 * l'architecture validée : ni l'une ni l'autre ne doit dépendre de l'autre).
 *
 * POINT OUVERT MAJEUR (voir FRONTEND_STARTER_PACK.md) : aucun endpoint
 * d'émission de token n'existe côté backend à ce jour. Ce contexte expose
 * donc `loginWithToken(token)` — il prend un JWT déjà émis, il ne sait pas
 * lui-même en obtenir un. La page de login (couche pages, plus tard) devra
 * soit désactiver la vraie soumission en attendant l'endpoint, soit
 * permettre une saisie manuelle de token en dev (voir BuildJwt des tests
 * backend comme référence de format : issuer, audience, claim "sub",
 * HMAC-SHA256).
 *
 * POINT OUVERT SECONDAIRE : le nom du claim de rôle n'est confirmé nulle
 * part dans le pack de contrats (seul "sub" est documenté explicitement,
 * lu littéralement grâce à MapInboundClaims=false côté backend). On
 * suppose ici un claim "role" — un seul endroit à changer (ROLE_CLAIM
 * ci-dessous) si le vrai format diffère une fois l'émission de token
 * implémentée.
 */

const ROLE_CLAIM = 'role';

interface DecodedToken {
  sub: string;
  exp: number;
  [ROLE_CLAIM]?: string | string[];
}

interface AuthState {
  token: string | null;
  agentId: string | null; // claim "sub" littéral — probablement un email, voir confirmedBy
  roles: string[];
}

interface AuthContextValue extends AuthState {
  isAuthenticated: boolean;
  hasReportsAccess: boolean;
  loginWithToken: (token: string) => boolean;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function decodeSafely(token: string): DecodedToken | null {
  try {
    return jwtDecode<DecodedToken>(token);
  } catch {
    return null;
  }
}

function isExpired(decoded: DecodedToken): boolean {
  return decoded.exp * 1000 <= Date.now();
}

function rolesOf(decoded: DecodedToken): string[] {
  const raw = decoded[ROLE_CLAIM];
  if (!raw) return [];
  return Array.isArray(raw) ? raw : [raw];
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Toujours initialisé à "non authentifié" — le token ne vit qu'en
  // mémoire (voir tokenStore.ts), donc un rechargement de page perd
  // nécessairement la session. Pas un bug à corriger ici.
  const [state, setState] = useState<AuthState>({ token: null, agentId: null, roles: [] });

  const logout = useCallback(() => {
    setStoredToken(null);
    setState({ token: null, agentId: null, roles: [] });
  }, []);

  const loginWithToken = useCallback(
    (token: string): boolean => {
      const decoded = decodeSafely(token);
      if (!decoded || isExpired(decoded)) {
        // Décision volontaire : un token invalide ou déjà expiré au moment
        // de la connexion échoue silencieusement vers l'état déconnecté ;
        // c'est à l'appelant (LoginForm) d'afficher l'UI d'erreur en
        // réagissant à la valeur de retour, pas à ce contexte de le faire.
        logout();
        return false;
      }
      setStoredToken(token);
      setState({ token, agentId: decoded.sub, roles: rolesOf(decoded) });
      return true;
    },
    [logout],
  );

  // Déconnexion automatique à l'expiration — pas seulement une vérification
  // paresseuse à la prochaine requête. Un agent qui laisse un onglet ouvert
  // doit être redirigé vers /login (état "session expirée") sans attendre
  // qu'il déclenche une action.
  useEffect(() => {
    if (!state.token) return;
    const decoded = decodeSafely(state.token);
    if (!decoded) return;
    const msUntilExpiry = decoded.exp * 1000 - Date.now();
    const timer = setTimeout(logout, Math.max(msUntilExpiry, 0));
    return () => clearTimeout(timer);
  }, [state.token, logout]);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      isAuthenticated: state.token !== null,
      hasReportsAccess: state.roles.includes('compliance_officer') || state.roles.includes('supervisor'),
      loginWithToken,
      logout,
    }),
    [state, loginWithToken, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth doit être utilisé à l\'intérieur de <AuthProvider>');
  }
  return ctx;
}
