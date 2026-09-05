/** Minimal stub of @forge/sql. */
export const sql = {
  async executeRaw() {
    return { rows: [] };
  },
  prepare() {
    return { bindParams: () => ({ execute: async () => ({ rows: [] }) }) };
  },
};
export const migrationRunner = { enqueue: () => migrationRunner, run: async () => [], list: async () => [] };
