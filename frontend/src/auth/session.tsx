import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, type ReactNode } from "react";

import { ApiError } from "../api/client";
import { getMe, type Capabilities, type Me } from "../api/auth";

interface SessionValue {
  me: Me | null;
  isLoading: boolean;
  /** Reload after anything that changes status, role or party membership. */
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["me"],
    queryFn: getMe,
    // A 401 here means "not signed in", which is an answer, not a failure.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 401) && failureCount < 2,
    // Capabilities depend on the server clock (the event may have started),
    // so this is re-checked periodically rather than cached for the session.
    refetchInterval: 60_000,
  });

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["me"] });
  }, [queryClient]);

  const me = query.data ?? null;

  return (
    <SessionContext.Provider value={{ me, isLoading: query.isPending, refresh }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used inside a SessionProvider");
  }
  return value;
}

export function useCapabilities(): Capabilities | null {
  return useSession().me?.capabilities ?? null;
}
