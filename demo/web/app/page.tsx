import { redirect } from "next/navigation";
import Ground from "@/components/Ground";
import { startFrom, tilesFrom } from "@/lib/start";

type Params = Promise<Record<string, string | string[] | undefined>>;

// Read when the page is asked for, not when it is built: one image, any Comune.
export const dynamic = "force-dynamic";

export default async function Page({ searchParams }: { searchParams: Params }) {
  const asked = await searchParams;
  const one = (name: string) => {
    const value = asked[name];
    return Array.isArray(value) ? value[0] : value;
  };
  // The old tabs of the card now live on the page of the data.
  const tab = one("tab");
  if (tab === "fonti" || tab === "sources") redirect(`/dati?lang=${one("lang") ?? ""}`);
  if (tab === "aggiungi" || tab === "add") redirect(`/dati?lang=${one("lang") ?? ""}#aggiungi`);
  const env = process.env;
  const start = startFrom(
    { lat: one("lat"), lon: one("lon"), zoom: one("zoom"), place: one("place"), lang: one("lang"), embed: one("embed") },
    { lat: env.EGMS_UI_LAT, lon: env.EGMS_UI_LON, zoom: env.EGMS_UI_ZOOM, place: env.EGMS_UI_PLACE, lang: env.EGMS_UI_LANG },
  );
  return <Ground start={start} tiles={tilesFrom(env.EGMS_UI_TILES, env.EGMS_UI_TILES_CREDIT)} />;
}
