/* Reverse proxy so browsers reach the app on *.workers.dev, which DNS filters
 * that block trycloudflare.com allow. Set ORIGIN in the dashboard. */
const DEFAULT_ORIGIN = "https://fed-tmp-improvement-defined.trycloudflare.com";

export default {
  async fetch(request, env) {
    const origin = (env && env.ORIGIN) || DEFAULT_ORIGIN;
    const incoming = new URL(request.url);
    const target = new URL(incoming.pathname + incoming.search, origin);

    const headers = new Headers(request.headers);
    headers.set("host", new URL(origin).host);    // origin's certificate is for its own name
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
