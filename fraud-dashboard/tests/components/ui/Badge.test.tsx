import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Badge } from '../../../src/components/ui/Badge';
import { TONE_CLASSES, type Tone } from '../../../src/components/ui/toneStyles';

describe('Badge', () => {
  it('affiche le contenu passé en enfant', () => {
    render(<Badge tone="danger">Block</Badge>);
    expect(screen.getByText('Block')).toBeInTheDocument();
  });

  // Test paramétré sur les 6 tons plutôt que 6 tests séparés dupliqués —
  // le but est de garantir qu'AUCUN ton ne retombe silencieusement sur
  // les classes d'un autre (ex: un copier-coller mal terminé dans
  // toneStyles.ts), pas de vérifier le rendu visuel exact.
  const tones = Object.keys(TONE_CLASSES) as Tone[];

  it.each(tones)('applique les classes correctes pour le ton "%s"', (tone) => {
    render(<Badge tone={tone}>Test</Badge>);
    const badge = screen.getByText('Test');
    for (const className of TONE_CLASSES[tone].split(' ')) {
      expect(badge).toHaveClass(className);
    }
  });
});
