import { Route, Routes } from 'react-router-dom';
import { RequireRole } from './auth/RequireRole';
import { Layout } from './layout/Layout';
import { Login } from './pages/Login';
import { InboxPage } from './orders/InboxPage';
import { OrderDetailPage } from './orders/OrderDetailPage';

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireRole>
            <Layout />
          </RequireRole>
        }
      >
        <Route index element={<InboxPage />} />
        <Route path="orders/:orderId" element={<OrderDetailPage />} />
      </Route>
    </Routes>
  );
}
