import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth } from "./auth/RequireAuth";
import AppLayout from "./components/AppLayout";
import AdminChallengesPage from "./routes/AdminChallengesPage";
import AdminUsersPage from "./routes/AdminUsersPage";
import ChallengeDetailPage from "./routes/ChallengeDetailPage";
import ChallengesPage from "./routes/ChallengesPage";
import FirstRunPage from "./routes/FirstRunPage";
import HomePage from "./routes/HomePage";
import LoginPage from "./routes/LoginPage";
import MagicLinkPage from "./routes/MagicLinkPage";
import PartyPage from "./routes/PartyPage";
import StatusPage from "./routes/StatusPage";

export default function App() {
  return (
    <Routes>
      {/* Unauthenticated */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/auth/magic-link" element={<MagicLinkPage />} />
      <Route path="/status" element={<StatusPage />} />

      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<HomePage />} />
        <Route path="/welcome" element={<FirstRunPage />} />
        <Route path="/party" element={<PartyPage />} />
        <Route path="/challenges" element={<ChallengesPage />} />
        <Route path="/challenges/:challengeId" element={<ChallengeDetailPage />} />
        <Route
          path="/admin/challenges"
          element={
            <RequireAuth staffOnly>
              <AdminChallengesPage />
            </RequireAuth>
          }
        />
        <Route
          path="/admin/users"
          element={
            <RequireAuth staffOnly>
              <AdminUsersPage />
            </RequireAuth>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
