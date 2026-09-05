/**
 * Test module loader.
 *
 * The Forge bundler allows extensionless relative imports and provides the
 * `@forge/*` runtime packages. Under plain Node (node --test) we:
 *   1. map `@forge/*` imports to local in-memory stubs, and
 *   2. resolve extensionless relative imports to `.js`, forcing ESM format
 *      (the package has no `"type": "module"` because Forge bundles it).
 */
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const STUBS = {
  '@forge/api': new URL('./stubs/forge-api.mjs', import.meta.url).href,
  '@forge/kvs': new URL('./stubs/forge-kvs.mjs', import.meta.url).href,
  '@forge/sql': new URL('./stubs/forge-sql.mjs', import.meta.url).href,
  '@forge/events': new URL('./stubs/forge-events.mjs', import.meta.url).href,
  '@forge/resolver': new URL('./stubs/forge-resolver.mjs', import.meta.url).href,
};

const SRC_DIR = new URL('../src/', import.meta.url).href;

export async function resolve(specifier, context, next) {
  if (STUBS[specifier]) return { url: STUBS[specifier], shortCircuit: true };
  if (
    (specifier.startsWith('./') || specifier.startsWith('../')) &&
    !/\.(js|mjs|cjs|json)$/.test(specifier)
  ) {
    return next(`${specifier}.js`, context);
  }
  return next(specifier, context);
}

export async function load(url, context, next) {
  // Source files use ESM syntax but live in a CJS-default package; force ESM.
  if (url.startsWith(SRC_DIR) && url.endsWith('.js')) {
    const source = await readFile(fileURLToPath(url), 'utf8');
    return { format: 'module', source, shortCircuit: true };
  }
  return next(url, context);
}
