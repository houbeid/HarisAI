import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Button } from '../../../src/components/ui/Button';

describe('Button', () => {
  it('déclenche onClick au clic quand actif', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Valider</Button>);

    await user.click(screen.getByRole('button', { name: 'Valider' }));

    expect(onClick).toHaveBeenCalledOnce();
  });

  it("n'appelle jamais onClick quand disabled — pas juste une classe visuelle", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabled>
        Valider
      </Button>,
    );

    await user.click(screen.getByRole('button', { name: 'Valider' }));

    expect(onClick).not.toHaveBeenCalled();
  });

  it('applique la variante secondary demandée', () => {
    render(<Button variant="secondary">Écarter</Button>);
    expect(screen.getByRole('button', { name: 'Écarter' })).toHaveClass('border-gray-300');
  });
});
