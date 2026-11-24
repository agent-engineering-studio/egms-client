"use client";

import { useEffect, useState } from "react";
import { TEXT } from "@/lib/i18n";
import type { Start, Tiles } from "@/lib/start";
import type { Health } from "@/lib/types";
import Ground, { ask, failed } from "./Ground";

/** How often the loading screen asks how far the download is. */
const POLL_MS = 1500;

/**
 * The page opens on its data. At startup the API downloads the EGMS tiles of
 * the area; until they are on the disk this screen shows how far it is, then
 * the map opens. In demo mode, or when the tiles are already there, at once.
 */
export default function Startup({ start, tiles }: { start: Start; tiles: Tiles }) {
  const t = TEXT[start.lang];
  const [health, setHealth] = useState<Health | null>(null);
  const [silent, setSilent] = useState(false);
  const [entered, setEntered] = useState(false);
  const ready = entered || health?.startup?.ready === true;

  useEffect(() => {
    if (ready) return;
    let live = true;
    let timer: number | undefined;
    const poll = async () => {
      const h = await ask<Health>("health", {});
      if (!live) return;
      if (failed(h)) setSilent(true);
      else {
        setSilent(false);
        setHealth(h);
        if (h.startup?.ready) return;
      }
      timer = window.setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [ready]);

  if (ready) return <Ground start={start} tiles={tiles} />;

  const s = health?.startup;
  const pct = Math.round((s?.share ?? 0) * 100);
  const mb = (bytes: number) => (bytes / 1e6).toLocaleString(t.locale, { maximumFractionDigits: 0 });
  const loading = s?.tiles.filter((x) => x.state === "downloading") ?? [];
  const got = loading.reduce((sum, x) => sum + x.received, 0);
  const all = loading.reduce((sum, x) => sum + x.total, 0);
  return (
    <div className="egms-startup" role="status" aria-live="polite">
      <div className="egms-startup-box">
        <h1>{t.loadingTitle(start.place ?? t.loadingArea)}</h1>
        <p>{t.loadingWhy}</p>
        <div className="progress egms-startup-bar" aria-label={`${pct}%`}>
          <div
            className="progress-bar bg-primary"
            role="progressbar"
            style={{ width: `${pct}%` }}
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        </div>
        <p className="egms-startup-pct">
          {pct}%{all > 0 && <> · {t.loadingMb(mb(got), mb(all))}</>}
        </p>
        {s && (
          <ul className="egms-startup-tiles">
            {s.tiles.map((x) => (
              <li key={`${x.tile}-${x.component}`} className={x.state}>
                <span>
                  {x.tile} · {t.loadingComponent[x.component]}
                </span>
                <span>
                  {t.loadingStates[x.state]}
                  {x.state === "downloading" && ` ${Math.round(x.share * 100)}%`}
                </span>
              </li>
            ))}
            {s.boundaries && (
              <li className={s.boundaries.state}>
                <span>{t.loadingBoundaries}</span>
                <span>
                  {t.loadingBoundaryStates[s.boundaries.state]}
                  {s.boundaries.state === "downloading" && ` ${Math.round(s.boundaries.share * 100)}%`}
                </span>
              </li>
            )}
          </ul>
        )}
        {silent && <p className="egms-warning">{t.loadingNoApi}</p>}
        {(s?.state === "slow" || (s?.state === "waiting" && s.error)) && (
          <>
            <p className="egms-warning">
              {s.state === "slow" ? t.loadingSlow : t.loadingRetry(s.retry_in_s ?? 0, (s.error ?? "").split(":")[0])}
            </p>
            <button type="button" className="btn btn-outline-primary btn-sm" onClick={() => setEntered(true)}>
              {t.loadingEnter}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
