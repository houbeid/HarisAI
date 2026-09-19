import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Drawer } from '../../../src/components/ui/Drawer';

describe('Drawer', () => {
  it("ne rend rien quand open est false", () => {
    render(
      <Drawer open={false} onClose={vi.fn()} title="Détail">
        <p>Contenu</p>
      </Drawer>,
    );
    expect(screen.queryByText('Contenu')).not.toBeInTheDocument();
  });

  it('affiche le titre et le contenu quand open', () => {
    render(
      <Drawer open onClose={vi.fn()} title="Détail de l'alerte">
        <p>Contenu</p>
      </Drawer>,
    );
    expect(screen.getByRole('dialog', { name: "Détail de l'alerte" })).toBeInTheDocument();
    expect(screen.getByText('Contenu')).toBeInTheDocument();
  });

  it('appelle onClose au clic sur le bouton de fermeture', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="Détail">
        <p>Contenu</p>
      </Drawer>,
    );
    await user.click(screen.getByRole('button', { name: 'Fermer' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('appelle onClose à la touche Échap', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="Détail">
        <p>Contenu</p>
      </Drawer>,
    );
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledOnce();
  });
});
