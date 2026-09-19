/**
 * jwt-decode ne vérifie JAMAIS la signature côté client (ce n'est pas son
 * rôle — seul le backend la vérifie). Un JWT "faux" mais structurellement
 * valide suffit donc à tester AuthContext, sans avoir besoin de la vraie
 * clé HMAC partagée du backend.
 */
function base64url(obj: unknown): string {
  return btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function makeFakeJwt(payload: Record<string, unknown>): string {
  const header = base64url({ alg: 'HS256', typ: 'JWT' });
  const body = base64url(payload);
  return `${header}.${body}.fakesignature`;
}
