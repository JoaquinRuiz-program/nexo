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
    "google-sheets": "Google Sheets",
    automatizaciones: "Automatizaciones",
    sincronizacion: "Automatizaciones",
    suscripcion: "Mi plan",
    soporte: "Ayuda y soporte",
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

  // Última ruta pintada — la usa rerenderActual() para que un "refrescá
  // esta pantalla" disparado desde un handler vuelva a pasar por render()
  // (y por su manejo de errores), en vez de llamar al renderer directo y
  // quedarse con una promesa rechazada en silencio si falla la carga.
  let rutaActual = { routeName: "dashboard", param: null };

  function rerenderActual() {
    return render(rutaActual.routeName, rutaActual.param);
  }

  async function render(routeName, param) {
    rutaActual = { routeName, param };
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
        case "google-sheets":
          await LC.googleSheetsFlow.render(main);
          break;
        case "automatizaciones":
        case "sincronizacion": // ruta anterior — misma pantalla, concepto ampliado
          await renderAutomatizaciones(main);
          break;
        case "suscripcion":
          await renderSuscripcion(main);
          break;
        case "soporte":
          await LC.soporte.render(main, param);
          break;
        case "configuracion":
          await renderConfiguracion(main);
          break;
        default:
          main.innerHTML = `<div class="page-wrap">Sección no encontrada.</div>`;
      }
    } catch (err) {
      // 6 de septiembre de 2026 (P0-1): un fallo cargando datos REALES
      // tiene su propia pantalla, con la causa en lenguaje humano y un
      // botón para reintentar — antes esto caía en datos de demostración
      // sin que el dueño se enterara (ver js/dataSource.js).
      if (err instanceof LC.dataSource.ErrorDatosReales) {
        renderErrorDeDatos(main, err, routeName, param);
      } else {
        // El mensaje técnico (err.message) queda plegado en "Ver detalles" —
        // quien ve esta pantalla es el dueño del negocio, no alguien que
        // necesite leer un stack trace para saber que algo salió mal.
        main.innerHTML = `<div class="page-wrap"><div class="empty-state flex flex-col items-center text-center"><div class="empty-state-icon">${icon("alert")}</div><p class="empty-state-title">Algo no funcionó como esperábamos</p><p class="empty-state-desc">Intenta recargar la página. Si el problema sigue, avísanos.</p><details class="mt-4 text-xs text-slate-400"><summary class="cursor-pointer">Ver detalles técnicos</summary><p class="mt-1 font-mono">${escapeHtml(String(err && err.message ? err.message : err))}</p></details></div></div>`;
      }
    }

    if (scrollTarget) {
      const el = document.getElementById(scrollTarget);
      scrollTarget = null;
      if (el) setTimeout(() => el.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
    }
  }

  // 6 de septiembre de 2026 (P0-1) — no pudimos cargar los datos REALES de
  // esta empresa. Se distingue la causa (conexión / servidor / sesión) en
  // lenguaje humano, y NUNCA se rellena la pantalla con datos de
  // demostración para disimular el fallo.
  const CAUSA_ERROR_DATOS = {
    red: {
      titulo: "No pudimos conectar con el servidor",
      desc: "Revisá tu conexión a internet y volvé a intentar. Tus datos están a salvo — no se perdió nada.",
    },
    timeout: {
      titulo: "El servidor está tardando más de lo normal",
      desc: "Puede ser algo momentáneo. Esperá unos segundos y volvé a intentar.",
    },
    servidor: {
      titulo: "Tuvimos un problema al cargar tus datos",
      desc: "Es un problema nuestro, no tuyo. Volvé a intentar en un momento; si sigue pasando, escribinos desde Ayuda y soporte.",
    },
    integracion: {
      titulo: "No pudimos cargar tus datos en este momento",
      desc: "Volvé a intentar en un momento. Si el problema sigue, escribinos desde Ayuda y soporte.",
    },
    sesion: {
      titulo: "Tu sesión expiró",
      desc: "Por seguridad cerramos las sesiones después de un tiempo. Iniciá sesión de nuevo para seguir.",
    },
  };

  function renderErrorDeDatos(main, err, routeName, param) {
    // Sesión vencida: no tiene sentido ofrecer "Reintentar" (va a volver a
    // fallar) — el interceptor de 401 ya está mandando al login; acá solo
    // se evita mostrar una pantalla de error confusa mientras tanto.
    if (err.tipo === "sesion") {
      main.innerHTML = `
        <div class="page-wrap app-fade">
          <div class="panel-card text-center py-12">
            <div class="empty-state-icon">${icon("alert")}</div>
            <p class="empty-state-title">${escapeHtml(CAUSA_ERROR_DATOS.sesion.titulo)}</p>
            <p class="empty-state-desc mx-auto">${escapeHtml(CAUSA_ERROR_DATOS.sesion.desc)}</p>
            <button id="btn-ir-login" class="btn-primary mt-6">Iniciar sesión</button>
          </div>
        </div>`;
      document.getElementById("btn-ir-login").addEventListener("click", () => LC.router.navigate("/login"));
      return;
    }
    const causa = CAUSA_ERROR_DATOS[err.tipo] || {
      titulo: "No pudimos cargar tus datos",
      desc: "Volvé a intentar en un momento. Si el problema sigue, escribinos desde Ayuda y soporte.",
    };
    main.innerHTML = `
      <div class="page-wrap app-fade">
        <div class="panel-card text-center py-12">
          <div class="empty-state-icon">${icon("alert")}</div>
          <p class="empty-state-title">${escapeHtml(causa.titulo)}</p>
          <p class="empty-state-desc mx-auto">${escapeHtml(causa.desc)}</p>
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-4 max-w-md mx-auto">
            No te mostramos datos de ejemplo en lugar de los tuyos: preferimos decirte que algo falló antes que enseñarte información que no es real.
          </p>
          <div class="flex items-center justify-center gap-3 mt-6">
            <button id="btn-reintentar-datos" class="btn-primary">Reintentar</button>
            <button data-nav="/soporte" class="btn-secondary">Ayuda y soporte</button>
          </div>
        </div>
      </div>
    `;
    document.getElementById("btn-reintentar-datos").addEventListener("click", () => render(routeName, param));
    main.querySelectorAll("[data-nav]").forEach((btn) => {
      btn.addEventListener("click", () => LC.router.navigate(btn.dataset.nav));
    });
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
    // 6 de septiembre de 2026 — un admin VIENDO una empresa
    // (session.modoSoporte) sí tiene empresa activa: se muestra su nombre,
    // igual que lo vería el cliente.
    const viendoEmpresa = !!session.modoSoporte;
    document.getElementById("sidebar-empresa-activa").textContent =
      session.esNexoAdmin && !viendoEmpresa ? "Panel Nexo" : nombreEmpresaActiva(session);
    document.getElementById("nav-link-admin").classList.toggle("hidden", !session.esNexoAdmin);
    // Un admin de Nexo no tiene tienda propia — las pantallas de cliente
    // ni siquiera cargarían (get_current_store le daría error), así que
    // esos links ni se muestran (además del guard de router.js que ya
    // redirige si igual se navega ahí a mano). Mientras ve una empresa sí
    // se muestran: es exactamente lo que fue a ver.
    ["dashboard", "productos", "oportunidades", "importar", "integraciones", "automatizaciones", "suscripcion", "soporte", "configuracion"].forEach((r) => {
      const link = document.querySelector(`.nav-link[data-route="${r}"]`);
      if (link) link.classList.toggle("hidden", !!session.esNexoAdmin && !viendoEmpresa);
    });
    actualizarPillModoDemo();
    actualizarBannerModoSoporte(session);
  }

  // 6 de septiembre de 2026 — aviso persistente mientras un administrador
  // de Nexo está viendo la cuenta de un cliente (ver
  // app/api/routes/admin.py::entrar_a_ver_empresa) — nunca silencioso.
  function actualizarBannerModoSoporte(session) {
    const banner = document.getElementById("soporte-banner");
    if (!banner) return;
    const modoSoporte = session && session.modoSoporte;
    banner.classList.toggle("hidden", !modoSoporte);
    if (modoSoporte) {
      document.getElementById("soporte-banner-texto").textContent =
        `Estás viendo la cuenta de ${modoSoporte.empresaNombre || nombreEmpresaActiva(session) || "esta empresa"} como administrador de Nexo (${modoSoporte.adminEmail || "admin"}). Tu sesión de administrador sigue abierta.`;
    }
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

    document.getElementById("soporte-banner-salir").addEventListener("click", async () => {
      // Solo saca el contexto de empresa: la sesión del admin nunca se
      // cerró (ver app/api/routes/admin.py::salir_de_ver_empresa), así que
      // vuelve directo al panel, autenticado, sin pasar por /login.
      const res = await LC.backendApi.salirDeVerComoEmpresa();
      if (!res.ok) {
        toast("error", res.error.mensaje);
        return;
      }
      window.location.hash = "/admin";
      window.location.reload();
    });
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
        ${esReal ? "" : `
        <div class="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 text-amber-800 dark:text-amber-200 px-4 py-3 mb-6 text-sm flex items-center gap-2">
          <span>Estás viendo datos de demostración (catálogo y ventas de Mercado Libre). Importa tu catálogo real (Excel, CSV o Google Sheets) y conecta tu cuenta de Mercado Libre para ver tu negocio real.</span>
        </div>`}

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
            <p class="stat-hint">${esReal ? "Tu catálogo" : "Datos de demostración"}</p>
          </div>
        </div>

        ${esReal ? renderPublicacionesYPlan(resumen) : ""}
        ${esReal ? renderOnboarding(resumen, canalMl) : ""}
        ${esReal ? renderQueHacerAhora(resumen) : ""}
        ${esReal ? renderRentabilidadVentasPanel(resumen) : ""}

        <div class="panel-card mb-6">
          <div class="flex items-center justify-between gap-3 flex-wrap mb-4">
            <div class="flex items-center gap-2">
              <h3 class="panel-title">Ventas Mercado Libre</h3>
              ${esReal ? `<span class="text-xs text-slate-400">Sin sincronización de ventas todavía</span>` : `<span class="demo-pill">Datos de demostración</span>`}
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
            <p class="panel-subtitle mb-2">${esReal ? "Así están hoy tus conexiones." : "Ninguna de estas conexiones está activa todavía."}</p>
            <div>
              ${statusRow("Mercado Libre", estado.mercadoLibre)}
              ${statusRow("Google Sheets", estado.googleSheets)}
              ${statusRow("Base de datos", estado.baseDeDatos)}
            </div>
          </div>
          <div class="panel-card">
            <div class="flex items-center justify-between gap-3 mb-1">
              <h3 class="panel-title">Productos más vendidos</h3>
              <span class="text-xs text-slate-400">Últimos 30 días${esReal ? "" : " (demo)"}</span>
            </div>
            ${masVendidos.length ? masVendidos.map((p, i) => rankRow(i + 1, p, masVendidos[0].cantidad)).join("") : `<p class="text-sm text-slate-400 mt-3">${esReal ? "Todavía no hay ventas registradas." : "Todavía no hay ventas de ejemplo."}</p>`}
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
            <p class="panel-subtitle mb-3">${esReal ? "Atajos a lo que más vas a usar." : "Todo lo de acá usa datos de ejemplo por ahora."}</p>
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
  // 6 de septiembre de 2026 — auditoría comercial: el Dashboard tenía que
  // responder de un vistazo "¿cuántas publicaciones tengo, cuántas están
  // activas?" y "¿estoy cerca del límite de mi plan?" — antes ninguna de
  // las dos preguntas tenía respuesta acá (había que ir a Mercado Libre o
  // a Mi plan por separado).
  function renderPublicacionesYPlan(resumen) {
    const pub = resumen.publicaciones;
    const sus = resumen.suscripcion;
    if (!pub && !sus) return "";
    const plan = sus && sus.plan;
    const pctProductos = plan && plan.limiteProductos ? Math.round((sus.uso.productos / plan.limiteProductos) * 100) : null;
    const pctPublicaciones = plan && plan.limitePublicaciones ? Math.round((sus.uso.publicaciones / plan.limitePublicaciones) * 100) : null;
    const cercaDelLimite = (pctProductos !== null && pctProductos >= 80) || (pctPublicaciones !== null && pctPublicaciones >= 80);
    return `
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div class="stat-card">
          <p class="stat-label">Publicaciones en Mercado Libre</p>
          <p class="stat-value">${pub ? pub.total : "—"}</p>
          <p class="stat-hint">${pub ? `${pub.activas} activas · ${pub.pausadas} pausadas` : "Sin datos todavía"}</p>
        </div>
        <div class="stat-card">
          <p class="stat-label">Plan actual</p>
          <p class="stat-value stat-value--sm">${plan ? escapeHtml(plan.nombre) : "Sin asignar"}</p>
          <p class="stat-hint"><a href="#/suscripcion" class="hover:underline">Ver Mi plan →</a></p>
        </div>
        <div class="stat-card">
          <p class="stat-label">Uso del plan</p>
          ${plan ? `
            <p class="stat-value stat-value--sm ${cercaDelLimite ? "stat-value--warning" : ""}">${sus.uso.productos}${plan.limiteProductos ? `/${plan.limiteProductos}` : ""} productos</p>
            <p class="stat-hint">${sus.uso.publicaciones}${plan.limitePublicaciones ? `/${plan.limitePublicaciones}` : ""} publicaciones${cercaDelLimite ? " · cerca del límite" : ""}</p>
          ` : `<p class="stat-value stat-value--sm">—</p><p class="stat-hint">Sin plan asignado</p>`}
        </div>
      </div>
    `;
  }

  function buildPasosOnboarding(resumen, canalMl) {
    return [
      { titulo: "Configura tu empresa", hecho: true, ruta: null },
      { titulo: "Importa tus productos", hecho: resumen.total > 0, ruta: "/importar" },
      { titulo: "Configura costos y margen de Mercado Libre", hecho: !!(canalMl && canalMl.targetMarginPct != null), ruta: "/configuracion" },
      { titulo: "Conecta Mercado Libre", hecho: !!(resumen.mercadoLibre && resumen.mercadoLibre.conectado), ruta: "/integraciones" },
      { titulo: "Sube imágenes a tus productos", hecho: (resumen.productosConImagenes || 0) > 0, ruta: "/productos" },
      { titulo: "Publica tu primer producto", hecho: !!(resumen.publicaciones && resumen.publicaciones.total > 0), ruta: "/productos" },
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
    // 14 de septiembre de 2026 — un producto que se vende por Mercado Libre
    // sin llevar stock de tienda no está "sin stock" si tiene unidades
    // reservadas para Mercado Libre (caso real: volante publicado con 4 u.).
    const sinStockDeTienda = row.gestionaStock ? !(row.stockQuantity > 0) : row.estadoStock !== "instock";
    if (sinStockDeTienda && row.marketplaceStock > 0) {
      return { dotClass: "dot--green", label: `${row.marketplaceStock} para Mercado Libre` };
    }
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

  // 6 de septiembre de 2026 — "estado claro de cada producto" (auditoría
  // comercial): antes había que entrar al detalle de cada producto para
  // saber si ya estaba publicado en Mercado Libre — ahora se ve de un
  // vistazo en la lista. `undefined` = todavía no se consultó (demo mode
  // no manda este campo), `null` = se consultó y nunca se publicó.
  const ESTADO_PUBLICACION_LABEL = { active: "Publicado", paused: "Pausado", closed: "Eliminado" };
  const ESTADO_PUBLICACION_DOT = { active: "dot--green", paused: "dot--amber", closed: "dot--gray" };

  function celdaEstadoPublicacion(estado) {
    if (estado === undefined) return `<span class="text-xs text-slate-400">—</span>`;
    if (estado === null) return `<span class="stock-cell text-xs text-slate-400"><span class="dot dot--gray"></span> Sin publicar</span>`;
    return `<span class="stock-cell text-xs"><span class="dot ${ESTADO_PUBLICACION_DOT[estado] || "dot--gray"}"></span> ${ESTADO_PUBLICACION_LABEL[estado] || estado}</span>`;
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
                  <th class="sortable-th px-3 py-2 font-medium" data-sort="sku">SKU</th>
                  <th class="sortable-th px-3 py-2 font-medium" data-sort="nombre">Nombre</th>
                  <th class="sortable-th px-3 py-2 font-medium" data-sort="tipo">Tipo</th>
                  <th class="sortable-th px-3 py-2 font-medium" data-sort="stock">Stock</th>
                  <th class="sortable-th px-3 py-2 font-medium text-right" data-sort="precio">Precio</th>
                  <th class="px-3 py-2 font-medium text-right">Costo</th>
                  <th class="px-3 py-2 font-medium text-right" title="Precio de venta menos costo de compra (sin comisiones ni envío)">Margen</th>
                  <th class="px-3 py-2 font-medium">Mercado Libre</th>
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
      // 6 de septiembre de 2026 — UX de estados vacíos: "ningún producto
      // coincide" era el mensaje SIEMPRE, incluso con el catálogo
      // realmente vacío (0 productos, sin ningún filtro aplicado) — ahí
      // "probá con otro filtro" no tiene sentido, hay que decir cómo
      // empezar.
      const catalogoRealmenteVacio = rows.length === 0;
      emptyEl.innerHTML = catalogoRealmenteVacio ? `
        <div class="empty-state-icon">${icon("box")}</div>
        <p class="empty-state-title">No tienes productos todavía</p>
        <p class="empty-state-desc">Importa tu catálogo para comenzar.</p>
        <button data-ir-importar class="btn-primary mt-4">Importar catálogo</button>
      ` : `
        <div class="empty-state-icon">${icon("search")}</div>
        <p class="empty-state-title">Ningún producto coincide</p>
        <p class="empty-state-desc">Prueba con otro término de búsqueda o quita algún filtro.</p>
      `;
      const btnIrImportar = document.getElementById("products-empty").querySelector("[data-ir-importar]");
      if (btnIrImportar) btnIrImportar.addEventListener("click", () => LC.router.navigate("/importar"));
    } else {
      emptyEl.classList.add("hidden");
      tbody.innerHTML = pageRows
        .map((r) => {
          const ind = stockIndicator(r);
          const tipoBadge =
            r.tipo === "variable"
              ? `<span class="badge badge-variable">Variable${r.colorVariante ? " · " + escapeHtml(r.colorVariante) : ""}</span>`
              : `<span class="badge badge-simple">Simple</span>`;
          return `
            <tr data-row-id="${r.id}">
              <td class="font-mono text-xs text-slate-500 dark:text-slate-400 cursor-pointer" data-open="${r.id}">${escapeHtml(r.sku) || "—"}</td>
              <td class="font-medium text-slate-800 dark:text-slate-100 cursor-pointer" data-open="${r.id}">${escapeHtml(r.nombre) || "—"}</td>
              <td>${tipoBadge}</td>
              <td><span class="stock-cell"><span class="dot ${ind.dotClass}"></span> ${ind.label}</span></td>
              <td class="text-right font-medium">${formatCLP(r.precio)}</td>
              <td class="text-right text-slate-500 dark:text-slate-400">${r.costo != null ? formatCLP(r.costo) : "—"}</td>
              <td class="text-right whitespace-nowrap">${r.margenClp != null
                ? `<span class="font-medium ${r.margenClp < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}">${formatCLP(r.margenClp)}</span>${r.margenPct != null ? `<span class="text-xs text-slate-400 ml-1">${r.margenPct.toFixed(1)}%</span>` : ""}`
                : `<span class="text-xs text-slate-400" title="Falta el costo de compra">—</span>`}</td>
              <td>${celdaEstadoPublicacion(r.estadoPublicacionMercadoLibre)}</td>
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
    tbody.querySelectorAll("[data-menu]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const id = Number(btn.dataset.menu);
        openRowMenu(btn, id, pageRows.find((r) => r.id === id));
      });
    });
  }

  function openRowMenu(btn, id, row) {
    document.querySelectorAll(".row-menu").forEach((m) => m.remove());
    const menu = document.createElement("div");
    menu.className = "row-menu";
    menu.innerHTML = `
      <button class="dropdown-item" data-action="ver">Ver producto</button>
      <button class="dropdown-item" data-action="detalles">Ver detalles</button>
      <button class="dropdown-item" data-action="historial">Ver historial</button>
      <button class="dropdown-item dropdown-item--danger" data-action="eliminar">Eliminar producto</button>
    `;
    btn.parentElement.appendChild(menu);
    menu.addEventListener("click", (e) => {
      const item = e.target.closest("[data-action]");
      if (!item) return;
      if (item.dataset.action === "eliminar") {
        menu.remove();
        confirmarEliminarProducto(id, row);
        return;
      }
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

  function confirmarEliminarProducto(id, row) {
    const nombre = (row && row.nombre) || "este producto";
    openModal({
      title: "Eliminar producto",
      body: `<p>¿Seguro que querés eliminar <strong>${escapeHtml(nombre)}</strong>? Se borra del catálogo con sus variantes e imágenes. Las ventas ya registradas se conservan en el historial.</p>`,
      primaryLabel: "Eliminar",
      secondaryLabel: "Cancelar",
      onPrimary: async () => {
        const res = await LC.backendApi.eliminarProducto(id);
        if (!res.ok) {
          // 409 = está publicado en Mercado Libre; el backend explica que hay
          // que despublicarlo primero (res.error.mensaje trae ese detalle).
          toast("error", res.error.mensaje || "No pudimos eliminar el producto.");
          return;
        }
        toast("success", "Producto eliminado.");
        renderProductos(document.getElementById("main-content"));
      },
    });
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
          <div><p class="stat-label">Margen (venta − compra)</p><p class="text-lg font-semibold mt-1 ${rentabilidad.margenTiendaClp != null && rentabilidad.margenTiendaClp < 0 ? "text-red-600 dark:text-red-400" : ""}">${rentabilidad.margenTiendaClp != null ? `${formatCLP(rentabilidad.margenTiendaClp)}${rentabilidad.margenTiendaPct != null ? ` <span class="text-sm font-normal text-slate-400">${rentabilidad.margenTiendaPct.toFixed(1)}%</span>` : ""}` : "—"}</p></div>
          <div><p class="stat-label">Ganancia neta ML</p><p class="text-lg font-semibold mt-1 ${rentabilidad.margenMercadoLibreClp != null && rentabilidad.margenMercadoLibreClp < 0 ? "text-red-600 dark:text-red-400" : ""}">${rentabilidad.margenMercadoLibreClp != null ? formatCLP(rentabilidad.margenMercadoLibreClp) : "—"}</p></div>
          <div><p class="stat-label">Margen neto ML</p><p class="text-lg font-semibold mt-1">${rentabilidad.margenMercadoLibrePct != null ? `${rentabilidad.margenMercadoLibrePct.toFixed(1)}%` : "—"}</p></div>
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
  // 13 de septiembre de 2026 — cambiar la contrasena desde la aplicacion.
  // Antes este boton abria un cartel que decia que no estaba disponible: no
  // habia ninguna forma de cambiarla. Pide la actual a proposito (ver
  // app/api/routes/auth.py::cambiar_password) y el backend cierra las demas
  // sesiones abiertas de esa cuenta.
  function abrirCambioDePassword() {
    const root = document.getElementById("modal-root");
    root.innerHTML = `
      <div class="modal-overlay fixed inset-0 bg-slate-900/50 dark:bg-slate-950/70 flex items-center justify-center z-[60] p-4">
        <div class="modal-card bg-white dark:bg-slate-800 rounded-2xl shadow-2xl max-w-sm w-full p-6">
          <h3 class="text-lg font-semibold mb-1">Cambiar contraseña</h3>
          <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">Si tenés la sesión abierta en otro dispositivo, se va a cerrar.</p>
          <label class="form-label" for="pwd-actual">Contraseña actual</label>
          <input id="pwd-actual" type="password" class="form-input" autocomplete="current-password" />
          <label class="form-label mt-3" for="pwd-nueva">Contraseña nueva</label>
          <input id="pwd-nueva" type="password" class="form-input" autocomplete="new-password" />
          <label class="form-label mt-3" for="pwd-confirmar">Repetí la contraseña nueva</label>
          <input id="pwd-confirmar" type="password" class="form-input" autocomplete="new-password" />
          <p class="text-xs text-slate-400 mt-1.5">Al menos 8 caracteres.</p>
          <p id="pwd-feedback" class="text-sm mt-2 min-h-[1.25rem]"></p>
          <div class="flex justify-end gap-3 mt-3">
            <button id="pwd-cancelar" class="btn-secondary">Cancelar</button>
            <button id="pwd-guardar" class="btn-primary">Cambiar</button>
          </div>
        </div>
      </div>
    `;
    const close = () => { root.innerHTML = ""; };
    root.querySelector(".modal-overlay").addEventListener("click", (e) => {
      if (e.target.classList.contains("modal-overlay")) close();
    });
    document.getElementById("pwd-cancelar").addEventListener("click", close);
    document.getElementById("pwd-actual").focus();

    document.getElementById("pwd-guardar").addEventListener("click", async () => {
      const feedback = document.getElementById("pwd-feedback");
      const error = (texto) => {
        feedback.textContent = texto;
        feedback.className = "text-sm mt-2 min-h-[1.25rem] text-red-600 dark:text-red-400";
      };
      const actual = document.getElementById("pwd-actual").value;
      const nueva = document.getElementById("pwd-nueva").value;
      const confirmar = document.getElementById("pwd-confirmar").value;

      if (!actual) return error("Ingresá tu contraseña actual.");
      if (nueva.length < 8) return error("La contraseña nueva tiene que tener al menos 8 caracteres.");
      if (nueva !== confirmar) return error("Las dos contraseñas nuevas no coinciden.");

      const btn = document.getElementById("pwd-guardar");
      btn.disabled = true;
      btn.textContent = "Cambiando…";
      feedback.textContent = "";

      const res = await LC.backendApi.cambiarPassword(actual, nueva);
      if (!res.ok) {
        btn.disabled = false;
        btn.textContent = "Cambiar";
        return error(res.error.mensaje);
      }
      btn.textContent = "✓ Contraseña cambiada";
      const cerradas = res.data.sesionesCerradas;
      toast("success", cerradas > 0
        ? `Contraseña cambiada. Se cerraron ${cerradas} sesión(es) en otros dispositivos.`
        : "Contraseña cambiada.");
      setTimeout(close, 700);
    });
  }

  // 13 de septiembre de 2026 — stock fisico editable a mano, mismo patron que
  // abrirEditorCosto: un Excel real normalmente no trae columna de stock, asi
  // que tiene que poder cargarse desde aca. Vaciar el campo = "no gestiona
  // stock", que no es lo mismo que 0.
  // Resultado de mandar el stock a las publicaciones reales de Mercado Libre
  // (14 de septiembre de 2026) -> [tipo, mensaje] para toast().
  function mensajeStockMl(base, s) {
    if (s === null) return ["info", `${base} No pudimos actualizar Mercado Libre ahora — probá de nuevo más tarde.`];
    if (!s) return ["success", base];
    const partes = [base];
    if (s.publicacionesActualizadas) partes.push(`${s.publicacionesActualizadas} publicación(es) de Mercado Libre actualizada(s).`);
    if (s.conError) partes.push(`${s.conError} no se pudo actualizar en Mercado Libre.`);
    return [s.conError ? "info" : "success", partes.join(" ")];
  }

  function abrirEditorStock(producto, onGuardado) {
    const root = document.getElementById("modal-root");
    root.innerHTML = `
      <div class="modal-overlay fixed inset-0 bg-slate-900/50 dark:bg-slate-950/70 flex items-center justify-center z-[60] p-4">
        <div class="modal-card bg-white dark:bg-slate-800 rounded-2xl shadow-2xl max-w-sm w-full p-6">
          <h3 class="text-lg font-semibold mb-1">${producto.mercadoLibre ? "Unidades para Mercado Libre" : producto.stock == null ? "Agregar stock" : "Editar stock"}</h3>
          <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">${escapeHtml(producto.nombre)}</p>
          <label class="form-label" for="stock-input">Unidades disponibles</label>
          <input id="stock-input" type="number" min="0" step="1" inputmode="numeric" class="form-input" placeholder="0" value="${producto.stock ?? ""}" />
          <p class="text-xs text-slate-400 mt-1.5">${producto.mercadoLibre
            ? "Cuántas unidades ofrecés en Mercado Libre. Si el producto ya está publicado, también se actualiza la publicación."
            : "Dejalo vacio si este producto no lleva control de stock. Esto no cambia las unidades reservadas para Mercado Libre."}</p>
          <p id="stock-feedback" class="text-sm mt-2 min-h-[1.25rem]"></p>
          <div class="flex justify-end gap-3 mt-3">
            <button id="stock-cancelar" class="btn-secondary">Cancelar</button>
            <button id="stock-guardar" class="btn-primary">Guardar</button>
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
    document.getElementById("stock-cancelar").addEventListener("click", close);
    document.getElementById("stock-input").focus();

    document.getElementById("stock-guardar").addEventListener("click", async () => {
      const feedback = document.getElementById("stock-feedback");
      const valor = document.getElementById("stock-input").value.trim();
      const cantidad = valor === "" ? null : Number(valor);
      if (cantidad !== null && (!Number.isInteger(cantidad) || cantidad < 0)) {
        feedback.textContent = "Ingresa un numero entero de 0 o mas.";
        feedback.className = "text-sm mt-2 min-h-[1.25rem] text-red-600 dark:text-red-400";
        return;
      }
      const btn = document.getElementById("stock-guardar");
      btn.disabled = true;
      btn.textContent = "Guardando…";
      feedback.textContent = "";

      const res = producto.mercadoLibre
        ? await LC.backendApi.configurarStockMercadoLibre(producto.id, cantidad)
        : await LC.backendApi.actualizarStockProducto(producto.id, cantidad);
      if (!res.ok) {
        btn.disabled = false;
        btn.textContent = "Guardar";
        feedback.textContent = res.error.mensaje;
        feedback.className = "text-sm mt-2 min-h-[1.25rem] text-red-600 dark:text-red-400";
        return;
      }
      btn.textContent = "✓ Stock actualizado";
      if (producto.mercadoLibre) toast(...mensajeStockMl("Unidades para Mercado Libre actualizadas.", res.data.sincronizacionMl));
      else toast("success", "Stock actualizado.");
      setTimeout(() => {
        close();
        onGuardado();
      }, 500);
    });
  }

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

  // ------------------------------------------------------------------
  // Imágenes — subida real desde el computador (5 de septiembre de 2026:
  // click o arrastrar y soltar archivos, ver
  // backend/app/domain/image_storage.py) + el agregar-por-URL que ya
  // existía (útil para pegar una imagen ya alojada afuera). Arrastrar una
  // miniatura reordena; la primera es la principal al publicar.
  // ------------------------------------------------------------------

  function renderImagenesDetalle(row) {
    const imagenes = row.imagenes || [];
    return `
      <div class="panel-card mb-5">
        <h3 class="panel-title mb-1">Imágenes</h3>
        <p class="text-xs text-slate-400 dark:text-slate-500 mb-4">Arrastrá una miniatura para cambiar el orden — la primera es la que se usa como principal al publicar.</p>
        <div id="img-grid" class="flex flex-wrap gap-3 mb-4">
          ${imagenes.length === 0 ? `<p class="text-sm text-slate-500 dark:text-slate-400">Sin imágenes cargadas todavía.</p>` : ""}
          ${imagenes.map((img) => `
            <div class="img-thumb-wrap relative" draggable="true" data-image-id="${img.id}">
              <img src="${escapeHtml(img.url)}" class="w-24 h-24 object-cover rounded-lg border border-slate-200 dark:border-slate-700" />
              ${img.principal ? `<span class="absolute top-1 left-1 text-[10px] font-medium bg-indigo-600 text-white rounded px-1.5 py-0.5">Principal</span>` : ""}
              <button data-quitar-imagen="${img.id}" title="Quitar imagen" class="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-slate-700 text-white text-xs flex items-center justify-center hover:bg-red-600">✕</button>
            </div>
          `).join("")}
        </div>

        <div id="img-dropzone" class="border-2 border-dashed border-slate-300 dark:border-slate-700 rounded-lg p-5 text-center cursor-pointer hover:border-indigo-400 dark:hover:border-indigo-500 transition-colors">
          <input id="img-file-input" type="file" accept="image/png,image/jpeg,image/webp" multiple class="hidden" />
          <p class="text-sm text-slate-500 dark:text-slate-400">Arrastrá imágenes acá o <span class="text-indigo-600 dark:text-indigo-400 font-medium">hacé clic para elegirlas</span></p>
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-1">JPG, PNG o WEBP · hasta 5 MB cada una</p>
        </div>
        <div id="img-upload-progreso" class="mt-3 space-y-1.5"></div>

        <div class="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
          <input id="img-nueva-url" type="text" class="form-input flex-1 min-w-[220px]" placeholder="O pegá la URL de una imagen ya alojada (https://...)" />
          <button id="img-agregar" class="btn-secondary">Agregar por URL</button>
        </div>
        <div id="img-preview-nueva" class="mt-2"></div>
      </div>
    `;
  }

  async function subirArchivosDeImagen(row, fileList, onCambio) {
    const progreso = document.getElementById("img-upload-progreso");
    const archivos = Array.from(fileList);
    if (archivos.length === 0) return;
    const fila = document.createElement("p");
    fila.className = "text-sm text-slate-500 dark:text-slate-400";
    fila.textContent = archivos.length === 1 ? `Subiendo ${archivos[0].name}…` : `Subiendo ${archivos.length} imágenes…`;
    progreso.appendChild(fila);

    const res = await LC.backendApi.subirImagenesProducto(row.id, archivos);
    fila.remove();
    if (!res.ok) {
      toast("error", res.error.mensaje);
      return;
    }
    const { guardadas, rechazadas } = res.data.subidas || { guardadas: 0, rechazadas: [] };
    if (guardadas > 0) toast("success", guardadas === 1 ? "Imagen subida." : `${guardadas} imágenes subidas.`);
    rechazadas.forEach((r) => toast("error", `${r.archivo}: ${r.motivo}`));
    if (guardadas > 0) onCambio();
  }

  function wireImagenesDetalle(main, row, onCambio) {
    const input = document.getElementById("img-nueva-url");
    const preview = document.getElementById("img-preview-nueva");
    const btnAgregar = document.getElementById("img-agregar");

    const dropzone = document.getElementById("img-dropzone");
    const fileInput = document.getElementById("img-file-input");
    dropzone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      subirArchivosDeImagen(row, fileInput.files, onCambio);
      fileInput.value = "";
    });
    dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzone.classList.add("border-indigo-400", "dark:border-indigo-500");
    });
    dropzone.addEventListener("dragleave", () => {
      dropzone.classList.remove("border-indigo-400", "dark:border-indigo-500");
    });
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("border-indigo-400", "dark:border-indigo-500");
      if (e.dataTransfer && e.dataTransfer.files.length) {
        subirArchivosDeImagen(row, e.dataTransfer.files, onCambio);
      }
    });

    // Previsualización inmediata (nunca sube nada al escribir) — si la
    // imagen no carga, se avisa antes de que el dueño intente agregarla.
    input.addEventListener("input", () => {
      const url = input.value.trim();
      preview.innerHTML = "";
      if (!url) return;
      const img = document.createElement("img");
      img.src = url;
      img.className = "w-16 h-16 object-cover rounded-lg border border-slate-200 dark:border-slate-700";
      img.onerror = () => {
        const aviso = document.createElement("p");
        aviso.className = "text-xs text-red-600 dark:text-red-400";
        aviso.textContent = "Esa URL no cargó como imagen — revisala.";
        img.replaceWith(aviso);
      };
      preview.appendChild(img);
    });

    btnAgregar.addEventListener("click", async () => {
      const url = input.value.trim();
      if (!url) { toast("error", "Pegá la URL de una imagen primero."); return; }
      btnAgregar.disabled = true;
      btnAgregar.textContent = "Agregando…";
      const res = await LC.backendApi.agregarImagenProducto(row.id, url);
      if (!res.ok) {
        toast("error", res.error.mensaje);
        btnAgregar.disabled = false;
        btnAgregar.textContent = "Agregar imagen";
        return;
      }
      toast("success", "Imagen agregada.");
      onCambio();
    });

    main.querySelectorAll("[data-quitar-imagen]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const imageId = Number(btn.dataset.quitarImagen);
        btn.disabled = true;
        const res = await LC.backendApi.eliminarImagenProducto(row.id, imageId);
        if (!res.ok) {
          toast("error", res.error.mensaje);
          btn.disabled = false;
          return;
        }
        toast("success", "Imagen eliminada.");
        onCambio();
      });
    });

    // Reordenar arrastrando — drag & drop nativo, sin librería. El drop
    // arma el orden final completo (todos los ids, en el orden visual
    // resultante) y se lo manda al backend de una sola vez.
    let arrastrandoId = null;
    main.querySelectorAll("[data-image-id]").forEach((el) => {
      el.addEventListener("dragstart", () => { arrastrandoId = Number(el.dataset.imageId); el.classList.add("opacity-40"); });
      el.addEventListener("dragend", () => el.classList.remove("opacity-40"));
      el.addEventListener("dragover", (e) => e.preventDefault());
      el.addEventListener("drop", async (e) => {
        e.preventDefault();
        const destinoId = Number(el.dataset.imageId);
        if (arrastrandoId === null || arrastrandoId === destinoId) return;
        const idsActuales = (row.imagenes || []).map((img) => img.id);
        const sinArrastrada = idsActuales.filter((id) => id !== arrastrandoId);
        const indiceDestino = sinArrastrada.indexOf(destinoId);
        sinArrastrada.splice(indiceDestino, 0, arrastrandoId);
        const res = await LC.backendApi.reordenarImagenesProducto(row.id, sinArrastrada);
        if (!res.ok) {
          toast("error", res.error.mensaje);
          return;
        }
        onCambio();
      });
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
            <div>
              <p class="stat-label">Stock</p>
              <p class="text-lg font-semibold mt-1">${row.stockQuantity ?? "Sin registrar"}</p>
              <button id="detail-editar-stock" class="text-xs text-indigo-600 dark:text-indigo-400 hover:underline mt-0.5">${row.stockQuantity == null ? "Agregar stock" : "Editar"}</button>
            </div>
            <div>
              <p class="stat-label">Unidades para Mercado Libre</p>
              <p class="text-lg font-semibold mt-1">${row.marketplaceStock ?? "Sin definir"}</p>
              <button id="detail-editar-stock-ml" class="text-xs text-indigo-600 dark:text-indigo-400 hover:underline mt-0.5">${row.marketplaceStock == null ? "Definir" : "Editar"}</button>
            </div>
            <div><p class="stat-label">Categoría</p><p class="text-lg font-semibold mt-1">${escapeHtml(row.categoria || "—")}</p></div>
            <div><p class="stat-label">Creado</p><p class="text-lg font-semibold mt-1">${formatDate(creado)}</p></div>
          </div>
        </div>

        ${renderRentabilidadDetalle(row, rentabilidad)}

        ${renderImagenesDetalle(row)}

        ${variantes && variantes.length ? `
        <div class="panel-card mb-5">
          <h3 class="panel-title mb-3">Variantes</h3>
          <div class="flex flex-wrap gap-2">
            ${variantes.map((v) => `<span class="badge badge-variable">${escapeHtml(v.color)} · ${v.stockQuantity} un.</span>`).join("")}
          </div>
        </div>` : ""}

        <div class="panel-card mb-5">
          <h3 class="panel-title mb-2">Mercado Libre</h3>
          <div id="ml-mini-decision"><p class="text-sm text-slate-400">Consultando…</p></div>
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
    const editarStockBtn = document.getElementById("detail-editar-stock");
    if (editarStockBtn) {
      editarStockBtn.addEventListener("click", () => {
        abrirEditorStock({ id: row.id, nombre: row.nombre, stock: row.stockQuantity }, () => rerenderActual());
      });
    }
    const editarStockMlBtn = document.getElementById("detail-editar-stock-ml");
    if (editarStockMlBtn) {
      editarStockMlBtn.addEventListener("click", () => {
        abrirEditorStock({ id: row.id, nombre: row.nombre, stock: row.marketplaceStock, mercadoLibre: true }, () => rerenderActual());
      });
    }
    const agregarCostoBtn = document.getElementById("detail-agregar-costo");
    if (agregarCostoBtn) {
      agregarCostoBtn.addEventListener("click", () => {
        abrirEditorCosto({ id: row.id, nombre: row.nombre, costo: rentabilidad ? rentabilidad.costo : null }, () => rerenderActual());
      });
    }
    wireImagenesDetalle(main, row, () => rerenderActual());
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
            Tu cuenta está conectada correctamente. Cuando importes tus ventas de Mercado Libre las vas a ver acá.
          </p>
          <div id="ml-devoluciones" class="mt-4"></div>
          <div id="ml-conciliacion" class="mt-4"></div>
          <div id="ml-facturas" class="mt-4"></div>
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

    const [estadoRes, resumen, productosFiltro, modo] = await Promise.all([
      LC.backendApi.fetchMercadoLibreEstado(),
      LC.dataSource.getResumenMercadoLibre(),
      LC.dataSource.getProductosVendidosEnMercadoLibre(),
      LC.dataSource.getModo(),
    ]);
    const ml = estadoRes.ok ? estadoRes.data : null;
    const esReal = modo === "real";
    mlState.page = 1;

    main.innerHTML = `
      <div class="page-wrap app-fade">
        ${renderConexionMercadoLibre(ml)}

        <div class="panel-card mb-6">
          <div class="flex items-center gap-2">
            ${esReal
              ? `<p class="text-sm text-slate-500 dark:text-slate-400">Todavía no hay sincronización real de ventas de Mercado Libre — las cifras de acá abajo reflejan eso (en cero), no son datos de ejemplo.</p>`
              : `<span class="demo-pill">Datos de demostración</span><p class="text-sm text-slate-500 dark:text-slate-400">Ventas, pedidos e ingresos de acá abajo son de ejemplo, para poder evaluar la interfaz.</p>`}
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
            <span class="text-xs text-slate-400">Últimos 30 días${esReal ? "" : " (demo)"}</span>
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
            rerenderActual();
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
        cargarDevolucionesML();
        cargarConciliacionML();
        cargarFacturasML();
      });
      cargarDevolucionesML();
      cargarConciliacionML();
      cargarFacturasML();
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
      const esReal = (await LC.dataSource.getModo()) === "real";
      slot.innerHTML = `<p class="text-sm text-slate-400 mt-2">${esReal ? "Sin ventas registradas en este período." : "Sin ventas de ejemplo en este período."}</p>`;
      return;
    }
    const maxCantidad = top[0].cantidad;
    slot.innerHTML = top.map((p, i) => rankRow(i + 1, p, maxCantidad)).join("");
  }

  // Devoluciones reales de Mercado Libre (14 de septiembre de 2026) — se
  // sincronizan al importar ventas; nunca datos del comprador.
  const DEVOLUCION_ESTADO_LABEL = {
    opened: "Devolución iniciada", shipped: "En camino de vuelta", delivered: "Entregada", closed: "Cerrada",
    not_delivered: "No entregada", cancelled: "Cancelada", failed: "Falló", expired: "Vencida",
  };
  const DEVOLUCION_DINERO_LABEL = {
    retained: "Dinero retenido por Mercado Libre", refunded: "Dinero devuelto al comprador", available: "Dinero liberado para vos",
  };

  async function cargarDevolucionesML() {
    const cont = document.getElementById("ml-devoluciones");
    if (!cont) return;
    const res = await LC.backendApi.listarDevolucionesMercadoLibre();
    if (!res.ok) {
      cont.innerHTML = `<p class="text-xs text-slate-400">No pudimos cargar las devoluciones ahora mismo.</p>`;
      return;
    }
    const filas = res.data.devoluciones;
    if (!filas.length) {
      cont.innerHTML = `<p class="text-sm font-medium mb-1">Devoluciones</p><p class="text-xs text-slate-400">Sin devoluciones registradas en Mercado Libre.</p>`;
      return;
    }
    cont.innerHTML = `
      <p class="text-sm font-medium mb-2">Devoluciones (${filas.length})</p>
      <div class="table-wrap"><table class="w-full text-sm">
        <thead><tr class="text-left border-b border-slate-200 dark:border-slate-700"><th class="px-3 py-2 font-medium">Fecha</th><th class="px-3 py-2 font-medium">Pedido</th><th class="px-3 py-2 font-medium">Devolución</th><th class="px-3 py-2 font-medium">Dinero</th></tr></thead>
        <tbody>
          ${filas.map((d) => `
            <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0">
              <td class="px-3 py-2 whitespace-nowrap">${d.fechaReclamo ? escapeHtml(new Date(d.fechaReclamo).toLocaleDateString("es-CL")) : "—"}</td>
              <td class="px-3 py-2">${escapeHtml(d.pedidoId || "—")}${d.ventaImportada ? "" : ` <span class="text-xs text-slate-400">(venta no importada)</span>`}</td>
              <td class="px-3 py-2">${escapeHtml(DEVOLUCION_ESTADO_LABEL[d.estadoDevolucion] || (d.estadoDevolucion ? d.estadoDevolucion : "Reclamo sin devolución todavía"))}</td>
              <td class="px-3 py-2">${escapeHtml(DEVOLUCION_DINERO_LABEL[d.estadoDinero] || "—")}</td>
            </tr>`).join("")}
        </tbody>
      </table></div>`;
  }

  // Conciliación de comisiones (14 de septiembre de 2026): lo que Mercado
  // Libre FACTURÓ por venta vs. la comisión que calcula Nexo. Solo datos reales.
  const CONCILIACION_ESTADO_LABEL = {
    coincide: "Coincide", diferencia: "Diferencia", sin_estimacion: "Sin cálculo de Nexo", sin_facturar: "Aún sin facturar",
  };

  async function cargarConciliacionML() {
    const cont = document.getElementById("ml-conciliacion");
    if (!cont) return;
    const res = await LC.backendApi.conciliacionComisionesMercadoLibre();
    if (!res.ok) {
      cont.innerHTML = `<p class="text-xs text-slate-400">No pudimos cargar la conciliación de comisiones ahora mismo.</p>`;
      return;
    }
    const clp = (n) => (n == null ? "—" : `$${Math.round(n).toLocaleString("es-CL")}`);
    const { resumen, pedidos } = res.data;
    if (!pedidos.length) {
      cont.innerHTML = `<p class="text-sm font-medium mb-1">Conciliación de comisiones</p><p class="text-xs text-slate-400">Sin datos suficientes: todavía no hay ventas importadas para comparar con la facturación de Mercado Libre.</p>`;
      return;
    }
    cont.innerHTML = `
      <p class="text-sm font-medium mb-1">Conciliación de comisiones</p>
      <p class="text-xs text-slate-500 dark:text-slate-400 mb-2">${resumen.ventasComparadas
        ? `En ${resumen.ventasComparadas} venta${resumen.ventasComparadas === 1 ? "" : "s"}: Mercado Libre facturó ${clp(resumen.comisionFacturada)} y Nexo calculó ${clp(resumen.comisionEstimada)} (diferencia ${clp(resumen.diferencia)}; ${resumen.ventasConDiferencia} con diferencia).`
        : "Todavía no hay ventas con facturación y cálculo de Nexo para comparar."}${resumen.ventasSinFacturar ? ` ${resumen.ventasSinFacturar} aún sin facturar.` : ""}</p>
      <div class="table-wrap"><table class="w-full text-sm">
        <thead><tr class="text-left border-b border-slate-200 dark:border-slate-700"><th class="px-3 py-2 font-medium">Fecha</th><th class="px-3 py-2 font-medium">Pedido</th><th class="px-3 py-2 font-medium">Facturado por ML</th><th class="px-3 py-2 font-medium">Calculado por Nexo</th><th class="px-3 py-2 font-medium">Diferencia</th><th class="px-3 py-2 font-medium">Estado</th></tr></thead>
        <tbody>
          ${pedidos.map((p) => `
            <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0">
              <td class="px-3 py-2 whitespace-nowrap">${escapeHtml(new Date(p.fecha).toLocaleDateString("es-CL"))}</td>
              <td class="px-3 py-2">${escapeHtml(p.pedidoId)}</td>
              <td class="px-3 py-2">${clp(p.comisionFacturada)}</td>
              <td class="px-3 py-2">${clp(p.comisionEstimada)}</td>
              <td class="px-3 py-2">${clp(p.diferencia)}</td>
              <td class="px-3 py-2"><span class="inline-flex items-center gap-1.5"><span class="dot ${p.estado === "coincide" ? "dot--green" : p.estado === "diferencia" ? "dot--red" : "dot--gray"}"></span>${escapeHtml(CONCILIACION_ESTADO_LABEL[p.estado] || p.estado)}</span></td>
            </tr>`).join("")}
        </tbody>
      </table></div>`;
  }

  // Facturas propias por venta (15 de septiembre de 2026): el dueño adjunta a
  // cada venta la factura que emitió con su proveedor autorizado por el SII.
  // Nexo no emite facturas ni guarda el archivo: lo reenvía a Mercado Libre.
  async function cargarFacturasML() {
    const cont = document.getElementById("ml-facturas");
    if (!cont) return;
    const res = await LC.backendApi.listarFacturasMercadoLibre();
    if (!res.ok) {
      cont.innerHTML = `<p class="text-xs text-slate-400">No pudimos cargar las facturas de tus ventas ahora mismo.</p>`;
      return;
    }
    const titulo = `
      <p class="text-sm font-medium mb-1">Facturas de tus ventas</p>
      <p class="text-xs text-slate-400 mb-2">Adjunta a cada venta la factura que emitiste con tu proveedor autorizado por el SII: un PDF de hasta 1 MB y, si quieres, su XML. Nexo no emite facturas. No aplica a ventas con envío Full.</p>`;
    const ventas = res.data.ventas;
    if (!ventas.length) {
      cont.innerHTML = `${titulo}<p class="text-xs text-slate-400">Sin datos suficientes: todavía no hay ventas importadas.</p>`;
      return;
    }
    cont.innerHTML = `${titulo}
      <div class="table-wrap"><table class="w-full text-sm">
        <thead><tr class="text-left border-b border-slate-200 dark:border-slate-700"><th class="px-3 py-2 font-medium">Fecha</th><th class="px-3 py-2 font-medium">Pedido</th><th class="px-3 py-2 font-medium">Factura</th><th class="px-3 py-2 font-medium"></th></tr></thead>
        <tbody>
          ${ventas.map((v) => {
            const id = escapeHtml(v.pedidoId);
            const estado = v.factura
              ? `<span class="inline-flex items-center gap-1.5"><span class="dot dot--green"></span>${escapeHtml(v.factura.archivos.join(", "))}</span>`
              : `<span class="inline-flex items-center gap-1.5"><span class="dot dot--gray"></span>Sin factura</span>`;
            const accion = v.factura
              ? `<button class="btn-secondary !py-1.5 !text-xs" data-quitar-factura="${id}">Quitar</button>`
              : `<div class="flex flex-wrap items-center gap-2">
                  <label class="text-xs">PDF <input type="file" accept="application/pdf,.pdf" data-factura-pdf="${id}" class="text-xs" /></label>
                  <label class="text-xs">XML (opcional) <input type="file" accept=".xml,application/xml,text/xml" data-factura-xml="${id}" class="text-xs" /></label>
                  <button class="btn-secondary !py-1.5 !text-xs" data-subir-factura="${id}">Subir factura</button>
                </div>`;
            return `
              <tr class="border-b border-slate-100 dark:border-slate-800 last:border-0 align-top">
                <td class="px-3 py-2 whitespace-nowrap">${escapeHtml(new Date(v.fecha).toLocaleDateString("es-CL"))}</td>
                <td class="px-3 py-2">${id}</td>
                <td class="px-3 py-2">${estado}</td>
                <td class="px-3 py-2">${accion}</td>
              </tr>`;
          }).join("")}
        </tbody>
      </table></div>`;

    cont.querySelectorAll("[data-subir-factura]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.subirFactura;
        const pdf = cont.querySelector(`[data-factura-pdf="${CSS.escape(id)}"]`).files[0];
        const xml = cont.querySelector(`[data-factura-xml="${CSS.escape(id)}"]`).files[0];
        if (!pdf) {
          toast("error", "Elige el PDF de la factura.");
          return;
        }
        btn.disabled = true;
        btn.textContent = "Subiendo…";
        const r = await LC.backendApi.subirFacturaMercadoLibre(id, pdf, xml);
        if (!r.ok) {
          btn.disabled = false;
          btn.textContent = "Subir factura";
          toast("error", r.error.mensaje);
          return;
        }
        toast("success", "Factura adjuntada a la venta en Mercado Libre.");
        cargarFacturasML();
      });
    });
    cont.querySelectorAll("[data-quitar-factura]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!window.confirm("¿Quitar la factura de esta venta en Mercado Libre?")) return;
        btn.disabled = true;
        const r = await LC.backendApi.quitarFacturaMercadoLibre(btn.dataset.quitarFactura);
        if (!r.ok) {
          btn.disabled = false;
          toast("error", r.error.mensaje);
          return;
        }
        toast("success", "Factura quitada de la venta.");
        cargarFacturasML();
      });
    });
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
      const sinFiltros = !mlState.search && mlState.filterEstado === "todos" && mlState.filterProducto === "todos";
      emptyEl.innerHTML = sinFiltros
        ? `
        <div class="empty-state-icon">${icon("box")}</div>
        <p class="empty-state-title">Todavía no hay pedidos registrados</p>
        <p class="empty-state-desc">Van a aparecer acá cuando Nexo sincronice ventas reales de Mercado Libre.</p>
      `
        : `
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
    { id: "revision", clasificaciones: ["sin_datos", "sin_stock"], titulo: "Requiere revisión", desc: "Falta información para decidir — conviene completarla." },
    // margen_bajo = no alcanza el margen mínimo configurado: es exactamente lo
    // que "¿Conviene?" marca como "no conviene", así que va en este grupo.
    { id: "no_rentable", clasificaciones: ["margen_bajo", "no_rentable"], titulo: "No conviene todavía", desc: "Con la comisión y los costos de Mercado Libre no alcanza el margen mínimo ni la ganancia neta mínima configurados — revisa el costo o el precio." },
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

  // Costo de envío REAL de Mercado Libre (14 de septiembre de 2026) — solo
  // el que Mercado Libre informa para la publicación; nunca estimado.
  function celdaEnvioMl(p) {
    if (p.envioMlFuente === "mercadolibre") {
      return `<td class="px-3 py-2.5 text-right text-xs">
        <span class="inline-flex items-center gap-1.5 font-medium"><span class="dot dot--green"></span>${formatCLP(p.costoEnvioMl)}</span>
        <p class="text-slate-400 mt-0.5">Obtenido de Mercado Libre</p>
      </td>`;
    }
    return `<td class="px-3 py-2.5 text-right text-xs" title="${escapeHtml(p.envioMlMotivo || "")}">
      <span class="inline-flex items-center gap-1.5 text-slate-500 dark:text-slate-400"><span class="dot dot--gray"></span>No disponible</span>
    </td>`;
  }

  const DECISION_COLUMNA_LABEL = { conviene: "Conviene", revisar: "Revisar", no_conviene: "No conviene", datos_insuficientes: "Faltan datos" };

  function celdaDecision(p, decisionMap) {
    // Ya publicado: el estado real reemplaza a la "decisión" de publicar; si
    // el margen quedó bajo el mínimo (ej. con el envío real), se avisa.
    if (p.publicacionMlEstado === "active" || p.publicacionMlEstado === "paused") {
      const aviso = (p.clasificacion === "margen_bajo" || p.clasificacion === "no_rentable") && p.razon
        ? `<p class="text-xs text-amber-600 dark:text-amber-400 mt-1 max-w-[220px]">${escapeHtml(p.razon)}</p>` : "";
      return `<td class="px-3 py-2.5">
        <span class="reco-badge ${p.publicacionMlEstado === "active" ? "reco-conviene" : "reco-revisar"} !text-xs !py-1">${p.publicacionMlEstado === "active" ? "Publicado" : "Pausado"}</span>
        ${aviso}
      </td>`;
    }
    const d = decisionMap && decisionMap.get(p.id);
    if (!d) return `<td class="px-3 py-2.5"><span class="text-xs text-slate-400">—</span></td>`;
    const visual = d.decision === "revisar" && d.faltantes && d.faltantes.length ? "datos_insuficientes" : d.decision;
    return `<td class="px-3 py-2.5">
      <span class="reco-badge reco-${visual} !text-xs !py-1">${DECISION_COLUMNA_LABEL[visual] || visual}</span>
      ${d.decision !== "conviene" && d.razon ? `<p class="text-xs text-slate-400 mt-1 max-w-[220px]">${escapeHtml(d.razon)}</p>` : ""}
    </td>`;
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
        <td class="px-3 py-2.5 text-right font-medium ${p.margenMercadoLibreClp != null && p.margenMercadoLibreClp < 0 ? "text-red-600 dark:text-red-400" : ""}">${p.margenMercadoLibreClp != null ? formatCLP(p.margenMercadoLibreClp) : "—"}${p.rentabilidadMlProvisional ? `<p class="text-xs font-normal text-slate-400">Provisional</p>` : ""}${p.margenTiendaClp != null ? `<p class="text-xs font-normal text-slate-500 dark:text-slate-400 whitespace-nowrap">Venta − compra: ${formatCLP(p.margenTiendaClp)}${p.margenTiendaPct != null ? ` (${p.margenTiendaPct.toFixed(1)}%)` : ""}</p>` : ""}</td>
        <td class="px-3 py-2.5 text-right">${p.margenMercadoLibrePct != null ? `${p.margenMercadoLibrePct.toFixed(1)}%` : "—"}</td>
        <td class="px-3 py-2.5 text-right text-xs text-slate-500 dark:text-slate-400">${escapeHtml(comisionMlTexto(p.comisionMlReal))}</td>
        ${celdaEnvioMl(p)}
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
          <th class="px-3 py-2 font-medium text-right">Ganancia neta ML</th>
          <th class="px-3 py-2 font-medium text-right">Margen neto ML</th>
          <th class="px-3 py-2 font-medium text-right">Comisión ML real</th>
          <th class="px-3 py-2 font-medium text-right">Costo de envío</th>
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
    const productos = [...(data.productos || [])].sort((a, b) => (b.margenMercadoLibreClp ?? -Infinity) - (a.margenMercadoLibreClp ?? -Infinity));
    // Ya publicados en Mercado Libre: sección propia, nunca como "oportunidad"
    // (caso real: el volante recién publicado aparecía en "No conviene").
    const publicados = productos.filter((p) => p.publicacionMlEstado === "active" || p.publicacionMlEstado === "paused");
    const porPublicar = productos.filter((p) => !publicados.includes(p));
    const cuentaPorPublicar = (clasificacion) => porPublicar.filter((p) => p.clasificacion === clasificacion).length;
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

    // 6 de septiembre de 2026 — Preview de publicación: mismo dato que ya
    // trae decisionPorVariante (GET /mercadolibre/decision-lote), agregado
    // acá nomás para responder de un vistazo "si publico esto en Mercado
    // Libre, ¿qué va a pasar?" — nunca un cálculo nuevo, solo un resumen
    // de lo que el motor de decisión ya calculó por producto.
    const decisiones = [...decisionPorVariante.values()];
    const previewMl = esReal && decisiones.length ? (() => {
      const listos = decisiones.filter((d) => d.decision === "conviene");
      const revision = decisiones.filter((d) => d.decision === "revisar");
      const omitidos = decisiones.filter((d) => d.decision === "no_conviene");
      const margenes = listos.map((d) => d.margenEstimadoPct).filter((m) => m != null);
      const margenPromedio = margenes.length ? margenes.reduce((a, b) => a + b, 0) / margenes.length : null;
      return { listos, revision, omitidos, margenPromedio };
    })() : null;

    main.innerHTML = `
      <div class="page-wrap app-fade">
        ${esReal ? "" : `<div class="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 px-4 py-3 mb-6 text-sm text-amber-800 dark:text-amber-200">Estás viendo datos de demostración — sube tu catálogo en "Importar catálogo" para ver tus oportunidades reales.</div>`}

        ${previewMl ? `
        <div class="panel-card mb-6">
          <h3 class="panel-title mb-1">Vista previa de publicación en Mercado Libre</h3>
          <p class="panel-subtitle mb-4">Qué pasaría si preparás una publicación para cada producto de tu catálogo, hoy.</p>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div class="stat-card"><p class="stat-label">Listos para publicar</p><p class="stat-value stat-value--sm stat-value--success">${previewMl.listos.length}</p></div>
            <div class="stat-card"><p class="stat-label">Requieren revisión</p><p class="stat-value stat-value--sm stat-value--warning">${previewMl.revision.length}</p></div>
            <div class="stat-card"><p class="stat-label">Omitidos</p><p class="stat-value stat-value--sm stat-value--danger">${previewMl.omitidos.length}</p></div>
            <div class="stat-card"><p class="stat-label">Margen promedio (listos)</p><p class="stat-value stat-value--sm">${previewMl.margenPromedio != null ? previewMl.margenPromedio.toFixed(1) + "%" : "—"}</p></div>
          </div>
        </div>` : ""}

        ${esReal && productos.length ? `
        <div class="panel-card mb-6">
          <h3 class="panel-title mb-1">Reservar stock para Mercado Libre en lote</h3>
          <p class="panel-subtitle mb-4">Sin unidades reservadas, un producto no se puede publicar. Fijá una cantidad por defecto para <strong>todos</strong> tus productos de una vez — después la ajustás por producto si hace falta.</p>
          <div class="flex flex-wrap items-end gap-3">
            <div>
              <label class="form-label" for="lote-stock-input">Unidades por producto</label>
              <input id="lote-stock-input" type="number" min="0" step="1" inputmode="numeric" class="form-input w-32" placeholder="Ej: 5" />
            </div>
            <button id="lote-stock-btn" class="btn-primary">Aplicar a todos</button>
          </div>
        </div>` : ""}

        ${
          esReal
            ? `<div class="flex flex-wrap items-center justify-between gap-3 mb-6">
                <p class="text-sm text-slate-500 dark:text-slate-400 max-w-xl">La comisión real de Mercado Libre (según la categoría y el precio de cada producto) se consulta sola al importar el catálogo y al conectar Mercado Libre. Si recién agregaste productos, podés forzarla ahora.</p>
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
          <div class="stat-card"><p class="stat-label">Buenas oportunidades</p><p class="stat-value stat-value--sm stat-value--success">${cuentaPorPublicar("rentable")}</p></div>
          <div class="stat-card"><p class="stat-label">Margen bajo</p><p class="stat-value stat-value--sm stat-value--warning">${cuentaPorPublicar("margen_bajo")}</p></div>
          <div class="stat-card"><p class="stat-label">No conviene</p><p class="stat-value stat-value--sm stat-value--danger">${cuentaPorPublicar("no_rentable")}</p></div>
          <div class="stat-card"><p class="stat-label">Ya publicados</p><p class="stat-value stat-value--sm">${publicados.length}</p></div>
        </div>

        ${publicados.length ? `
        <div class="panel-card mb-5">
          <div class="flex items-center gap-2 mb-1">
            <span class="dot dot--blue"></span>
            <h3 class="panel-title">Publicados en Mercado Libre</h3>
            <span class="text-sm text-slate-400">(${publicados.length})</span>
          </div>
          <p class="panel-subtitle mb-4">Ya están a la venta. La ganancia incluye el costo de envío real que informa Mercado Libre.</p>
          ${tablaOportunidades(publicados, decisionPorVariante)}
        </div>` : ""}

        ${
          productos.length
            ? GRUPOS_OPORTUNIDAD.map((g) => {
                const items = porPublicar.filter((p) => g.clasificaciones.includes(p.clasificacion));
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
        abrirEditorCosto(p, () => rerenderActual());
      });
    });
    main.querySelectorAll("[data-ir-configuracion]").forEach((btn) => {
      btn.addEventListener("click", () => LC.router.navigate("/configuracion"));
    });

    const loteStockBtn = document.getElementById("lote-stock-btn");
    if (loteStockBtn) {
      loteStockBtn.addEventListener("click", async () => {
        const valor = document.getElementById("lote-stock-input").value.trim();
        const cantidad = valor === "" ? null : Number(valor);
        if (cantidad !== null && (!Number.isInteger(cantidad) || cantidad < 0)) {
          toast("error", "Ingresá un número entero de 0 o más.");
          return;
        }
        loteStockBtn.disabled = true;
        const textoOrig = loteStockBtn.textContent;
        loteStockBtn.textContent = "Aplicando…";
        // variantIds=null -> todos los productos de la tienda.
        const res = await LC.backendApi.reservarStockMlEnLote(null, cantidad);
        loteStockBtn.disabled = false;
        loteStockBtn.textContent = textoOrig;
        if (!res.ok) {
          toast("error", res.error.mensaje);
          return;
        }
        toast(...mensajeStockMl(`Stock reservado en ${res.data.actualizados} producto(s).`, res.data.sincronizacionMl));
        rerenderActual();
      });
    }

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
        rerenderActual();
      });
    }
  }

  // ------------------------------------------------------------------
  // Integraciones — con qué sistemas puede conectarse la empresa. Mercado
  // Libre es UNA integración más, no el centro de la plataforma.
  // ------------------------------------------------------------------

  const INTEGRACION_ICON = { mercadolibre: "cart", excel: "upload" };
  // "desconocido" (6 de septiembre de 2026, P0-1): no pudimos consultar el
  // estado real — nunca se afirma "No conectado" sin haberlo verificado.
  const INTEGRACION_ESTADO_LABEL = { conectado: "Conectado", no_conectado: "No conectado", disponible: "Disponible", desconocido: "Estado no disponible" };
  const INTEGRACION_ESTADO_DOT = { conectado: "dot--green", no_conectado: "dot--gray", disponible: "dot--green", desconocido: "dot--amber" };
  const INTEGRACION_CTA = { conectado: "Ver detalles", no_conectado: "Conectar", disponible: "Usar ahora", desconocido: "Ver detalles" };

  async function renderIntegraciones(main) {
    const data = await LC.dataSource.getIntegraciones();
    main.innerHTML = `
      <div class="page-wrap app-fade">
        <p class="text-sm text-slate-500 dark:text-slate-400 mb-6 max-w-2xl">Estas son las integraciones con las que tu empresa puede conectarse hoy.</p>
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
              ${i.ruta ? `<button data-nav="${i.ruta}" class="btn-secondary">${INTEGRACION_CTA[i.estado]}</button>` : `<span class="btn-disabled">No disponible</span>`}
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

  const ESTADO_SUSCRIPCION_LABEL = { trialing: "Prueba gratuita", active: "Activa", past_due: "Pago pendiente", canceled: "Cancelada", expired: "Vencida" };
  const CICLO_LABEL = { mensual: "mensual", anual: "anual" };

  // Motivo corto que manda /api/pagos/callback (?pago=...) -> texto humano
  // — mismo criterio que RAZON_ERROR_ML: nunca un detalle técnico acá.
  const MENSAJE_PAGO = {
    procesando: { tono: "info", texto: "Estamos confirmando tu pago con Mercado Pago — puede tardar unos segundos. Esta pantalla se actualiza sola." },
    rechazado: { tono: "error", texto: "El pago no se completó. Podés intentar de nuevo cuando quieras." },
  };

  let cicloElegido = "mensual";

  function renderTarjetaPlanPago(p, sus, ciclo) {
    const esActual = sus.plan.id === p.codigo && sus.cicloFacturacion === ciclo && sus.estado && sus.estado !== "canceled";
    const precio = ciclo === "mensual" ? p.precioMensualClp : p.precioAnualClp;
    const sinPrecio = precio == null;
    return `
      <div class="plan-card ${esActual ? "plan-current" : ""}">
        <div>
          <div class="flex items-center justify-between">
            <h4 class="text-base font-semibold">${escapeHtml(p.nombre)}</h4>
            ${esActual ? '<span class="badge badge-variable">Plan actual</span>' : ""}
          </div>
          <p class="text-xs text-slate-400 mt-0.5">${p.limiteProductos ? `Hasta ${p.limiteProductos.toLocaleString("es-CL")} productos` : "Sin límite fijo"}</p>
        </div>
        <p class="text-2xl font-bold">${sinPrecio ? "Precio a coordinar" : formatCLP(precio)}${sinPrecio ? "" : `<span class="text-sm font-normal text-slate-400"> / ${ciclo === "mensual" ? "mes" : "año"}</span>`}</p>
        ${ciclo === "anual" && !sinPrecio ? `<p class="text-xs text-emerald-600 dark:text-emerald-400">${p.descuentoAnualPct}% de descuento pagando el año</p>` : ""}
        <ul class="text-sm text-slate-600 dark:text-slate-300 space-y-1.5 flex-1">
          ${p.features.map((f) => `<li class="flex items-start gap-1.5"><span class="text-emerald-500">✓</span>${escapeHtml(f)}</li>`).join("")}
        </ul>
        ${esActual
          ? '<span class="btn-disabled justify-center">Plan actual</span>'
          : sinPrecio
            ? '<span class="btn-disabled justify-center">Escribinos para cotizar</span>'
            : `<button data-plan="${escapeHtml(p.codigo)}" data-ciclo="${ciclo}" class="btn-primary justify-center pagar-plan-btn">Elegir y pagar</button>`}
      </div>
    `;
  }

  async function renderSuscripcion(main) {
    const url = new URL(window.location.href);
    const pagoParam = url.searchParams.get("pago");
    if (pagoParam) {
      const m = MENSAJE_PAGO[pagoParam];
      if (m) toast(m.tono, m.texto);
      url.searchParams.delete("pago");
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }

    const sus = await LC.dataSource.getSuscripcion();
    const planesPago = sus.real ? await (async () => {
      const res = await LC.backendApi.fetchPlanesPago();
      return res.ok ? res.data : null;
    })() : null;
    const pct = sus.plan.limite ? Math.min(100, Math.round((sus.productosUtilizados / sus.plan.limite) * 100)) : 0;
    const barClass = pct >= 90 ? "progress-danger" : pct >= 70 ? "progress-warn" : "";
    const pctPub = sus.real && sus.plan.limitePublicaciones
      ? Math.min(100, Math.round((sus.publicacionesUtilizadas / sus.plan.limitePublicaciones) * 100)) : 0;
    const barClassPub = pctPub >= 90 ? "progress-danger" : pctPub >= 70 ? "progress-warn" : "";
    const esPagoReal = sus.real && !!sus.cicloFacturacion; // hay al menos un pago real confirmado alguna vez

    main.innerHTML = `
      <div class="page-wrap app-fade">
        <div class="panel-card mb-6">
          <div class="flex flex-wrap items-start justify-between gap-4 mb-5">
            <div>
              <p class="stat-label">Plan actual</p>
              <p class="text-2xl font-bold mt-1">${escapeHtml(sus.plan.nombre)}</p>
              <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">
                ${escapeHtml(sus.plan.precio)}${sus.real ? "" : " / mes"}
                ${sus.real && sus.estado ? ` · ${escapeHtml(ESTADO_SUSCRIPCION_LABEL[sus.estado] || sus.estado)}` : ""}
                ${sus.real && sus.cicloFacturacion ? ` · Facturación ${CICLO_LABEL[sus.cicloFacturacion] || sus.cicloFacturacion}` : ""}
                ${sus.fechaRenovacion ? ` · Próxima renovación: ${formatDate(sus.fechaRenovacion)}` : ""}
              </p>
            </div>
            ${sus.real
              ? (esPagoReal && sus.estado !== "canceled" ? '<button id="cancelar-suscripcion-btn" class="btn-secondary btn-secondary--danger">Cancelar suscripción</button>' : "")
              : '<button id="manage-sub-btn" class="btn-secondary">Administrar suscripción</button>'}
          </div>

          <div>
            <div class="flex items-center justify-between text-sm mb-1.5">
              <span class="text-slate-500 dark:text-slate-400">Productos</span>
              <span class="font-medium">${sus.productosUtilizados} / ${sus.plan.limite ?? "∞"} <span class="text-slate-400">(${pct}%)</span></span>
            </div>
            <div class="progress-track"><div class="progress-fill ${barClass}" style="width:${pct}%"></div></div>
          </div>
          ${sus.real ? `
          <div class="mt-4">
            <div class="flex items-center justify-between text-sm mb-1.5">
              <span class="text-slate-500 dark:text-slate-400">Publicaciones</span>
              <span class="font-medium">${sus.publicacionesUtilizadas} / ${sus.plan.limitePublicaciones ?? "∞"} <span class="text-slate-400">(${pctPub}%)</span></span>
            </div>
            <div class="progress-track"><div class="progress-fill ${barClassPub}" style="width:${pctPub}%"></div></div>
          </div>` : ""}
        </div>

        ${sus.real ? `
        <div class="panel-card">
          <div class="flex flex-wrap items-center justify-between gap-3 mb-1">
            <h3 class="panel-title">Cambiar de plan</h3>
            ${planesPago && planesPago.length ? `
            <div class="chart-tabs" id="ciclo-facturacion-tabs">
              <button data-ciclo="mensual" class="chart-tab ${cicloElegido === "mensual" ? "is-active" : ""}">Mensual</button>
              <button data-ciclo="anual" class="chart-tab ${cicloElegido === "anual" ? "is-active" : ""}">Anual (${planesPago[0] ? planesPago[0].descuentoAnualPct : 15}% off)</button>
            </div>` : ""}
          </div>
          <p class="panel-subtitle mb-4">El pago se hace en el checkout real de Mercado Pago — Nexo nunca ve el número de tu tarjeta.</p>
          ${planesPago && planesPago.length ? `
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4" id="planes-pago-grid">
            ${planesPago.map((p) => renderTarjetaPlanPago(p, sus, cicloElegido)).join("")}
          </div>
          ` : `<p class="text-sm text-slate-500 dark:text-slate-400">No pudimos cargar los planes disponibles ahora mismo.</p>`}
        </div>
        ` : `
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
        `}
      </div>
    `;

    const manageBtn = document.getElementById("manage-sub-btn");
    if (manageBtn) {
      manageBtn.addEventListener("click", () => {
        infoModal("Administrar suscripción", "Esto es una vista de demostración (sin conexión al backend real) — no hay ningún pago que administrar acá. Con el backend real conectado, esta pantalla deja elegir un plan y pagarlo de verdad con Mercado Pago.");
      });
    }

    main.querySelectorAll("#ciclo-facturacion-tabs [data-ciclo]").forEach((btn) => {
      btn.addEventListener("click", () => {
        cicloElegido = btn.dataset.ciclo;
        rerenderActual();
      });
    });

    main.querySelectorAll(".pagar-plan-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const planCode = btn.dataset.plan;
        const ciclo = btn.dataset.ciclo;
        const plan = planesPago.find((p) => p.codigo === planCode);
        const precio = ciclo === "mensual" ? plan.precioMensualClp : plan.precioAnualClp;
        openModal({
          title: "Confirmar plan",
          body: `<p>Vas a pagar <strong>${formatCLP(precio)}</strong> (${CICLO_LABEL[ciclo]}) por <strong>${escapeHtml(plan.nombre)}</strong>. Vas a completar el pago en el checkout real de Mercado Pago — Nexo nunca ve tu tarjeta.</p>`,
          primaryLabel: "Ir a pagar",
          secondaryLabel: "Cancelar",
          onPrimary: async () => {
            const res = await LC.backendApi.iniciarPago(planCode, ciclo);
            if (!res.ok) {
              toast("error", res.error.mensaje);
              return;
            }
            // Navegación real de página completa — es Mercado Pago quien
            // tiene que mostrar su propio checkout, nunca algo con fetch().
            window.location.href = res.data.checkoutUrl;
          },
        });
      });
    });

    const cancelarBtn = document.getElementById("cancelar-suscripcion-btn");
    if (cancelarBtn) {
      cancelarBtn.addEventListener("click", () => {
        openModal({
          title: "¿Cancelar tu suscripción?",
          body: `<p>${sus.cicloFacturacion === "mensual" ? "Mercado Pago va a dejar de cobrar tu tarjeta automáticamente cada mes." : "No se te va a volver a cobrar cuando termine el período ya pagado."} Vas a poder volver a activar un plan cuando quieras.</p>`,
          primaryLabel: "Sí, cancelar",
          secondaryLabel: "Volver",
          onPrimary: async () => {
            const res = await LC.backendApi.cancelarSuscripcionPago();
            if (!res.ok) {
              toast("error", res.error.mensaje);
              return;
            }
            toast("info", "Suscripción cancelada.");
            rerenderActual();
          },
        });
      });
    }

    main.querySelectorAll(".choose-plan-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const planId = btn.dataset.plan;
        const plan = LC.demoData.plans.find((p) => p.id === planId);
        openModal({
          title: "Cambiar de plan",
          body: `<p>¿Quieres cambiar tu plan de demostración a <strong>${escapeHtml(plan.nombre)}</strong>? Esto es solo para probar la interfaz — no hay backend real conectado en este modo. Con el backend real conectado, el cambio de plan se paga de verdad con Mercado Pago.</p>`,
          primaryLabel: "Cambiar plan (demo)",
          secondaryLabel: "Cancelar",
          onPrimary: () => {
            LC.settings.setCurrentPlanId(planId);
            toast("success", `Plan actualizado a ${plan.nombre} (demo).`);
            rerenderActual();
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
    // 13 de septiembre de 2026 — nombre de empresa y de tienda salen del
    // backend (GET /api/configuracion/general), ya no del localStorage: el
    // "Nombre de la tienda" era una etiqueta local desconectada del nombre
    // real de la empresa. En modo demostración se usa lo que ya hay en
    // pantalla, que es lo unico disponible sin backend.
    let general = { companyName: nombreEmpresaActiva(session) || "", storeName: settings.storeName || "" };
    if (await LC.dataSource.getModo() === "real") {
      const res = await LC.backendApi.obtenerConfiguracionCanales();
      if (res.ok) canalMl = res.data.find((c) => c.channel === "mercadolibre") || {};
      const resGeneral = await LC.backendApi.obtenerDatosGenerales();
      if (resGeneral.ok) general = resGeneral.data;
    }

    main.innerHTML = `
      <div class="page-wrap app-fade max-w-3xl space-y-5">

        <div class="panel-card">
          <h3 class="panel-title mb-1">General</h3>
          <p class="panel-subtitle mb-4">Información básica de tu negocio.</p>
          <div class="space-y-3">
            <div>
              <label class="form-label" for="cfg-empresa">Empresa</label>
              <input id="cfg-empresa" type="text" value="${escapeHtml(general.companyName)}" class="form-input" maxlength="255" />
              <p class="text-xs text-slate-400 mt-1">El nombre real de tu empresa en Nexo. Se ve en el panel y en tus publicaciones.</p>
            </div>
            <div>
              <label class="form-label" for="cfg-store">Nombre de la tienda</label>
              <input id="cfg-store" type="text" value="${escapeHtml(general.storeName)}" class="form-input" maxlength="255" />
              <p class="text-xs text-slate-400 mt-1">Opcional, si tu tienda se llama distinto que la empresa.</p>
            </div>
            <div>
              <label class="form-label">Email</label>
              <p class="form-input flex items-center text-slate-500 dark:text-slate-400">${escapeHtml(session.email)}</p>
              <p class="text-xs text-slate-400 mt-1">Es el email con el que inicias sesión. Para cambiarlo, escribinos desde Ayuda y soporte.</p>
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
              <p class="text-xs text-slate-400 mt-1">Valor de respaldo — se usa solo si abajo elegís "Comparar ambas" o si un producto todavía no tiene su comisión real consultada.</p>
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
              <input id="cfg-ml-margen-minimo" type="number" min="0" step="0.1" class="form-input" value="${canalMl.minMarginPct ?? (canalMl.channel ? "" : 15)}" />
            </div>
            <div>
              <label class="form-label">Ganancia neta mínima por unidad ($)</label>
              <input id="cfg-ml-ganancia-minima" type="number" min="0" step="1" class="form-input" value="${canalMl.minProfitClp ?? (canalMl.channel ? "" : 3000)}" />
              <p class="text-xs text-slate-400 mt-1">Un producto conviene si alcanza el margen mínimo (%) <strong>o</strong> esta ganancia en pesos. Por defecto: 15 % y $3.000. Vacío = ese mínimo no se exige.</p>
            </div>
            <div class="sm:col-span-2">
              <label class="form-label">Comisión real por producto</label>
              <select id="cfg-ml-listing-pref" class="form-input">
                <option value="" ${!canalMl.listingTypePref ? "selected" : ""}>Comparar ambas (usar la comisión de respaldo de arriba para calcular márgenes)</option>
                <option value="classic" ${canalMl.listingTypePref === "classic" ? "selected" : ""}>Usar Clásica — la comisión real de cada producto, según su categoría y precio</option>
                <option value="premium" ${canalMl.listingTypePref === "premium" ? "selected" : ""}>Usar Premium — la comisión real de cada producto, según su categoría y precio</option>
              </select>
              <p class="text-xs text-slate-400 mt-1">La comisión de Mercado Libre varía por producto (categoría, precio y tipo de publicación) — elegí acá cuál usar para calcular el margen y la decisión de "¿conviene publicar?" de cada producto, en vez de la comisión de respaldo de arriba. Necesita haber corrido "Actualizar comisiones reales de Mercado Libre" (pantalla Oportunidades) al menos una vez para cada producto.</p>
            </div>
          </div>
          <p id="cfg-ml-feedback" class="text-sm mt-2 min-h-[1.25rem]"></p>
          <button id="cfg-ml-guardar" class="btn-primary mt-2">Guardar</button>
        </div>` : ""}

        <div class="panel-card">
          <div class="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <h3 class="panel-title mb-1">Integraciones</h3>
              <p class="panel-subtitle">Mercado Libre, Excel/CSV y Google Sheets.</p>
            </div>
            <button data-nav="/integraciones" class="btn-secondary shrink-0">Ver integraciones</button>
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

    document.getElementById("cfg-general-save").addEventListener("click", async () => {
      const btn = document.getElementById("cfg-general-save");
      const companyName = document.getElementById("cfg-empresa").value.trim();
      if (!companyName) {
        toast("error", "El nombre de la empresa no puede quedar vacío.");
        return;
      }
      btn.disabled = true;
      const textoOriginal = btn.textContent;
      btn.textContent = "Guardando…";
      const res = await LC.backendApi.guardarDatosGenerales({
        companyName,
        storeName: document.getElementById("cfg-store").value.trim(),
      });
      btn.disabled = false;
      btn.textContent = textoOriginal;
      if (!res.ok) {
        toast("error", res.error.mensaje);
        return;
      }
      toast("success", "Datos guardados.");
      // El nombre de la empresa se ve en la barra lateral y en el header:
      // se rehidrata la sesión para que cambie en toda la aplicación, no
      // solo en esta pantalla.
      await LC.auth.hydrate();
      updateUserHeader();
      rerenderActual();
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
          listing_type_pref: document.getElementById("cfg-ml-listing-pref").value || null,
          target_margin_pct: num("cfg-ml-margen-objetivo"),
          min_margin_pct: num("cfg-ml-margen-minimo"),
          min_profit_clp: num("cfg-ml-ganancia-minima"),
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
        rerenderActual();
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

    document.getElementById("cfg-change-password").addEventListener("click", abrirCambioDePassword);
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
