import type { Metadata } from "next";
import DataPage from "@/components/DataPage";

type Params = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "I dati e come riusarli · egms-client",
  description: "Le fonti della pagina, il formato dei record, i template da scaricare e il codice per riusare i dati.",
};

export default async function Page({ searchParams }: { searchParams: Params }) {
  const asked = await searchParams;
  const lang = asked.lang === "en" || (!asked.lang && process.env.EGMS_UI_LANG === "en") ? "en" : "it";
  return <DataPage lang={lang} />;
}
