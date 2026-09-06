import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { verifyMagicLink } from "../api/auth";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/** Where the emailed link lands. Consumes the token and starts the session. */
export default function MagicLinkPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useSession();
  const [error, setError] = useState<unknown>(null);
  // Tokens are single-use, so React 18's double-invoked effects in development
  // would consume the token and then report it invalid on the second run.
  const attempted = useRef(false);

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setError(new Error("missing token"));
      return;
    }
    if (attempted.current) return;
    attempted.current = true;

    verifyMagicLink(token)
      .then(async () => {
        await refresh();
        navigate("/", { replace: true });
      })
      .catch(setError);
  }, [params, navigate, refresh]);

  if (error) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
        <h1 className="text-2xl font-semibold">That link did not work</h1>
        <ErrorMessage error={error} />
        <Link to="/login" className="underline">
          Request a new one
        </Link>
      </main>
    );
  }

  return <Spinner label="Unlocking the door…" />;
}
