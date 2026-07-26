import type { ButtonHTMLAttributes } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary';
}

/**
 * Deux variantes suffisent pour couvrir la maquette actuelle :
 * - primary   : "Valider la décision", "Retour à la liste" (solide, foncé)
 * - secondary : "Confirmer la fraude", "Écarter l'alerte" (contour)
 * L'état disabled utilise l'attribut natif `disabled` + les pseudo-classes
 * Tailwind `disabled:*` — pas de prop `isLoading`/`isDisabled` custom qui
 * dupliquerait ce que le HTML fait déjà nativement.
 */
export function Button({ variant = 'primary', className = '', ...props }: ButtonProps) {
  const base = 'rounded-md px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed';
  const variants: Record<NonNullable<ButtonProps['variant']>, string> = {
    primary: 'bg-gray-900 text-white hover:bg-gray-800 disabled:bg-gray-200 disabled:text-gray-400',
    secondary:
      'border border-gray-300 bg-white text-gray-900 hover:bg-gray-50 disabled:border-gray-200 disabled:text-gray-400',
  };

  return <button className={`${base} ${variants[variant]} ${className}`} {...props} />;
}
