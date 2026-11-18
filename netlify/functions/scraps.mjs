import { getStore } from "@netlify/blobs";

const STORE_NAME = "dashboard-scraps";
const KEY = "items";

export default async (req) => {
  const store = getStore(STORE_NAME);

  if (req.method === "GET") {
    const items = (await store.get(KEY, { type: "json" })) || [];
    return Response.json({ items });
  }

  if (req.method === "POST") {
    const body = await req.json();
    const items = (await store.get(KEY, { type: "json" })) || [];
    const exists = items.some((x) => x.id === body.id || x.url === body.url);
    const updated = exists
      ? items.filter((x) => x.id !== body.id && x.url !== body.url)
      : [{ ...body, saved_at: new Date().toISOString() }, ...items];

    await store.setJSON(KEY, updated);
    return Response.json({ items: updated, saved: !exists });
  }

  return new Response("Method Not Allowed", { status: 405 });
};
