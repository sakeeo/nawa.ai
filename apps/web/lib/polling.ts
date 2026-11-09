export type Poller = { start: () => void; stop: () => void };

/**
 * Runs `run` every `intervalMs` until stopped. While `isHidden()` is true the tick is skipped
 * (the timer keeps going, so polling resumes by itself when the tab is visible again).
 * Ticks never overlap: the next one is scheduled after `run` settles.
 */
export function createPoller(options: {
  run: () => Promise<void>;
  intervalMs: number;
  isHidden?: () => boolean;
}): Poller {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active = false;

  const schedule = () => {
    if (!active) return;
    timer = setTimeout(async () => {
      if (!(options.isHidden?.() ?? false)) {
        try {
          await options.run();
        } catch {
          // A failed refresh is retried on the next tick.
        }
      }
      schedule();
    }, options.intervalMs);
  };

  return {
    start() {
      if (active) return;
      active = true;
      schedule();
    },
    stop() {
      active = false;
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
    },
  };
}
