export default function Loading({ label = "LOADING MARKET DATA" }) {
  return (
    <div className="loading-wrap">
      <div className="loader">
        <div className="loader-ring ring-outer"></div>
        <div className="loader-ring ring-inner"></div>
        <div className="loader-core"></div>
        <div className="loader-orbit">
          <div className="loader-dot"></div>
        </div>
        <div className="loader-orbit orbit-2">
          <div className="loader-dot dot-2"></div>
        </div>
      </div>
      <div className="loading-text">{label}</div>
      <div className="loading-bar">
        <div className="loading-bar-fill"></div>
      </div>
    </div>
  );
}
