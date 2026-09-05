/** In-memory stub of @forge/api for tests. */
let fetchImpl = async () => {
  throw new Error('fetch not stubbed — call __setFetch() in your test');
};

export const fetch = (...args) => fetchImpl(...args);
export function __setFetch(fn) {
  fetchImpl = fn;
}

/** Tagged-template `route` passthrough. */
export const route = (strings, ...values) =>
  typeof strings === 'string' ? strings : String.raw({ raw: strings.raw ?? strings }, ...values);

const notStubbed = () => {
  throw new Error('api.asApp() not stubbed');
};
export default { asApp: () => ({ requestConfluence: notStubbed, requestGraph: notStubbed }) };
