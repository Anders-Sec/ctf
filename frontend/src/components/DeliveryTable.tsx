import type { Delivery } from "../api/adminEmail";

/**
 * Shared by the Email Delivery page and the user detail drawer (spec 055 §4).
 *
 * The drawer placement is the one that matters most: someone is stuck, you open
 * their record, and you can see the three links that were sent and that all
 * three were accepted — so it is their spam folder, and you can tell them so.
 */
export default function DeliveryTable({
  rows,
  showRecipient = true,
}: {
  rows: Delivery[];
  showRecipient?: boolean;
}) {
  if (rows.length === 0) {
    return <p className="mt-3 text-sm text-content-muted">Nothing sent.</p>;
  }

  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-content-muted">
          <tr className="border-b border-border">
            <th className="py-2 pr-3 font-medium">When</th>
            {showRecipient && <th className="py-2 pr-3 font-medium">To</th>}
            <th className="py-2 pr-3 font-medium">Kind</th>
            <th className="py-2 pr-3 font-medium">Result</th>
            <th className="py-2 text-right font-medium">Took</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-border">
              <td className="py-2 pr-3 tabular-nums">
                {new Date(row.created_at).toLocaleString()}
              </td>
              {showRecipient && <td className="py-2 pr-3">{row.to_email}</td>}
              <td className="py-2 pr-3 text-content-muted">{row.kind.replace("_", " ")}</td>
              <td className="py-2 pr-3">
                <Result row={row} />
              </td>
              <td className="py-2 text-right tabular-nums text-content-muted">
                {row.duration_ms === null ? "—" : `${row.duration_ms} ms`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Result({ row }: { row: Delivery }) {
  if (row.status === "sent") {
    // Not "delivered": SMTP gives no confirmation, and claiming delivery for
    // something that bounced later would be a lie told confidently.
    return <span className="text-success">accepted by relay</span>;
  }
  if (row.status === "not_configured") {
    return <span className="text-warning">no mail configured</span>;
  }
  return (
    <span className="text-danger">
      failed{row.error_type ? ` · ${row.error_type}` : ""}
    </span>
  );
}
