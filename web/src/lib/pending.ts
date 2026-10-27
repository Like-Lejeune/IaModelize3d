// The first message travels from the home page to the studio in memory, so the studio opens at once
// and does the slow part (uploads, face check) where the user can watch it.
const queue = new Map<string, { text: string; files: File[] }>();

export function stashFirst(projectId: string, text: string, files: File[]) {
  queue.set(projectId, { text, files });
}

export function takeFirst(projectId: string) {
  const v = queue.get(projectId);
  queue.delete(projectId);
  return v;
}
