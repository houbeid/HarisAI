import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatCard } from '../../../src/components/ui/StatCard';

describe('StatCard', () => {
  it('affiche la valeur et le libellé', () => {
    render(<StatCard value={8} label="alertes en attente" />);
    expect(screen.getByText('8')).toBeInTheDocument();
    expect(screen.getByText('alertes en attente')).toBeInTheDocument();
  });
});
