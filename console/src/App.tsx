import { Link, Route, Routes } from 'react-router-dom';
import { RequireRole } from './auth/RequireRole';
import { Layout } from './layout/Layout';
import { Demo } from './pages/Demo';
import { Login } from './pages/Login';
import { ConversationDetailPage } from './conversations/ConversationDetailPage';
import { ConversationsPage } from './conversations/ConversationsPage';
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
        <Route path="conversations" element={<ConversationsPage />} />
        <Route path="conversations/:conversationId" element={<ConversationDetailPage />} />
        <Route path="demo" element={<Demo />} />
        <Route
          path="*"
          element={
            <p className="text-muted-foreground">
              Page not found.{' '}
              <Link to="/" className="font-semibold text-primary hover:underline">
                Back to orders
              </Link>
            </p>
          }
        />
      </Route>
    </Routes>
  );
}
