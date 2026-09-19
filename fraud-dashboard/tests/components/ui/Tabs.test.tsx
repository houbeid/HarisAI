import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Tabs } from '../../../src/components/ui/Tabs';

const options = [
  { value: 'pending' as const, label: 'En attente' },
  { value: 'done' as const, label: 'Traitées' },
];

describe('Tabs', () => {
  it('marque le bon onglet comme sélectionné via aria-selected', () => {
    render(<Tabs options={options} value="pending" onChange={vi.fn()} />);
    expect(screen.getByRole('tab', { name: 'En attente' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Traitées' })).toHaveAttribute('aria-selected', 'false');
  });

  it('appelle onChange avec la value du tab cliqué', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Tabs options={options} value="pending" onChange={onChange} />);

    await user.click(screen.getByRole('tab', { name: 'Traitées' }));

    expect(onChange).toHaveBeenCalledWith('done');
  });
});
