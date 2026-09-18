import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth } from "./auth/RequireAuth";
import AdminLayout from "./components/AdminLayout";
import AppLayout from "./components/AppLayout";
import AdminAchievementsPage from "./routes/AdminAchievementsPage";
import AdminAnnouncementsPage from "./routes/AdminAnnouncementsPage";
import AdminAssistantPage from "./routes/AdminAssistantPage";
import AdminAuditPage from "./routes/AdminAuditPage";
import AdminChallengesPage from "./routes/AdminChallengesPage";
import AdminClassesPage from "./routes/AdminClassesPage";
import AdminDashboardPage from "./routes/AdminDashboardPage";
import AdminDataPage from "./routes/AdminDataPage";
import AdminEmailPage from "./routes/AdminEmailPage";
import AdminEventPage from "./routes/AdminEventPage";
import AdminExportPage from "./routes/AdminExportPage";
import AdminHealthPage from "./routes/AdminHealthPage";
import AdminInstancesPage from "./routes/AdminInstancesPage";
import AdminMapPage from "./routes/AdminMapPage";
import AdminMetricsPage from "./routes/AdminMetricsPage";
import AdminOpsPage from "./routes/AdminOpsPage";
import AdminPartiesPage from "./routes/AdminPartiesPage";
import AdminScoreboardPage from "./routes/AdminScoreboardPage";
import AdminSignalsPage from "./routes/AdminSignalsPage";
import AdminSkillsPage from "./routes/AdminSkillsPage";
import AdminTemplatesPage from "./routes/AdminTemplatesPage";
import AdminThemePage from "./routes/AdminThemePage";
import AdminUsersPage from "./routes/AdminUsersPage";
import ChallengeDetailPage from "./routes/ChallengeDetailPage";
import ChallengesPage from "./routes/ChallengesPage";
import CharacterSheetPage from "./routes/CharacterSheetPage";
import FirstRunPage from "./routes/FirstRunPage";
import HomePage from "./routes/HomePage";
import LoginPage from "./routes/LoginPage";
import MagicLinkPage from "./routes/MagicLinkPage";
import PartyPage from "./routes/PartyPage";
import ScoreboardPage from "./routes/ScoreboardPage";
import SettingsPage from "./routes/SettingsPage";
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
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/scoreboard" element={<ScoreboardPage />} />
        <Route path="/character" element={<CharacterSheetPage />} />
        <Route path="/character/:userId" element={<CharacterSheetPage />} />
        {/* The detail is a child route, so opening a challenge never unmounts
            the board behind it (spec 062 §5). Scroll position survives by
            construction, a deep link still works, and Back closes the overlay. */}
        <Route path="/challenges" element={<ChallengesPage />}>
          <Route path=":challengeId" element={<ChallengeDetailPage />} />
        </Route>

        {/*
         * The admin area (spec 049). One staff gate on the shell rather than
         * one per route: the previous arrangement repeated `RequireAuth
         * staffOnly` fourteen times, which is fourteen chances to forget it on
         * the fifteenth page.
         */}
        <Route
          path="/admin"
          element={
            <RequireAuth staffOnly>
              <AdminLayout />
            </RequireAuth>
          }
        >
          <Route index element={<AdminDashboardPage />} />

          {/* Operations */}
          <Route path="ops" element={<AdminOpsPage />} />
          <Route path="signals" element={<AdminSignalsPage />} />
          <Route path="metrics" element={<AdminMetricsPage />} />
          <Route path="assistant" element={<AdminAssistantPage />} />
          <Route path="instances" element={<AdminInstancesPage />} />
          <Route path="users" element={<AdminUsersPage />} />
          <Route path="parties" element={<AdminPartiesPage />} />
          <Route path="audit" element={<AdminAuditPage />} />
          <Route path="scoreboard" element={<AdminScoreboardPage />} />
          <Route path="announcements" element={<AdminAnnouncementsPage />} />
          <Route path="health" element={<AdminHealthPage />} />

          {/* Content */}
          <Route path="challenges" element={<AdminChallengesPage />} />
          <Route path="skills" element={<AdminSkillsPage />} />
          <Route path="classes" element={<AdminClassesPage />} />
          <Route path="achievements" element={<AdminAchievementsPage />} />
          <Route path="map" element={<AdminMapPage />} />

          {/* Settings */}
          <Route path="event" element={<AdminEventPage />} />
          <Route path="theme" element={<AdminThemePage />} />
          <Route path="templates" element={<AdminTemplatesPage />} />
          <Route path="email" element={<AdminEmailPage />} />
          <Route path="export" element={<AdminExportPage />} />
          <Route path="data" element={<AdminDataPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
