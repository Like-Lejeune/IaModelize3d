// The project API the studio talks to (server/iamodelize3d/app.py): a project, its conversation with the designer
// agent, its program versions. Same session cookie as the shop.
import { ApiError } from "../api";
import type { AssetOut, ProgramOut, ProjectDetail, VersionRow } from "../geom/types";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin" };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let j: any = null;
    try {
      j = await res.json();
    } catch {
      /* not JSON */
    }
    const inner = j?.detail && typeof j.detail === "object" && !Array.isArray(j.detail) ? j.detail : j;
    const detail = typeof inner?.detail === "string" ? inner.detail : typeof inner?.message === "string" ? inner.message : res.statusText;
    throw new ApiError(res.status, inner?.code ?? `http_${res.status}`, detail);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("json") ? res.json() : res.blob()) as Promise<T>;
}

export const projects = {
  create: (title: string) => req<{ id: string; title: string }>("POST", "/api/projects", { title }),
  list: () => req<{ id: string; title: string; cover?: string | null; updated_at: number; version: number }[]>("GET", "/api/projects"),
  get: (id: string) => req<ProjectDetail>("GET", `/api/projects/${id}`),
  rename: (id: string, title: string) => req("PATCH", `/api/projects/${id}`, { title }),
  upload(id: string, file: File) {
    const fd = new FormData();
    fd.append("kind", "photo");
    fd.append("file", file, file.name);
    return req<AssetOut>("POST", `/api/projects/${id}/assets`, fd);
  },
  send: (id: string, text: string, assetIds: string[] = []) =>
    req<{ job_id: string }>("POST", `/api/projects/${id}/messages`, { text, asset_ids: assetIds }),
  answer: (jobId: string, answer: string) => req<{ ok: boolean }>("POST", `/api/jobs/${jobId}/answer`, { answer }),
  cancel: (jobId: string) => req<{ ok: boolean }>("POST", `/api/jobs/${jobId}/cancel`),
  program: (id: string, version: number) => req<ProgramOut>("GET", `/api/projects/${id}/program/${version}`),
  versions: (id: string) => req<VersionRow[]>("GET", `/api/projects/${id}/versions`),
  saveParams: (id: string, params: Record<string, any>, checks: unknown, client: string) =>
    req<{ version: number; params: Record<string, any> }>("PUT", `/api/projects/${id}/params`, { params, checks, client }),
  saveProgram: (id: string, body: { source: string; params: Record<string, any>; checks?: unknown; summary?: string; client: string }) =>
    req<{ version: number; params: Record<string, any> }>("PUT", `/api/projects/${id}/program`, body),
};
