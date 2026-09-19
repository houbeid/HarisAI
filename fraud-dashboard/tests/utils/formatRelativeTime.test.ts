import { describe, it, expect } from 'vitest';
import { formatRelativeTime } from '../../src/utils/formatRelativeTime';

// "now" fixé explicitement — jamais new Date() sans argument ici, pour
// que ce test ne devienne pas flaky selon le moment où il tourne.
const NOW = new Date('2026-07-26T12:00:00Z');

function minutesAgo(min: number): string {
  return new Date(NOW.getTime() - min * 60_000).toISOString();
}

describe('formatRelativeTime', () => {
  it('affiche "à l\'instant" pour moins d\'une minute', () => {
    expect(formatRelativeTime(minutesAgo(0), NOW)).toBe("à l'instant");
  });

  it('affiche "il y a X min" en dessous de 60 minutes', () => {
    expect(formatRelativeTime(minutesAgo(18), NOW)).toBe('il y a 18 min');
    expect(formatRelativeTime(minutesAgo(59), NOW)).toBe('il y a 59 min');
  });

  it('affiche "il y a X h" en dessous de 24 heures', () => {
    expect(formatRelativeTime(minutesAgo(120), NOW)).toBe('il y a 2 h');
    expect(formatRelativeTime(minutesAgo(60 * 23), NOW)).toBe('il y a 23 h');
  });

  it('affiche une date absolue JJ/MM HH:mm au-delà de 24 heures, sans préfixe "il y a"', () => {
    const result = formatRelativeTime(minutesAgo(60 * 30), NOW); // 30h avant
    expect(result).not.toContain('il y a');
    expect(result).toMatch(/^\d{2}\/\d{2} \d{2}:\d{2}$/);
  });
});