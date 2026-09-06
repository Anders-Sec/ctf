import { Route, Routes } from "react-router-dom";

import StatusPage from "./routes/StatusPage";

/**
 * Route table. Spec 001 has exactly one page; specs 002+ add login, the
 * challenge board, the scoreboard and the party screen here.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<StatusPage />} />
    </Routes>
  );
}
