/**
 * Tests for UpdateChecker and UpdateFallback components,
 * plus the pure utility functions in api.ts.
 */

import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    checkForUpdates: vi.fn(),
    api: { get: vi.fn() },
  };
});

import { compareSemver, checkForUpdates, api } from "../lib/api";
import { UpdateChecker } from "../components/UpdateChecker";
import { UpdateFallback } from "../components/UpdateFallback";

const mockCheckForUpdates = checkForUpdates as ReturnType<typeof vi.fn>;
const mockApiGet          = api.get as ReturnType<typeof vi.fn>;

function makeUpdateResult(overrides = {}) {
  return {
    currentVersion:     "1.0.0",
    latestVersion:      "1.1.0",
    updateAvailable:    true,
    backendUnreachable: false,
    ...overrides,
  };
}

/** Open the popover so inner elements become visible. */
async function openPanel() {
  const trigger = screen.getByTestId("update-checker-trigger");
  fireEvent.click(trigger);
  return screen.getByTestId("update-checker-panel");
}

// ---------------------------------------------------------------------------
// compareSemver — pure utility
// ---------------------------------------------------------------------------

describe("compareSemver", () => {
  it("returns 0 for equal versions", () => expect(compareSemver("1.0.0", "1.0.0")).toBe(0));
  it("returns 1 when b has higher major", () => expect(compareSemver("1.0.0", "2.0.0")).toBe(1));
  it("returns -1 when a has higher major", () => expect(compareSemver("2.0.0", "1.0.0")).toBe(-1));
  it("returns 1 when b has higher minor", () => expect(compareSemver("1.0.0", "1.1.0")).toBe(1));
  it("returns 1 when b has higher patch", () => expect(compareSemver("1.0.0", "1.0.1")).toBe(1));
  it("strips leading v prefix", () => expect(compareSemver("v1.0.0", "v1.1.0")).toBe(1));
  it("handles malformed strings without throwing", () => {
    expect(() => compareSemver("not-semver", "1.0.0")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// UpdateChecker
// ---------------------------------------------------------------------------

describe("UpdateChecker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult({ updateAvailable: false }));
  });

  afterEach(() => vi.clearAllMocks());

  // Trigger button is always visible

  it("always renders the trigger button", async () => {
    render(<UpdateChecker pollIntervalMs={99999999} />);
    expect(screen.getByTestId("update-checker-trigger")).toBeInTheDocument();
  });

  it("opens the panel when trigger is clicked", async () => {
    render(<UpdateChecker pollIntervalMs={99999999} />);
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    const panel = await openPanel();
    expect(panel).toBeInTheDocument();
  });

  it("panel has a 'Check now' button", async () => {
    render(<UpdateChecker pollIntervalMs={99999999} />);
    await openPanel();
    expect(screen.getByTestId("check-now-btn")).toBeInTheDocument();
  });

  it("shows current version in panel", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult({
      updateAvailable: false,
      currentVersion: "2.5.0",
    }));
    render(<UpdateChecker pollIntervalMs={99999999} />);
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    await openPanel();
    expect(screen.getByText("2.5.0")).toBeInTheDocument();
  });

  it("shows yellow badge on trigger when update is available", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult());
    render(<UpdateChecker pollIntervalMs={99999999} />);
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    // The badge is a sibling span inside the trigger button
    const trigger = screen.getByTestId("update-checker-trigger");
    expect(trigger.querySelector(".bg-\\[\\#e3b341\\]")).toBeInTheDocument();
  });

  it("shows 'Test Update' button in panel when update is available", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult());
    render(<UpdateChecker pollIntervalMs={99999999} />);
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    await openPanel();
    expect(screen.getByTestId("test-update-btn")).toBeInTheDocument();
  });

  it("does NOT show 'Test Update' button when no update is available", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult({ updateAvailable: false }));
    render(<UpdateChecker pollIntervalMs={99999999} />);
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    await openPanel();
    expect(screen.queryByTestId("test-update-btn")).toBeNull();
  });

  it("shows latest version in panel when update is available", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult({ latestVersion: "9.9.9" }));
    render(<UpdateChecker pollIntervalMs={99999999} />);
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    await openPanel();
    expect(screen.getByText("9.9.9")).toBeInTheDocument();
  });

  it("shows error message when checkForUpdates reports an error", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult({
      updateAvailable: false,
      latestVersion: null,
      error: "Could not reach GitHub",
    }));
    render(<UpdateChecker pollIntervalMs={99999999} />);
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    await openPanel();
    expect(screen.getByText(/Could not reach GitHub/i)).toBeInTheDocument();
  });

  // ── Test-update happy path ────────────────────────────────────────────────

  it("calls onUpdateSucceeded when test update passes health checks", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult());
    mockApiGet.mockResolvedValue({ status: 200, data: { status: "ok" } });

    const onSuccess   = vi.fn();
    const applyUpdate = vi.fn().mockResolvedValue(undefined);

    render(
      <UpdateChecker
        pollIntervalMs={99999999}
        applyUpdate={applyUpdate}
        onUpdateSucceeded={onSuccess}
      />
    );
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    await openPanel();
    fireEvent.click(screen.getByTestId("test-update-btn"));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce(), { timeout: 10000 });
  }, 15000);

  // ── Test-update fallback path ─────────────────────────────────────────────

  it("calls onUpdateFailed when post-update health check fails", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult());
    mockApiGet
      .mockResolvedValueOnce({ status: 200, data: { status: "ok" } }) // pre-health
      .mockRejectedValue(new Error("connection refused"));             // post-health ×3

    const onFailed    = vi.fn();
    const applyUpdate = vi.fn().mockResolvedValue(undefined);

    render(
      <UpdateChecker
        pollIntervalMs={99999999}
        applyUpdate={applyUpdate}
        onUpdateFailed={onFailed}
      />
    );
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    await openPanel();
    fireEvent.click(screen.getByTestId("test-update-btn"));
    await waitFor(() => expect(onFailed).toHaveBeenCalledOnce(), { timeout: 30000 });
  }, 35000);

  it("calls onUpdateFailed when pre-update health check fails", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult());
    mockApiGet.mockRejectedValue(new Error("backend down"));

    const onFailed    = vi.fn();
    const applyUpdate = vi.fn();

    render(
      <UpdateChecker
        pollIntervalMs={99999999}
        applyUpdate={applyUpdate}
        onUpdateFailed={onFailed}
      />
    );
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    await openPanel();
    fireEvent.click(screen.getByTestId("test-update-btn"));
    await waitFor(() => expect(onFailed).toHaveBeenCalledOnce(), { timeout: 10000 });
    expect(applyUpdate).not.toHaveBeenCalled();
  }, 15000);

  it("calls onUpdateFailed when applyUpdate throws", async () => {
    mockCheckForUpdates.mockResolvedValue(makeUpdateResult());
    mockApiGet.mockResolvedValueOnce({ status: 200, data: { status: "ok" } });

    const onFailed    = vi.fn();
    const applyUpdate = vi.fn().mockRejectedValue(new Error("pip install failed"));

    render(
      <UpdateChecker
        pollIntervalMs={99999999}
        applyUpdate={applyUpdate}
        onUpdateFailed={onFailed}
      />
    );
    await waitFor(() => expect(mockCheckForUpdates).toHaveBeenCalled());
    await openPanel();
    fireEvent.click(screen.getByTestId("test-update-btn"));
    await waitFor(() => {
      expect(onFailed).toHaveBeenCalledOnce();
      expect(onFailed.mock.calls[0][0]).toMatch(/pip install failed/);
    }, { timeout: 10000 });
  }, 15000);
});

