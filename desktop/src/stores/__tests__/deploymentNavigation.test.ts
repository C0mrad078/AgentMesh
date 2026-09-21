import { afterEach, describe, expect, it } from 'vitest';
import { useUiStore } from '../uiStore';

afterEach(() => {
  window.history.replaceState({}, '', '/');
  useUiStore.getState().syncLocation();
});

describe('Deployment routes', () => {
  it('opens and restores deployment URLs', () => {
    useUiStore.getState().openDeployment();
    expect(location.pathname).toBe('/deployment');
    expect(useUiStore.getState().activePage).toBe('deployment');

    useUiStore.getState().openDeployment('release-123');
    expect(location.pathname).toBe('/deployment/release-123');
    expect(useUiStore.getState().deploymentReleaseId).toBe('release-123');

    useUiStore.getState().setActivePage('office');
    expect(location.pathname).toBe('/');
    expect(useUiStore.getState().activePage).toBe('office');

    window.history.replaceState({}, '', '/deployment/restored-release');
    useUiStore.getState().syncLocation();
    expect(useUiStore.getState().activePage).toBe('deployment');
    expect(useUiStore.getState().deploymentReleaseId).toBe('restored-release');
  });

  it('handles malformed URL encoding gracefully', () => {
    window.history.replaceState({}, '', '/deployment/%broken');
    expect(() => useUiStore.getState().syncLocation()).not.toThrow();
    expect(useUiStore.getState().deploymentReleaseId).toBeNull();
  });
});
