<?php
/**
 * Genera una clave de la API REST de WooCommerce con permisos de SOLO
 * LECTURA para un usuario administrador, y la imprime en pantalla.
 *
 * Uso (parado en esta misma carpeta):
 *   wp eval-file create-api-key.php
 *
 * IMPORTANTE: copia el Consumer Key y Consumer Secret que se imprimen a tu
 * archivo .env (WOOCOMMERCE_CONSUMER_KEY / WOOCOMMERCE_CONSUMER_SECRET).
 * No quedan guardados en ningún archivo del proyecto, y WooCommerce no
 * vuelve a mostrar el Consumer Secret una vez generado — si lo pierdes,
 * simplemente vuelve a correr este script para generar una clave nueva
 * (las claves viejas se pueden borrar después desde WooCommerce → Ajustes
 * → Avanzado → API REST).
 */

global $wpdb;

$user = get_user_by( 'login', 'admin' );
if ( ! $user ) {
	$admins = get_users( array( 'role' => 'administrator', 'number' => 1 ) );
	$user   = $admins ? $admins[0] : null;
}
if ( ! $user ) {
	WP_CLI::error( 'No se encontró ningún usuario administrador en este sitio.' );
}

if ( ! function_exists( 'wc_rand_hash' ) || ! function_exists( 'wc_api_hash' ) ) {
	WP_CLI::error( 'WooCommerce no está activo en este sitio (faltan wc_rand_hash/wc_api_hash).' );
}

$consumer_key    = 'ck_' . wc_rand_hash();
$consumer_secret = 'cs_' . wc_rand_hash();

$wpdb->insert(
	$wpdb->prefix . 'woocommerce_api_keys',
	array(
		'user_id'         => $user->ID,
		'description'     => 'Auditoria de solo lectura (entorno de prueba)',
		'permissions'     => 'read',
		'consumer_key'    => wc_api_hash( $consumer_key ),
		'consumer_secret' => $consumer_secret,
		'truncated_key'   => substr( $consumer_key, -7 ),
	),
	array( '%d', '%s', '%s', '%s', '%s', '%s' )
);

WP_CLI::success( 'Clave de API creada con permisos de SOLO LECTURA (permissions=read).' );
WP_CLI::line( '' );
WP_CLI::line( 'WOOCOMMERCE_CONSUMER_KEY=' . $consumer_key );
WP_CLI::line( 'WOOCOMMERCE_CONSUMER_SECRET=' . $consumer_secret );
WP_CLI::line( '' );
WP_CLI::line( 'Copia esas dos líneas a tu archivo .env (scripts/woocommerce-audit/.env) — no se guardan en ningún otro lugar.' );
