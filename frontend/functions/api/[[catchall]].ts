// Cloudflare Pages Function: transparent edge proxy for /api/* requests to backend
export const onRequest: PagesFunction<{ BACKEND_URL?: string }> = async (context) => {
  const backendBase = (context.env.BACKEND_URL || "http://127.0.0.1:5000").replace(/\/+$/, "");
  const url = new URL(context.request.url);
  const targetUrl = `${backendBase}${url.pathname}${url.search}`;

  const requestHeaders = new Headers(context.request.headers);
  requestHeaders.set("X-Forwarded-Host", url.host);
  requestHeaders.set("X-Forwarded-Proto", url.protocol.replace(":", ""));

  const response = await fetch(targetUrl, {
    method: context.request.method,
    headers: requestHeaders,
    body: ["GET", "HEAD"].includes(context.request.method) ? undefined : context.request.body,
    redirect: "follow",
  });

  const responseHeaders = new Headers(response.headers);
  // Ensure CORS headers allow Cloudflare Pages origin
  responseHeaders.set("Access-Control-Allow-Origin", "*");
  responseHeaders.set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
  responseHeaders.set("Access-Control-Allow-Headers", "*");

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
};
