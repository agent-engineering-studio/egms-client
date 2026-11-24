"use client";

import L from "leaflet";
import { useEffect, useRef } from "react";
import type { Text } from "@/lib/i18n";
import { centre } from "@/lib/records";
import { MAX_ZOOM, type Start, type Tiles } from "@/lib/start";
import type {
  Area,
  Box,
  Filed,
  Hotspot,
  MovingCell,
  OpenRecord,
} from "@/lib/types";

type Props = {
  start: Start;
  tiles: Tiles;
  text: Text;
  /** The area of the page, from the API: the map stays inside it. Null until it is known. */
  area: Area | null;
  /** The point of the card, if any. */
  point: { lat: number; lon: number } | null;
  /** The EGMS ground map, on or off. */
  showGround: boolean;
  moving: MovingCell[];
  /** The records in view, from every source but EGMS (which is the map). */
  records: Filed[];
  colour: (r: OpenRecord) => string;
  onPoint: (lat: number, lon: number) => void;
  /** A click outside the area: the page reads nothing there. */
  onOutside: () => void;
  /** The view changed: for the records. */
  onBounds: (box: Box) => void;
  /** The squares where the ground moves most, ranked: zones to follow. */
  hotspots: Hotspot[];
  /** The element the card of the point is drawn into, over the map (null when closed). */
  onCard: (element: HTMLElement | null) => void;
  /** The card was closed on the map (Esc). */
  onCloseCard: () => void;
  /** The ground map: being loaded, shown, shown without some tiles (still downloading), failed, or off. */
  onGround: (state: GroundState, missing?: string[]) => void;
};

export type GroundState = "loading" | "ready" | "partial" | "failed" | "none";

/** A map without some tiles is asked again this often, until it is whole. */
const AGAIN_MS = 120_000;

const dot = (cell: MovingCell): L.CircleMarkerOptions => ({
  radius: 6,
  color: cell.reliable ? "#17324d" : "#7a8290",
  weight: cell.reliable ? 2 : 1,
  dashArray: cell.reliable ? undefined : "2 3",
  fillColor: cell.velocity_mm_per_year < 0 ? "#cb181d" : "#2171b5",
  fillOpacity: 0.85,
});

const boundsOf = (a: Area) =>
  L.latLngBounds([a.south, a.west], [a.north, a.east]);

