import { describe, it, expect } from 'vitest';
import { fraudTypeLabel } from '../../src/utils/fraudTypeLabels';

describe('fraudTypeLabels', () => {
  it('traduit les types connus (documentation technique)', () => {
    expect(fraudTypeLabel('SIM_SWAPPING')).toBe('SIM swapping');
    expect(fraudTypeLabel('MULE_ACCOUNT')).toBe('Compte mule');
    expect(fraudTypeLabel('STRUCTURING')).toBe('Structuring');
  });

  it("humanise proprement une valeur NON documentée plutôt que de l'afficher brute ou de planter", () => {
    // Cas réel rencontré : la maquette a produit "ACCOUNT_TAKEOVER",
    // absent de la doc technique — exactement le scénario que ce repli
    // doit couvrir.
    expect(fraudTypeLabel('ACCOUNT_TAKEOVER')).toBe('Account takeover');
  });

  it('gère une valeur à un seul mot sans underscore', () => {
    expect(fraudTypeLabel('PHISHING')).toBe('Phishing');
  });
});