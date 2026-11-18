import { getStore } from "@netlify/blobs";

const STORE_NAME = "dashboard-data";
const ALLOWED = new Set(["community_hot", "community_ai", "deals", "economy_briefing"]);

export default async (req) => {
  const url = new URL(req.url);
  const name = url.searchParams.get("name") || "";
  if (!ALLOWED.has(name)) {
    return new Response("Invalid dataset name", { status: 400 });
  }

  const store = getStore(STORE_NAME);

  if (req.method === "GET") {
    const data = await store.get(name, { type: "json" });
    if (!data) {
      return new Response("Not Found", { status: 404 });
    }
    return Response.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  }

  if (req.method === "POST") {
    const expected = Netlify.env.get("INGEST_TOKEN") || Netlify.env.get("DASHBOARD_PASSWORD") || "";
    const provided = req.headers.get("x-ingest-token") || "";
    if (!expected || provided !== expected) {
      return new Response("Unauthorized", { status: 401 });
    }
    const payload = await req.json();
    await store.setJSON(name, payload);
    return Response.json({ ok: true, name });
  }

  return new Response("Method Not Allowed", { status: 405 });
};
