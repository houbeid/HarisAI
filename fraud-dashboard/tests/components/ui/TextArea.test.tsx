import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TextArea } from '../../../src/components/ui/TextArea';

describe('TextArea', () => {
  it('associe le label au champ (accessible par son nom)', () => {
    render(<TextArea label="Note (optionnelle)" value="" onChange={vi.fn()} />);
    expect(screen.getByLabelText('Note (optionnelle)')).toBeInTheDocument();
  });

  it('déclenche onChange à la saisie', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TextArea label="Note" value="" onChange={onChange} />);

    await user.type(screen.getByLabelText('Note'), 'a');

    expect(onChange).toHaveBeenCalled();
  });
});