// ---------------------------------------------------------------------------
// UpdateFallback
// ---------------------------------------------------------------------------

describe("UpdateFallback", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the fallback screen with the reason", () => {
    render(
      <UpdateFallback reason="Post-update health check failed: connection refused" onRecovered={vi.fn()} autoRetrySeconds={0} />
    );
    expect(screen.getByTestId("update-fallback")).toBeInTheDocument();
    expect(screen.getByText(/Update broke the backend/i)).toBeInTheDocument();
    expect(screen.getByText(/connection refused/i)).toBeInTheDocument();
  });

  it("calls onRecovered when health check succeeds after manual retry", async () => {
    mockApiGet.mockResolvedValue({ status: 200, data: { status: "ok" } });
    const onRecovered = vi.fn();
    render(<UpdateFallback reason="backend broke" onRecovered={onRecovered} autoRetrySeconds={0} />);
    fireEvent.click(screen.getByTestId("retry-btn"));
    await waitFor(() => expect(onRecovered).toHaveBeenCalledOnce(), { timeout: 5000 });
  }, 8000);

  it("shows last retry error when health check still fails", async () => {
    mockApiGet.mockRejectedValue(new Error("still down"));
    render(<UpdateFallback reason="backend broke" onRecovered={vi.fn()} autoRetrySeconds={0} />);
    fireEvent.click(screen.getByTestId("retry-btn"));
    await waitFor(() => {
      expect(screen.getByText(/still down/i)).toBeInTheDocument();
    }, { timeout: 5000 });
  }, 8000);

  it("shows rollback instructions in expandable details", () => {
    render(<UpdateFallback reason="broke" onRecovered={vi.fn()} autoRetrySeconds={0} />);
    expect(screen.getByText(/Manual rollback instructions/i)).toBeInTheDocument();
  });
});
