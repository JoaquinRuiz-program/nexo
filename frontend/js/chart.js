"use strict";

/**
 * Nexo — gráfico de barras minimalista, dibujado a mano sobre
 * <canvas>. A propósito NO se usa ninguna librería externa (Chart.js,
 * etc.): esta pantalla no necesita nada más que barras simples con eje X de
 * fechas, y evitar una dependencia (y una carga desde un CDN externo que
 * podría fallar) es preferible a agregar peso por una necesidad tan chica.
 *
 * No sabe nada de Mercado Libre ni de ventas — solo recibe puntos
 * {fecha, valor} y los dibuja. Los datos y su cálculo viven en
 * js/dataSource.js.
 */

window.LC = window.LC || {};

(function () {
  function isDark() {
    return document.documentElement.classList.contains("dark");
  }

  function renderBarChart(canvas, points, opts) {
    const options = opts || {};
    const formatValue = options.formatValue || ((v) => String(v));
    const dpr = window.devicePixelRatio || 1;
    const cssWidth = canvas.clientWidth || canvas.parentElement.clientWidth || 600;
    const cssHeight = options.height || 220;

    canvas.width = cssWidth * dpr;
    canvas.height = cssHeight * dpr;
    canvas.style.width = cssWidth + "px";
    canvas.style.height = cssHeight + "px";

    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    const dark = isDark();
    const colors = {
      bar: dark ? "#6366f1" : "#4f46e5",
      barMuted: dark ? "#312e81" : "#e0e7ff",
      axis: dark ? "#334155" : "#e2e8f0",
      label: dark ? "#94a3b8" : "#64748b",
      empty: dark ? "#475569" : "#94a3b8",
    };

    const padding = { top: 16, right: 12, bottom: 28, left: 12 };
    const plotW = cssWidth - padding.left - padding.right;
    const plotH = cssHeight - padding.top - padding.bottom;

    if (!points.length) {
      ctx.fillStyle = colors.empty;
      ctx.font = "13px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Sin datos en este período", cssWidth / 2, cssHeight / 2);
      return;
    }

    const maxVal = Math.max(1, ...points.map((p) => p.valor));
    const n = points.length;
    const gap = n > 45 ? 1 : n > 20 ? 2 : 4;
    const barW = Math.max(1, (plotW - gap * (n - 1)) / n);

    // Línea base
    ctx.strokeStyle = colors.axis;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top + plotH + 0.5);
    ctx.lineTo(padding.left + plotW, padding.top + plotH + 0.5);
    ctx.stroke();

    // Cuántas etiquetas de fecha caben sin amontonarse
    const labelEvery = n <= 8 ? 1 : n <= 16 ? 2 : n <= 32 ? 5 : 7;

    points.forEach((p, i) => {
      const x = padding.left + i * (barW + gap);
      const h = maxVal > 0 ? (p.valor / maxVal) * (plotH - 6) : 0;
      const y = padding.top + plotH - h;

      ctx.fillStyle = p.valor > 0 ? colors.bar : colors.barMuted;
      const radius = Math.min(3, barW / 2);
      roundRectTop(ctx, x, y, barW, Math.max(h, 1), radius);
      ctx.fill();

      if (i % labelEvery === 0 || i === n - 1) {
        ctx.fillStyle = colors.label;
        ctx.font = "10px Inter, sans-serif";
        ctx.textAlign = "center";
        const etiqueta = p.fecha.toLocaleDateString("es-CL", { day: "2-digit", month: "2-digit" });
        ctx.fillText(etiqueta, x + barW / 2, padding.top + plotH + 16);
      }
    });

    // Valor máximo, arriba a la izquierda, para dar contexto de escala.
    ctx.fillStyle = colors.label;
    ctx.font = "10px Inter, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(`máx: ${formatValue(maxVal)}`, padding.left, 10);
  }

  function roundRectTop(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x, y + h);
    ctx.lineTo(x, y + r);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.lineTo(x + w - r, y);
    ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h);
    ctx.closePath();
  }

  // ------------------------------------------------------------------
  // 14 de septiembre de 2026 — gráficos del Overview del admin (BI). SVG
  // devuelto como STRING para incrustar directo en el innerHTML de la página
  // (mismo enfoque de composición que el resto del frontend), sin librería
  // externa. Tooltips nativos vía <title>. Los colores son vivos y funcionan
  // igual en claro/oscuro; el texto usa clases con tokens de tema.
  // ------------------------------------------------------------------

  const PALETA = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7", "#94a3b8"];

  function _escapeXml(s) {
    return String(s == null ? "" : s).replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));
  }

  function lineChartSVG(points, opts) {
    const o = opts || {};
    const fmt = o.formatValue || ((v) => String(v));
    const fmtFecha = o.formatFecha || ((iso) => iso);
    if (!points || !points.length) return '<div class="chart-empty">Sin datos suficientes</div>';

    const W = 720, H = 240, pad = { t: 20, r: 16, b: 28, l: 16 };
    const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
    const n = points.length;
    const max = Math.max(1, ...points.map((p) => p.monto));
    // 14 de septiembre de 2026 — la serie de margen puede ser negativa (se
    // vendió a pérdida): la escala va de min(0, valores) a max. Con valores
    // >= 0 (ventas) min es 0 y el gráfico queda exactamente igual que antes.
    const min = Math.min(0, ...points.map((p) => p.monto));
    const x = (i) => pad.l + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
    const y = (v) => pad.t + plotH - ((v - min) / (max - min)) * (plotH - 6);

    const linea = points.map((p, i) => `${x(i).toFixed(1)},${y(p.monto).toFixed(1)}`).join(" ");
    const base = min < 0 ? y(0) : pad.t + plotH;  // el área se rellena contra el cero
    const area = `${x(0).toFixed(1)},${base.toFixed(1)} ${linea} ${x(n - 1).toFixed(1)},${base.toFixed(1)}`;
    const every = n <= 8 ? 1 : n <= 16 ? 2 : Math.ceil(n / 8);
    const labels = points.map((p, i) => (i % every === 0 || i === n - 1)
      ? `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="chart-axis-label">${_escapeXml(fmtFecha(p.fecha))}</text>` : "").join("");
    const dots = points.map((p, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(p.monto).toFixed(1)}" r="${n > 40 ? 0 : 2.5}" fill="#6366f1"><title>${_escapeXml(fmtFecha(p.fecha))}: ${_escapeXml(fmt(p.monto))}</title></circle>`).join("");

    return `<svg viewBox="0 0 ${W} ${H}" class="chart-svg" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Evolución en el tiempo">
      <defs><linearGradient id="lc-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6366f1" stop-opacity="0.22"/><stop offset="1" stop-color="#6366f1" stop-opacity="0"/></linearGradient></defs>
      <polygon points="${area}" fill="url(#lc-area)"/>
      <polyline points="${linea}" fill="none" stroke="#6366f1" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      ${dots}${labels}
      <text x="${pad.l}" y="12" class="chart-axis-label">${points.every((p) => p.monto === 0) ? "Sin movimientos en el período" : `máx ${_escapeXml(fmt(max))}`}</text>
      ${min < 0 ? `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="#94a3b8" stroke-dasharray="4 4" stroke-width="1"/>
      <text x="${W - pad.r}" y="12" text-anchor="end" class="chart-axis-label">mín ${_escapeXml(fmt(min))}</text>` : ""}
    </svg>`;
  }

  function _pol(cx, cy, r, a) { return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; }

  function _arco(cx, cy, r, rin, a1, a2, large) {
    const [x1, y1] = _pol(cx, cy, r, a1), [x2, y2] = _pol(cx, cy, r, a2);
    const [x3, y3] = _pol(cx, cy, rin, a2), [x4, y4] = _pol(cx, cy, rin, a1);
    return `M${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large} 1 ${x2.toFixed(2)},${y2.toFixed(2)} L${x3.toFixed(2)},${y3.toFixed(2)} A${rin},${rin} 0 ${large} 0 ${x4.toFixed(2)},${y4.toFixed(2)} Z`;
  }

  function donutChartSVG(segments, opts) {
    const o = opts || {};
    const fmt = o.formatValue || ((v) => String(v));
    const total = (segments || []).reduce((s, x) => s + (x.monto || 0), 0);
    if (!segments || !segments.length || total <= 0) return '<div class="chart-empty">Sin datos suficientes</div>';

    const cx = 110, cy = 110, r = 92, rin = 60;
    let ang = -Math.PI / 2;
    const arcos = segments.map((s, i) => {
      const frac = s.monto / total;
      const a2 = ang + frac * 2 * Math.PI;
      const large = frac > 0.5 ? 1 : 0;
      // Un único segmento (100%) no se puede dibujar como arco: es un anillo completo.
      const path = frac >= 0.9999
        ? `M${cx - r},${cy} A${r},${r} 0 1 1 ${cx + r},${cy} A${r},${r} 0 1 1 ${cx - r},${cy} M${cx - rin},${cy} A${rin},${rin} 0 1 0 ${cx + rin},${cy} A${rin},${rin} 0 1 0 ${cx - rin},${cy} Z`
        : _arco(cx, cy, r, rin, ang, a2, large);
      ang = a2;
      const color = s.color || PALETA[i % PALETA.length];
      return `<path d="${path}" fill="${color}" fill-rule="evenodd"><title>${_escapeXml(s.nombre)}: ${_escapeXml(fmt(s.monto))} (${s.pct}%)</title></path>`;
    }).join("");

    return `<svg viewBox="0 0 220 220" class="chart-donut" role="img" aria-label="Distribución por empresa">
      ${arcos}
      <text x="110" y="106" text-anchor="middle" class="donut-num">${_escapeXml(fmt(total))}</text>
      <text x="110" y="126" text-anchor="middle" class="donut-lbl">total</text>
    </svg>`;
  }

  LC.chart = { renderBarChart, lineChartSVG, donutChartSVG, PALETA };
})();
