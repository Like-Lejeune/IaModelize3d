// Client for a project's PCB versions (contract C8, server/formwright/pcbapi.py): the list of versions and
// their files by URL. Same origin and cookie session as $lib/api; errors come back as its ApiError.
import { apiError, deadline } from '$lib/api';
import type { PcbDrc, PcbVersion, RouteFrames } from '$lib/types';

/** The files the server keeps for every version (pcb_store.ARTIFACTS). */
export type PcbArtifact =
  | 'circuit.tsx' | 'circuit.json' | 'board.json' | 'drc.json' | 'route_frames.json' | 'pcb_top.svg' | 'pcb_bottom.svg'
  | 'schematic.svg' | 'board.glb' | 'gerbers.zip' | 'bom.csv' | 'cpl.csv';

/** What a fab needs, in the order the panel offers them. */
export const FAB_FILES: PcbArtifact[] = ['gerbers.zip', 'bom.csv', 'cpl.csv'];

async function get(path: string): Promise<Response> {
  const res = await fetch(path, { credentials: 'same-origin', signal: deadline(60_000) });
  if (!res.ok) throw await apiError(res);
  return res;
}

export const pcbApi = {
  /** Every version of the project's board, oldest first; [] for a project without one. */
  versions: async (projectId: string) => (await (await get(`/api/projects/${encodeURIComponent(projectId)}/pcb`)).json()) as PcbVersion[],
  /** One file of a version, as the list gives its URL, or built for 'latest'. */
  url: (projectId: string, version: number | 'latest', name: PcbArtifact) => `/api/projects/${encodeURIComponent(projectId)}/pcb/${version}/${name}`,
  drc: async (url: string) => (await (await get(url)).json()) as PcbDrc,
  frames: async (url: string) => (await (await get(url)).json()) as RouteFrames,
};

/** A route frame's segments as one SVG path, mapped by the version's svg_map matrix (px = a*x + e, py = d*y + f). */
export function framePath(lines: [number, number, number, number][], m: number[] = [1, 0, 0, 1, 0, 0]): string {
  const [a, , , d, e, f] = m;
  const r = (v: number) => Math.round(v * 10) / 10;
  let s = '';
  for (const [x1, y1, x2, y2] of lines) s += `M${r(a * x1 + e)} ${r(d * y1 + f)}L${r(a * x2 + e)} ${r(d * y2 + f)}`;
  return s;
}
