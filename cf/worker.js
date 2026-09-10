/* Reverse proxy so the browser only ever talks to *.workers.dev.
 *
 * Why: the app is served over a Cloudflare quick tunnel, and corporate DNS
 * filters block the whole trycloudflare.com suffix, so reviewers got
 * NXDOMAIN. Cloudflare's edge is not behind that filter, so it can reach the
 * tunnel and hand the answer back over a hostname nobody blocks.
 *
 * Vapi's webhooks still go straight to the tunnel; Vapi is not DNS-filtered,
 * and one less hop on the tool round trip is worth having.
 *
 * ORIGIN is set in the dashboard, not here, so the tunnel address is not
 * baked into the repository and can be changed without a redeploy.
 */
const DEFAULT_ORIGIN = "https://fed-tmp-improvement-defined.trycloudflare.com";

export default {
  async fetch(request, env) {
    const origin = (env && env.ORIGIN) || DEFAULT_ORIGIN;
    const incoming = new URL(request.url);
    const target = new URL(incoming.pathname + incoming.search, origin);

    const headers = new Headers(request.headers);
    // The origin's certificate was issued for its own name, not ours.
    headers.set("host", new URL(origin).host);
    headers.set("x-forwarded-proto", "https");
    headers.set("x-forwarded-host", incoming.host);
    headers.delete("accept-encoding");

    const init = { method: request.method, headers, redirect: "manual" };
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
      init.duplex = "half";
    }

    const res = await fetch(target.toString(), init);
    const out = new Headers(res.headers);
    out.delete("content-encoding");
    out.delete("content-length");
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
  },
};
