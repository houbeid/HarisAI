import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { AlertList } from '../components/alerts/AlertList';
import { AlertDetailPanel } from '../components/alerts/AlertDetailPanel';
import type { AlertListItem } from '../types/alerts';

export function AlertsPage() {
  const [selectedAlert, setSelectedAlert] = useState<AlertListItem | null>(null);
  const queryClient = useQueryClient();

  return (
    <>
      <AlertList onSelectAlert={setSelectedAlert} />
      <AlertDetailPanel
        alert={selectedAlert}
        onClose={() => setSelectedAlert(null)}
        onValidated={() => {
          // Invalide TOUTES les requêtes 'alerts' (En attente, Traitées/
          // Toutes, et le compteur de la Sidebar) — plus simple et plus
          // sûr qu'essayer de deviner précisément laquelle a changé.
          queryClient.invalidateQueries({ queryKey: ['alerts'] });
        }}
      />
    </>
  );
}
