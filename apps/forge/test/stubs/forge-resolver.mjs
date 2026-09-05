/** Minimal stub of @forge/resolver. */
export default class Resolver {
  constructor() {
    this.defs = new Map();
  }
  define(name, fn) {
    this.defs.set(name, fn);
  }
  getDefinitions() {
    return (req) => this.defs.get(req.payload?.functionKey)?.(req);
  }
}
