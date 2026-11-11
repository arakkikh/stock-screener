// チャートの描画（Lightweight Charts）。ローソク足・移動平均線・ボリンジャーバンド・出来高・サインの印。
import { REVERSAL, WARNING, SHORT } from "./labels.js";

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function points(times, values) {
  const out = [];
  for (let i = 0; i < times.length; i++) {
    if (values[i] != null) out.push({ time: times[i], value: values[i] });
  }
  return out;
}

export const LINE_COLORS = { ma_s: "#e8a213", ma_m: "#d946ef", ma_l: "#0ea5e9", band: "#8b93a1" };

// その日に出たサインをまとめて、チャートの印にする
function buildMarkers(marks, labelFrom) {
  const up = cssVar("--accent"), down = cssVar("--danger"), sub = cssVar("--muted");
  const byDay = new Map();
  for (const m of marks) {
    if (!byDay.has(m.d)) byDay.set(m.d, []);
    byDay.get(m.d).push(m.k);
  }
  const markers = [];
  for (const [day, kinds] of byDay) {
    // 文字を付けるのは直近だけ（古い印まで文字を出すと重なって読めない）
    const names = (table) => {
      const hit = kinds.filter((k) => k in table).map((k) => SHORT[k]);
      return day >= labelFrom ? hit.join("・") : hit.length ? " " : "";
    };
    // 反転サインは、エントリー候補になった日だけ印を付ける（単独では多すぎるため）
    if (kinds.includes("entry")) {
      markers.push({ time: day, position: "belowBar", color: up, shape: "arrowUp", text: names(REVERSAL).trim() });
    }
    const warn = names(WARNING);
    if (warn) markers.push({ time: day, position: "aboveBar", color: down, shape: "arrowDown", text: warn.trim() });
    for (const k of ["bounce", "divergence", "two_white"]) {
      if (kinds.includes(k)) markers.push({ time: day, position: "belowBar", color: sub, shape: "circle", text: day >= labelFrom ? SHORT[k] : "" });
    }
  }
  return markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
}

// lines = 描く線の一覧 [{ key, color, width, style }]（省略すると逆張り用の線）
// priceLines = 水平線 [{ price, title, color }]、markers = 印（省略すると data.marks から作る）
export function drawChart(el, data, { digits = 1, showBands = true, bars = 90, labelDays = 10, lines = null, priceLines = [], markers = null } = {}) {
  el.innerHTML = "";
  const text = cssVar("--text"), grid = cssVar("--line"), up = cssVar("--up"), down = cssVar("--down");
  const chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: text, fontSize: 11 },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    rightPriceScale: { borderColor: grid },
    timeScale: { borderColor: grid, rightOffset: 3 },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { locale: "ja-JP", dateFormat: "yyyy/MM/dd" },
    handleScale: { axisPressedMouseMove: false },
  });
  const format = { type: "price", precision: digits, minMove: 1 / 10 ** digits };

  const candles = chart.addCandlestickSeries({
    upColor: up, downColor: down, borderUpColor: up, borderDownColor: down,
    wickUpColor: up, wickDownColor: down, priceFormat: format,
  });
  candles.setData(data.t.map((time, i) => ({ time, open: data.o[i], high: data.h[i], low: data.l[i], close: data.c[i] })));

  const line = (values, color, extra = {}) =>
    chart
      .addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: format, ...extra })
      .setData(points(data.t, values));
  const dashed = LightweightCharts.LineStyle.Dashed, dotted = LightweightCharts.LineStyle.Dotted;
  const defaults = [
    { key: "ma_s", color: LINE_COLORS.ma_s, width: 2 },
    { key: "ma_m", color: LINE_COLORS.ma_m, width: 2 },
    { key: "ma_l", color: LINE_COLORS.ma_l, width: 2 },
    ...(showBands
      ? [
          { key: "bb_l2", color: LINE_COLORS.band, style: dashed },
          { key: "bb_l3", color: LINE_COLORS.band, style: dotted },
          { key: "bb_u2", color: LINE_COLORS.band, style: dashed },
        ]
      : []),
  ];
  for (const item of lines ?? defaults) {
    if (data[item.key]) line(data[item.key], item.color, { lineWidth: item.width ?? 1, ...(item.style != null ? { lineStyle: item.style } : {}) });
  }
  for (const item of priceLines) {
    candles.createPriceLine({ price: item.price, color: item.color, lineWidth: 1, lineStyle: dashed, axisLabelVisible: true, title: item.title });
  }

  const volume = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } });
  volume.setData(
    data.t.map((time, i) => ({ time, value: data.v[i] ?? 0, color: (data.c[i] >= data.o[i] ? up : down) + "66" }))
  );

  if (markers) candles.setMarkers(markers);
  else if (data.marks) candles.setMarkers(buildMarkers(data.marks, data.t[Math.max(0, data.t.length - labelDays)]));

  const n = data.t.length;
  chart.timeScale().setVisibleLogicalRange({ from: n - bars, to: n + (priceLines.length ? 8 : 2) });
  return chart;
}

export function legendHTML(cfg, showBands = true) {
  const item = (color, label) => `<span><i style="background:${color}"></i>${label}</span>`;
  return (
    `<div class="legend">` +
    item(LINE_COLORS.ma_s, `${cfg.ma.short}日線`) +
    item(LINE_COLORS.ma_m, `${cfg.ma.mid}日線`) +
    item(LINE_COLORS.ma_l, `${cfg.ma.long}日線`) +
    (showBands ? item(LINE_COLORS.band, `±2σ・−3σ（${cfg.buy.bb_period}日）`) : "") +
    `</div>`
  );
}

// 線の色と名前の一覧から凡例を作る
export function legendItems(items) {
  return `<div class="legend">${items.map(([color, label]) => `<span><i style="background:${color}"></i>${label}</span>`).join("")}</div>`;
}
