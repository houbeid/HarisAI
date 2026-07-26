/**
 * Source unique du token JWT courant. Volontairement sans dépendance React :
 * httpClient et alertHubClient en ont besoin tous les deux, et aucun des
 * deux ne doit dépendre de AuthContext (couche React, construite après).
 * AuthContext sera le SEUL écrivain (setToken), tout le reste ne fait que lire.
 *
 * Décision de sécurité à documenter explicitement, pas un détail anodin
 * (voir react-frontend-builder, anti-patterns) : le token vit uniquement
 * en mémoire (variable de module), jamais dans localStorage/sessionStorage.
 * Un token en mémoire ne survit pas à un rafraîchissement de page — c'est
 * un compromis assumé pour réduire la surface d'exposition XSS, pas un
 * oubli. AuthContext devra donc gérer une re-authentification silencieuse
 * ou une redirection vers /login à chaque rechargement complet de l'app.
 */

let currentToken: string | null = null;

export function getToken(): string | null {
  return currentToken;
}

export function setToken(token: string | null): void {
  currentToken = token;
}