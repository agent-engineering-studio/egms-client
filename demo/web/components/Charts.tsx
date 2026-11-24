// Small charts for the card of a point, in plain SVG: no library, readable in both
// languages, and each with a text alternative. They draw the numbers of the sources;
// they compute nothing but positions.

/** An arrow for a motion: up, down, east, west, or a dot when there is no motion or no measure. */
export function MotionIcon({
  value,
  component,
}: {
  value: number | null;
  component: "U" | "E";
}) {
  const still = value === null || Math.abs(value) < 0.05;
  const angle = still
    ? 0
    : component === "U"
      ? value! > 0
        ? 0
        : 180
      : value! > 0
        ? 90
        : 270;
  const colour =
    value === null
      ? "#7a8290"
      : component === "U"
        ? value > 0
          ? "#08519c"
          : "#cb181d"
        : "#5c2d91";
  return (
    <svg
      className="egms-motion"
      viewBox="0 0 32 32"
      width="32"
      height="32"
      aria-hidden="true"
    >
      <circle cx="16" cy="16" r="15" fill={colour} opacity="0.12" />
      {still ? (
        <circle cx="16" cy="16" r="4" fill={colour} />
      ) : (
        <path
          d="M16 6 L24 16 H19 V26 H13 V16 H8 Z"
          fill={colour}
          transform={`rotate(${angle} 16 16)`}
        />
      )}
    </svg>
  );
}

type Bar = { label: string; value: number | null; colour: string };

/** Horizontal bars around zero on one scale: the point and its surroundings, side by side. */
export function CompareBars({
  bars,
  unit,
  label,
  locale,
}: {
  bars: Bar[];
  unit: string;
  label: string;
  locale: string;
}) {
  const known = bars.filter(
    (b): b is Bar & { value: number } => b.value !== null,
  );
  const reach = Math.max(1, ...known.map((b) => Math.abs(b.value)));
  const width = 260;
  const zero = width / 2;
  // Room on each side for the number at the end of the bar.
  const scale = (v: number) => (v / reach) * (width / 2 - 46);
  const fmt = (v: number) =>
    `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString(locale, { maximumFractionDigits: 1 })}`;
  return (
    <figure className="egms-chart" aria-label={label}>
      <svg
        viewBox={`0 0 ${width} ${bars.length * 26 + 6}`}
        width="100%"
        role="img"
        aria-label={label}
      >
        <line
          x1={zero}
          x2={zero}
          y1="0"
          y2={bars.length * 26 + 6}
          stroke="#9aa3b0"
          strokeDasharray="2 2"
        />
        {bars.map((b, i) => {
          const y = i * 26 + 4;
          if (b.value === null) {
            return (
              <text
                key={b.label}
                x={zero + 6}
                y={y + 14}
                className="egms-chart-none"
              >
                {b.label}: —
              </text>
            );
          }
          const w = scale(b.value);
          const x = w >= 0 ? zero : zero + w;
          return (
            <g key={b.label}>
              <rect
                x={x}
                y={y}
                width={Math.max(1.5, Math.abs(w))}
                height="16"
                rx="3"
                fill={b.colour}
              />
              <text
                x={w >= 0 ? zero - 6 : zero + 6}
                y={y + 12}
                textAnchor={w >= 0 ? "end" : "start"}
                className="egms-chart-label"
              >
                {b.label}
              </text>
              <text
                x={w >= 0 ? zero + w + 4 : zero + w - 4}
                y={y + 12}
                textAnchor={w >= 0 ? "start" : "end"}
                className="egms-chart-value"
              >
                {fmt(b.value)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption>{unit}</figcaption>
    </figure>
  );
}

/** A meter from 0 to 1, with the mark from which a value is reliable. */
export function Meter({
  value,
  mark,
  label,
}: {
  value: number;
  mark: number;
  label: string;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const colour = value >= mark ? "#1d6b38" : value > 0 ? "#b36b00" : "#7a8290";
  return (
    <div
      className="egms-meter"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={value}
      aria-label={label}
    >
      <span
        className="egms-meter-fill"
        style={{ width: `${pct}%`, background: colour }}
      />
      <span className="egms-meter-mark" style={{ left: `${mark * 100}%` }} />
    </div>
  );
}

/** A thin line of values over time, with its first and last reading. */
export function Sparkline({
  values,
  label,
}: {
  values: (number | null)[];
  label: string;
}) {
  const known = values.filter((v): v is number => v !== null);
  if (known.length < 2) return null;
  const w = 220;
  const h = 40;
  const low = Math.min(...known);
  const high = Math.max(...known);
  const span = high - low || 1;
  const x = (i: number) => (i / (values.length - 1)) * (w - 8) + 4;
  const y = (v: number) => h - 4 - ((v - low) / span) * (h - 8);
  const parts: string[] = [];
  values.forEach((v, i) => {
    if (v === null) return;
    const prev = values[i - 1];
    parts.push(
      `${prev === null || prev === undefined || i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`,
    );
  });
  return (
    <svg
      className="egms-spark"
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height={h}
      role="img"
      aria-label={label}
    >
      <path
        d={parts.join(" ")}
        fill="none"
        stroke="#0066cc"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      {values.map((v, i) =>
        v === null ? (
          <circle
            key={i}
            cx={x(i)}
            cy={h - 4}
            r="2.5"
            fill="none"
            stroke="#7a8290"
          />
        ) : (
          <circle key={i} cx={x(i)} cy={y(v)} r="2.5" fill="#0066cc" />
        ),
      )}
    </svg>
  );
}

/** The period a measure covers, as a bar on the years it spans. */
export function Period({
  first,
  last,
  label,
}: {
  first: string;
  last: string;
  label: string;
}) {
  const y0 = Number(first.slice(0, 4));
  const y1 = Number(last.slice(0, 4)) + 1;
  const at = (d: string) => {
    const t = new Date(d + "T00:00:00Z");
    return (
      ((t.getUTCFullYear() + t.getUTCMonth() / 12 + t.getUTCDate() / 365 - y0) /
        (y1 - y0)) *
      100
    );
  };
  const years = Array.from({ length: y1 - y0 + 1 }, (_, i) => y0 + i);
  return (
    <div className="egms-period" aria-label={label}>
      <div className="egms-period-track">
        <span
          className="egms-period-fill"
          style={{ left: `${at(first)}%`, width: `${at(last) - at(first)}%` }}
        />
      </div>
      <div className="egms-period-years">
        {years.map((year) => (
          <span key={year}>{String(year).slice(2)}</span>
        ))}
      </div>
    </div>
  );
}
