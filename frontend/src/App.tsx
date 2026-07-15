import { Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import AppShell from "./layout/AppShell";
import { APP_ROUTES } from "./navigation/routes";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  return (
    <AppShell>
      <Suspense fallback={<div className="route-loading" role="status" aria-live="polite">页面加载中</div>}>
        <Routes>
          {APP_ROUTES.map((route) => (
            <Route key={route.id} path={route.path} element={route.element} />
          ))}
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
