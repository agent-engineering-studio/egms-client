"use client";

import L from "leaflet";
import { useEffect, useRef } from "react";
import type { Text } from "@/lib/i18n";
import { MAX_ZOOM, MIN_ZOOM, type Start, type Tiles } from "@/lib/start";
import { centre } from "@/lib/records";
import type { Box, Filed, MovingCell, OpenRecord } from "@/lib/types";

/** The velocity map is asked for only on views at most this wide, in degrees. */
export const MAX_SPAN = 0.3;

type Props = {
  start: Start;
  tiles: Tiles;
  text: Text;
  /** The point of the card, if any. */
  point: { lat: number; lon: number } | null;
  /** The EGMS ground map, on or off. */
  showGround: boolean;
  moving: MovingCell[];
  onPoint: (lat: number, lon: number) => void;
  /** The view changed: its box, or null when it is too wide for the velocity map. */
  onView: (box: Box | null) => void;
  /** The view changed, at any size: for the records. */
  onBounds: (box: Box) => void;
  /** The records in view, from every source but EGMS (which is the map). */
  records: Filed[];
  colour: (r: OpenRecord) => string;
};

const dot = (cell: MovingCell): L.CircleMarkerOptions => ({
  radius: 6,
  color: cell.reliable ? "#17324d" : "#7a8290",
  weight: cell.reliable ? 2 : 1,
  dashArray: cell.reliable ? undefined : "2 3",
  fillColor: cell.velocity_mm_per_year < 0 ? "#cb181d" : "#2171b5",
  fillOpacity: 0.85,
});

export default function MapView(props: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const overlay = useRef<L.ImageOverlay | null>(null);
  const reportRef = useRef<() => void>(() => undefined);
  const marker = useRef<L.CircleMarker | null>(null);
  const cells = useRef<L.LayerGroup | null>(null);
  const others = useRef<L.LayerGroup | null>(null);
  const handlers = useRef({ onPoint: props.onPoint, onView: props.onView, onBounds: props.onBounds });
  const ground = useRef(props.showGround);
  useEffect(() => {
    handlers.current = { onPoint: props.onPoint, onView: props.onView, onBounds: props.onBounds };
  });

  useEffect(() => {
    const m = L.map(box.current!, {
      center: [props.start.lat, props.start.lon],
      zoom: props.start.zoom,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      // The map fills the page: the wheel zooms it.
      scrollWheelZoom: true,
    });
    L.tileLayer(props.tiles.url, { attribution: props.tiles.attribution, maxZoom: MAX_ZOOM }).addTo(m);
    cells.current = L.layerGroup().addTo(m);
    others.current = L.layerGroup().addTo(m);
    const report = () => {
      const b = m.getBounds();
      const view = { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() };
      const small = view.east - view.west <= MAX_SPAN && view.north - view.south <= MAX_SPAN;
      handlers.current.onView(small ? view : null);
      handlers.current.onBounds(view);
      if ((!small || !ground.current) && overlay.current) {
        overlay.current.remove();
        overlay.current = null;
      }
      if (small && ground.current) {
        const url = `/api/map.png?${new URLSearchParams(Object.entries(view).map(([k, v]) => [k, v.toFixed(5)]))}`;
        const bounds: L.LatLngBoundsExpression = [
          [view.south, view.west],
          [view.north, view.east],
        ];
        if (overlay.current) {
          overlay.current.setUrl(url).setBounds(L.latLngBounds(bounds));
        } else {
          overlay.current = L.imageOverlay(url, bounds, { opacity: 0.75, interactive: false }).addTo(m);
        }
      }
    };
    m.on("moveend", report);
    m.on("click", (e: L.LeafletMouseEvent) => handlers.current.onPoint(e.latlng.lat, e.latlng.lng));
    map.current = m;
    reportRef.current = report;
    report();
    // The panel or the sheet changes the size of the map.
    const resized = new ResizeObserver(() => m.invalidateSize());
    resized.observe(box.current!);
    return () => {
      resized.disconnect();
      m.remove();
      map.current = null;
    };
    // The map is made once; later props move what is on it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    ground.current = props.showGround;
    reportRef.current();
  }, [props.showGround]);

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
  }, [props.point]);

  useEffect(() => {
    const group = cells.current;
    if (!group) return;
    group.clearLayers();
    for (const cell of props.moving) {
      L.circleMarker([cell.lat, cell.lon], dot(cell))
        .bindTooltip(`${cell.velocity_mm_per_year > 0 ? "+" : ""}${cell.velocity_mm_per_year} mm`)
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
      const label = r.kind === "fact" ? r.question : `${r.thing ?? r.source.name} · ${r.property}`;
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
          : L.geoJSON(r.where as GeoJSON.Geometry, { style: { color: colour, weight: 2, dashArray: "4 4", fill: false } });
      mark
        .bindTooltip(`${r.source.name}: ${label ?? ""}`)
        .on("click", () => handlers.current.onPoint(lat, lon))
        .addTo(group);
    }
  }, [props.records, props.colour]);

  return <div ref={box} className="egms-map" role="region" aria-label={props.text.mapLabel} />;
}
