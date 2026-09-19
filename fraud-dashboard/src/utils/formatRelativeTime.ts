/**
 * Règles calées sur les captures maquette : "il y a 18 min", "il y a 2 h"
 * pour le récent ; au-delà de 24h, une date absolue sans préfixe "il y a"
 * (voir Rapports STR : "23/07 14:10", "20/07 09:05").
 */
export function formatRelativeTime(isoString: string, now: Date = new Date()): string {
  const then = new Date(isoString);
  const diffMs = now.getTime() - then.getTime();
  const diffMin = Math.floor(diffMs / 60_000);

  if (diffMin < 1) return "à l'instant";
  if (diffMin < 60) return `il y a ${diffMin} min`;

  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `il y a ${diffH} h`;

  const day = String(then.getDate()).padStart(2, '0');
  const month = String(then.getMonth() + 1).padStart(2, '0');
  const hours = String(then.getHours()).padStart(2, '0');
  const minutes = String(then.getMinutes()).padStart(2, '0');
  return `${day}/${month} ${hours}:${minutes}`;
}