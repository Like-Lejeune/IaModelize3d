// The price of finished devices and their orders for the Manufacturing stage: the quote follows the quantity and the
// board version on show; placing an order keeps its reference and timeline.
import { errorText } from '$lib/api';
import { deviceApi, type DeviceOrder, type Quote } from './api';

export class QuoteState {
  qty = $state(5);
  quote = $state.raw<Quote | null>(null);
  busy = $state(false);
  error = $state<string | null>(null);
  placed = $state.raw<DeviceOrder | null>(null);
  orders = $state.raw<DeviceOrder[]>([]);
  placing = $state(false);
  private key = '';
  private seq = 0;

  constructor(private projectId: string) {}

  /** Load the quote for this board version and quantity (once per pair). */
  async load(pcbVersion: number | null | undefined, force = false) {
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

  async loadOrders() {
    try {
      this.orders = await deviceApi.orders(this.projectId);
    } catch {
      this.orders = [];
    }
  }

  async place(contact: { name?: string; contact?: string; city?: string; note?: string }) {
    this.placing = true;
    this.error = null;
    try {
      this.placed = await deviceApi.order(this.projectId, { qty: this.qty, ...contact });
      await this.loadOrders();
    } catch (e) {
      this.error = errorText(e);
    } finally {
      this.placing = false;
    }
  }
}
