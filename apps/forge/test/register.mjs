/** Registers the test module loader (Forge stubs + extensionless imports). */
import { register } from 'node:module';
register('./loader.mjs', import.meta.url);
