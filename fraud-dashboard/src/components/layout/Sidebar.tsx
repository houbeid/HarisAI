import { NavLink, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../../auth/AuthContext';
import { alertsApi } from '../../api/alertsApi';

function roleLabel(roles: string[]): string {
  if (roles.includes('supervisor')) return 'Superviseur';
  if (roles.includes('compliance_officer')) return 'Compliance officer';
  return 'Agent de conformité';
}

export function Sidebar() {
  const { agentId, roles, hasReportsAccess, logout } = useAuth();
  const navigate = useNavigate();

  // POINT OUVERT : pas d'endpoint "compteur seul" côté contrat — on
  // demande pageSize=1 juste pour lire totalPending, qui reste correct
  // quel que soit pageSize (c'est un total serveur, pas une longueur de
  // tableau). Un peu de gaspillage réseau, mais pas de donnée inventée.
  const { data } = useQuery({
    queryKey: ['alerts', 'pending-count'],
    queryFn: () => alertsApi.getAlerts({ status: 'Pending', page: 1, pageSize: 1 }),
    refetchInterval: 30_000,
  });

  function handleLogout() {
    logout();
    navigate('/login');
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center justify-between rounded-md px-3 py-2 text-sm font-medium ${
      isActive ? 'bg-gray-800 text-white' : 'text-gray-300 hover:bg-gray-800/50'
    }`;

  return (
    <aside className="flex h-screen w-64 flex-col bg-gray-900 px-4 py-6">
      <div className="mb-8 flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded bg-blue-600 font-bold text-white">
          H
        </div>
        <span className="text-lg font-bold text-white">HarisAI</span>
      </div>

      <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
        Navigation
      </p>
      <nav className="flex flex-col gap-1">
        <NavLink to="/alerts" className={linkClass}>
          <span>Alertes</span>
          {data && (
            <span className="rounded-full bg-blue-600 px-2 py-0.5 text-xs text-white">
              {data.totalPending}
            </span>
          )}
        </NavLink>
        {/* Masqué (pas juste désactivé) pour un agent standard — cohérent
            avec la capture de la sidebar sans rôle privilégié. */}
        {hasReportsAccess && (
          <NavLink to="/reports" className={linkClass}>
            <span>Rapports STR</span>
          </NavLink>
        )}
      </nav>

      <div className="mt-auto border-t border-gray-800 pt-4">
        <div className="mb-2 flex items-center gap-2 px-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-700 text-xs font-semibold text-white">
            {agentId?.slice(0, 2).toUpperCase() ?? '??'}
          </div>
          <div>
            <div className="text-sm font-medium text-white">{agentId ?? 'Agent'}</div>
            <div className="text-xs text-gray-400">{roleLabel(roles)}</div>
          </div>
        </div>
        <button onClick={handleLogout} className="px-3 text-xs text-gray-500 hover:text-gray-300">
          Se déconnecter
        </button>
      </div>
    </aside>
  );
}
