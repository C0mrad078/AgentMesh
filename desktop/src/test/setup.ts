import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Tests run in jsdom, outside of an actual Tauri webview, so every module
// that talks to `@tauri-apps/api` is mocked at the boundary. Individual
// tests override these mocks (via `vi.mocked(...)`) when they need to
// assert on specific calls.
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async () => () => {}),
}));
