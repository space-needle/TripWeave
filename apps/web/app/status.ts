export type BackendStatus = {
  ready?: boolean;
  api?: { ok?: boolean };
  database?: { ok?: boolean; error?: string };
  postgis?: { ok?: boolean; version?: string; error?: string };
  worker?: {
    ok?: boolean;
    status?: string;
    updated_at?: string;
    error?: string;
  };
};

export type StatusItem = {
  name: string;
  ok: boolean;
  detail: string;
};

export function buildStatusItems(status: BackendStatus | null): StatusItem[] {
  return [
    {
      name: "Web",
      ok: true,
      detail: "Next.js is rendering this page",
    },
    {
      name: "API",
      ok: status?.api?.ok === true,
      detail:
        status?.api?.ok === true
          ? "FastAPI is reachable"
          : "API is not reachable",
    },
    {
      name: "Database",
      ok: status?.database?.ok === true,
      detail:
        status?.database?.ok === true
          ? "PostgreSQL connection succeeded"
          : (status?.database?.error ?? "Database check failed"),
    },
    {
      name: "PostGIS",
      ok: status?.postgis?.ok === true,
      detail:
        status?.postgis?.ok === true
          ? `Extension enabled${status.postgis.version ? ` (${status.postgis.version})` : ""}`
          : (status?.postgis?.error ?? "PostGIS check failed"),
    },
    {
      name: "Worker",
      ok: status?.worker?.ok === true,
      detail:
        status?.worker?.ok === true
          ? `Heartbeat ${status.worker.updated_at ?? "received"}`
          : (status?.worker?.error ?? "Worker heartbeat failed"),
    },
  ];
}
