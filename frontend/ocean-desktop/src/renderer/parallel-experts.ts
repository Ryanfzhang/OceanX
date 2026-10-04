// How many data Experts may work at once. One value for the whole app: the backend's slot pool is
// app-wide, and each research request carries the current choice (session.submit max_parallel_experts).
export const PARALLEL_EXPERTS_CHOICES = [1, 2, 3, 4] as const;
export type ParallelExperts = (typeof PARALLEL_EXPERTS_CHOICES)[number];

export const DEFAULT_PARALLEL_EXPERTS: ParallelExperts = 2;
export const PARALLEL_EXPERTS_STORAGE_KEY = 'oceanx.parallel-experts.v1';

function choice(value: unknown): ParallelExperts | null {
  return PARALLEL_EXPERTS_CHOICES.find((candidate) => String(candidate) === value) ?? null;
}

export function readParallelExperts(storage: Pick<Storage, 'getItem'>): ParallelExperts {
  try {
    return choice(storage.getItem(PARALLEL_EXPERTS_STORAGE_KEY)) ?? DEFAULT_PARALLEL_EXPERTS;
  } catch {
    return DEFAULT_PARALLEL_EXPERTS;
  }
}

export function writeParallelExperts(storage: Pick<Storage, 'setItem'>, value: number): void {
  if (choice(String(value)) !== null) storage.setItem(PARALLEL_EXPERTS_STORAGE_KEY, String(value));
}
