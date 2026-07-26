/**
 * Configuration d'environnement, injectée au build par site (Bankily,
 * Sedad, Masrvi) via Kustomize/variables Vite — voir
 * architecture_fraud_infrastructure.txt, kubernetes/overlays/{site}/.
 *
 * PAS de valeur par défaut codée en dur ici. Un fallback silencieux
 * (ex: "http://localhost:5000" par défaut) serait dangereux dans une
 * topologie on-premise isolée par site : un build mal configuré pointerait
 * vers le mauvais backend sans qu'aucune erreur ne le signale avant la
 * première requête réseau, potentiellement en production chez un opérateur.
 * On préfère échouer fort et tôt, au démarrage de l'app.
 */

function readRequiredEnvVar(key: string): string {
  const value = import.meta.env[key];
  if (!value) {
    throw new Error(
      `Variable d'environnement manquante : ${key}. ` +
        `Vérifier la configuration du site (overlay Kustomize ou .env local).`,
    );
  }
  return value;
}

export const env = {
  apiBaseUrl: readRequiredEnvVar('VITE_API_BASE_URL'),
  signalRUrl: readRequiredEnvVar('VITE_SIGNALR_URL'),
} as const;