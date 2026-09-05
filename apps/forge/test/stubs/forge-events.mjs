/** Minimal stub of @forge/events. */
export class Queue {
  constructor() {
    this.pushed = [];
  }
  async push(events) {
    this.pushed.push(events);
    return { ids: ['stub'] };
  }
}
