import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider } from '../../../src/auth/AuthContext';
import { LoginForm } from '../../../src/components/auth/LoginForm';
import { makeFakeJwt } from '../../testUtils/makeFakeJwt';

function renderLoginForm(onLoginSuccess = vi.fn()) {
  return { onLoginSuccess, ...render(
    <AuthProvider>
      <LoginForm onLoginSuccess={onLoginSuccess} />
    </AuthProvider>,
  ) };
}

describe('LoginForm', () => {
  it('le formulaire email/mot de passe est désactivé (endpoint absent)', () => {
    renderLoginForm();
    expect(screen.getByLabelText('Identifiant')).toBeDisabled();
    expect(screen.getByLabelText('Mot de passe')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Se connecter' })).toBeDisabled();
  });

  it('le mode développeur est masqué par défaut', () => {
    renderLoginForm();
    expect(screen.queryByLabelText(/Coller un token JWT/)).not.toBeInTheDocument();
  });

  it('connecte avec succès via un token valide en mode développeur', async () => {
    const user = userEvent.setup();
    const { onLoginSuccess } = renderLoginForm();

    await user.click(screen.getByText('Afficher le mode développeur'));
    const validToken = makeFakeJwt({ sub: 'agent@bankily.mr', exp: Math.floor(Date.now() / 1000) + 3600 });
    await user.type(screen.getByLabelText(/Coller un token JWT/), validToken);
    await user.click(screen.getByRole('button', { name: 'Se connecter avec ce token' }));

    expect(onLoginSuccess).toHaveBeenCalledOnce();
  });

  it('affiche une erreur explicite pour un token invalide, sans appeler onLoginSuccess', async () => {
    const user = userEvent.setup();
    const { onLoginSuccess } = renderLoginForm();

    await user.click(screen.getByText('Afficher le mode développeur'));
    await user.type(screen.getByLabelText(/Coller un token JWT/), 'pas-un-token');
    await user.click(screen.getByRole('button', { name: 'Se connecter avec ce token' }));

    expect(await screen.findByText('Token invalide ou expiré.')).toBeInTheDocument();
    expect(onLoginSuccess).not.toHaveBeenCalled();
  });
});
