import { describe, expect, it } from "vitest";
import { describeConnectionStatus } from "@/hooks/useConnectionStatus";

describe("describeConnectionStatus", () => {
  it("maps 'initializing' to a neutral, non-retryable state", () => {
    const result = describeConnectionStatus({ status: "initializing" });
    expect(result).toMatchObject({ tone: "neutral", isConnected: false, canRetry: false });
  });

  it("maps 'connected' to success", () => {
    const result = describeConnectionStatus({ status: "connected" });
    expect(result).toMatchObject({ tone: "success", isConnected: true, canRetry: false });
  });

  it("maps 'reconnecting' to a warning that includes the attempt number", () => {
    const result = describeConnectionStatus({ status: "reconnecting", attempt: 3 });
    expect(result.tone).toBe("warning");
    expect(result.label).toContain("3");
  });

  it("maps 'offline' to a retryable destructive state", () => {
    const result = describeConnectionStatus({ status: "offline" });
    expect(result).toMatchObject({ tone: "destructive", canRetry: true, isConnected: false });
  });

  it("maps 'unavailable' to a retryable destructive state", () => {
    const result = describeConnectionStatus({ status: "unavailable" });
    expect(result).toMatchObject({ tone: "destructive", canRetry: true, isConnected: false });
  });

  it("maps 'error' to a retryable destructive state with the message", () => {
    const result = describeConnectionStatus({ status: "error", message: "boom" });
    expect(result.tone).toBe("destructive");
    expect(result.canRetry).toBe(true);
    expect(result.label).toContain("boom");
  });
});
