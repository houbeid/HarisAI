import { useNavigate } from 'react-router-dom';
import { LoginForm } from '../components/auth/LoginForm';

export function LoginPage() {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-gray-50">
      <LoginForm onLoginSuccess={() => navigate('/alerts')} />
    </div>
  );
}
