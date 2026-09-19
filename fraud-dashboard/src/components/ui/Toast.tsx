import type { ReactNode } from 'react';

interface ToastProps {
  message: ReactNode;
  onDismiss: () => void;
  icon?: ReactNode;
}

/**
 * Purement présentationnel — ne sait pas d'où vient le message (SignalR,
 * polling, ou autre). Le composant métier décide QUAND l'afficher et QUOI
 * y mettre ("3 nouvelles alertes reçues en direct" est composé ailleurs).
 */
export function Toast({ message, onDismiss, icon }: ToastProps) {
  return (
    <div className="fixed right-6 top-6 z-50 flex items-center gap-3 rounded-lg bg-gray-900 px-4 py-3 text-sm text-white shadow-lg">
      {icon}
      <span>{message}</span>
      <button
        aria-label="Fermer la notification"
        onClick={onDismiss}
        className="text-gray-400 hover:text-white"
      >
        ✕
      </button>
    </div>
  );
}
