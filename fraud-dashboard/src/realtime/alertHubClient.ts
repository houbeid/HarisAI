import * as signalR from '@microsoft/signalr';
import { env } from '../config/env';
import { getToken } from '../auth/tokenStore';
import type { ReceiveAlertPayload } from '../types/realtime';

/**
 * Wrapper autour de @microsoft/signalr pour /alertHub. Un seul consommateur
 * prévu (le contexte d'alertes temps réel côté composants métier) — pas de
 * multiplexing d'événements au-delà de "ReceiveAlert", le seul documenté
 * dans le pack de contrats.
 *
 * RAPPEL CONTRACTUEL (voir types/realtime.ts) : ce flux ne couvre PAS les
 * alertes créées par le Worker en arrière-plan (NoOpAlertNotifier). Tout
 * code consommant ce client DOIT être doublé d'un rafraîchissement
 * périodique via alertsApi.getAlerts — jamais utilisé comme unique source.
 */

let connection: signalR.HubConnection | null = null;

function getConnection(): signalR.HubConnection {
  if (!connection) {
    connection = new signalR.HubConnectionBuilder()
      .withUrl(`${env.signalRUrl}/alertHub`, {
        // accessTokenFactory est appelé à chaque (re)négociation, pas une
        // seule fois à la création — donc toujours le token le plus
        // récent du tokenStore, y compris après un refresh de session.
        accessTokenFactory: () => getToken() ?? '',
      })
      .withAutomaticReconnect()
      .build();
  }
  return connection;
}

export async function connectAlertHub(): Promise<void> {
  const conn = getConnection();
  if (conn.state === signalR.HubConnectionState.Disconnected) {
    await conn.start();
  }
}

export async function disconnectAlertHub(): Promise<void> {
  if (connection && connection.state !== signalR.HubConnectionState.Disconnected) {
    await connection.stop();
  }
}

/**
 * Retourne une fonction de désinscription — même convention que les
 * listeners DOM/React (useEffect cleanup), pour que le composant appelant
 * n'ait jamais à connaître l'API interne de signalR.HubConnection.
 */
export function onReceiveAlert(callback: (payload: ReceiveAlertPayload) => void): () => void {
  const conn = getConnection();
  conn.on('ReceiveAlert', callback);
  return () => conn.off('ReceiveAlert', callback);
}