// The page asks its own address for the data, and this hands the question to the
// Python API (demo/api.py). The address of the API is read when the question
// comes, not when the page is built: one image, any Comune.
export const dynamic = "force-dynamic";

const API = () => (process.env.EGMS_UI_API ?? "http://127.0.0.1:8010").replace(/\/$/, "");

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = `${API()}/api/${path.map(encodeURIComponent).join("/")}${new URL(request.url).search}`;
  let answer: Response;
  try {
    answer = await fetch(target, { cache: "no-store" });
  } catch {
    return Response.json({ error: "the egms-client API does not answer: is demo/api.py running?" }, { status: 502 });
  }
  const headers = new Headers();
  for (const name of ["content-type", "cache-control"]) {
    const value = answer.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(answer.body, { status: answer.status, headers });
}

/** Only the readings of a sensor are sent here: the rest of the API is read-only. */
export async function POST(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (path[0] !== "ingest" || path.length !== 2) {
    return Response.json({ error: "only POST /api/ingest/{sensor}" }, { status: 405 });
  }
  const headers = new Headers();
  for (const name of ["authorization", "content-type", "content-length"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let answer: Response;
  try {
    answer = await fetch(`${API()}/api/ingest/${encodeURIComponent(path[1])}`, {
      method: "POST",
      headers,
      body: await request.arrayBuffer(),
      cache: "no-store",
    });
  } catch {
    return Response.json({ error: "the egms-client API does not answer" }, { status: 502 });
  }
  return new Response(answer.body, {
    status: answer.status,
    headers: { "content-type": answer.headers.get("content-type") ?? "application/json" },
  });
}
