"use strict";

/**
 * Nexo — orquestador de pantallas.
 *
 * Todo lo que se ve viene de LC.dataSource (Demo Mode hoy). Este archivo no
 * sabe de dónde vienen los datos, solo cómo pintarlos — cuando dataSource
 * empiece a hablar con el backend real, esto no debería necesitar cambios.
 */

window.LC = window.LC || {};

(function () {
  const { escapeHtml, formatCLP, formatDate, initials, toast, infoModal, openModal, icon } = LC.ui;

  const SECTION_TITLES = {
    admin: "Panel Nexo",
    dashboard: "Dashboard",
    productos: "Productos",
    publicaciones: "Publicar en Mercado Libre",
    oportunidades: "Oportunidades",
    importar: "Importar catálogo",
    integraciones: "Integraciones",
    mercadolibre: "Mercado Libre",
    automatizaciones: "Automatizaciones",
    sincronizacion: "Automatizaciones",
    suscripcion: "Suscripción",
    configuracion: "Configuración",
  };

  // ------------------------------------------------------------------
  // ⚠️ CONTENIDO LEGAL INTERINO — NO es un documento legal real, y quien
  // lo escribió (Claude, 30 de agosto de 2026) no es abogado. Es un texto
  // informativo mínimo y honesto para el piloto, mientras el dueño de
  // Nexo no tenga términos de servicio y política de privacidad reales
  // redactados. REEMPLAZAR este string entero antes de un lanzamiento
  // público — es el único lugar de todo el frontend que hay que tocar
  // para eso.
  // ------------------------------------------------------------------
  const TEXTO_TERMINOS_INTERINO =
    "Nexo está en etapa piloto. Guardamos los datos que cargás para operar la plataforma (tu catálogo, costos, configuración de márgenes, y — si conectás Mercado Libre — los datos de tu cuenta vendedora, cifrados). No compartimos tus datos con terceros salvo lo estrictamente necesario para conectar los servicios que vos mismo autorices. Este texto es informativo, no un documento legal — antes de un lanzamiento público vamos a publicar términos de servicio y política de privacidad formales. Cualquier duda, escribinos directamente.";

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
    document.getElementById("page-title").textContent = SECTION_TITLES[routeName] || "Nexo";
    updateUserHeader();

    const main = document.getElementById("main-content");
    main.innerHTML = skeletonPage();

    try {
      switch (routeName) {
        case "admin":
          await LC.adminPanel.render(main, param);
          break;
        case "dashboard":
          await renderDashboard(main);
          break;
        case "productos":
          if (param) await renderProductDetail(main, param);
          else await renderProductos(main);
          break;
        case "oportunidades":
          await renderOportunidades(main);
          break;
        case "publicaciones":
          await LC.mlPublicar.render(main, param);
          break;
        case "importar":
          await LC.importFlow.render(main);
          break;
        case "integraciones":
          await renderIntegraciones(main);
          break;
        case "mercadolibre":
          await renderMercadoLibre(main);
          break;
        case "automatizaciones":
        case "sincronizacion": // ruta anterior — misma pantalla, concepto ampliado
          await renderAutomatizaciones(main);
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
      // El mensaje técnico (err.message) queda plegado en "Ver detalles" —
      // quien ve esta pantalla es el dueño del negocio, no alguien que
      // necesite leer un stack trace para saber que algo salió mal.
      main.innerHTML = `<div class="page-wrap"><div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("alert")}</div><p class="empty-state-title">Algo no funcionó como esperábamos</p><p class="empty-state-desc">Intenta recargar la página. Si el problema sigue, avísanos.</p><details class="mt-4 text-xs text-slate-400"><summary class="cursor-pointer">Ver detalles técnicos</summary><p class="mt-1 font-mono">${escapeHtml(String(err && err.message ? err.message : err))}</p></details></div></div>`;
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

  // "Empresa activa" — SIEMPRE el nombre real que devolvió el backend
  // (GET /api/auth/me -> empresa.nombre), nunca un valor local editable
  // (LC.settings ya no tiene un "companyName" propio, a propósito: una
  // sola fuente de verdad). En Demo Mode, `session.empresa` es un string
  // simple (ver demoData.js) en vez de {id, nombre} — se soportan los dos.
  function nombreEmpresaActiva(session) {
    if (!session || !session.empresa) return "";
    return typeof session.empresa === "string" ? session.empresa : session.empresa.nombre;
  }

  function updateUserHeader() {
    const session = LC.auth.getSession() || LC.demoData.account;
    document.getElementById("user-name-label").textContent = session.nombre;
    document.getElementById("user-avatar").textContent = initials(session.nombre);
    document.getElementById("theme-toggle-icon").innerHTML = icon(LC.theme.isDark() ? "sun" : "moon");
    document.getElementById("sidebar-empresa-activa").textContent = session.esNexoAdmin ? "Panel Nexo" : nombreEmpresaActiva(session);
    document.getElementById("nav-link-admin").classList.toggle("hidden", !session.esNexoAdmin);
    // Un admin de Nexo no tiene tienda propia — las pantallas de cliente
    // ni siquiera cargarían (get_current_store le daría error), así que
    // esos links ni se muestran (además del guard de router.js que ya
    // redirige si igual se navega ahí a mano).
    ["dashboard", "productos", "oportunidades", "importar", "integraciones", "automatizaciones", "suscripcion", "configuracion"].forEach((r) => {
      const link = document.querySelector(`.nav-link[data-route="${r}"]`);
      if (link) link.classList.toggle("hidden", !!session.esNexoAdmin);
    });
    actualizarPillModoDemo();
  }

  // 30 de agosto de 2026 — hallazgo de frontend-ux-engineer: este pill
  // quedaba SIEMPRE visible en el header, aunque el catálogo ya fuera
  // real (contradecía el resto de la interfaz, que sí distingue bien
  // real/demo panel por panel). display inline (no la clase "hidden") a
  // propósito: "hidden"/"sm:inline-flex" ya gobiernan la visibilidad
  // responsive (oculto en mobile, visible en desktop) — un estilo inline
  // es la única forma de forzar "oculto" en cualquier tamaño sin pisar esa
  // regla.
  async function actualizarPillModoDemo() {
    const pill = document.getElementById("header-demo-pill");
    if (!pill) return;
    const modo = await LC.dataSource.getModo();
    pill.style.display = modo === "demo" ? "" : "none";
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
      document.getElementById("theme-toggle-icon").innerHTML = icon(LC.theme.isDark() ? "sun" : "moon");
    });

    const userMenuBtn = document.getElementById("user-menu-btn");
    const userMenuDropdown = document.getElementById("user-menu-dropdown");
    userMenuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      userMenuDropdown.classList.toggle("hidden");
    });
    document.addEventListener("click", () => userMenuDropdown.classList.add("hidden"));

    userMenuDropdown.addEventListener("click", async (e) => {
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
        await LC.auth.logout();
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
      btn.innerHTML = icon(show ? "eyeOff" : "eye");
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
        "Todavía no está disponible recuperar la contraseña desde acá — escribinos si necesitás ayuda para entrar a tu cuenta."
      );
    });

    document.getElementById("signup-terms-link").addEventListener("click", () => {
      infoModal("Términos de servicio", TEXTO_TERMINOS_INTERINO);
    });

    document.getElementById("login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = document.getElementById("login-email").value.trim();
      const password = document.getElementById("login-password").value;
      const remember = document.getElementById("login-remember").checked;
      const errorEl = document.getElementById("login-error");
      const submitBtn = document.getElementById("login-submit");
      if (!email || !password) {
        errorEl.textContent = "Completa tu email y contraseña para continuar.";
        errorEl.classList.remove("hidden");
        return;
      }
      errorEl.classList.add("hidden");
      submitBtn.disabled = true;
      submitBtn.textContent = "Ingresando…";
      const res = await LC.auth.login(email, password, remember);
      submitBtn.disabled = false;
      submitBtn.textContent = "Iniciar sesión";
      if (!res.ok) {
        errorEl.textContent = res.mensaje;
        errorEl.classList.remove("hidden");
        return;
      }
      toast("success", "Bienvenido de nuevo.");
      LC.router.navigate("/dashboard");
    });

    document.getElementById("signup-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const nombre = document.getElementById("signup-name").value.trim();
      const empresa = document.getElementById("signup-company").value.trim();
      const email = document.getElementById("signup-email").value.trim();
      const password = document.getElementById("signup-password").value;
      const confirm = document.getElementById("signup-password-confirm").value;
      const terms = document.getElementById("signup-terms").checked;
      const errorEl = document.getElementById("signup-error");
      const submitBtn = document.getElementById("signup-submit");

      if (!nombre || !empresa || !email || !password || !confirm) {
        errorEl.textContent = "Completa todos los campos para crear tu cuenta.";
        errorEl.classList.remove("hidden");
        return;
      }
      if (password.length < 8) {
        errorEl.textContent = "La contraseña tiene que tener al menos 8 caracteres.";
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
      submitBtn.disabled = true;
      submitBtn.textContent = "Creando cuenta…";
      const res = await LC.auth.signup(nombre, email, password, empresa, true);
      submitBtn.disabled = false;
      submitBtn.textContent = "Crear cuenta";
      if (!res.ok) {
        errorEl.textContent = res.mensaje;
        errorEl.classList.remove("hidden");
        return;
      }
      toast("success", "Cuenta creada. ¡Bienvenido a Nexo!");
      LC.router.navigate("/dashboard");
    });
  }

  // ------------------------------------------------------------------
  // Dashboard
  // ------------------------------------------------------------------

  async function renderDashboard(main) {
    const [modo, resumen, estado, resumenML, masVendidos] = await Promise.all([
      LC.dataSource.getModo(),
      LC.dataSource.getDashboardResumen(),
      LC.dataSource.getEstadoSistema(),
      LC.dataSource.getResumenMercadoLibre(),
      LC.dataSource.getProductosMasVendidosMercadoLibre("30d", 5),
    ]);
    const esReal = modo === "real";

    // Margen/comisión de Mercado Libre — solo para el paso de onboarding
    // "Configura costos y margen" (30 de agosto de 2026); no bloquea el
    // resto del dashboard si falla.
    let canalMl = null;
    if (esReal) {
      const cfgRes = await LC.backendApi.obtenerConfiguracionCanales();
      if (cfgRes.ok) canalMl = cfgRes.data.find((c) => c.channel === "mercadolibre") || null;
    }

    const alertas = [...resumen.alertasSinStock, ...resumen.alertasStockBajo].slice(0, 5);

    main.innerHTML = `
      <div class="page-wrap app-fade">
        <div class="rounded-xl border ${esReal ? "border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-200" : "border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 text-amber-800 dark:text-amber-200"} px-4 py-3 mb-6 text-sm flex items-center gap-2">
          <span>${
            esReal
              ? "Catálogo real conectado al backend — el bloque de Mercado Libre y \"productos más vendidos\" abajo sigue siendo de ejemplo hasta conectar la sincronización."
              : "Estás viendo datos de demostración (catálogo y ventas de Mercado Libre). Cuando conectemos tu WooCommerce y tu Mercado Libre reales, estos números reflejarán tu negocio real."
          }</span>
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
            <p class="stat-hint">${esReal ? "Catálogo real" : "Datos de demostración"}</p>
          </div>
        </div>

        ${esReal ? renderOnboarding(resumen, canalMl) : ""}
        ${esReal ? renderQueHacerAhora(resumen) : ""}
        ${esReal ? renderRentabilidadVentasPanel(resumen) : ""}

        <div class="panel-card mb-6">
          <div class="flex items-center justify-between gap-3 flex-wrap mb-4">
            <div class="flex items-center gap-2">
              <h3 class="panel-title">Ventas Mercado Libre</h3>
              <span class="demo-pill">Datos de demostración</span>
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
            <p class="panel-subtitle mb-2">${esReal ? "Base de datos real conectada — WooCommerce y Mercado Libre según su estado real." : "Ninguna de estas conexiones está activa todavía."}</p>
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
                : `<p class="text-sm text-emerald-600 dark:text-emerald-400 mt-3">Todo tu stock está en buen estado.</p>`
            }
            ${alertas.length ? `<button data-nav="/productos" class="text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:underline mt-3">Ver todos los productos →</button>` : ""}
          </div>
          <div class="panel-card">
            <h3 class="panel-title">Accesos rápidos</h3>
            <p class="panel-subtitle mb-3">${esReal ? "El catálogo es real; las ventas de Mercado Libre de abajo siguen siendo de ejemplo." : "Todo lo de acá usa datos de ejemplo por ahora."}</p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              ${quickLink("box", "Ver productos", "/productos")}
              ${quickLink("bulb", "Oportunidades", "/oportunidades")}
              ${quickLink("upload", "Importar catálogo", "/importar")}
              ${quickLink("link", "Integraciones", "/integraciones")}
            </div>
          </div>
        </div>
      </div>
    `;

    main.querySelectorAll("[data-nav]").forEach((btn) => {
      btn.addEventListener("click", () => LC.router.navigate(btn.dataset.nav));
    });
  }

  // Onboarding — 30 de agosto de 2026, reordenado según hallazgo de
  // frontend-ux-engineer: el orden real en que un dueño nuevo usa Nexo es
  // importar su catálogo PRIMERO, después configurar costos/margen, recién
  // ahí conectar Mercado Libre (opcional en este punto) y ver oportunidades
  // — antes el paso de "conectar fuentes" aparecía segundo, aunque nadie lo
  // hace antes de tener productos cargados. "Configura costos y margen" es
  // un paso propio ahora (antes estaba escondido dentro del criterio de
  // "Revisa tus oportunidades", sin ningún ítem que lo señalara). Cada paso
  // trae su `ruta` para ser clickeable — "Activa tus automatizaciones"
  // quedó aparte (ver pasosPendientesAutomatizacion): nunca se completa
  // hoy (no hay motor real), mezclarla en la misma barra de progreso hacía
  // que nunca llegara a 100%.
  function buildPasosOnboarding(resumen, canalMl) {
    return [
      { titulo: "Configura tu empresa", hecho: true, ruta: null },
      { titulo: "Importa tus productos", hecho: resumen.total > 0, ruta: "/importar" },
      { titulo: "Configura costos y margen de Mercado Libre", hecho: !!(canalMl && canalMl.targetMarginPct != null), ruta: "/configuracion" },
      { titulo: "Conecta Mercado Libre", hecho: !!(resumen.mercadoLibre && resumen.mercadoLibre.conectado), ruta: "/integraciones" },
      { titulo: "Revisa tus oportunidades", hecho: !!(resumen.rentabilidad && resumen.rentabilidad.productosConCosto > 0), ruta: "/oportunidades" },
    ];
  }

  function renderOnboarding(resumen, canalMl) {
    const pasos = buildPasosOnboarding(resumen, canalMl);
    const completados = pasos.filter((p) => p.hecho).length;
    if (completados === pasos.length) return "";
    return `
      <div class="panel-card mb-6">
        <div class="flex items-center justify-between gap-3 mb-1 flex-wrap">
          <h3 class="panel-title">Primeros pasos en Nexo</h3>
          <span class="text-sm text-slate-400">${completados} de ${pasos.length} pasos completados</span>
        </div>
        <div class="progress-track my-3"><div class="progress-fill" style="width:${Math.round((completados / pasos.length) * 100)}%"></div></div>
        <div class="space-y-2 mt-3">
          ${pasos
            .map(
              (p) => `
            <div class="flex items-center gap-2.5 text-sm ${!p.hecho && p.ruta ? "onboarding-paso-pendiente cursor-pointer" : ""}" ${!p.hecho && p.ruta ? `data-nav="${p.ruta}"` : ""}>
              <span class="dot ${p.hecho ? "dot--green" : "dot--gray"}"></span>
              <span class="${p.hecho ? "text-slate-400 dark:text-slate-500" : "text-slate-700 dark:text-slate-200"} ${!p.hecho && p.ruta ? "hover:underline" : ""}">${escapeHtml(p.titulo)}</span>
            </div>`
            )
            .join("")}
        </div>
      </div>
    `;
  }

  // "Qué hacer ahora" — el corazón de la sección Oportunidades del
  // Dashboard: sintetiza en 1-3 frases accionables lo que ya devolvió
  // /api/dashboard/resumen, sin pedir ningún dato nuevo al backend ni
  // inventar ninguna métrica que no venga de ahí.
  function buildAccionesRecomendadas(resumen) {
    const acciones = [];
    const rent = resumen.rentabilidad;
    const ml = resumen.mercadoLibre;

    if (rent && rent.totalProductos > 0 && rent.productosConCosto < rent.totalProductos) {
      const faltan = rent.totalProductos - rent.productosConCosto;
      acciones.push({
        tono: "warning",
        texto: `${faltan} producto${faltan === 1 ? "" : "s"} sin costo registrado`,
        detalle: "Sin costo no podemos calcular si conviene venderlos.",
        cta: "Revisar productos",
        ruta: "/oportunidades",
      });
    }
    if (rent && rent.productosRentables > 0) {
      acciones.push({
        tono: "success",
        texto: `${rent.productosRentables} producto${rent.productosRentables === 1 ? "" : "s"} con buena oportunidad de venta`,
        detalle: "Ya tienen costo y precio cargados, y dejan margen positivo.",
        cta: "Ver oportunidades",
        ruta: "/oportunidades",
      });
    }
    if (resumen.stockBajo > 0) {
      acciones.push({
        tono: "warning",
        texto: `${resumen.stockBajo} producto${resumen.stockBajo === 1 ? "" : "s"} con stock bajo`,
        detalle: "Podrían agotarse pronto.",
        cta: "Ver productos",
        ruta: "/productos",
      });
    }
    if (ml) {
      acciones.push(
        ml.conectado
          ? { tono: "success", texto: "Mercado Libre está conectado correctamente", detalle: "", cta: "Ver integración", ruta: "/integraciones" }
          : {
              tono: "neutral",
              texto: "Mercado Libre todavía no está conectado",
              detalle: ml.credencialesConfiguradas ? "Las credenciales ya están listas — falta autorizar la cuenta." : "Conéctalo para vender por ese canal.",
              cta: "Conectar",
              ruta: "/integraciones",
            }
      );
    }
    return acciones;
  }

  function renderQueHacerAhora(resumen) {
    const acciones = buildAccionesRecomendadas(resumen);
    const dotClass = { success: "dot--green", warning: "dot--amber", neutral: "dot--gray" };
    return `
      <div class="panel-card mb-6">
        <h3 class="panel-title mb-1">Qué hacer ahora</h3>
        <p class="panel-subtitle mb-4">Lo más importante para revisar hoy en tu empresa.</p>
        ${
          acciones.length
            ? acciones
                .map(
                  (a) => `
          <div class="flex items-center justify-between gap-4 py-2.5 border-b border-slate-100 dark:border-slate-800 last:border-0">
            <div class="flex items-start gap-3 min-w-0">
              <span class="dot ${dotClass[a.tono]} mt-2"></span>
              <div class="min-w-0">
                <p class="text-sm font-medium">${escapeHtml(a.texto)}</p>
                ${a.detalle ? `<p class="text-xs text-slate-400 mt-0.5">${escapeHtml(a.detalle)}</p>` : ""}
              </div>
            </div>
            <button data-nav="${a.ruta}" class="btn-secondary !py-1.5 !text-xs shrink-0">${escapeHtml(a.cta)}</button>
          </div>`
                )
                .join("")
            : `<p class="text-sm text-emerald-600 dark:text-emerald-400">Todo está en orden — no hay nada urgente que revisar.</p>`
        }
      </div>
    `;
  }

  function renderRentabilidadVentasPanel(resumen) {
    const rent = resumen.rentabilidad;
    const ventas = resumen.ventas;
    return `
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-6">
        <div class="panel-card">
          <h3 class="panel-title mb-1">Rentabilidad</h3>
          <p class="panel-subtitle mb-3">${rent.productosConCosto === 0 ? "Todavía no hay costos de compra cargados — importa un Excel/CSV con costo para ver esto." : "Calculado con tus costos y precios reales."}</p>
          <div class="grid grid-cols-3 gap-3">
            <div><p class="stat-label">Con costo cargado</p><p class="stat-value stat-value--sm mt-1">${rent.productosConCosto} / ${rent.totalProductos}</p></div>
            <div><p class="stat-label">Rentables</p><p class="stat-value stat-value--sm stat-value--success mt-1">${rent.productosRentables ?? "—"}</p></div>
            <div><p class="stat-label">Mercado Libre configurado</p><p class="stat-value stat-value--sm mt-1">${rent.canalesConfigurados.includes("mercadolibre") ? "Sí" : "No"}</p></div>
          </div>
          <button data-nav="/importar" class="text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:underline mt-3">Importar catálogo con costos →</button>
        </div>
        <div class="panel-card">
          <h3 class="panel-title mb-1">Ventas importadas</h3>
          <p class="panel-subtitle mb-3">${ventas.pedidosImportados === 0 ? "Todavía no se importó ninguna venta de Mercado Libre." : "Pedidos reales importados desde Mercado Libre."}</p>
          <div class="grid grid-cols-2 gap-3">
            <div><p class="stat-label">Pedidos importados</p><p class="stat-value stat-value--sm mt-1">${ventas.pedidosImportados}</p></div>
            <div><p class="stat-label">Últimos 30 días</p><p class="stat-value stat-value--sm mt-1">${ventas.pedidosUltimos30Dias}</p></div>
          </div>
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-3">${ventas.ultimaVentaImportada ? `Última venta importada: ${formatDate(new Date(ventas.ultimaVentaImportada))}` : "Ninguna venta importada todavía."}</p>
        </div>
      </div>
    `;
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
        <span class="stock-cell text-sm shrink-0"><span class="dot ${ind.dotClass}"></span> ${ind.label}</span>
      </div>
    `;
  }

  function statusRow(label, info) {
    // "conectado"/"conectada" (concuerda en género con cada label: Mercado
    // Libre/WooCommerce vs. Base de datos) — se compara por prefijo en vez
    // de armar dos strings distintos para el mismo estado.
    const conectado = info.estado.startsWith("conectad");
    const modificador = conectado ? "status-dot--conectado" : info.estado === "demo" ? "status-dot--demo" : "status-dot--pendiente";
    return `
      <div class="status-row">
        <span class="status-dot ${modificador}"></span>
        <div class="min-w-0">
          <p class="status-row-label">${escapeHtml(label)}</p>
          <p class="status-row-detail">${escapeHtml(info.detalle)}</p>
        </div>
      </div>
    `;
  }

  function quickLink(iconName, label, path) {
    return `
      <button data-nav="${path}" class="flex items-center gap-2.5 px-3.5 py-3 rounded-xl border border-slate-200 dark:border-slate-700 hover:border-indigo-300 dark:hover:border-indigo-600 hover:bg-indigo-50/50 dark:hover:bg-indigo-950/40 transition text-left text-sm font-medium">
        <span class="text-lg">${icon(iconName)}</span> ${escapeHtml(label)}
      </button>
    `;
  }

  // ------------------------------------------------------------------
  // Productos: lista
  // ------------------------------------------------------------------

  function stockIndicator(row) {
    if (!row.gestionaStock) {
      if (row.estadoStock === "instock") return { dotClass: "dot--green", label: "En stock" };
      if (row.estadoStock === "outofstock") return { dotClass: "dot--red", label: "Sin stock" };
      return { dotClass: "dot--amber", label: "Por encargo" };
    }
    const qty = row.stockQuantity;
    if (qty === null || qty === undefined) return { dotClass: "dot--gray", label: "Sin dato" };
    if (qty <= 0) return { dotClass: "dot--red", label: String(qty) };
    if (qty <= LC.settings.getLowStockThreshold()) return { dotClass: "dot--amber", label: String(qty) };
    return { dotClass: "dot--green", label: String(qty) };
  }

  function stockBucket(row) {
    const ind = stockIndicator(row);
    if (ind.dotClass === "dot--red") return "sin-stock";
    if (ind.dotClass === "dot--amber") return "stock-bajo";
    if (ind.dotClass === "dot--green") return "con-stock";
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
              <option value="con-stock">En stock</option>
              <option value="stock-bajo">Stock bajo</option>
              <option value="sin-stock">Sin stock</option>
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
        <div class="empty-state-icon">${icon("search")}</div>
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
              <td><span class="stock-cell"><span class="dot ${ind.dotClass}"></span> ${ind.label}</span></td>
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

  // Evaluación de rentabilidad de un producto — mismos 5 estados que ya usa
  // Oportunidades/el asistente de importación (reco-badge), para que
  // "conviene o no conviene" se vea igual en toda la aplicación.
  const EVALUACION_LABEL = {
    rentable: "Buena oportunidad",
    margen_bajo: "Requiere revisión",
    no_rentable: "No recomendable",
    sin_stock: "Sin stock reservado",
    sin_datos: "Requiere revisión",
  };

  function renderRentabilidadDetalle(row, rentabilidad) {
    if (!rentabilidad) {
      return `
        <div class="panel-card mb-5">
          <h3 class="panel-title mb-1">Rentabilidad</h3>
          <p class="text-sm text-slate-500 dark:text-slate-400">Todavía no hay datos de rentabilidad para este producto.</p>
        </div>
      `;
    }
    const sinCosto = !rentabilidad.tieneCosto;
    return `
      <div class="panel-card mb-5">
        <div class="flex items-center justify-between gap-3 mb-4">
          <h3 class="panel-title">Rentabilidad</h3>
          ${sinCosto ? "" : `<span class="reco-badge reco-${rentabilidad.clasificacion}">${EVALUACION_LABEL[rentabilidad.clasificacion] || rentabilidad.clasificacion}</span>`}
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
          <div><p class="stat-label">Costo de compra</p><p class="text-lg font-semibold mt-1">${rentabilidad.costo != null ? formatCLP(rentabilidad.costo) : "Sin registrar"}</p></div>
          <div><p class="stat-label">Ganancia estimada</p><p class="text-lg font-semibold mt-1 ${rentabilidad.margenTiendaClp != null && rentabilidad.margenTiendaClp < 0 ? "text-red-600 dark:text-red-400" : ""}">${rentabilidad.margenTiendaClp != null ? formatCLP(rentabilidad.margenTiendaClp) : "—"}</p></div>
          <div><p class="stat-label">Margen</p><p class="text-lg font-semibold mt-1">${rentabilidad.margenTiendaPct != null ? `${rentabilidad.margenTiendaPct.toFixed(1)}%` : "—"}</p></div>
          <div><p class="stat-label">Mercado Libre</p><p class="text-lg font-semibold mt-1">${rentabilidad.mercadoLibreConfigurado ? "Configurado" : "Sin configurar"}</p></div>
        </div>
        <p class="text-xs text-slate-400 dark:text-slate-500 mb-4">Calculado con tu costo y precio reales — sin asumir ninguna comisión que no hayas confirmado.</p>
        ${
          sinCosto
            ? `<button id="detail-agregar-costo" class="btn-primary">Agregar costo</button>`
            : `<button data-nav="/oportunidades" class="btn-secondary">Ver en Oportunidades →</button>`
        }
      </div>
    `;
  }

  // Modal simple de "Agregar costo" — con feedback Guardando… / ✓
  // actualizado en el propio botón, para que nunca quede la duda de si
  // funcionó (pedido explícito: nunca dejar al usuario preguntándose).
  function abrirEditorCosto(producto, onGuardado) {
    const root = document.getElementById("modal-root");
    root.innerHTML = `
      <div class="modal-overlay fixed inset-0 bg-slate-900/50 dark:bg-slate-950/70 flex items-center justify-center z-[60] p-4">
        <div class="modal-card bg-white dark:bg-slate-800 rounded-2xl shadow-2xl max-w-sm w-full p-6">
          <h3 class="text-lg font-semibold mb-1">Agregar costo</h3>
          <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">${escapeHtml(producto.nombre)}</p>
          <label class="form-label" for="costo-input">Precio de compra</label>
          <input id="costo-input" type="number" min="0" step="1" inputmode="numeric" class="form-input" placeholder="$" value="${producto.costo ?? ""}" />
          <p id="costo-feedback" class="text-sm mt-2 min-h-[1.25rem]"></p>
          <div class="flex justify-end gap-3 mt-3">
            <button id="costo-cancelar" class="btn-secondary">Cancelar</button>
            <button id="costo-guardar" class="btn-primary">Guardar</button>
          </div>
        </div>
      </div>
    `;
    const close = () => {
      root.innerHTML = "";
    };
    root.querySelector(".modal-overlay").addEventListener("click", (e) => {
      if (e.target.classList.contains("modal-overlay")) close();
    });
    document.getElementById("costo-cancelar").addEventListener("click", close);
    document.getElementById("costo-input").focus();

    document.getElementById("costo-guardar").addEventListener("click", async () => {
      const feedback = document.getElementById("costo-feedback");
      const valor = document.getElementById("costo-input").value.trim();
      const costo = valor === "" ? null : Number(valor);
      if (costo !== null && (!Number.isFinite(costo) || costo < 0)) {
        feedback.textContent = "Ingresa un número válido.";
        feedback.className = "text-sm mt-2 min-h-[1.25rem] text-red-600 dark:text-red-400";
        return;
      }
      const btn = document.getElementById("costo-guardar");
      btn.disabled = true;
      btn.textContent = "Guardando…";
      feedback.textContent = "";

      const res = await LC.backendApi.actualizarCostoProducto(producto.id, costo);
      if (!res.ok) {
        btn.disabled = false;
        btn.textContent = "Guardar";
        feedback.textContent = res.error.mensaje;
        feedback.className = "text-sm mt-2 min-h-[1.25rem] text-red-600 dark:text-red-400";
        return;
      }
      btn.textContent = "✓ Costo actualizado";
      toast("success", "Costo actualizado.");
      setTimeout(() => {
        close();
        onGuardado();
      }, 500);
    });
  }

  async function renderProductDetail(main, id) {
    const detalle = await LC.dataSource.getProductoDetalle(id);
    if (!detalle) {
      main.innerHTML = `<div class="page-wrap"><div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("help")}</div><p class="empty-state-title">Producto no encontrado</p><button data-back class="btn-secondary mt-4">← Volver a Productos</button></div></div>`;
      main.querySelector("[data-back]").addEventListener("click", () => LC.router.navigate("/productos"));
      return;
    }
    const { row, variantes, historial, creado, rentabilidad } = detalle;
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
            <span class="stock-cell text-sm font-medium"><span class="dot ${ind.dotClass}"></span> ${ind.label}</span>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
            <div><p class="stat-label">Precio</p><p class="text-lg font-semibold mt-1">${formatCLP(row.precio)}</p></div>
            <div><p class="stat-label">Stock</p><p class="text-lg font-semibold mt-1">${row.stockQuantity ?? "—"}</p></div>
            <div><p class="stat-label">Categoría</p><p class="text-lg font-semibold mt-1">${escapeHtml(row.categoria || "—")}</p></div>
            <div><p class="stat-label">Creado</p><p class="text-lg font-semibold mt-1">${formatDate(creado)}</p></div>
          </div>
        </div>

        ${renderRentabilidadDetalle(row, rentabilidad)}

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
            <h3 class="panel-title mb-2">Mercado Libre</h3>
            <div id="ml-mini-decision"><p class="text-sm text-slate-400">Consultando…</p></div>
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
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-4 pt-3 border-t border-slate-100 dark:border-slate-800">${historial.length ? "Historial de ejemplo — se reemplazará por el historial real del producto." : "Todavía no hay historial de cambios registrado para este producto."}</p>
        </div>
      </div>
    `;

    document.getElementById("back-to-list").addEventListener("click", () => LC.router.navigate("/productos"));
    cargarMiniDecisionMercadoLibre(main, row.id);
    main.querySelectorAll("[data-nav]").forEach((btn) => {
      btn.addEventListener("click", () => LC.router.navigate(btn.dataset.nav));
    });
    const agregarCostoBtn = document.getElementById("detail-agregar-costo");
    if (agregarCostoBtn) {
      agregarCostoBtn.addEventListener("click", () => {
        abrirEditorCosto({ id: row.id, nombre: row.nombre, costo: rentabilidad ? rentabilidad.costo : null }, () => renderProductDetail(main, id));
      });
    }
  }

  // Miniatura de decisión "¿conviene vender en Mercado Libre?" (30 de
  // agosto de 2026, FASE 6 frontend) — carga aparte del resto del detalle
  // del producto porque puede consultar Mercado Libre y tardar más; nunca
  // bloquea el resto de la pantalla mientras responde.
  const MINI_DECISION_LABEL = { conviene: "Conviene", revisar: "Conviene revisar", no_conviene: "No conviene", datos_insuficientes: "Faltan datos" };

  async function cargarMiniDecisionMercadoLibre(main, variantId) {
    const el = document.getElementById("ml-mini-decision");
    if (!el) return;
    const modo = await LC.dataSource.getModo();
    if (modo !== "real") {
      el.innerHTML = `<p class="text-sm text-slate-400">Disponible cuando conectes el backend real.</p>`;
      return;
    }
    const res = await LC.backendApi.decisionMercadoLibre(variantId);
    if (!document.getElementById("ml-mini-decision")) return; // la pantalla ya cambió
    if (!res.ok) {
      el.innerHTML = `<p class="text-sm text-slate-400 mb-3">${escapeHtml(res.error.mensaje)}</p><button data-mini-ml class="btn-secondary">Analizar para Mercado Libre</button>`;
    } else {
      const d = res.data;
      const visual = d.decision === "revisar" && d.faltantes && d.faltantes.length ? "datos_insuficientes" : d.decision;
      el.innerHTML = `
        <span class="reco-badge reco-${visual} mb-3">${escapeHtml(MINI_DECISION_LABEL[visual] || visual)}</span>
        <p class="text-sm text-slate-500 dark:text-slate-400 mb-3">${escapeHtml(d.razon)}</p>
        <button data-mini-ml class="btn-secondary">Analizar para Mercado Libre</button>
      `;
    }
    const btn = el.querySelector("[data-mini-ml]");
    if (btn) btn.addEventListener("click", () => LC.router.navigate(`/publicaciones/${variantId}`));
  }

  // ------------------------------------------------------------------
  // Mercado Libre
  // ------------------------------------------------------------------

  function orderStatusBadge(estado) {
    const labels = { pendiente: "Pendiente", enviado: "Enviado", entregado: "Entregado", cancelado: "Cancelado" };
    return `<span class="order-status order-status--${estado}">${labels[estado] || estado}</span>`;
  }

  // Motivo corto que manda el backend (?razon=...) -> texto humano. Nunca
  // se muestra el "razon" crudo ni ningún detalle técnico (HTTP, excepción,
  // JSON) — eso queda en los logs del servidor.
  const RAZON_ERROR_ML = {
    rechazado: "No se completó la autorización en Mercado Libre.",
    error_autorizacion: "Mercado Libre no pudo autorizar la conexión.",
    solicitud_invalida: "La respuesta de Mercado Libre no fue la esperada.",
    estado_invalido: "El enlace de conexión venció — probá conectar de nuevo.",
    credenciales_faltantes: "Todavía no configuraste las credenciales de Mercado Libre.",
    conexion_fallida: "No pudimos conectar con Mercado Libre. Probá de nuevo en un momento.",
    cifrado_no_configurado: "Hay un problema de configuración interno — avisale a soporte.",
  };

  function renderConexionMercadoLibre(ml) {
    if (!ml) {
      return `
        <div class="panel-card mb-6">
          <h3 class="panel-title mb-1">Mercado Libre</h3>
          <p class="text-sm text-slate-500 dark:text-slate-400">No pudimos consultar el estado de la conexión ahora mismo.</p>
        </div>`;
    }
    if (ml.conectado) {
      const cuenta = ml.nickname ? `${ml.nickname}${ml.siteId ? ` · ${ml.siteId}` : ""}` : ml.cuentaExternaId;
      const ultimaConexion = ml.conectadoEn
        ? new Date(ml.conectadoEn).toLocaleString("es-CL", { dateStyle: "medium", timeStyle: "short" })
        : null;
      return `
        <div class="panel-card mb-6">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center gap-2.5">
              <span class="dot dot--green"></span>
              <div>
                <p class="text-sm font-medium">Mercado Libre conectado</p>
                <p class="text-xs text-slate-400">Cuenta vendedora: ${escapeHtml(cuenta)}</p>
                ${ultimaConexion ? `<p class="text-xs text-slate-400">Última conexión: ${escapeHtml(ultimaConexion)}</p>` : ""}
              </div>
            </div>
            <div class="flex items-center gap-2">
              <button id="ml-importar-ventas-btn" class="btn-secondary">Importar ventas ahora</button>
              <button id="ml-administrar-btn" class="btn-secondary">Administrar</button>
            </div>
          </div>
          <p class="text-sm text-slate-500 dark:text-slate-400 mt-3">
            Tu cuenta está conectada correctamente. Las ventas, pedidos e ingresos de abajo siguen siendo de ejemplo hasta que importes tus ventas reales.
          </p>
        </div>`;
    }
    return `
      <div class="panel-card mb-6">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2.5">
            <span class="dot dot--gray"></span>
            <p class="text-sm font-medium">Mercado Libre no está conectado</p>
          </div>
          <button id="connect-ml-btn" class="btn-primary">Conectar Mercado Libre</button>
        </div>
        <p class="text-sm text-slate-500 dark:text-slate-400 mt-3">
          ${ml.credencialesConfiguradas ? "Conecta la cuenta de Mercado Libre de tu empresa para empezar a traer tus ventas reales." : "Todavía no está lista la conexión con Mercado Libre — contactanos para activarla."}
        </p>
      </div>`;
  }

  async function renderMercadoLibre(main) {
    const url = new URL(window.location.href);
    const mlParam = url.searchParams.get("ml");
    if (mlParam) {
      if (mlParam === "conectado") toast("success", "Mercado Libre conectado correctamente.");
      else toast("error", RAZON_ERROR_ML[url.searchParams.get("razon")] || "No se completó la conexión con Mercado Libre.");
      url.searchParams.delete("ml");
      url.searchParams.delete("razon");
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }

    const [estadoRes, resumen, productosFiltro] = await Promise.all([
      LC.backendApi.fetchMercadoLibreEstado(),
      LC.dataSource.getResumenMercadoLibre(),
      LC.dataSource.getProductosVendidosEnMercadoLibre(),
    ]);
    const ml = estadoRes.ok ? estadoRes.data : null;
    mlState.page = 1;

    main.innerHTML = `
      <div class="page-wrap app-fade">
        ${renderConexionMercadoLibre(ml)}

        <div class="panel-card mb-6">
          <div class="flex items-center gap-2">
            <span class="demo-pill">Datos de demostración</span>
            <p class="text-sm text-slate-500 dark:text-slate-400">Ventas, pedidos e ingresos de acá abajo son de ejemplo, para poder evaluar la interfaz.</p>
          </div>
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
              <option value="pendiente">Pendiente</option>
              <option value="enviado">Enviado</option>
              <option value="entregado">Entregado</option>
              <option value="cancelado">Cancelado</option>
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

    const connectBtn = document.getElementById("connect-ml-btn");
    if (connectBtn) {
      connectBtn.addEventListener("click", async () => {
        connectBtn.disabled = true;
        connectBtn.textContent = "Conectando…";
        const res = await LC.backendApi.conectarMercadoLibre();
        if (!res.ok) {
          connectBtn.disabled = false;
          connectBtn.textContent = "Conectar Mercado Libre";
          toast("error", res.error.mensaje);
          return;
        }
        // Navegación real de página completa — es Mercado Libre quien tiene
        // que mostrar su propia pantalla de inicio de sesión/autorización,
        // no algo que se pueda hacer con un fetch().
        window.location.href = res.data.authorizationUrl;
      });
    }

    const administrarBtn = document.getElementById("ml-administrar-btn");
    if (administrarBtn) {
      administrarBtn.addEventListener("click", () => {
        openModal({
          title: "¿Quieres desconectar Mercado Libre?",
          body: `<p>Podrás volver a conectar tu cuenta cuando quieras.</p>`,
          primaryLabel: "Desconectar",
          secondaryLabel: "Cancelar",
          onPrimary: async () => {
            const res = await LC.backendApi.desconectarMercadoLibre();
            if (!res.ok) {
              toast("error", res.error.mensaje);
              return;
            }
            toast("info", "Mercado Libre desconectado.");
            renderMercadoLibre(main);
          },
        });
      });
    }

    const importarVentasBtn = document.getElementById("ml-importar-ventas-btn");
    if (importarVentasBtn) {
      importarVentasBtn.addEventListener("click", async () => {
        importarVentasBtn.disabled = true;
        importarVentasBtn.textContent = "Importando…";
        const res = await LC.backendApi.importarVentasMercadoLibre();
        if (!res.ok) {
          importarVentasBtn.disabled = false;
          importarVentasBtn.textContent = "Importar ventas ahora";
          toast("error", res.error.mensaje);
          return;
        }
        const nuevas = res.data.ordenesNuevas.length;
        toast("success", nuevas > 0 ? `${nuevas} venta${nuevas === 1 ? "" : "s"} nueva${nuevas === 1 ? "" : "s"} importada${nuevas === 1 ? "" : "s"}.` : "No hay ventas nuevas para importar.");
        importarVentasBtn.disabled = false;
        importarVentasBtn.textContent = "Importar ventas ahora";
      });
    }

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
        <div class="empty-state-icon">${icon("search")}</div>
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
  // Oportunidades — qué conviene revisar o vender ahora, para cualquier
  // rubro: reusa el mismo motor de rentabilidad que ya usa el asistente de
  // importación (GET /api/seleccion vía LC.dataSource.getOportunidades()),
  // pero como una pantalla propia a la que se vuelve sin re-subir nada.
  // ------------------------------------------------------------------

  const OPORTUNIDAD_LABEL = {
    rentable: "Buena oportunidad",
    margen_bajo: "Margen bajo",
    no_rentable: "No conviene todavía",
    sin_stock: "Sin stock reservado",
    sin_datos: "Falta información",
    no_seleccionado: "Fuera del límite",
  };

  // Agrupado por importancia (no una tabla plana): qué mirar primero y por
  // qué — mismas 5 clasificaciones que ya calcula el backend, solo
  // organizadas para que la atención vaya a lo que más importa primero.
  const GRUPOS_OPORTUNIDAD = [
    { id: "rentable", clasificaciones: ["rentable"], titulo: "Alta oportunidad", desc: "Ganancia potencial y buen margen — buenos candidatos para vender más." },
    { id: "revision", clasificaciones: ["margen_bajo", "sin_datos", "sin_stock"], titulo: "Requiere revisión", desc: "Información incompleta o margen ajustado — conviene completarlos." },
    { id: "no_rentable", clasificaciones: ["no_rentable"], titulo: "Baja rentabilidad", desc: "Hoy no conviene venderlos — revisa el costo o el precio." },
  ];

  // Comisión REAL de Mercado Libre (29 de agosto de 2026) — "Clásica 15% /
  // Premium 19%" cuando ya se corrió "Actualizar comisiones reales"; "—"
  // si el producto todavía no tiene esa comisión consultada (nunca se
  // inventa un %).
  function comisionMlTexto(comisionMlReal) {
    if (!comisionMlReal) return "—";
    const partes = [];
    if (comisionMlReal.classic) partes.push(`Clásica ${comisionMlReal.classic.comisionPct}%`);
    if (comisionMlReal.premium) partes.push(`Premium ${comisionMlReal.premium.comisionPct}%`);
    return partes.length ? partes.join(" · ") : "—";
  }

  const DECISION_COLUMNA_LABEL = { conviene: "Conviene", revisar: "Revisar", no_conviene: "No conviene", datos_insuficientes: "Faltan datos" };

  function celdaDecision(p, decisionMap) {
    const d = decisionMap && decisionMap.get(p.id);
    if (!d) return `<td class="px-3 py-2.5"><span class="text-xs text-slate-400">—</span></td>`;
    const visual = d.decision === "revisar" && d.faltantes && d.faltantes.length ? "datos_insuficientes" : d.decision;
    return `<td class="px-3 py-2.5"><span class="reco-badge reco-${visual} !text-xs !py-1">${DECISION_COLUMNA_LABEL[visual] || visual}</span></td>`;
  }

  // 30 de agosto de 2026 — hallazgo de frontend-ux-engineer: "sin_datos"
  // tiene 3 causas reales distintas (ver domain/catalog_selection.py), pero
  // el botón mostraba siempre "Agregar costo" — inútil si la causa real
  // era "falta configurar el canal Mercado Libre". Ahora se lee `p.razon`
  // (texto real que ya manda el backend, nunca inventado acá) para elegir
  // la acción correcta.
  function accionSinDatos(p) {
    const razon = p.razon || "";
    if (/mercado libre/i.test(razon)) {
      return `<button data-ir-configuracion class="btn-secondary !py-1.5 !text-xs">Configurar Mercado Libre</button>`;
    }
    if (/costo de compra/i.test(razon)) {
      return `<button data-agregar-costo="${p.id}" class="btn-secondary !py-1.5 !text-xs">Agregar costo</button>`;
    }
    // Falta precio de venta u otra causa sin acción directa desde acá —
    // se manda al detalle del producto en vez de un botón que no resuelve
    // nada.
    return `<button data-open="${p.id}" class="btn-secondary !py-1.5 !text-xs">Ver producto</button>`;
  }

  function filaOportunidad(p, decisionMap) {
    const accion = p.clasificacion === "sin_datos" ? accionSinDatos(p) : `<button data-open="${p.id}" class="btn-secondary !py-1.5 !text-xs">Ver producto</button>`;
    return `
      <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0">
        <td class="px-3 py-2.5">
          <p class="font-medium text-slate-800 dark:text-slate-100">${escapeHtml(p.nombre)}</p>
          <p class="text-xs text-slate-400 font-mono">${escapeHtml(p.sku || "—")}</p>
          ${p.clasificacion === "sin_datos" && p.razon ? `<p class="text-xs text-amber-600 dark:text-amber-400 mt-0.5">${escapeHtml(p.razon)}</p>` : ""}
        </td>
        <td class="px-3 py-2.5 text-right">${p.precio != null ? formatCLP(p.precio) : "—"}</td>
        <td class="px-3 py-2.5 text-right">${p.costo != null ? formatCLP(p.costo) : "—"}</td>
        <td class="px-3 py-2.5 text-right font-medium ${p.margenTiendaClp != null && p.margenTiendaClp < 0 ? "text-red-600 dark:text-red-400" : ""}">${p.margenTiendaClp != null ? formatCLP(p.margenTiendaClp) : "—"}</td>
        <td class="px-3 py-2.5 text-right">${p.margenTiendaPct != null ? `${p.margenTiendaPct.toFixed(1)}%` : "—"}</td>
        <td class="px-3 py-2.5 text-right text-xs text-slate-500 dark:text-slate-400">${escapeHtml(comisionMlTexto(p.comisionMlReal))}</td>
        ${celdaDecision(p, decisionMap)}
        <td class="px-3 py-2.5">${accion}</td>
      </tr>`;
  }

  function tablaOportunidades(productos, decisionMap) {
    return `<div class="table-wrap"><table class="w-full text-sm">
      <thead>
        <tr class="text-left border-b border-slate-200 dark:border-slate-700">
          <th class="px-3 py-2 font-medium">Producto</th>
          <th class="px-3 py-2 font-medium text-right">Precio</th>
          <th class="px-3 py-2 font-medium text-right">Costo</th>
          <th class="px-3 py-2 font-medium text-right">Ganancia estimada</th>
          <th class="px-3 py-2 font-medium text-right">Margen</th>
          <th class="px-3 py-2 font-medium text-right">Comisión ML real</th>
          <th class="px-3 py-2 font-medium" title="Evaluación rápida sin consultar competencia — abrí el producto para la evaluación completa.">Decisión preliminar</th>
          <th class="px-3 py-2 font-medium"></th>
        </tr>
      </thead>
      <tbody>${productos.map((p) => filaOportunidad(p, decisionMap)).join("")}</tbody>
    </table></div>`;
  }

  async function renderOportunidades(main) {
    const [modo, data] = await Promise.all([LC.dataSource.getModo(), LC.dataSource.getOportunidades()]);
    const esReal = modo === "real";
    const productos = [...(data.productos || [])].sort((a, b) => (b.margenTiendaClp ?? -Infinity) - (a.margenTiendaClp ?? -Infinity));
    const r = data.resumen || {};

    // Comisión REAL de Mercado Libre (29 de agosto de 2026) — el botón
    // solo tiene sentido si la cuenta está conectada (la consulta usa su
    // access token real); si no, se explica por qué no está disponible en
    // vez de mostrar un botón que va a fallar.
    let mlConectado = false;
    let decisionPorVariante = new Map();
    if (esReal) {
      const estadoMl = await LC.backendApi.fetchMercadoLibreEstado();
      mlConectado = estadoMl.ok && estadoMl.data.conectado;
      // Decisión "¿conviene publicar en Mercado Libre?" por producto (30
      // de agosto de 2026, FASE 6) — en lote, sin competencia, para no
      // pedirle a Mercado Libre una consulta por cada fila de la tabla
      // (ver GET /mercadolibre/decision-lote).
      const decisionRes = await LC.backendApi.decisionLoteMercadoLibre();
      if (decisionRes.ok) decisionPorVariante = new Map(decisionRes.data.map((d) => [d.variantId, d]));
    }

    main.innerHTML = `
      <div class="page-wrap app-fade">
        ${esReal ? "" : `<div class="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 px-4 py-3 mb-6 text-sm text-amber-800 dark:text-amber-200">Estás viendo datos de demostración — sube tu catálogo en "Importar catálogo" para ver tus oportunidades reales.</div>`}

        ${
          esReal
            ? `<div class="flex flex-wrap items-center justify-between gap-3 mb-6">
                <p class="text-sm text-slate-500 dark:text-slate-400 max-w-xl">La comisión real de Mercado Libre varía por producto (categoría, precio y tipo de publicación) — actualizala para ver cuál conviene subir.</p>
                ${
                  mlConectado
                    ? `<button id="recalcular-comisiones-btn" class="btn-secondary shrink-0">Actualizar comisiones reales de Mercado Libre</button>`
                    : `<span class="text-xs text-slate-400 shrink-0">Conectá Mercado Libre en Integraciones para ver la comisión real.</span>`
                }
              </div>`
            : ""
        }

        <div class="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-6">
          <div class="stat-card"><p class="stat-label">Total</p><p class="stat-value stat-value--sm">${r.total ?? productos.length}</p></div>
          <div class="stat-card"><p class="stat-label">Buenas oportunidades</p><p class="stat-value stat-value--sm stat-value--success">${r.rentables ?? 0}</p></div>
          <div class="stat-card"><p class="stat-label">Margen bajo</p><p class="stat-value stat-value--sm stat-value--warning">${r.margenBajo ?? 0}</p></div>
          <div class="stat-card"><p class="stat-label">No conviene</p><p class="stat-value stat-value--sm stat-value--danger">${r.noRentables ?? 0}</p></div>
          <div class="stat-card"><p class="stat-label">Falta información</p><p class="stat-value stat-value--sm">${r.sinDatos ?? 0}</p></div>
        </div>

        ${
          productos.length
            ? GRUPOS_OPORTUNIDAD.map((g) => {
                const items = productos.filter((p) => g.clasificaciones.includes(p.clasificacion));
                if (!items.length) return "";
                return `
                <div class="panel-card mb-5">
                  <div class="flex items-center gap-2 mb-1">
                    <span class="dot ${g.id === "rentable" ? "dot--green" : g.id === "revision" ? "dot--amber" : "dot--red"}"></span>
                    <h3 class="panel-title">${g.titulo}</h3>
                    <span class="text-sm text-slate-400">(${items.length})</span>
                  </div>
                  <p class="panel-subtitle mb-4">${g.desc}</p>
                  ${tablaOportunidades(items, decisionPorVariante)}
                </div>`;
              }).join("")
            : `<div class="panel-card"><div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("bulb")}</div><p class="empty-state-title">Todavía no hay productos para revisar</p><p class="empty-state-desc">Sube tu catálogo para que calculemos qué te conviene vender.</p></div></div>`
        }
      </div>
    `;

    main.querySelectorAll("[data-open]").forEach((btn) => {
      btn.addEventListener("click", () => LC.router.navigate(`/productos/${btn.dataset.open}`));
    });
    main.querySelectorAll("[data-agregar-costo]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const p = productos.find((x) => String(x.id) === btn.dataset.agregarCosto);
        abrirEditorCosto(p, () => renderOportunidades(main));
      });
    });
    main.querySelectorAll("[data-ir-configuracion]").forEach((btn) => {
      btn.addEventListener("click", () => LC.router.navigate("/configuracion"));
    });

    const recalcularBtn = document.getElementById("recalcular-comisiones-btn");
    if (recalcularBtn) {
      recalcularBtn.addEventListener("click", async () => {
        recalcularBtn.disabled = true;
        recalcularBtn.textContent = "Consultando comisiones reales…";
        const res = await LC.backendApi.recalcularComisionesMercadoLibre();
        if (!res.ok) {
          toast("error", res.error.mensaje);
          recalcularBtn.disabled = false;
          recalcularBtn.textContent = "Actualizar comisiones reales de Mercado Libre";
          return;
        }
        const { combinacionesComisionActualizadas, productosSinCategoriaDetectada } = res.data;
        if (productosSinCategoriaDetectada.length) {
          toast("info", `Comisiones actualizadas. ${productosSinCategoriaDetectada.length} producto(s) sin categoría detectada por Mercado Libre — revisá su nombre.`);
        } else {
          toast("success", combinacionesComisionActualizadas > 0 ? "Comisiones reales actualizadas." : "Las comisiones ya estaban actualizadas.");
        }
        renderOportunidades(main);
      });
    }
  }

  // ------------------------------------------------------------------
  // Integraciones — con qué sistemas puede conectarse la empresa. Mercado
  // Libre es UNA integración más, no el centro de la plataforma.
  // ------------------------------------------------------------------

  const INTEGRACION_ICON = { mercadolibre: "cart", woocommerce: "store", excel: "upload", shopify: "cart", sheets: "document" };
  const INTEGRACION_ESTADO_LABEL = { conectado: "Conectado", no_conectado: "No conectado", disponible: "Disponible", proximamente: "Próximamente" };
  const INTEGRACION_ESTADO_DOT = { conectado: "dot--green", no_conectado: "dot--gray", disponible: "dot--green", proximamente: "dot--gray" };
  const INTEGRACION_CTA = { conectado: "Ver detalles", no_conectado: "Conectar", disponible: "Usar ahora", proximamente: "" };

  async function renderIntegraciones(main) {
    const data = await LC.dataSource.getIntegraciones();
    main.innerHTML = `
      <div class="page-wrap app-fade">
        <p class="text-sm text-slate-500 dark:text-slate-400 mb-6 max-w-2xl">Estas son las integraciones con las que tu empresa puede conectarse. Algunas ya están disponibles hoy; otras están planificadas.</p>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          ${data.integraciones
            .map(
              (i) => `
            <div class="panel-card">
              <div class="flex items-center justify-between gap-3 mb-1">
                <h3 class="panel-title">${escapeHtml(i.nombre)}</h3>
                <span class="dot ${INTEGRACION_ESTADO_DOT[i.estado]}"></span>
              </div>
              <p class="text-xs text-slate-400 mb-3">${escapeHtml(i.categoria)} · ${INTEGRACION_ESTADO_LABEL[i.estado]}</p>
              <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">${escapeHtml(i.detalle)}</p>
              ${i.ruta ? `<button data-nav="${i.ruta}" class="btn-secondary">${INTEGRACION_CTA[i.estado]}</button>` : `<span class="btn-disabled">Próximamente</span>`}
            </div>`
            )
            .join("")}
        </div>
      </div>
    `;
    main.querySelectorAll("[data-nav]").forEach((btn) => {
      btn.addEventListener("click", () => LC.router.navigate(btn.dataset.nav));
    });
  }

  // ------------------------------------------------------------------
  // Automatizaciones — qué está haciendo el sistema por la empresa sin
  // que nadie tenga que hacerlo a mano. Hoy no hay ningún motor de
  // automatización real corriendo (ni programado) — se muestra un estado
  // vacío honesto, nunca una ejecución inventada.
  // ------------------------------------------------------------------

  const TIPOS_AUTOMATIZACION = [
    "Actualizar catálogo", "Sincronizar ventas", "Analizar rentabilidad",
    "Actualizar precios", "Generar reportes", "Detectar oportunidades",
  ];

  async function renderAutomatizaciones(main) {
    main.innerHTML = `
      <div class="page-wrap app-fade max-w-3xl">
        <div class="panel-card text-center py-12 mb-5">
          <div class="empty-state-icon">${icon("sync")}</div>
          <p class="empty-state-title">Todavía no tienes automatizaciones activas</p>
          <p class="empty-state-desc mx-auto">Cuando actives una, vas a poder ver acá su estado, cuándo corrió por última vez y cuándo vuelve a correr.</p>
        </div>
        <div class="panel-card">
          <h3 class="panel-title mb-3">Lo que vas a poder automatizar</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            ${TIPOS_AUTOMATIZACION.map((t) => `<div class="flex items-center gap-2.5 text-sm text-slate-600 dark:text-slate-300"><span class="dot dot--gray"></span>${escapeHtml(t)}</div>`).join("")}
          </div>
        </div>
      </div>
    `;
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
              <p class="text-2xl font-bold mt-1">${escapeHtml(sus.plan.nombre)}</p>
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
                <p class="text-xs text-slate-400">${p.id === "enterprise" ? "Precio a coordinar" : "Aún no definido"}</p>
                <ul class="text-sm text-slate-600 dark:text-slate-300 space-y-1.5 flex-1">
                  ${p.features.map((f) => `<li class="flex items-start gap-1.5"><span class="text-emerald-500">✓</span>${escapeHtml(f)}</li>`).join("")}
                </ul>
                ${isCurrent ? '<span class="btn-disabled justify-center">Plan actual</span>' : `<button data-plan="${p.id}" class="btn-primary justify-center choose-plan-btn">Elegir plan</button>`}
              </div>
            `;
            })
            .join("")}
        </div>
        <p class="text-xs text-slate-400 dark:text-slate-500 mt-4">Los precios todavía no están definidos — se confirmarán antes de operar con clientes reales.</p>
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

    // Comisión/envío/otros costos + margen objetivo/mínimo de Mercado
    // Libre (30 de agosto de 2026, FASE 6 frontend) — sin esto, el precio
    // recomendado y la decisión "¿conviene?" siempre dan "faltan datos".
    let canalMl = null;
    if (await LC.dataSource.getModo() === "real") {
      const res = await LC.backendApi.obtenerConfiguracionCanales();
      if (res.ok) canalMl = res.data.find((c) => c.channel === "mercadolibre") || {};
    }

    main.innerHTML = `
      <div class="page-wrap app-fade max-w-3xl space-y-5">

        <div class="panel-card">
          <h3 class="panel-title mb-1">General</h3>
          <p class="panel-subtitle mb-4">Información básica de tu negocio.</p>
          <div class="space-y-3">
            <div>
              <label class="form-label">Empresa</label>
              <p class="form-input flex items-center text-slate-500 dark:text-slate-400">${escapeHtml(nombreEmpresaActiva(session))}</p>
              <p class="text-xs text-slate-400 mt-1">Todavía no se puede editar desde acá.</p>
            </div>
            <div>
              <label class="form-label">Nombre de la tienda</label>
              <input id="cfg-store" type="text" value="${escapeHtml(settings.storeName)}" class="form-input" />
              <p class="text-xs text-slate-400 mt-1">Es solo una etiqueta para vos — todavía no cambia el nombre real de tu empresa en Nexo.</p>
            </div>
            <div>
              <label class="form-label">Email</label>
              <p class="form-input flex items-center text-slate-500 dark:text-slate-400">${escapeHtml(session.email)}</p>
              <p class="text-xs text-slate-400 mt-1">Todavía no se puede editar desde acá.</p>
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
                ${t === "light" ? "Claro" : t === "dark" ? "Oscuro" : "Automático"}
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
          <p class="panel-subtitle mb-3">Un producto se marca como stock bajo cuando su cantidad es mayor que cero y menor o igual a este número.</p>
          <div class="flex items-center gap-3">
            <input id="cfg-low-stock" type="number" min="0" step="1" value="${LC.settings.getLowStockThreshold()}" class="form-input w-24" />
            <span class="text-sm text-slate-500 dark:text-slate-400">unidades</span>
          </div>
        </div>

        ${canalMl !== null ? `
        <div class="panel-card">
          <h3 class="panel-title mb-1">Mercado Libre — costos y margen</h3>
          <p class="panel-subtitle mb-4">Con esto Nexo calcula el precio recomendado y si te conviene publicar cada producto. Sin margen objetivo cargado, esas pantallas van a mostrar "faltan datos".</p>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="form-label">Comisión de Mercado Libre (%)</label>
              <input id="cfg-ml-comision" type="number" min="0" step="0.1" class="form-input" value="${canalMl.commissionPct ?? ""}" />
            </div>
            <div>
              <label class="form-label">Costo de envío ($)</label>
              <input id="cfg-ml-envio" type="number" min="0" step="1" class="form-input" value="${canalMl.shippingCost ?? ""}" />
            </div>
            <div>
              <label class="form-label">Otros costos fijos ($)</label>
              <input id="cfg-ml-otros" type="number" min="0" step="1" class="form-input" value="${canalMl.otherFixedCost ?? ""}" />
            </div>
            <div>
              <label class="form-label">Margen objetivo (%)</label>
              <input id="cfg-ml-margen-objetivo" type="number" min="0" step="0.1" class="form-input" value="${canalMl.targetMarginPct ?? ""}" />
            </div>
            <div>
              <label class="form-label">Margen mínimo aceptable (%)</label>
              <input id="cfg-ml-margen-minimo" type="number" min="0" step="0.1" class="form-input" value="${canalMl.minMarginPct ?? ""}" />
            </div>
          </div>
          <p id="cfg-ml-feedback" class="text-sm mt-2 min-h-[1.25rem]"></p>
          <button id="cfg-ml-guardar" class="btn-primary mt-2">Guardar</button>
        </div>` : ""}

        <div class="panel-card">
          <div class="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <h3 class="panel-title mb-1">Integraciones</h3>
              <p class="panel-subtitle">Mercado Libre, WooCommerce, Excel y las que se agreguen más adelante.</p>
            </div>
            <button data-nav="/integraciones" class="btn-secondary shrink-0">Ver integraciones</button>
          </div>
        </div>

        <div class="panel-card">
          <div class="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <h3 class="panel-title mb-1">Usuarios y permisos</h3>
              <p class="panel-subtitle">Todavía solo hay una cuenta por empresa — más adelante vas a poder invitar a tu equipo con distintos permisos.</p>
            </div>
            <span class="btn-disabled shrink-0">Próximamente</span>
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
        storeName: document.getElementById("cfg-store").value.trim() || settings.storeName,
      });
      toast("success", "Configuración guardada correctamente.");
    });

    const btnGuardarMl = document.getElementById("cfg-ml-guardar");
    if (btnGuardarMl) {
      btnGuardarMl.addEventListener("click", async () => {
        const num = (id) => {
          const v = document.getElementById(id).value.trim();
          return v === "" ? null : Number(v);
        };
        const feedback = document.getElementById("cfg-ml-feedback");
        btnGuardarMl.disabled = true;
        btnGuardarMl.textContent = "Guardando…";
        const res = await LC.backendApi.configurarCanal("mercadolibre", {
          commission_pct: num("cfg-ml-comision"),
          shipping_cost: num("cfg-ml-envio"),
          other_fixed_cost: num("cfg-ml-otros"),
          target_margin_pct: num("cfg-ml-margen-objetivo"),
          min_margin_pct: num("cfg-ml-margen-minimo"),
        });
        btnGuardarMl.disabled = false;
        btnGuardarMl.textContent = "Guardar";
        if (!res.ok) {
          feedback.textContent = res.error.mensaje;
          feedback.className = "text-sm mt-2 min-h-[1.25rem] text-red-600 dark:text-red-400";
          return;
        }
        feedback.textContent = "";
        toast("success", "Configuración de Mercado Libre guardada.");
      });
    }

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

    main.querySelectorAll("[data-nav]").forEach((btn) => {
      btn.addEventListener("click", () => LC.router.navigate(btn.dataset.nav));
    });

    document.getElementById("cfg-change-password").addEventListener("click", () => {
      infoModal("Cambiar contraseña", "Todavía no está disponible cambiar la contraseña desde acá.");
    });
    document.getElementById("cfg-logout").addEventListener("click", async () => {
      await LC.auth.logout();
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


  LC.app = { render };
})();
