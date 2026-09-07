import { ApiError } from "../api/client";

/**
 * Renders our own copy per error code rather than echoing the server's prose,
 * so wording stays in the frontend where the Phase 3 personality pass lives.
 */
const MESSAGES: Record<string, string> = {
  already_in_party: "Leave your current party before joining another.",
  team_full: "That party is full — eight adventurers is the limit.",
  team_name_unavailable: "Another party has already claimed that name.",
  invalid_team_name:
    "That name will not do. Three to thirty-two characters, nothing staff-like.",
  invalid_party_password: "That password is not right.",
  join_request_required: "This party is private. Ask the leader to let you in.",
  not_party_leader: "Only the party leader can do that.",
  weak_party_password: "Party passwords need at least six characters.",
  invalid_or_expired_token:
    "That link has expired or was already used. Request a new one.",
  account_pending_approval: "Your account is still awaiting approval.",
  account_disabled: "Your account has been disabled.",
  event_not_started: "The dungeon doors have not opened yet.",
  event_ended: "This crawl has ended.",
  csrf_failed: "Your session got out of step. Reload the page and try again.",
  validation_error: "Something in that form was not quite right.",
  applicant_in_other_party: "They have already joined another party.",
  request_decided: "That request has already been dealt with.",
  team_is_public: "That party is open — you can just join it.",
  template_in_use:
    "This template still has running instances. Tear them down first.",
};

export default function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;

  const code = error instanceof ApiError ? error.code : "unknown";
  const text = MESSAGES[code] ?? "Something went wrong. Try again in a moment.";
  const requestId = error instanceof ApiError ? error.requestId : null;

  return (
    <p
      role="alert"
      className="mt-3 rounded border border-torch/40 bg-torch/10 px-3 py-2 text-sm"
    >
      {text}
      {requestId && (
        // Gives a player something concrete to quote when they report a problem.
        <span className="mt-1 block text-xs text-muted">
          Reference: {requestId}
        </span>
      )}
    </p>
  );
}
