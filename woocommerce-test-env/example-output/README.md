# Nota sobre estos archivos

Los reportes en esta carpeta **no vienen de WooCommerce** — se generaron
corriendo `scripts/woocommerce-audit` contra un pequeño servidor HTTP
simulado (usado solo durante el desarrollo, en un entorno sin acceso a
Docker Hub/WordPress.org) que replica el mismo contrato de la API de
WooCommerce v3 y sirve los mismos 20 productos definidos en
`../seed/products.json`.

Sirven para que veas el formato exacto de lo que vas a obtener cuando
corras `npm run audit` contra tu propio WooCommerce de prueba en LocalWP —
los números (18 con SKU, 1 posible duplicado, 2 claves candidatas a código
de barras, etc.) deberían coincidir, porque son los mismos 20 productos.

Cuando corras la auditoría real, los reportes se escriben en
`reports/woocommerce-audit/` (esa carpeta está en `.gitignore` porque es
data regenerable, no código) — no sobrescriben esta carpeta de ejemplo.
