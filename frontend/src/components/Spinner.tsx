export default function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-[40vh] items-center justify-center" role="status">
      <span className="animate-pulse text-content-muted">{label}</span>
    </div>
  );
}
