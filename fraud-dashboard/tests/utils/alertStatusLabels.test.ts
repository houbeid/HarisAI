import { describe, it, expect } from 'vitest';
import { alertStatusLabel, alertStatusTone } from '../../src/utils/alertStatusLabels';

describe('alertStatusLabels', () => {
  it.each([
    ['Pending', 'En attente', 'neutral'],
    ['Confirmed', 'Confirmée', 'info'],
    ['Dismissed', 'Écartée', 'muted'],
  ] as const)('"%s" -> libellé "%s" et ton "%s"', (status, label, tone) => {
    expect(alertStatusLabel(status)).toBe(label);
    expect(alertStatusTone(status)).toBe(tone);
  });
});