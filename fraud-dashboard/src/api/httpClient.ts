import { env } from '../config/env';
import { getToken } from '../auth/tokenStore';
import type { ApiErrorCode, ApiErrorResponse } from '../types/alerts';

/**
 * Client HTTP unique de l'application. Centralise ce que le skill
 * react-frontend-builder interdit de dupliquer : base URL, header
 * Authorization, gestion d'erreur. Aucun composant ni aucun autre module
 * ne doit appeler fetch() directement vers fraud-backend.
 *
 * Le token vient de auth/tokenStore.ts, PAS d'un point d'injection local :
 * alertHubClient a besoin du même token, un seul endroit doit donc en être
 * la source (voir tokenStore.ts pour le raisonnement complet).
 */

// -----------------------------------------------------------------------
// Erreur typée — distingue explicitement une erreur métier connue
// (ApiErrorCode) d'une erreur réseau/parsing imprévue, pour que
// l'appelant (ex: le formulaire de validation d'alerte) puisse réagir
// différemment à un 409 qu'à une coupure réseau.
// -----------------------------------------------------------------------
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: ApiErrorCode,
    public readonly details: string[] | null,
  ) {
    super(`Erreur API ${status} : ${code}`);
    this.name = 'ApiError';
  }
}

export class NetworkError extends Error {
  constructor(cause: unknown) {
    super('Impossible de joindre fraud-backend');
    this.name = 'NetworkError';
    this.cause = cause;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  searchParams?: Record<string, string | number | undefined>;
}

function buildUrl(path: string, searchParams?: RequestOptions['searchParams']): string {
  const url = new URL(path, env.apiBaseUrl);
  if (searchParams) {
    for (const [key, value] of Object.entries(searchParams)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function request<TResponse>(path: string, options: RequestOptions = {}): Promise<TResponse> {
  const { method = 'GET', body, searchParams } = options;
  const token = getToken();

  let response: Response;
  try {
    response = await fetch(buildUrl(path, searchParams), {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (cause) {
    // fetch() ne rejette que sur une vraie panne réseau (DNS, timeout, CORS
    // bloqué) — jamais sur un statut HTTP d'erreur, géré ci-dessous.
    throw new NetworkError(cause);
  }

  if (!response.ok) {
    // Le contrat garantit que TOUTE erreur (400/404/409/500) suit la même
    // forme ApiErrorResponse — voir GlobalExceptionMiddleware. Si jamais ce
    // n'est pas le cas (ex: 401 du pipeline d'auth avant d'atteindre le
    // middleware), on ne suppose pas la forme : on retombe sur un code
    // générique plutôt que de laisser .json() planter silencieusement.
    let parsed: ApiErrorResponse;
    try {
      parsed = (await response.json()) as ApiErrorResponse;
    } catch {
      parsed = { error: 'internal_server_error', details: null };
    }
    throw new ApiError(response.status, parsed.error, parsed.details);
  }

  return (await response.json()) as TResponse;
}

export const httpClient = {
  get: <TResponse>(path: string, searchParams?: RequestOptions['searchParams']) =>
    request<TResponse>(path, { method: 'GET', searchParams }),
  post: <TResponse>(path: string, body: unknown) => request<TResponse>(path, { method: 'POST', body }),
};