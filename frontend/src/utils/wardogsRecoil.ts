/** Accumulate the source's per-shot sideways/upward kick without inventing units. */
export type RecoilPoint = { x: number; y: number }
export function recoilPath(pattern: RecoilPoint[]): RecoilPoint[] {
  const points: RecoilPoint[] = [{ x: 0, y: 0 }]
  for (const shot of pattern) {
    if (!Number.isFinite(shot.x) || !Number.isFinite(shot.y)) return []
    const previous = points[points.length - 1]
    points.push({ x: previous.x + shot.x, y: previous.y + shot.y })
  }
  return points
}
