// Production entry point for a packaged SAMIDA install. Runs the app's own
// `vinext build` output through vinext's Node-native production server
// (vinext/server/prod-server's startProdServer) instead of `wrangler dev` -
// this needs only a Node runtime (Electron already embeds one via
// ELECTRON_RUN_AS_NODE=1), never Cloudflare's wrangler/workerd.
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { startProdServer } from 'vinext/server/prod-server';

const webRoot = path.dirname(fileURLToPath(import.meta.url));

await startProdServer({
  port: Number(process.env.PORT ?? 3200),
  host: process.env.HOST ?? 'localhost',
  outDir: path.join(webRoot, 'dist'),
});
