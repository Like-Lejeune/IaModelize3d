// The price of finished devices for the Manufacturing stage: the quote follows the quantity and the board version on show.
import { errorText } from '$lib/api';
import { deviceApi, type Quote } from './api';

export class QuoteState {
  qty = $state(5);
  quote = $state.raw<Quote | null>(null);
  busy = $state(false);
  error = $state<string | null>(null);
  private key = '';
  private seq = 0;
  private version: number | null = null;

  constructor(private projectId: string) {}

  /** The quote that failed, asked again. */
  retry() {
    return this.load(this.version, true);
  }

  /** Load the quote for this board version and quantity (once per pair). */
  async load(pcbVersion: number | null | undefined, force = false) {
    this.version = pcbVersion ?? null;
    if (!pcbVersion) {
      this.quote = null;
      return;
    }
    const key = `${pcbVersion}:${this.qty}`;
    if (key === this.key && !force && (this.quote || this.busy)) return;
    this.key = key;
    const my = ++this.seq;
    this.busy = true;
    this.error = null;
    try {
      const q = await deviceApi.quote(this.projectId, this.qty);
      if (my === this.seq) this.quote = q;
    } catch (e) {
      if (my === this.seq) {
        this.error = errorText(e);
        this.quote = null;
      }
    } finally {
      if (my === this.seq) this.busy = false;
    }
  }
}
