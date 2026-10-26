import { NavLink, Outlet } from 'react-router-dom';
import logo from '../../../assets/brand/suppliagent_logo_light.svg';
import { useAuth } from '../auth/AuthContext';
import { isReadOnly } from '../auth/roles';

export function Layout() {
  const auth = useAuth();
  if (auth.status !== 'signedIn') return null; // always rendered under <RequireRole>
  const { user } = auth;
  return (
    <>
      <header className="topbar">
        <img src={logo} alt="SuppliAgent" className="logo" />
        <nav>
          <NavLink to="/" end>
            Orders
          </NavLink>
        </nav>
        <span className="who">
          {user.email} · {user.roles.join(', ')}
          {isReadOnly(user.roles) && <strong className="badge">Read-only</strong>}
        </span>
        <button type="button" onClick={() => void auth.signOut()}>
          Sign out
        </button>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </>
  );
}