export default function MapView(props: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const overlay = useRef<L.ImageOverlay | null>(null);
  const frame = useRef<L.LayerGroup | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const cells = useRef<L.LayerGroup | null>(null);
  const hot = useRef<L.LayerGroup | null>(null);
  const popup = useRef<L.Popup | null>(null);
  const others = useRef<L.LayerGroup | null>(null);
  const area = useRef<Area | null>(null);
  const handlers = useRef(props);
  useEffect(() => {
    handlers.current = props;
  });

  useEffect(() => {
    const m = L.map(box.current!, {
      center: [props.start.lat, props.start.lon],
      zoom: props.start.zoom,
      maxZoom: MAX_ZOOM,
      // The map fills the page: the wheel zooms it.
      scrollWheelZoom: true,
      // Inside the area of the page: it cannot be dragged out of it.
      maxBoundsViscosity: 1,
    });
    L.tileLayer(props.tiles.url, {
      attribution: props.tiles.attribution,
      maxZoom: MAX_ZOOM,
    }).addTo(m);
    frame.current = L.layerGroup().addTo(m);
    hot.current = L.layerGroup().addTo(m);
    cells.current = L.layerGroup().addTo(m);
    others.current = L.layerGroup().addTo(m);
    const report = () => {
      const b = m.getBounds();
      handlers.current.onBounds({
        west: b.getWest(),
        south: b.getSouth(),
        east: b.getEast(),
        north: b.getNorth(),
      });
    };
    m.on("moveend", report);
    m.on("click", (e: L.LeafletMouseEvent) => {
      const a = area.current;
      if (a && !boundsOf(a).contains(e.latlng)) handlers.current.onOutside();
      else handlers.current.onPoint(e.latlng.lat, e.latlng.lng);
    });
    map.current = m;
    report();
    // The panel or the sheet changes the size of the map, and so the zoom that shows the area.
    const resized = new ResizeObserver(() => {
      m.invalidateSize();
      if (area.current) m.setMinZoom(m.getBoundsZoom(boundsOf(area.current)));
    });
    resized.observe(box.current!);
    return () => {
      resized.disconnect();
      m.remove();
      map.current = null;
    };
    // The map is made once; later props move what is on it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The area: lock the map on it, veil what is outside, and draw its edge.
  useEffect(() => {
    const m = map.current;
    const a = props.area;
    if (!m || !a || !frame.current) return;
    area.current = a;
    const bounds = boundsOf(a);
    const fit = m.getBoundsZoom(bounds);
    m.setMaxBounds(bounds.pad(0.05));
    m.setMinZoom(fit);
    if (
      props.start.given &&
      bounds.contains([props.start.lat, props.start.lon])
    ) {
      m.setView(
        [props.start.lat, props.start.lon],
        Math.max(props.start.zoom, fit),
      );
    } else {
      // On a phone the sheet covers the bottom third of the map: frame the area above it.
      const sheet = window.matchMedia("(max-width: 768px)").matches
        ? m.getSize().y * 0.34
        : 0;
      m.fitBounds(bounds, { paddingBottomRight: [0, sheet] });
    }
    frame.current.clearLayers();
    const world: L.LatLngExpression[] = [
      [-89, -179],
      [-89, 179],
      [89, 179],
      [89, -179],
    ];
    const hole: L.LatLngExpression[] = [
      [a.south, a.west],
      [a.north, a.west],
      [a.north, a.east],
      [a.south, a.east],
    ];
    L.polygon([world, hole], {
      stroke: false,
      fillColor: "#17324d",
      fillOpacity: 0.28,
      interactive: false,
    }).addTo(frame.current);
    L.rectangle(bounds, {
      color: "#17324d",
      weight: 2,
      dashArray: "6 4",
      fill: false,
      interactive: false,
    }).addTo(frame.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.area]);

  // The outline of the Comune, from ISTAT: where its own data gaps are counted.
  useEffect(() => {
    const m = map.current;
    if (!m || !props.area) return;
    let layer: L.GeoJSON | null = null;
    let live = true;
    fetch("/api/boundary")
      .then((r) => (r.ok ? r.json() : null))
      .then((feature) => {
        if (!live || !feature?.geometry) return;
        layer = L.geoJSON(feature, {
          style: {
            color: "#5c2d91",
            weight: 2.5,
            fill: false,
            dashArray: "8 5",
          },
          interactive: false,
        }).addTo(m);
      })
      .catch(() => undefined);
    return () => {
      live = false;
      layer?.remove();
    };
  }, [props.area]);

  // The ground map: one picture of the whole area. Tiles not downloaded yet are
  // striped, and the picture is asked again until it is whole.
  useEffect(() => {
    const m = map.current;
    const a = props.area;
    if (!m || !a) return;
    if (!props.showGround) {
      handlers.current.onGround("none");
      return;
    }
    const query = new URLSearchParams({
      west: String(a.west),
      south: String(a.south),
      east: String(a.east),
      north: String(a.north),
    });
    let stopped = false;
    let again: number | undefined;
    let shown: string | null = null;
    const load = async () => {
      if (!overlay.current) handlers.current.onGround("loading");
      try {
        const answer = await fetch(`/api/map.png?${query}`, {
          cache: "no-store",
        });
        if (!answer.ok) throw new Error(String(answer.status));
        const missing =
          answer.headers.get("x-missing-tiles")?.split(",").filter(Boolean) ??
          [];
        const url = URL.createObjectURL(await answer.blob());
        if (stopped) return URL.revokeObjectURL(url);
        if (overlay.current) overlay.current.setUrl(url);
        else
          overlay.current = L.imageOverlay(url, boundsOf(a), {
            opacity: 0.75,
            interactive: false,
          }).addTo(m);
        if (shown) URL.revokeObjectURL(shown);
        shown = url;
        handlers.current.onGround(
          missing.length ? "partial" : "ready",
          missing,
        );
        if (missing.length) again = window.setTimeout(load, AGAIN_MS);
      } catch {
        if (stopped) return;
        handlers.current.onGround("failed");
        again = window.setTimeout(load, AGAIN_MS);
      }
    };
    load();
    return () => {
      stopped = true;
      window.clearTimeout(again);
      overlay.current?.remove();
      overlay.current = null;
      if (shown) URL.revokeObjectURL(shown);
    };
  }, [props.area, props.showGround]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    marker.current?.remove();
    marker.current = props.point
      ? L.circleMarker([props.point.lat, props.point.lon], {
          radius: 9,
          color: "#0066cc",
          weight: 3,
          fillOpacity: 0,
        }).addTo(m)
      : null;
    // The card of the point: a popup over the map, filled by the page (a portal).
    if (!props.point) {
      popup.current?.remove();
      popup.current = null;
      handlers.current.onCard(null);
      return;
    }
    if (!popup.current) {
      const element = document.createElement("div");
      popup.current = L.popup({
        className: "egms-popup",
        maxWidth: Math.min(360, window.innerWidth - 40),
        minWidth: Math.min(300, window.innerWidth - 40),
        closeButton: false,
        closeOnClick: false,
        autoPanPaddingTopLeft: [16, 16],
        autoPanPaddingBottomRight: [16, 16],
      }).setContent(element);
      popup.current.on("remove", () => {
        // Closed by the map (Esc), not by a new point: the card goes.
        if (popup.current && !m.hasLayer(popup.current))
          handlers.current.onCloseCard();
      });
      // The page fills the card after it opens: place it again, and keep it in view, as it grows.
      new ResizeObserver(() => popup.current?.update()).observe(element);
      handlers.current.onCard(element);
    }
    popup.current.setLatLng([props.point.lat, props.point.lon]).openOn(m);
  }, [props.point]);

  // The squares where the ground moves most: outlined, with their rank.
  useEffect(() => {
    const group = hot.current;
    if (!group) return;
    group.clearLayers();
    for (const h of props.hotspots) {
      const ring = h.square.map(([lon, lat]) => [lat, lon] as L.LatLngTuple);
      const sign = h.median_mm_per_year > 0 ? "+" : "−";
      const text = `${h.rank}. ${sign}${Math.abs(h.median_mm_per_year)} mm`;
      L.polygon(ring, {
        color: "#5c2d91",
        weight: 2.5,
        fillColor: "#5c2d91",
        fillOpacity: 0.06,
      })
        .bindTooltip(text)
        .on("click", () => handlers.current.onPoint(h.lat, h.lon))
        .addTo(group);
      L.marker(ring[0], {
        icon: L.divIcon({
          className: "egms-hot-badge",
          html: `<span>${h.rank}</span>`,
          iconSize: [22, 22],
        }),
        keyboard: false,
      })
        .on("click", () => handlers.current.onPoint(h.lat, h.lon))
        .addTo(group);
    }
  }, [props.hotspots]);

  useEffect(() => {
    const group = cells.current;
    if (!group) return;
    group.clearLayers();
    for (const cell of props.moving) {
      L.circleMarker([cell.lat, cell.lon], dot(cell))
        .bindTooltip(
          `${cell.velocity_mm_per_year > 0 ? "+" : ""}${cell.velocity_mm_per_year} mm`,
        )
        .on("click", () => handlers.current.onPoint(cell.lat, cell.lon))
        .addTo(group);
    }
  }, [props.moving]);

  useEffect(() => {
    const group = others.current;
    if (!group) return;
    group.clearLayers();
    // One mark per place and source: a series of a rain gauge is one square, not one per reading.
    const seen = new Set<string>();
    for (const { record: r } of props.records) {
      if (r.kind === "layer") continue;
      const [lon, lat] = centre(r.where);
      const key = `${r.source.name}|${lon},${lat}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const colour = props.colour(r);
      const label =
        r.kind === "fact"
          ? r.question
          : `${r.thing ?? r.source.name} · ${r.property}`;
      const mark =
        r.where.type === "Point"
          ? L.marker([lat, lon], {
              icon: L.divIcon({
                className: "egms-source-mark",
                html: `<span style="background:${colour}"></span>`,
                iconSize: [16, 16],
              }),
              keyboard: false,
            })
          : L.geoJSON(r.where as GeoJSON.Geometry, {
              style: {
                color: colour,
                weight: 2,
                dashArray: "4 4",
                fill: false,
              },
            });
      mark
        .bindTooltip(`${r.source.name}: ${label ?? ""}`)
        .on("click", () => handlers.current.onPoint(lat, lon))
        .addTo(group);
    }
  }, [props.records, props.colour]);

  return (
    <div
      ref={box}
      className="egms-map"
      role="region"
      aria-label={props.text.mapLabel}
    />
  );
}
