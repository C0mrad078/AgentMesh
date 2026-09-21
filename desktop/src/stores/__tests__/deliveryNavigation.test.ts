import { afterEach, describe, expect, it } from 'vitest';
import { useUiStore } from '../uiStore';
afterEach(() => { window.history.replaceState({}, '', '/'); useUiStore.getState().syncLocation(); });
describe('Delivery routes', () => {
  it('opens and restores both URLs', () => {
    useUiStore.getState().openDelivery(); expect(location.pathname).toBe('/delivery'); expect(useUiStore.getState().activePage).toBe('delivery');
    useUiStore.getState().openDelivery('candidate-1'); expect(location.pathname).toBe('/delivery/candidate-1'); expect(useUiStore.getState().deliveryCandidateId).toBe('candidate-1');
    useUiStore.getState().setActivePage('office'); expect(location.pathname).toBe('/');
    window.history.replaceState({}, '', '/delivery/restored'); useUiStore.getState().syncLocation(); expect(useUiStore.getState().deliveryCandidateId).toBe('restored');
  });
  it('handles malformed URL encoding without crashing', () => {
    window.history.replaceState({}, '', '/delivery/%broken'); expect(() => useUiStore.getState().syncLocation()).not.toThrow(); expect(useUiStore.getState().deliveryCandidateId).toBeNull();
  });
});
