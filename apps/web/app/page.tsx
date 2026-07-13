import { buildStatusItems, type BackendStatus } from "./status";

async function fetchStatus(): Promise<BackendStatus | null> {
  const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${apiUrl}/status`, {
      cache: "no-store",
      next: { revalidate: 0 },
    });
    if (!response.ok && response.status !== 503) {
      return null;
    }
    return (await response.json()) as BackendStatus;
  } catch {
    return null;
  }
}

export default async function StatusPage() {
  const status = await fetchStatus();
  const items = buildStatusItems(status);
  const allHealthy = items.every((item) => item.ok);

  return (
    <main className="status-shell">
      <section className="status-header" aria-labelledby="status-title">
        <div>
          <p className="eyebrow">TripWeave local development</p>
          <h1 id="status-title">System status</h1>
        </div>
        <div
          className={allHealthy ? "summary summary-ok" : "summary summary-warn"}
        >
          {allHealthy ? "Healthy" : "Needs attention"}
        </div>
      </section>

      <section className="status-grid" aria-label="Service checks">
        {items.map((item) => (
          <article className="status-card" key={item.name}>
            <div
              className={item.ok ? "indicator indicator-ok" : "indicator-warn"}
            />
            <div>
              <h2>{item.name}</h2>
              <p>{item.detail}</p>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
