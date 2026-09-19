import { useId, type TextareaHTMLAttributes } from 'react';

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
}

/**
 * useId() génère un id unique par instance — évite qu'un futur écran avec
 * deux TextArea (peu probable ici, mais pas coûteux à éviter) ne casse
 * l'association label/champ via un id en dur.
 */
export function TextArea({ label, className = '', ...props }: TextAreaProps) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-gray-700">
        {label}
      </label>
      <textarea
        id={id}
        className={`w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none ${className}`}
        {...props}
      />
    </div>
  );
}
