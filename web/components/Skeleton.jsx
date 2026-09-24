export default function Skeleton({ variant = "table", rows = 8 }) {
  if (variant === "cards") {
    return (
      <div className="skel-cards" aria-hidden="true">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skel skel-card" />
        ))}
      </div>
    );
  }
  if (variant === "chart") {
    return <div className="skel skel-chart" aria-hidden="true" />;
  }
  if (variant === "dashboard") {
    return (
      <div aria-hidden="true">
        <Skeleton variant="cards" rows={5} />
        <Skeleton variant="chart" />
        <Skeleton variant="table" rows={8} />
      </div>
    );
  }
  // table
  return (
    <div className="panel" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skel skel-row" style={{ width: `${88 - (i % 3) * 9}%` }} />
      ))}
    </div>
  );
}
