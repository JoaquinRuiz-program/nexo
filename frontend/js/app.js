"use strict";

/**
 * Librería Central — orquestador de pantallas.
 *
 * Todo lo que se ve viene de LC.dataSource (Demo Mode hoy). Este archivo no
 * sabe de dónde vienen los datos, solo cómo pintarlos — cuando dataSource
 * empiece a hablar con el backend real, esto no debería necesitar cambios.
 */

window.LC = window.LC || {};

(function () {
  const { escapeHtml, formatCLP, formatDate, initials, toast, infoModal, openModal } = LC.ui;

  const SECTION_TITLES = {
    dashboard: "Dashboard",
    productos: "Productos",
    mercadolibre: "Mercado Libre",
    sincronizacion: "Sincronización",
    suscripcion: "Suscripción",
    configuracion: "Configuración",
  };

  const state = {
    search: "",
    filterTipo: "todos",
    filterStock: "todos",
    sortKey: "nombre",
    sortDir: "asc",
    page: 1,
    pageSize: 10,
    selected: new Set(),
  };

  let shellWired = false;
  let scrollTarget = null;

  const mlState = {
    rango: "30d",
    metric: "ingresos",
    search: "",
    filterEstado: "todos",
    filterProducto: "todos",
    page: 1,
    pageSize: 8,
  };

  // ------------------------------------------------------------------
  // Render orquestador
  // ------------------------------------------------------------------

  async function render(routeName, param) {
    const loggedIn = LC.auth.isLoggedIn();
    document.getElementById("auth-screens").classList.toggle("hidden", loggedIn);
    document.getElementById("app-shell").classList.toggle("hidden", !loggedIn);

    if (!loggedIn) {
      wireAuthScreens();
      showAuthScreen(routeName);
      return;
    }

    wireShell();
    closeMobileSidebar();
    setActiveNav(routeName);
    document.getElementById("page-title").textContent = SECTION_TITLES[routeName] || "Librería Central";
    updateUserHeader();

    const main = document.getElementById("main-content");
    main.innerHTML = skeletonPage();

    try {
      switch (routeName) {
        case "dashboard":
          await renderDashboard(main);
          break;
        case "productos":
          if (param) await renderProductDetail(main, param);
          else await renderProductos(main);
          break;
        case "mercadolibre":
          await renderMercadoLibre(main);
          break;
        case "sincronizacion":
          await renderSincronizacion(main);
          break;
        case "suscripcion":
          await renderSuscripcion(main);
          break;
        case "configuracion":
          await renderConfiguracion(main);
          break;
        default:
          main.innerHTML = `<div class="page-wrap">Sección no encontrada.</div>`;
      }
    } catch (err) {
      main.innerHTML = `<div class="page-wrap"><div class="panel-card"><p class="text-red-600 dark:text-red-400 font-medium">Ocurrió un problema mostrando esta sección.</p><p class="text-sm text-slate-500 mt-1">${escapeHtml(String(err && err.message ? err.message : err))}</p></div></div>`;
    }

    if (scrollTarget) {
      const el = document.getElementById(scrollTarget);
      scrollTarget = null;
      if (el) setTimeout(() => el.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
    }
  }

  function skeletonPage() {
    return `<div class="page-wrap app-fade">
      <div class="skeleton-line h-8 w-56 mb-6"></div>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        ${Array.from({ length: 4 }).map(() => '<div class="skeleton-line h-28 w-full"></div>').join("")}
      </div>
    </div>`;
  }

  // ------------------------------------------------------------------
  // Shell: sidebar, header, menú de usuario, tema
  // ------------------------------------------------------------------

  function setActiveNav(routeName) {
    document.querySelectorAll(".nav-link").forEach((a) => {
      a.classList.toggle("active-nav", a.dataset.route === routeName);
    });
  }

  function updateUserHeader() {
    const session = LC.auth.getSession() || LC.demoData.account;
    document.getElementById("user-name-label").textContent = session.nombre;
    document.getElementById("user-avatar").textContent = initials(session.nombre);
    document.getElementById("theme-toggle-icon").textContent = LC.theme.isDark() ? "☀️" : "🌙";
  }

  function openMobileSidebar() {
    document.getElementById("sidebar").classList.remove("-translate-x-full");
    document.getElementById("sidebar-overlay").classList.remove("hidden");
  }
  function closeMobileSidebar() {
    document.getElementById("sidebar").classList.add("-translate-x-full");
    document.getElementById("sidebar-overlay").classList.add("hidden");
  }

  function wireShell() {
    if (shellWired) {
      updateUserHeader();
      return;
    }
    shellWired = true;

    document.getElementById("hamburger-btn").addEventListener("click", openMobileSidebar);
    document.getElementById("sidebar-close-btn").addEventListener("click", closeMobileSidebar);
    document.getElementById("sidebar-overlay").addEventListener("click", closeMobileSidebar);

    document.getElementById("theme-toggle-btn").addEventListener("click", () => {
      LC.theme.toggleQuick();
    });
    document.addEventListener("lc:theme-changed", () => {
      document.getElementById("theme-toggle-icon").textContent = LC.theme.isDark() ? "☀️" : "🌙";
    });

    const userMenuBtn = document.getElementById("user-menu-btn");
    const userMenuDropdown = document.getElementById("user-menu-dropdown");
    userMenuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      userMenuDropdown.classList.toggle("hidden");
    });
    document.addEventListener("click", () => userMenuDropdown.classList.add("hidden"));

    userMenuDropdown.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      userMenuDropdown.classList.add("hidden");
      if (action === "account") {
        scrollTarget = "config-cuenta";
        LC.router.navigate("/configuracion");
      } else if (action === "subscription") {
        LC.router.navigate("/suscripcion");
      } else if (action === "settings") {
        LC.router.navigate("/configuracion");
      } else if (action === "logout") {
        LC.auth.logout();
        toast("info", "Sesión cerrada.");
        LC.router.navigate("/login");
      }
    });

    updateUserHeader();
  }

  // ------------------------------------------------------------------
  // Auth screens (login / signup)
  // ------------------------------------------------------------------

  let authWired = false;

  function showAuthScreen(routeName) {
    document.getElementById("screen-login").classList.toggle("hidden", routeName !== "login");
    document.getElementById("screen-signup").classList.toggle("hidden", routeName !== "signup");
  }

  function wirePasswordToggle(inputId, btnId) {
    const input = document.getElementById(inputId);
    const btn = document.getElementById(btnId);
    btn.addEventListener("click", () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "🙈" : "👁️";
    });
  }

  function wireAuthScreens() {
    if (authWired) return;
    authWired = true;

    wirePasswordToggle("login-password", "login-toggle-password");
    wirePasswordToggle("signup-password", "signup-toggle-password");

    document.getElementById("login-forgot").addEventListener("click", () => {
      infoModal(
        "Recuperar contraseña",
        "La recuperación de contraseña estará disponible cuando conectemos el sistema de autenticación real. Por ahora, esta es una demostración: cualquier email y contraseña permiten entrar."
      );
    });

    document.getElementById("signup-terms-link").addEventListener("click", () => {
      infoModal(
        "Términos de servicio",
        "Este es un documento de ejemplo para la demostración. Se reemplazará por el documento legal real antes de operar con usuarios reales."
      );
    });

    document.getElementById("login-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const email = document.getElementById("login-email").value.trim();
      const password = document.getElementById("login-password").value;
      const remember = document.getElementById("login-remember").checked;
      const errorEl = document.getElementById("login-error");
      if (!email || !password) {
        errorEl.textContent = "Completa tu email y contraseña para continuar.";
        errorEl.classList.remove("hidden");
        return;
      }
      errorEl.classList.add("hidden");
      LC.auth.login(email, remember);
      toast("success", "Bienvenido de nuevo.");
      LC.router.navigate("/dashboard");
    });

    document.getElementById("signup-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const nombre = document.getElementById("signup-name").value.trim();
      const email = document.getElementById("signup-email").value.trim();
      const password = document.getElementById("signup-password").value;
      const confirm = document.getElementById("signup-password-confirm").value;
      const terms = document.getElementById("signup-terms").checked;
      const errorEl = document.getElementById("signup-error");

      if (!nombre || !email || !password || !confirm) {
        errorEl.textContent = "Completa todos los campos para crear tu cuenta.";
        errorEl.classList.remove("hidden");
        return;
      }
      if (password !== confirm) {
        errorEl.textContent = "Las contraseñas no coinciden.";
        errorEl.classList.remove("hidden");
        return;
      }
      if (!terms) {
        errorEl.textContent = "Debes aceptar los términos de servicio para continuar.";
        errorEl.classList.remove("hidden");
        return;
      }
      errorEl.classList.add("hidden");
      LC.auth.signup(nombre, email);
      toast("success", "Cuenta creada. ¡Bienvenido a Librería Central!");
      LC.router.navigate("/dashboard");
    });
  }

  // ------------------------------------------------------------------
  // Dashboard
  // ------------------------------------------------------------------

  async function renderDashboard(main) {
    const [resumen, estado, resumenML, masVendidos] = await Promise.all([
      LC.dataSource.getDashboardResumen(),
      LC.dataSource.getEstadoSistema(),
      LC.dataSource.getResumenMercadoLibre(),
      LC.dataSource.getProductosMasVendidosMercadoLibre("30d", 5),
    ]);

    const alertas = [...resumen.alertasSinStock, ...resumen.alertasStockBajo].slice(0, 5);

    main.innerHTML = `
      <div class="page-wrap app-fade">
        <div class="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 px-4 py-3 mb-6 text-sm text-amber-800 dark:text-amber-200 flex items-center gap-2">
          <span>🧪</span>
          <span>Estás viendo datos de demostración (catálogo y ventas de Mercado Libre). Cuando conectemos tu WooCommerce y tu Mercado Libre reales, estos números reflejarán tu negocio real.</span>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
          <div class="stat-card">
            <p class="stat-label">Productos totales</p>
            <p class="stat-value">${resumen.total}</p>
            <p class="stat-hint">Una fila por color en productos con variantes</p>
          </div>
          <div class="stat-card">
            <p class="stat-label">Con stock</p>
            <p class="stat-value stat-value--success">${resumen.conStock}</p>
            <p class="stat-hint">Disponibles para vender</p>
          </div>
          <div class="stat-card">
            <p class="stat-label">Sin stock</p>
            <p class="stat-value stat-value--danger">${resumen.sinStock}</p>
            <p class="stat-hint">Agotados</p>
          </div>
          <div class="stat-card">
            <p class="stat-label">Stock bajo</p>
            <p class="stat-value stat-value--warning">${resumen.stockBajo}</p>
            <p class="stat-hint">Umbral configurable en Configuración</p>
          </div>
          <div class="stat-card">
            <p class="stat-label">Última actualización</p>
            <p class="stat-value stat-value--sm">${formatDate(resumen.ultimaActualizacion)}</p>
            <p class="stat-hint">Datos de demostración</p>
          </div>
        </div>

        <div class="panel-card mb-6">
          <div class="flex items-center justify-between gap-3 flex-wrap mb-4">
            <div class="flex items-center gap-2">
              <h3 class="panel-title">Ventas Mercado Libre</h3>
              <span class="demo-pill">🟡 Datos de demostración</span>
            </div>
            <button data-nav="/mercadolibre" class="text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:underline">Ver Mercado Libre →</button>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            <div>
              <p class="stat-label">Ventas del mes</p>
              <p class="stat-value stat-value--sm">${formatCLP(resumenML.ventasMes)}</p>
            </div>
            <div>
              <p class="stat-label">Pedidos</p>
              <p class="stat-value stat-value--sm">${resumenML.pedidosMes}</p>
            </div>
            <div>
              <p class="stat-label">Productos vendidos</p>
              <p class="stat-value stat-value--sm">${resumenML.productosVendidosMes}</p>
            </div>
            <div>
              <p class="stat-label">Ventas de hoy</p>
              <p class="stat-value stat-value--sm">${formatCLP(resumenML.ventasHoy)}</p>
            </div>
            <div>
              <p class="stat-label">Pedidos pendientes</p>
              <p class="stat-value stat-value--sm ${resumenML.pedidosPendientes > 0 ? "stat-value--warning" : ""}">${resumenML.pedidosPendientes}</p>
            </div>
          </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-5">
          <div class="panel-card">
            <h3 class="panel-title">Estado del sistema</h3>
            <p class="panel-subtitle mb-2">Ninguna de estas conexiones está activa todavía.</p>
            <div>
              ${statusRow("WooCommerce", estado.woocommerce)}
              ${statusRow("Mercado Libre", estado.mercadoLibre)}
              ${statusRow("Base de datos", estado.baseDeDatos)}
            </div>
          </div>
          <div class="panel-card">
            <div class="flex items-center justify-between gap-3 mb-1">
              <h3 class="panel-title">Productos más vendidos</h3>
              <span class="text-xs text-slate-400">Últimos 30 días (demo)</span>
            </div>
            ${masVendidos.length ? masVendidos.map((p, i) => rankRow(i + 1, p, masVendidos[0].cantidad)).join("") : `<p class="text-sm text-slate-400 mt-3">Todavía no hay ventas de ejemplo.</p>`}
          </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div class="panel-card">
            <h3 class="panel-title mb-1">Alertas de stock</h3>
            <p class="panel-subtitle mb-2">Productos sin stock o por debajo del umbral configurado.</p>
            ${
              alertas.length
                ? alertas.map((r) => stockAlertRow(r)).join("")
                : `<p class="text-sm text-emerald-600 dark:text-emerald-400 mt-3">🟢 Todo tu stock está en buen estado.</p>`
            }
            ${alertas.length ? `<button data-nav="/productos" class="text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:underline mt-3">Ver todos los productos →</button>` : ""}
          </div>
          <div class="panel-card">
            <h3 class="panel-title">Accesos rápidos</h3>
            <p class="panel-subtitle mb-3">Todo lo de acá usa datos de ejemplo por ahora.</p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              ${quickLink("📦", "Ver productos", "/productos")}
              ${quickLink("🛒", "Mercado Libre", "/mercadolibre")}
              ${quickLink("🔄", "Sincronización", "/sincronizacion")}
              ${quickLink("💳", "Suscripción", "/suscripcion")}
            </div>
          </div>
        </div>
      </div>
    `;

    main.querySelectorAll("[data-nav]").forEach((btn) => {
      btn.addEventListener("click", () => LC.router.navigate(btn.dataset.nav));
    });
  }

  function rankRow(posicion, item, maxCantidad) {
    const pct = maxCantidad > 0 ? Math.max(4, Math.round((item.cantidad / maxCantidad) * 100)) : 0;
    return `
      <div class="rank-row">
        <span class="rank-number">${posicion}</span>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium truncate">${escapeHtml(item.nombre)}</p>
          <div class="rank-bar-track mt-1"><div class="rank-bar-fill" style="width:${pct}%"></div></div>
        </div>
        <span class="text-sm font-semibold text-slate-600 dark:text-slate-300 shrink-0">${item.cantidad} vendidos</span>
      </div>
    `;
  }

  function stockAlertRow(row) {
    const ind = stockIndicator(row);
    return `
      <div class="flex items-center justify-between gap-3 py-2 border-b border-slate-100 dark:border-slate-800 last:border-0">
        <div class="min-w-0">
          <p class="text-sm font-medium truncate">${escapeHtml(row.nombre)}</p>
          <p class="text-xs text-slate-400 font-mono">${escapeHtml(row.sku) || "—"}</p>
        </div>
        <span class="stock-cell text-sm shrink-0">${ind.emoji} ${ind.label}</span>
      </div>
    `;
  }

  function statusRow(label, info) {
    const dotClass = info.estado === "demo" ? "bg-amber-400" : "bg-red-400";
    return `
      <div class="status-row">
        <div class="flex items-center gap-2.5">
          <span class="status-dot ${dotClass}"></span>
          <span class="text-sm font-medium">${escapeHtml(label)}</span>
        </div>
        <span class="text-xs font-medium text-slate-500 dark:text-slate-400">${escapeHtml(info.detalle)}</span>
      </div>
    `;
  }

  function quickLink(icon, label, path) {
    return `
      <button data-nav="${path}" class="flex items-center gap-2.5 px-3.5 py-3 rounded-xl border border-slate-200 dark:border-slate-700 hover:border-indigo-300 dark:hover:border-indigo-600 hover:bg-indigo-50/50 dark:hover:bg-indigo-950/40 transition text-left text-sm font-medium">
        <span class="text-lg">${icon}</span> ${escapeHtml(label)}
      </button>
    `;
  }

  // ------------------------------------------------------------------
  // Productos: lista
  // ------------------------------------------------------------------

  function stockIndicator(row) {
    if (!row.gestionaStock) {
      if (row.estadoStock === "instock") return { emoji: "🟢", label: "En stock" };
      if (row.estadoStock === "outofstock") return { emoji: "🔴", label: "Sin stock" };
      return { emoji: "🟡", label: "Por encargo" };
    }
    const qty = row.stockQuantity;
    if (qty === null || qty === undefined) return { emoji: "⚪", label: "Sin dato" };
    if (qty <= 0) return { emoji: "🔴", label: String(qty) };
    if (qty <= LC.settings.getLowStockThreshold()) return { emoji: "🟡", label: String(qty) };
    return { emoji: "🟢", label: String(qty) };
  }

  function stockBucket(row) {
    const ind = stockIndicator(row);
    if (ind.emoji === "🔴") return "sin-stock";
    if (ind.emoji === "🟡") return "stock-bajo";
    if (ind.emoji === "🟢") return "con-stock";
    return "desconocido";
  }

  function normalizeText(s) {
    return String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }

  function getFilteredSortedRows(rows) {
    let out = rows;
    if (state.search.trim()) {
      const q = normalizeText(state.search);
      out = out.filter((r) => normalizeText(r.nombre).includes(q) || normalizeText(r.sku).includes(q));
    }
    if (state.filterTipo !== "todos") out = out.filter((r) => r.tipo === state.filterTipo);
    if (state.filterStock !== "todos") out = out.filter((r) => stockBucket(r) === state.filterStock);

    const dir = state.sortDir === "asc" ? 1 : -1;
    out = [...out].sort((a, b) => {
      switch (state.sortKey) {
        case "stock":
          return ((a.stockQuantity ?? -1) - (b.stockQuantity ?? -1)) * dir;
        case "precio":
          return ((a.precio || 0) - (b.precio || 0)) * dir;
        case "sku":
        case "tipo":
          return String(a[state.sortKey] || "").localeCompare(String(b[state.sortKey] || "")) * dir;
        default:
          return String(a.nombre || "").localeCompare(String(b.nombre || "")) * dir;
      }
    });
    return out;
  }

  async function renderProductos(main) {
    const rows = await LC.dataSource.getProductos();

    main.innerHTML = `
      <div class="page-wrap app-fade">
        <div class="panel-card">
          <div id="selection-bar-slot"></div>
          <div class="flex flex-col md:flex-row md:items-center gap-3 mb-5">
            <div class="relative flex-1">
              <svg width="16" height="16" class="search-icon-svg absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path stroke-linecap="round" d="m20 20-3-3"/></svg>
              <input id="search-input" type="text" placeholder="Buscar por nombre o SKU…" value="${escapeHtml(state.search)}"
                class="w-full pl-9 pr-3 py-2.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-200 dark:focus:ring-indigo-800 focus:border-indigo-400" />
            </div>
            <select id="filter-tipo" class="text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2.5">
              <option value="todos">Todos los tipos</option>
              <option value="simple">Simple</option>
              <option value="variable">Variable (color)</option>
            </select>
            <select id="filter-stock" class="text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2.5">
              <option value="todos">Todo el stock</option>
              <option value="con-stock">🟢 En stock</option>
              <option value="stock-bajo">🟡 Stock bajo</option>
              <option value="sin-stock">🔴 Sin stock</option>
            </select>
          </div>

          <div class="table-wrap">
            <table class="w-full text-sm" id="products-table">
              <thead>
                <tr class="text-left border-b border-slate-200 dark:border-slate-700">
                  <th class="px-3 py-2 w-8"><input type="checkbox" id="select-all-checkbox" class="form-checkbox" /></th>
                  <th class="sortable-th px-3 py-2 font-medium" data-sort="sku">SKU</th>
                  <th class="sortable-th px-3 py-2 font-medium" data-sort="nombre">Nombre</th>
                  <th class="sortable-th px-3 py-2 font-medium" data-sort="tipo">Tipo</th>
                  <th class="sortable-th px-3 py-2 font-medium" data-sort="stock">Stock</th>
                  <th class="sortable-th px-3 py-2 font-medium text-right" data-sort="precio">Precio</th>
                  <th class="px-3 py-2 w-10"></th>
                </tr>
              </thead>
              <tbody id="products-tbody"></tbody>
            </table>
          </div>
          <div id="products-empty" class="hidden empty-state flex flex-col items-center text-center"></div>

          <div class="flex items-center justify-between mt-4 text-sm text-slate-500 dark:text-slate-400">
            <span id="pagination-summary"></span>
            <div class="flex items-center gap-2">
              <button id="page-prev" class="page-btn">← Anterior</button>
              <span id="pagination-page"></span>
              <button id="page-next" class="page-btn">Siguiente →</button>
            </div>
          </div>
        </div>
      </div>
    `;

    document.getElementById("search-input").value = state.search;
    document.getElementById("filter-tipo").value = state.filterTipo;
    document.getElementById("filter-stock").value = state.filterStock;

    document.getElementById("search-input").addEventListener("input", (e) => {
      state.search = e.target.value;
      state.page = 1;
      renderTableBody(rows);
    });
    document.getElementById("filter-tipo").addEventListener("change", (e) => {
      state.filterTipo = e.target.value;
      state.page = 1;
      renderTableBody(rows);
    });
    document.getElementById("filter-stock").addEventListener("change", (e) => {
      state.filterStock = e.target.value;
      state.page = 1;
      renderTableBody(rows);
    });
    document.querySelectorAll(".sortable-th").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
        else {
          state.sortKey = key;
          state.sortDir = "asc";
        }
        renderTableBody(rows);
      });
    });
    document.getElementById("page-prev").addEventListener("click", () => {
      if (state.page > 1) {
        state.page -= 1;
        renderTableBody(rows);
      }
    });
    document.getElementById("page-next").addEventListener("click", () => {
      state.page += 1;
      renderTableBody(rows);
    });
    document.getElementById("select-all-checkbox").addEventListener("change", (e) => {
      const visible = getFilteredSortedRows(rows).slice((state.page - 1) * state.pageSize, state.page * state.pageSize);
      if (e.target.checked) visible.forEach((r) => state.selected.add(r.id));
      else visible.forEach((r) => state.selected.delete(r.id));
      renderTableBody(rows);
    });

    renderTableBody(rows);
  }

  function renderTableBody(rows) {
    const filtered = getFilteredSortedRows(rows);
    const totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
    if (state.page > totalPages) state.page = totalPages;
    const start = (state.page - 1) * state.pageSize;
    const pageRows = filtered.slice(start, start + state.pageSize);

    const tbody = document.getElementById("products-tbody");
    const emptyEl = document.getElementById("products-empty");

    if (filtered.length === 0) {
      tbody.innerHTML = "";
      emptyEl.classList.remove("hidden");
      emptyEl.innerHTML = `
        <div class="empty-state-icon">🔍</div>
        <p class="empty-state-title">Ningún producto coincide</p>
        <p class="empty-state-desc">Prueba con otro término de búsqueda o quita algún filtro.</p>
      `;
    } else {
      emptyEl.classList.add("hidden");
      tbody.innerHTML = pageRows
        .map((r) => {
          const ind = stockIndicator(r);
          const tipoBadge =
            r.tipo === "variable"
              ? `<span class="badge badge-variable">Variable${r.colorVariante ? " · " + escapeHtml(r.colorVariante) : ""}</span>`
              : `<span class="badge badge-simple">Simple</span>`;
          const checked = state.selected.has(r.id) ? "checked" : "";
          const rowSelectedClass = state.selected.has(r.id) ? "row-selected" : "";
          return `
            <tr class="${rowSelectedClass}" data-row-id="${r.id}">
              <td class="px-3"><input type="checkbox" class="form-checkbox row-checkbox" data-id="${r.id}" ${checked} /></td>
              <td class="font-mono text-xs text-slate-500 dark:text-slate-400 cursor-pointer" data-open="${r.id}">${escapeHtml(r.sku) || "—"}</td>
              <td class="font-medium text-slate-800 dark:text-slate-100 cursor-pointer" data-open="${r.id}">${escapeHtml(r.nombre) || "—"}</td>
              <td>${tipoBadge}</td>
              <td><span class="stock-cell">${ind.emoji} ${ind.label}</span></td>
              <td class="text-right font-medium">${formatCLP(r.precio)}</td>
              <td class="relative">
                <button class="row-menu-btn" data-menu="${r.id}">⋯</button>
              </td>
            </tr>`;
        })
        .join("");
    }

    document.getElementById("pagination-summary").textContent =
      filtered.length === 0 ? "Mostrando 0 productos" : `Mostrando ${start + 1}–${Math.min(start + state.pageSize, filtered.length)} de ${filtered.length}`;
    document.getElementById("pagination-page").textContent = `Página ${state.page} de ${totalPages}`;
    document.getElementById("page-prev").disabled = state.page <= 1;
    document.getElementById("page-next").disabled = state.page >= totalPages;
    document.getElementById("select-all-checkbox").checked = pageRows.length > 0 && pageRows.every((r) => state.selected.has(r.id));

    document.querySelectorAll(".sortable-th .sort-arrow").forEach((a) => a.remove());
    document.querySelectorAll(".sortable-th").forEach((th) => {
      if (th.dataset.sort === state.sortKey) {
        const arrow = document.createElement("span");
        arrow.className = "sort-arrow";
        arrow.textContent = state.sortDir === "asc" ? "▲" : "▼";
        th.appendChild(arrow);
      }
    });

    tbody.querySelectorAll("[data-open]").forEach((cell) => {
      cell.addEventListener("click", () => LC.router.navigate(`/productos/${cell.dataset.open}`));
    });
    tbody.querySelectorAll(".row-checkbox").forEach((cb) => {
      cb.addEventListener("change", (e) => {
        const id = Number(e.target.dataset.id);
        if (e.target.checked) state.selected.add(id);
        else state.selected.delete(id);
        renderSelectionBar(rows);
        tbody.querySelector(`tr[data-row-id="${id}"]`).classList.toggle("row-selected", e.target.checked);
      });
    });
    tbody.querySelectorAll("[data-menu]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        openRowMenu(btn, Number(btn.dataset.menu));
      });
    });

    renderSelectionBar(rows);
  }

  function renderSelectionBar(rows) {
    const slot = document.getElementById("selection-bar-slot");
    if (!slot) return;
    if (state.selected.size === 0) {
      slot.innerHTML = "";
      return;
    }
    slot.innerHTML = `
      <div class="selection-bar">
        <span>${state.selected.size} producto${state.selected.size === 1 ? "" : "s"} seleccionado${state.selected.size === 1 ? "" : "s"}</span>
        <div class="flex items-center gap-2">
          <button id="selection-export-btn" class="btn-secondary !py-1.5 !text-xs">Exportar seleccionados</button>
          <button id="selection-clear-btn" class="btn-secondary !py-1.5 !text-xs">Limpiar selección</button>
        </div>
      </div>
    `;
    document.getElementById("selection-export-btn").addEventListener("click", () => {
      toast("info", "Exportar productos estará disponible próximamente.");
    });
    document.getElementById("selection-clear-btn").addEventListener("click", () => {
      state.selected.clear();
      renderTableBody(rows);
    });
  }

  function openRowMenu(btn, id) {
    document.querySelectorAll(".row-menu").forEach((m) => m.remove());
    const menu = document.createElement("div");
    menu.className = "row-menu";
    menu.innerHTML = `
      <button class="dropdown-item" data-action="ver">Ver producto</button>
      <button class="dropdown-item" data-action="detalles">Ver detalles</button>
      <button class="dropdown-item" data-action="historial">Ver historial</button>
    `;
    btn.parentElement.appendChild(menu);
    menu.addEventListener("click", (e) => {
      const item = e.target.closest("[data-action]");
      if (!item) return;
      if (item.dataset.action === "historial") scrollTarget = "detail-historial";
      LC.router.navigate(`/productos/${id}`);
    });
    const closeOnOutside = (e) => {
      if (!menu.contains(e.target)) {
        menu.remove();
        document.removeEventListener("click", closeOnOutside);
      }
    };
    setTimeout(() => document.addEventListener("click", closeOnOutside), 0);
  }

  // ------------------------------------------------------------------
  // Detalle de producto
  // ------------------------------------------------------------------

  async function renderProductDetail(main, id) {
    const detalle = await LC.dataSource.getProductoDetalle(id);
    if (!detalle) {
      main.innerHTML = `<div class="page-wrap"><div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">🤔</div><p class="empty-state-title">Producto no encontrado</p><button data-back class="btn-secondary mt-4">← Volver a Productos</button></div></div>`;
      main.querySelector("[data-back]").addEventListener("click", () => LC.router.navigate("/productos"));
      return;
    }
    const { row, variantes, historial, creado } = detalle;
    const ind = stockIndicator(row);

    main.innerHTML = `
      <div class="page-wrap app-fade max-w-4xl">
        <button id="back-to-list" class="text-sm text-slate-500 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 mb-4 inline-flex items-center gap-1">← Volver a Productos</button>

        <div class="panel-card mb-5">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div class="flex items-center gap-2 mb-1">
                <h2 class="text-xl font-semibold">${escapeHtml(row.nombre)}</h2>
                ${row.tipo === "variable" ? '<span class="badge badge-variable">Variable</span>' : '<span class="badge badge-simple">Simple</span>'}
              </div>
              <p class="text-sm text-slate-500 dark:text-slate-400 font-mono">${escapeHtml(row.sku) || "Sin SKU"}</p>
            </div>
            <span class="stock-cell text-sm font-medium">${ind.emoji} ${ind.label}</span>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
            <div><p class="stat-label">Precio</p><p class="text-lg font-semibold mt-1">${formatCLP(row.precio)}</p></div>
            <div><p class="stat-label">Stock</p><p class="text-lg font-semibold mt-1">${row.stockQuantity ?? "—"}</p></div>
            <div><p class="stat-label">Categoría</p><p class="text-lg font-semibold mt-1">${escapeHtml(row.categoria || "—")}</p></div>
            <div><p class="stat-label">Creado</p><p class="text-lg font-semibold mt-1">${formatDate(creado)}</p></div>
          </div>
        </div>

        ${variantes && variantes.length ? `
        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Variantes</h3>
          <div class="flex flex-wrap gap-2">
            ${variantes.map((v) => `<span class="badge badge-variable">${escapeHtml(v.color)} · ${v.stockQuantity} un.</span>`).join("")}
          </div>
        </div>` : ""}

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-5">
          <div class="panel-card">
            <h3 class="panel-title mb-2">Información de WooCommerce</h3>
            <div class="text-sm space-y-1.5 mb-3">
              <div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">ID de producto (padre)</span><span class="font-mono">${row.woocommerceParentId ?? "—"}</span></div>
              ${row.woocommerceVariationId ? `<div class="flex justify-between"><span class="text-slate-500 dark:text-slate-400">ID de variación</span><span class="font-mono">${row.woocommerceVariationId}</span></div>` : ""}
            </div>
            <p class="text-xs text-slate-400 dark:text-slate-500">IDs de ejemplo — este producto todavía no está sincronizado con una tienda WooCommerce real.</p>
          </div>
          <div class="panel-card">
            <h3 class="panel-title mb-2">Información de Mercado Libre</h3>
            <p class="text-sm font-medium text-slate-600 dark:text-slate-300 mb-3">No vinculado</p>
            <button id="link-ml-btn" class="btn-secondary">Vincular producto</button>
          </div>
        </div>

        <div id="detail-historial" class="panel-card">
          <h3 class="panel-title mb-3">Historial</h3>
          <div class="space-y-3">
            ${historial
              .map(
                (h) => `
              <div class="flex items-start gap-3 text-sm">
                <span class="text-slate-400 dark:text-slate-500 shrink-0 w-24">${formatDate(h.fecha)}</span>
                <span class="text-slate-600 dark:text-slate-300">${escapeHtml(h.evento)}</span>
              </div>`
              )
              .join("")}
          </div>
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-4 pt-3 border-t border-slate-100 dark:border-slate-800">Historial de ejemplo — se reemplazará por el historial real del producto.</p>
        </div>
      </div>
    `;

    document.getElementById("back-to-list").addEventListener("click", () => LC.router.navigate("/productos"));
    document.getElementById("link-ml-btn").addEventListener("click", () => {
      infoModal("Vincular con Mercado Libre", "La vinculación de productos con Mercado Libre estará disponible cuando conectemos la integración real.");
    });
  }

  // ------------------------------------------------------------------
  // Mercado Libre
  // ------------------------------------------------------------------

  function orderStatusBadge(estado) {
    const labels = { pendiente: "🟡 Pendiente", enviado: "🔵 Enviado", entregado: "🟢 Entregado", cancelado: "🔴 Cancelado" };
    return `<span class="order-status order-status--${estado}">${labels[estado] || estado}</span>`;
  }

  async function renderMercadoLibre(main) {
    const [resumen, productosFiltro] = await Promise.all([
      LC.dataSource.getResumenMercadoLibre(),
      LC.dataSource.getProductosVendidosEnMercadoLibre(),
    ]);
    mlState.page = 1;

    main.innerHTML = `
      <div class="page-wrap app-fade">
        <div class="panel-card mb-6">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex flex-wrap items-center gap-2">
              <span class="demo-pill">🟡 Datos de demostración</span>
              <span class="connection-pill">⚪ Conexión pendiente</span>
            </div>
            <button id="connect-ml-btn" class="btn-primary">Conectar Mercado Libre</button>
          </div>
          <p class="text-sm text-slate-500 dark:text-slate-400 mt-3">
            Todo lo que ves acá (ventas, pedidos, ingresos) es de ejemplo, para poder evaluar la interfaz. Ningún dato es real todavía — cuando conectemos tu cuenta de Mercado Libre, estos números se reemplazarán por tu información real.
          </p>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          <div class="stat-card"><p class="stat-label">Ventas del mes</p><p class="stat-value stat-value--sm">${formatCLP(resumen.ventasMes)}</p></div>
          <div class="stat-card"><p class="stat-label">Pedidos del mes</p><p class="stat-value stat-value--sm">${resumen.pedidosMes}</p></div>
          <div class="stat-card"><p class="stat-label">Productos vendidos</p><p class="stat-value stat-value--sm">${resumen.productosVendidosMes}</p></div>
          <div class="stat-card"><p class="stat-label">Ticket promedio</p><p class="stat-value stat-value--sm">${formatCLP(resumen.ticketPromedioMes)}</p></div>
          <div class="stat-card"><p class="stat-label">Pedidos pendientes</p><p class="stat-value stat-value--sm stat-value--warning">${resumen.pedidosPendientes}</p></div>
          <div class="stat-card"><p class="stat-label">Pedidos enviados</p><p class="stat-value stat-value--sm">${resumen.pedidosEnviados}</p></div>
          <div class="stat-card"><p class="stat-label">Pedidos entregados</p><p class="stat-value stat-value--sm stat-value--success">${resumen.pedidosEntregados}</p></div>
          <div class="stat-card"><p class="stat-label">Pedidos cancelados</p><p class="stat-value stat-value--sm stat-value--danger">${resumen.pedidosCancelados}</p></div>
        </div>

        <div class="panel-card chart-card mb-6">
          <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h3 class="panel-title">Ventas Mercado Libre</h3>
            <div class="flex flex-wrap items-center gap-3">
              <div class="chart-tabs" id="ml-metric-tabs">
                <button data-metric="ingresos" class="chart-tab">Ingresos</button>
                <button data-metric="pedidos" class="chart-tab">Pedidos</button>
              </div>
              <div class="chart-tabs" id="ml-rango-tabs">
                <button data-rango="7d" class="chart-tab">7 días</button>
                <button data-rango="30d" class="chart-tab">30 días</button>
                <button data-rango="mes" class="chart-tab">Este mes</button>
              </div>
            </div>
          </div>
          <canvas id="ml-chart-canvas"></canvas>
          <p id="ml-chart-summary" class="text-sm text-slate-500 dark:text-slate-400 mt-3"></p>
        </div>

        <div class="panel-card mb-6">
          <div class="flex items-center justify-between gap-3 mb-1">
            <h3 class="panel-title">Productos más vendidos</h3>
            <span class="text-xs text-slate-400">Últimos 30 días (demo)</span>
          </div>
          <div id="ml-top-productos" class="mt-2"></div>
        </div>

        <div class="panel-card">
          <div class="flex items-center justify-between gap-3 mb-4">
            <h3 class="panel-title">Últimos pedidos</h3>
          </div>

          <div class="flex flex-col md:flex-row md:items-center gap-3 mb-5">
            <div class="relative flex-1">
              <svg width="16" height="16" class="search-icon-svg absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path stroke-linecap="round" d="m20 20-3-3"/></svg>
              <input id="ml-search-input" type="text" placeholder="Buscar por ID de pedido, SKU o producto…"
                class="w-full pl-9 pr-3 py-2.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-200 dark:focus:ring-indigo-800 focus:border-indigo-400" />
            </div>
            <select id="ml-filter-estado" class="text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2.5">
              <option value="todos">Todos los estados</option>
              <option value="pendiente">🟡 Pendiente</option>
              <option value="enviado">🔵 Enviado</option>
              <option value="entregado">🟢 Entregado</option>
              <option value="cancelado">🔴 Cancelado</option>
            </select>
            <select id="ml-filter-producto" class="text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2.5 max-w-full md:max-w-xs">
              <option value="todos">Todos los productos</option>
              ${productosFiltro.map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("")}
            </select>
          </div>

          <div class="table-wrap">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-left border-b border-slate-200 dark:border-slate-700">
                  <th class="px-3 py-2 font-medium">Pedido</th>
                  <th class="px-3 py-2 font-medium">Producto</th>
                  <th class="px-3 py-2 font-medium text-right">Cantidad</th>
                  <th class="px-3 py-2 font-medium text-right">Total</th>
                  <th class="px-3 py-2 font-medium">Estado</th>
                  <th class="px-3 py-2 font-medium">Fecha</th>
                </tr>
              </thead>
              <tbody id="ml-pedidos-tbody"></tbody>
            </table>
          </div>
          <div id="ml-pedidos-empty" class="hidden empty-state flex flex-col items-center text-center"></div>

          <div class="flex items-center justify-between mt-4 text-sm text-slate-500 dark:text-slate-400">
            <span id="ml-pagination-summary"></span>
            <div class="flex items-center gap-2">
              <button id="ml-page-prev" class="page-btn">← Anterior</button>
              <span id="ml-pagination-page"></span>
              <button id="ml-page-next" class="page-btn">Siguiente →</button>
            </div>
          </div>
        </div>
      </div>
    `;

    document.getElementById("connect-ml-btn").addEventListener("click", () => {
      infoModal("Conectar Mercado Libre", "La conexión con Mercado Libre estará disponible cuando configuremos la integración. Todavía no implementamos el inicio de sesión (OAuth) con Mercado Libre — por eso hoy solo puedes explorar la interfaz con datos de demostración.");
    });

    document.getElementById("ml-search-input").addEventListener("input", (e) => {
      mlState.search = e.target.value;
      mlState.page = 1;
      renderMLPedidos();
    });
    document.getElementById("ml-filter-estado").addEventListener("change", (e) => {
      mlState.filterEstado = e.target.value;
      mlState.page = 1;
      renderMLPedidos();
    });
    document.getElementById("ml-filter-producto").addEventListener("change", (e) => {
      mlState.filterProducto = e.target.value;
      mlState.page = 1;
      renderMLPedidos();
    });
    document.getElementById("ml-page-prev").addEventListener("click", () => {
      if (mlState.page > 1) {
        mlState.page -= 1;
        renderMLPedidos();
      }
    });
    document.getElementById("ml-page-next").addEventListener("click", () => {
      mlState.page += 1;
      renderMLPedidos();
    });
    document.getElementById("ml-metric-tabs").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-metric]");
      if (!btn) return;
      mlState.metric = btn.dataset.metric;
      renderMLChart();
    });
    document.getElementById("ml-rango-tabs").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-rango]");
      if (!btn) return;
      mlState.rango = btn.dataset.rango;
      renderMLChart();
      renderMLTopProductos();
    });

    renderMLChart();
    renderMLTopProductos();
    renderMLPedidos();
  }

  async function renderMLChart() {
    const canvas = document.getElementById("ml-chart-canvas");
    if (!canvas) return; // la sección pudo haberse dejado antes de que termine de cargar

    document.querySelectorAll("#ml-metric-tabs .chart-tab").forEach((b) => b.classList.toggle("chart-tab-active", b.dataset.metric === mlState.metric));
    document.querySelectorAll("#ml-rango-tabs .chart-tab").forEach((b) => b.classList.toggle("chart-tab-active", b.dataset.rango === mlState.rango));

    const puntos = await LC.dataSource.getGraficoVentasMercadoLibre(mlState.rango);
    const esIngresos = mlState.metric === "ingresos";
    const datosChart = puntos.map((p) => ({ fecha: p.fecha, valor: esIngresos ? p.ingresos : p.pedidos }));

    LC.chart.renderBarChart(canvas, datosChart, {
      formatValue: esIngresos ? formatCLP : (v) => String(v),
    });

    const totalIngresos = puntos.reduce((acc, p) => acc + p.ingresos, 0);
    const totalPedidos = puntos.reduce((acc, p) => acc + p.pedidos, 0);
    const summary = document.getElementById("ml-chart-summary");
    if (summary) {
      summary.textContent = `En este período: ${formatCLP(totalIngresos)} en ventas, ${totalPedidos} pedido${totalPedidos === 1 ? "" : "s"} (no incluye pedidos cancelados).`;
    }
  }

  async function renderMLTopProductos() {
    const slot = document.getElementById("ml-top-productos");
    if (!slot) return;
    const top = await LC.dataSource.getProductosMasVendidosMercadoLibre(mlState.rango, 8);
    if (!top.length) {
      slot.innerHTML = `<p class="text-sm text-slate-400 mt-2">Sin ventas de ejemplo en este período.</p>`;
      return;
    }
    const maxCantidad = top[0].cantidad;
    slot.innerHTML = top.map((p, i) => rankRow(i + 1, p, maxCantidad)).join("");
  }

  async function renderMLPedidos() {
    const tbody = document.getElementById("ml-pedidos-tbody");
    if (!tbody) return;

    const { rows, total, page, totalPages } = await LC.dataSource.getPedidosMercadoLibre({
      search: mlState.search,
      estado: mlState.filterEstado,
      producto: mlState.filterProducto,
      page: mlState.page,
      pageSize: mlState.pageSize,
    });
    mlState.page = page;

    const emptyEl = document.getElementById("ml-pedidos-empty");
    if (rows.length === 0) {
      tbody.innerHTML = "";
      emptyEl.classList.remove("hidden");
      emptyEl.innerHTML = `
        <div class="empty-state-icon">🔍</div>
        <p class="empty-state-title">Ningún pedido coincide</p>
        <p class="empty-state-desc">Prueba con otro término de búsqueda o quita algún filtro.</p>
      `;
    } else {
      emptyEl.classList.add("hidden");
      tbody.innerHTML = rows
        .map(
          (p) => `
        <tr class="border-b border-slate-100 dark:border-slate-800">
          <td class="px-3 py-2.5 font-mono text-xs text-slate-500 dark:text-slate-400">${escapeHtml(p.externalId)}</td>
          <td class="px-3 py-2.5">
            <p class="font-medium text-slate-800 dark:text-slate-100">${escapeHtml(p.productoNombre)}</p>
            <p class="text-xs text-slate-400 font-mono">${escapeHtml(p.sku)}</p>
          </td>
          <td class="px-3 py-2.5 text-right">${p.cantidad}</td>
          <td class="px-3 py-2.5 text-right font-medium">${formatCLP(p.total)}</td>
          <td class="px-3 py-2.5">${orderStatusBadge(p.estado)}</td>
          <td class="px-3 py-2.5 text-slate-500 dark:text-slate-400">${formatDate(p.fecha)}</td>
        </tr>`
        )
        .join("");
    }

    document.getElementById("ml-pagination-summary").textContent =
      total === 0 ? "Mostrando 0 pedidos" : `Mostrando ${(page - 1) * mlState.pageSize + 1}–${Math.min(page * mlState.pageSize, total)} de ${total}`;
    document.getElementById("ml-pagination-page").textContent = `Página ${page} de ${totalPages}`;
    document.getElementById("ml-page-prev").disabled = page <= 1;
    document.getElementById("ml-page-next").disabled = page >= totalPages;
  }

  // ------------------------------------------------------------------
  // Sincronización
  // ------------------------------------------------------------------

  async function renderSincronizacion(main) {
    const sync = await LC.dataSource.getSincronizacion();
    main.innerHTML = `
      <div class="page-wrap app-fade">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <div class="stat-card"><p class="stat-label">Estado</p><p class="stat-value stat-value--sm">No conectado</p></div>
          <div class="stat-card"><p class="stat-label">Última sincronización</p><p class="stat-value stat-value--sm">${sync.ultimaSincronizacion ? formatDate(sync.ultimaSincronizacion) : "—"}</p></div>
          <div class="stat-card"><p class="stat-label">Productos sincronizados</p><p class="stat-value stat-value--sm">—</p></div>
          <div class="stat-card"><p class="stat-label">Pendientes / Errores</p><p class="stat-value stat-value--sm">—</p></div>
        </div>

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-4">Flujo de sincronización</h3>
          <div class="sync-flow">
            <div class="sync-node">🏬 WooCommerce</div>
            <span class="sync-arrow">→</span>
            <div class="sync-node">🛒 Mercado Libre</div>
            <span class="badge badge-simple ml-2">No configurado</span>
          </div>
          <p class="text-sm text-slate-500 dark:text-slate-400 mt-4">Última ejecución: —</p>
        </div>

        <div class="panel-card max-w-2xl">
          <div class="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <h3 class="panel-title mb-1">Sincronizar ahora</h3>
              <p class="text-sm text-slate-500 dark:text-slate-400">Trae y actualiza publicaciones de Mercado Libre a partir de tu catálogo.</p>
            </div>
            <button id="sync-now-btn" class="btn-primary shrink-0">Sincronizar ahora</button>
          </div>
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-4 pt-3 border-t border-slate-100 dark:border-slate-800">
            Este panel no simula sincronizaciones que no ocurrieron: los valores de arriba solo cambiarán cuando la sincronización real exista.
          </p>
        </div>
      </div>
    `;
    document.getElementById("sync-now-btn").addEventListener("click", () => {
      infoModal("Sincronización no disponible", "La sincronización todavía no está disponible porque Mercado Libre no está conectado.", {
        secondaryLabel: "Conectar Mercado Libre",
        onSecondary: () => LC.router.navigate("/mercadolibre"),
      });
    });
  }

  // ------------------------------------------------------------------
  // Suscripción
  // ------------------------------------------------------------------

  async function renderSuscripcion(main) {
    const sus = await LC.dataSource.getSuscripcion();
    const pct = sus.plan.limite ? Math.min(100, Math.round((sus.productosUtilizados / sus.plan.limite) * 100)) : 0;
    const barClass = pct >= 90 ? "progress-danger" : pct >= 70 ? "progress-warn" : "";

    main.innerHTML = `
      <div class="page-wrap app-fade">
        <div class="panel-card mb-6">
          <div class="flex flex-wrap items-start justify-between gap-4 mb-5">
            <div>
              <p class="stat-label">Plan actual</p>
              <p class="text-2xl font-bold mt-1">${escapeHtml(sus.plan.nombre)} <span class="text-sm font-normal text-slate-400">(precio demo)</span></p>
              <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">${escapeHtml(sus.plan.precio)} / mes · Próxima renovación: ${formatDate(sus.fechaRenovacion)}</p>
            </div>
            <button id="manage-sub-btn" class="btn-secondary">Administrar suscripción</button>
          </div>

          <div>
            <div class="flex items-center justify-between text-sm mb-1.5">
              <span class="text-slate-500 dark:text-slate-400">Productos utilizados</span>
              <span class="font-medium">${sus.productosUtilizados} / ${sus.plan.limite ?? "∞"} <span class="text-slate-400">(${pct}%)</span></span>
            </div>
            <div class="progress-track"><div class="progress-fill ${barClass}" style="width:${pct}%"></div></div>
          </div>
        </div>

        <h3 class="panel-title mb-3">Planes disponibles</h3>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          ${sus.planes
            .map((p) => {
              const isCurrent = p.id === sus.plan.id;
              return `
              <div class="plan-card ${isCurrent ? "plan-current" : ""}">
                <div>
                  <div class="flex items-center justify-between">
                    <h4 class="text-base font-semibold">${escapeHtml(p.nombre)}</h4>
                    ${isCurrent ? '<span class="badge badge-variable">Plan actual</span>' : ""}
                  </div>
                  <p class="text-xs text-slate-400 mt-0.5">${p.limite ? `Hasta ${p.limite.toLocaleString("es-CL")} productos` : "Sin límite fijo"}</p>
                </div>
                <p class="text-2xl font-bold">${escapeHtml(p.precio)}<span class="text-sm font-normal text-slate-400"> ${p.id === "enterprise" ? "" : "/ mes"}</span></p>
                <p class="text-xs text-slate-400">${p.id === "enterprise" ? "Precio a coordinar" : "Precio demo"}</p>
                <ul class="text-sm text-slate-600 dark:text-slate-300 space-y-1.5 flex-1">
                  ${p.features.map((f) => `<li class="flex items-start gap-1.5"><span class="text-emerald-500">✓</span>${escapeHtml(f)}</li>`).join("")}
                </ul>
                ${isCurrent ? '<span class="btn-disabled justify-center">Plan actual</span>' : `<button data-plan="${p.id}" class="btn-primary justify-center choose-plan-btn">Elegir plan</button>`}
              </div>
            `;
            })
            .join("")}
        </div>
        <p class="text-xs text-slate-400 dark:text-slate-500 mt-4">Los precios mostrados son de ejemplo, solo para esta demostración — se definirán antes de operar con clientes reales.</p>
      </div>
    `;

    document.getElementById("manage-sub-btn").addEventListener("click", () => {
      infoModal("Administrar suscripción", "La gestión de suscripciones y pagos estará disponible cuando conectemos Stripe u otro proveedor de pagos.");
    });

    main.querySelectorAll(".choose-plan-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const planId = btn.dataset.plan;
        const plan = LC.demoData.plans.find((p) => p.id === planId);
        openModal({
          title: "Cambiar de plan",
          body: `<p>¿Quieres cambiar tu plan de demostración a <strong>${escapeHtml(plan.nombre)}</strong>? Esto es parte de la demo — el cambio real de plan y el cobro se harán cuando conectemos el sistema de pagos.</p>`,
          primaryLabel: "Cambiar plan (demo)",
          secondaryLabel: "Cancelar",
          onPrimary: () => {
            LC.settings.setCurrentPlanId(planId);
            toast("success", `Plan actualizado a ${plan.nombre} (demo).`);
            renderSuscripcion(main);
          },
        });
      });
    });
  }

  // ------------------------------------------------------------------
  // Configuración
  // ------------------------------------------------------------------

  async function renderConfiguracion(main) {
    const settings = LC.settings.getAll();
    const session = LC.auth.getSession() || LC.demoData.account;
    const themePref = LC.theme.get();

    main.innerHTML = `
      <div class="page-wrap app-fade max-w-3xl space-y-5">

        <div class="panel-card">
          <h3 class="panel-title mb-1">General</h3>
          <p class="panel-subtitle mb-4">Información básica de tu negocio.</p>
          <div class="space-y-3">
            <div>
              <label class="form-label">Nombre de la empresa</label>
              <input id="cfg-company" type="text" value="${escapeHtml(settings.companyName)}" class="form-input" />
            </div>
            <div>
              <label class="form-label">Nombre de la tienda</label>
              <input id="cfg-store" type="text" value="${escapeHtml(settings.storeName)}" class="form-input" />
            </div>
            <div>
              <label class="form-label">Email</label>
              <input id="cfg-email" type="email" value="${escapeHtml(session.email)}" class="form-input" />
            </div>
          </div>
          <button id="cfg-general-save" class="btn-primary mt-4">Guardar cambios</button>
        </div>

        <div class="panel-card">
          <h3 class="panel-title mb-1">Apariencia</h3>
          <p class="panel-subtitle mb-4">Elige cómo se ve la interfaz.</p>
          <div class="flex flex-wrap gap-2">
            ${["light", "dark", "auto"]
              .map(
                (t) => `
              <button data-theme-opt="${t}" class="theme-opt-btn px-4 py-2 text-sm font-medium rounded-lg border ${themePref === t ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300" : "border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300"}">
                ${t === "light" ? "☀️ Claro" : t === "dark" ? "🌙 Oscuro" : "🖥️ Automático"}
              </button>`
              )
              .join("")}
          </div>
        </div>

        <div class="panel-card">
          <h3 class="panel-title mb-1">Notificaciones</h3>
          <p class="panel-subtitle mb-4">Estas notificaciones son solo de demostración por ahora — no se envía nada realmente.</p>
          <div class="space-y-3">
            ${toggleRow("cfg-notif-stock", "Alertas de stock bajo", settings.notifStock)}
            ${toggleRow("cfg-notif-sync", "Errores de sincronización", settings.notifSync)}
            ${toggleRow("cfg-notif-important", "Cambios importantes", settings.notifImportant)}
          </div>
        </div>

        <div class="panel-card">
          <h3 class="panel-title mb-1">Umbral de stock bajo</h3>
          <p class="panel-subtitle mb-3">Un producto se marca 🟡 cuando su stock es mayor que cero y menor o igual a este número.</p>
          <div class="flex items-center gap-3">
            <input id="cfg-low-stock" type="number" min="0" step="1" value="${LC.settings.getLowStockThreshold()}" class="form-input w-24" />
            <span class="text-sm text-slate-500 dark:text-slate-400">unidades</span>
          </div>
        </div>

        <div class="panel-card">
          <h3 class="panel-title mb-1">Integraciones</h3>
          <p class="panel-subtitle mb-4">Ninguna está conectada todavía.</p>
          <div class="space-y-3">
            ${integrationRow("🏬", "WooCommerce", "No conectado")}
            ${integrationRow("🛒", "Mercado Libre", "No conectado")}
          </div>
        </div>

        <div id="config-cuenta" class="panel-card">
          <h3 class="panel-title mb-1">Cuenta</h3>
          <p class="panel-subtitle mb-4">${escapeHtml(session.email)}</p>
          <div class="flex flex-wrap gap-3">
            <button id="cfg-change-password" class="btn-secondary">Cambiar contraseña</button>
            <button id="cfg-logout" class="btn-secondary btn-secondary--danger">Cerrar sesión</button>
          </div>
        </div>
      </div>
    `;

    document.getElementById("cfg-general-save").addEventListener("click", () => {
      LC.settings.update({
        companyName: document.getElementById("cfg-company").value.trim() || settings.companyName,
        storeName: document.getElementById("cfg-store").value.trim() || settings.storeName,
      });
      toast("success", "Configuración guardada correctamente.");
    });

    main.querySelectorAll(".theme-opt-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        LC.theme.set(btn.dataset.themeOpt);
        renderConfiguracion(main);
      });
    });

    ["cfg-notif-stock", "cfg-notif-sync", "cfg-notif-important"].forEach((id, i) => {
      const keys = ["notifStock", "notifSync", "notifImportant"];
      document.getElementById(id).addEventListener("change", (e) => {
        LC.settings.update({ [keys[i]]: e.target.checked });
        toast("success", "Preferencia guardada.");
      });
    });

    document.getElementById("cfg-low-stock").addEventListener("change", (e) => {
      const value = parseInt(e.target.value, 10);
      LC.settings.setLowStockThreshold(Number.isFinite(value) && value >= 0 ? value : 5);
      toast("success", "Umbral de stock bajo actualizado.");
    });

    main.querySelectorAll("[data-integration-configure]").forEach((btn) => {
      btn.addEventListener("click", () => {
        infoModal(
          `Conectar ${btn.dataset.integrationConfigure}`,
          `La integración con ${btn.dataset.integrationConfigure} estará disponible en una fase posterior del proyecto. Por ahora estás viendo la interfaz en modo demostración.`
        );
      });
    });

    document.getElementById("cfg-change-password").addEventListener("click", () => {
      infoModal("Cambiar contraseña", "Esta función estará disponible cuando implementemos el sistema de autenticación real.");
    });
    document.getElementById("cfg-logout").addEventListener("click", () => {
      LC.auth.logout();
      toast("info", "Sesión cerrada.");
      LC.router.navigate("/login");
    });
  }

  function toggleRow(id, label, checked) {
    return `
      <label class="flex items-center justify-between gap-4 cursor-pointer select-none py-1">
        <span class="text-sm text-slate-600 dark:text-slate-300">${escapeHtml(label)}</span>
        <input type="checkbox" id="${id}" class="form-checkbox" ${checked ? "checked" : ""} />
      </label>
    `;
  }

  function integrationRow(icon, label, status) {
    return `
      <div class="flex items-center justify-between gap-4 py-1">
        <div class="flex items-center gap-2.5">
          <span class="text-lg">${icon}</span>
          <div>
            <p class="text-sm font-medium">${escapeHtml(label)}</p>
            <p class="text-xs text-slate-400">${escapeHtml(status)}</p>
          </div>
        </div>
        <button data-integration-configure="${escapeHtml(label)}" class="btn-secondary !py-1.5 !text-xs">Configurar</button>
      </div>
    `;
  }

  LC.app = { render };
})();
