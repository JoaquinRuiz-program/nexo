"use strict";

/**
 * Librería Central — gráfico de barras minimalista, dibujado a mano sobre
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

  LC.chart = { renderBarChart };
})();
