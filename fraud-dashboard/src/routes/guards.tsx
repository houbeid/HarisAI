import { useEffect } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { Sidebar } from '../components/layout/Sidebar';
import { connectAlertHub, disconnectAlertHub } from '../realtime/alertHubClient';

/**
 * Layout des routes authentifiées : redirige vers /login si non connecté,
 * sinon rend la Sidebar + la page demandée (Outlet). Un seul endroit
 * décide de cette redirection — pas dupliqué dans chaque page. C'est
 * aussi ici, et seulement ici, que le hub SignalR se connecte/déconnecte
 * — une connexion pour toute la session authentifiée, pas une par page
 * qui se remonte à chaque navigation.
 */
export function RequireAuth() {
  const { isAuthenticated } = useAuth();

  useEffect(() => {
    if (!isAuthenticated) return;
    connectAlertHub();
    return () => {
      disconnectAlertHub();
    };
  }, [isAuthenticated]);

  if (!isAuthenticated) return <Navigate to="/login" replace />;

  return (
    <div className="flex">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-8">
        <Outlet />
      </main>
    </div>
  );
}

/**
 * Garde de rôle pour /reports : redirige vers /alerts si l'agent n'a pas
 * accès, plutôt que d'afficher une page d'erreur — cohérent avec le fait
 * que la Sidebar masque déjà ce lien pour un agent standard. Une
 * navigation directe (URL tapée à la main) doit avoir le même résultat
 * que le lien masqué, pas un comportement différent.
 */
export function RequireReportsAccess() {
  const { hasReportsAccess } = useAuth();
  if (!hasReportsAccess) return <Navigate to="/alerts" replace />;
  return <Outlet />;
}
