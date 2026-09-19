import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './auth/AuthContext';
import { RequireAuth, RequireReportsAccess } from './routes/guards';
import { LoginPage } from './pages/LoginPage';
import { AlertsPage } from './pages/AlertsPage';
import { ReportsPage } from './pages/ReportsPage';

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            <Route element={<RequireAuth />}>
              <Route path="/alerts" element={<AlertsPage />} />
              <Route element={<RequireReportsAccess />}>
                <Route path="/reports" element={<ReportsPage />} />
              </Route>
            </Route>

            <Route path="/" element={<Navigate to="/alerts" replace />} />
            <Route path="*" element={<Navigate to="/alerts" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
