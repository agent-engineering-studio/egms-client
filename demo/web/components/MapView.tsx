"use client";

import L from "leaflet";
import { useEffect, useRef } from "react";
import type { Text } from "@/lib/i18n";
import { MAX_ZOOM, MIN_ZOOM, type Start, type Tiles } from "@/lib/start";
import type { Box, MovingCell } from "@/lib/types";

/** The velocity map is asked for only on views at most this wide, in degrees. */
export const MAX_SPAN = 0.3;

type Props = {
  start: Start;
  tiles: Tiles;
  text: Text;
  /** The point of the card, if any. */
  point: { lat: number; lon: number } | null;
  moving: MovingCell[];
  onPoint: (lat: number, lon: number) => void;
  /** The view changed: its box, or null when it is too wide for the velocity map. */
  onView: (box: Box | null) => void;
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
  const marker = useRef<L.CircleMarker | null>(null);
  const cells = useRef<L.LayerGroup | null>(null);
  const handlers = useRef({ onPoint: props.onPoint, onView: props.onView });
  useEffect(() => {
    handlers.current = { onPoint: props.onPoint, onView: props.onView };
  });

  useEffect(() => {
    const m = L.map(box.current!, {
      center: [props.start.lat, props.start.lon],
      zoom: props.start.zoom,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      // The map is in a page that scrolls: the wheel moves the page, the buttons zoom.
      scrollWheelZoom: false,
    });
    L.tileLayer(props.tiles.url, { attribution: props.tiles.attribution, maxZoom: MAX_ZOOM }).addTo(m);
    cells.current = L.layerGroup().addTo(m);
    const report = () => {
      const b = m.getBounds();
      const view = { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() };
      const small = view.east - view.west <= MAX_SPAN && view.north - view.south <= MAX_SPAN;
      handlers.current.onView(small ? view : null);
      if (!small && overlay.current) {
        overlay.current.remove();
        overlay.current = null;
      }
      if (small) {
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
    report();
    return () => {
      m.remove();
      map.current = null;
    };
    // The map is made once; later props move what is on it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  return <div ref={box} className="egms-map" role="region" aria-label={props.text.mapLabel} />;
}
