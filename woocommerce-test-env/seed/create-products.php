<?php
/**
 * Crea los 20 productos de prueba definidos en products.json (categorías,
 * imágenes y meta_data incluidos).
 *
 * Pensado para ejecutarse con WP-CLI en CUALQUIER entorno (LocalWP → "Open
 * Site Shell", el servicio wpcli de docker-compose.yml si alguna vez se usa
 * en un entorno con acceso a los registros de contenedores, o cualquier
 * otro WordPress con WP-CLI) — no depende de Docker ni de ninguna
 * herramienta en particular, solo de WP-CLI + WooCommerce activo.
 *
 * Uso (parado en esta misma carpeta):
 *   wp eval-file create-products.php
 *
 * Es idempotente: si se corre más de una vez, no duplica productos que ya
 * hayan sido creados por este mismo script (los identifica por nombre +
 * meta _lc_test_case).
 *
 * No se conecta a ningún WooCommerce real ni escribe fuera de este sitio.
 */

if ( ! class_exists( 'WooCommerce' ) ) {
	WP_CLI::error( 'WooCommerce no está activo en este sitio. Actívalo primero (wp plugin activate woocommerce).' );
}

$base_dir   = __DIR__;
$json_path  = $base_dir . '/products.json';
$images_dir = $base_dir . '/images';

if ( ! file_exists( $json_path ) ) {
	WP_CLI::error( "No se encontró $json_path" );
}

$data = json_decode( file_get_contents( $json_path ), true );
if ( ! $data || empty( $data['products'] ) ) {
	WP_CLI::error( 'products.json no tiene el formato esperado.' );
}

/**
 * Busca una categoría de producto por nombre o la crea si no existe.
 */
function lc_get_or_create_category( $name ) {
	$term = get_term_by( 'name', $name, 'product_cat' );
	if ( $term ) {
		return (int) $term->term_id;
	}
	$result = wp_insert_term( $name, 'product_cat' );
	if ( is_wp_error( $result ) ) {
		WP_CLI::warning( "No se pudo crear la categoría '$name': " . $result->get_error_message() );
		return 0;
	}
	return (int) $result['term_id'];
}

/**
 * Sube (o reutiliza, si ya se subió antes) una imagen local como adjunto de
 * WordPress y devuelve su attachment ID.
 */
function lc_get_or_upload_image( $filename, $images_dir, &$cache ) {
	if ( isset( $cache[ $filename ] ) ) {
		return $cache[ $filename ];
	}
	$path = $images_dir . '/' . $filename;
	if ( ! file_exists( $path ) ) {
		WP_CLI::warning( "No se encontró la imagen $path" );
		return 0;
	}

	$title    = sanitize_file_name( $filename );
	$existing = get_page_by_title( $title, OBJECT, 'attachment' );
	if ( $existing ) {
		$cache[ $filename ] = (int) $existing->ID;
		return (int) $existing->ID;
	}

	$filetype = wp_check_filetype( basename( $path ), null );
	$contents = file_get_contents( $path );
	$upload   = wp_upload_bits( basename( $path ), null, $contents );
	if ( ! empty( $upload['error'] ) ) {
		WP_CLI::warning( "No se pudo subir $filename: " . $upload['error'] );
		return 0;
	}

	$attachment_id = wp_insert_attachment(
		array(
			'post_mime_type' => $filetype['type'],
			'post_title'     => $title,
			'post_content'   => '',
			'post_status'    => 'inherit',
		),
		$upload['file']
	);
	require_once ABSPATH . 'wp-admin/includes/image.php';
	$attach_data = wp_generate_attachment_metadata( $attachment_id, $upload['file'] );
	wp_update_attachment_metadata( $attachment_id, $attach_data );

	$cache[ $filename ] = $attachment_id;
	return $attachment_id;
}

$image_cache = array();
$created     = array();
$skipped     = array();

foreach ( $data['products'] as $p ) {
	$existing_query = new WP_Query(
		array(
			'post_type'      => 'product',
			'title'          => $p['name'],
			'posts_per_page' => -1,
			'post_status'    => 'any',
			'meta_query'     => array(
				array(
					'key'   => '_lc_test_case',
					'value' => $p['caso'],
				),
			),
		)
	);
	if ( $existing_query->have_posts() ) {
		$skipped[] = $p['name'] . ' (' . $p['caso'] . ')';
		continue;
	}

	$product = new WC_Product_Simple();
	$product->set_name( $p['name'] );
	$product->set_status( 'publish' );
	$product->set_regular_price( (string) $p['regular_price'] );
	$product->set_description( $p['description'] );

	if ( ! empty( $p['sku'] ) ) {
		$product->set_sku( $p['sku'] );
	}

	$product->set_manage_stock( (bool) $p['manage_stock'] );
	if ( $p['manage_stock'] && isset( $p['stock_quantity'] ) && null !== $p['stock_quantity'] ) {
		$product->set_stock_quantity( (int) $p['stock_quantity'] );
		$product->set_stock_status( $p['stock_quantity'] > 0 ? 'instock' : 'outofstock' );
	} else {
		$product->set_stock_status( 'instock' );
	}

	if ( ! empty( $p['category'] ) ) {
		$cat_id = lc_get_or_create_category( $p['category'] );
		if ( $cat_id ) {
			$product->set_category_ids( array( $cat_id ) );
		}
	}

	if ( ! empty( $p['images'] ) ) {
		$image_ids = array();
		foreach ( $p['images'] as $img_file ) {
			$id = lc_get_or_upload_image( $img_file, $images_dir, $image_cache );
			if ( $id ) {
				$image_ids[] = $id;
			}
		}
		if ( ! empty( $image_ids ) ) {
			$product->set_image_id( $image_ids[0] );
			if ( count( $image_ids ) > 1 ) {
				$product->set_gallery_image_ids( array_slice( $image_ids, 1 ) );
			}
		}
	}

	if ( ! empty( $p['meta_data'] ) ) {
		foreach ( $p['meta_data'] as $meta ) {
			$product->update_meta_data( $meta['key'], $meta['value'] );
		}
	}
	// Marca de trazabilidad: permite identificar (y, si hace falta, limpiar)
	// todo lo que creó este script, y hace el script idempotente.
	$product->update_meta_data( '_lc_test_case', $p['caso'] );
	$product->update_meta_data( '_lc_seed_source', 'libreria-central/woocommerce-test-env' );

	$product_id = $product->save();
	$created[]  = "$product_id\t{$p['name']}\t" . ( $p['sku'] ? $p['sku'] : '(sin SKU)' ) . "\t{$p['caso']}";
}

WP_CLI::success( count( $created ) . ' productos creados, ' . count( $skipped ) . ' ya existían (omitidos).' );
if ( $created ) {
	WP_CLI::line( "\nProductos creados (id, nombre, sku, caso de prueba):" );
	foreach ( $created as $line ) {
		WP_CLI::line( $line );
	}
}
if ( $skipped ) {
	WP_CLI::line( "\nOmitidos por ya existir (vuelve a correr con un sitio limpio si quieres recrearlos):" );
	foreach ( $skipped as $line ) {
		WP_CLI::line( "- $line" );
	}
}
