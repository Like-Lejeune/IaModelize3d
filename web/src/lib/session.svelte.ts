import { api } from './api';
import type { Usage } from './types';

export const session = $state<{ me: Usage | null }>({ me: null });

export async function refreshMe() {
  try {
    session.me = await api.me();
  } catch {
    /* backend offline */
  }
}

export async function setConsent(on: boolean) {
  await api.consent(on);
  await refreshMe();
}
