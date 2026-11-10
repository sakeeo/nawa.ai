import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPoller } from "@/lib/polling";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("createPoller", () => {
  it("runs every interval after start and stops cleanly", async () => {
    const run = vi.fn().mockResolvedValue(undefined);
    const poller = createPoller({ run, intervalMs: 3000 });
    poller.start();
    expect(run).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(3000);
    await vi.advanceTimersByTimeAsync(3000);
    expect(run).toHaveBeenCalledTimes(2);
    poller.stop();
    await vi.advanceTimersByTimeAsync(10000);
    expect(run).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("skips ticks while hidden and resumes when visible", async () => {
    const run = vi.fn().mockResolvedValue(undefined);
    let hidden = true;
    const poller = createPoller({ run, intervalMs: 1000, isHidden: () => hidden });
    poller.start();
    await vi.advanceTimersByTimeAsync(3000);
    expect(run).not.toHaveBeenCalled();
    hidden = false;
    await vi.advanceTimersByTimeAsync(1000);
    expect(run).toHaveBeenCalledTimes(1);
    poller.stop();
  });

  it("keeps going after a failed refresh and never starts twice", async () => {
    const run = vi.fn().mockRejectedValueOnce(new Error("net")).mockResolvedValue(undefined);
    const poller = createPoller({ run, intervalMs: 1000 });
    poller.start();
    poller.start();
    await vi.advanceTimersByTimeAsync(2000);
    expect(run).toHaveBeenCalledTimes(2);
    poller.stop();
  });

  it("does not overlap ticks while a refresh is slow", async () => {
    let release: () => void = () => {};
    const run = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
    const poller = createPoller({ run, intervalMs: 1000 });
    poller.start();
    await vi.advanceTimersByTimeAsync(5000);
    expect(run).toHaveBeenCalledTimes(1);
    release();
    await vi.advanceTimersByTimeAsync(1000);
    expect(run).toHaveBeenCalledTimes(2);
    poller.stop();
    release();
  });
});
