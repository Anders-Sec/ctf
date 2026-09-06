import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { useSession } from "./session";
import Spinner from "../components/Spinner";

/**
 * Gates a route on being signed in, and on the first-run flow being finished.
 *
 * The client-side check is convenience only — every one of these routes is
 * independently enforced by the API. A tampered client gets a 403, not access.
 */
export function RequireAuth({
  children,
  staffOnly = false,
  adminOnly = false,
}: {
  children: ReactNode;
  staffOnly?: boolean;
  adminOnly?: boolean;
}) {
  const { me, isLoading } = useSession();
  const location = useLocation();

  if (isLoading) return <Spinner label="Checking your torch…" />;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;

  if (adminOnly && !me.capabilities.administer) return <Navigate to="/" replace />;
  if (staffOnly && !me.capabilities.view_admin) return <Navigate to="/" replace />;

  return <>{children}</>;
}
