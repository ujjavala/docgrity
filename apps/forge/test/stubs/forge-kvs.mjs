/** In-memory stub of @forge/kvs. Secrets live in a separate map so tests can
 * assert that secrets never end up in the regular store. */
const store = new Map();
const secrets = new Map();

export const kvs = {
  async get(key) {
    return store.has(key) ? store.get(key) : undefined;
  },
  async set(key, value) {
    store.set(key, value);
  },
  async delete(key) {
    store.delete(key);
  },
  async getSecret(key) {
    return secrets.has(key) ? secrets.get(key) : undefined;
  },
  async setSecret(key, value) {
    secrets.set(key, value);
  },
  async deleteSecret(key) {
    secrets.delete(key);
  },
};

export const __kvs = {
  store,
  secrets,
  reset() {
    store.clear();
    secrets.clear();
  },
};
