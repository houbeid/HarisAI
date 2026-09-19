import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Toast } from '../../../src/components/ui/Toast';

describe('Toast', () => {
  it('affiche le message et appelle onDismiss au clic sur fermer', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<Toast message="3 nouvelles alertes reçues en direct" onDismiss={onDismiss} />);

    expect(screen.getByText('3 nouvelles alertes reçues en direct')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Fermer la notification' }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});
