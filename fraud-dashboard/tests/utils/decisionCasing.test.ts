import { describe, it, expect, vi } from 'vitest';
import { normalizeDecision, decisionLabel, decisionTone } from '../../src/utils/decisionCasing';
import type { DecisionRaw } from '../../src/types/alerts';

describe('decisionCasing', () => {
  it.each([
    ['Approve', 'approve'],
    ['APPROVE', 'approve'],
    ['Review', 'review'],
    ['REVIEW', 'review'],
    ['Block', 'block'],
    ['BLOCK', 'block'],
  ] as const)('normalise "%s" en "%s"', (raw, expected) => {
    expect(normalizeDecision(raw)).toBe(expected);
  });

  it('affiche toujours le même libellé Pascal, peu importe la casse brute reçue', () => {
    expect(decisionLabel('REVIEW')).toBe('Review');
    expect(decisionLabel('Review')).toBe('Review');
  });

  it('associe la bonne catégorie de ton à chaque décision', () => {
    expect(decisionTone('BLOCK')).toBe('danger');
    expect(decisionTone('REVIEW')).toBe('warning');
    expect(decisionTone('APPROVE')).toBe('success');
  });

  it('ne plante jamais sur une valeur inattendue — logue une erreur et se replie sur "review"', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const result = normalizeDecision('CANCELLED' as DecisionRaw);

    expect(result).toBe('review');
    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });
});