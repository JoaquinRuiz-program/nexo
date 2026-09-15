# QA integral — 15 de septiembre de 2026

Prueba autónoma de Nexo como equipo de QA: 4 vendedores ficticios de Mercado Libre (artículos
nuevos), 1 administrador interno de Nexo y un auditor final. Todo contra el backend y el
frontend reales de desarrollo, con datos claramente ficticios (`*@qa.nexo.local`,
empresas "(QA)"), que se **borraron al terminar** con el mismo servicio que "Eliminar cuenta".
No se tocó la cuenta real ni la conexión de Mercado Libre del dueño.

## 1. Alcance y método

| Perfil | Empresa | Catálogo | Configuración de Mercado Libre |
|---|---|---|---|
| Pyme especializada | TecnoNova (QA) | 40 productos (.xlsx), 16 casos frontera | comisión 16 %, envío $3.990 desde $19.990, mínimos 15 % o $3.000, objetivo 30 % |
| Importador / mayorista | Importadora Andes (QA) | 1.100 SKUs (.xlsx, precio mayorista y retail) | 13 %, envío $2.500, otros $350, mínimos 10 % o $1.000 |
| Retailer multimarca | UrbanMarket (QA) | 188 filas (.xlsx) con errores de usuario | 14 %, envío $4.000 desde $9.990, otros $500, mínimos 15 % o $5.000 |
| Revendedor online | SmartBuy (QA) | 11 productos (.csv con encabezados informales) | 15 %, envío $3.000, mínimos 20 % o $2.500 |
| Admin interno | qa-admin@qa.nexo.local | — | — |

- Importación con el flujo real (`/importar/analizar` → `/importar/confirmar` con el mapeo propuesto).
- Scripts contra la API real: regla de rentabilidad (1.232 productos), aislamiento (324 intentos
  cruzados + todas las rutas sin sesión), autenticación/sesiones y administrador.
- Navegador: Dashboard, Oportunidades, panel admin, "ver como empresa", refresh, URL directa.
- Suite de pruebas automáticas: 902 pasan (con las pruebas nuevas de cada bug).

## 2. Bugs encontrados y corregidos

| # | Sev. | Bug | Corrección |
|---|---|---|---|
| 1 | P1 | **Importador Excel: una fila en blanco en medio del catálogo cortaba la lectura** y los productos de abajo se perdían sin aviso (UrbanMarket perdía 3). | `spreadsheet_io.py`: las filas en blanco se saltan; después de una fila en blanco, una fila de una sola celda sigue tratándose como nota al pie. |
| 2 | P1 | **Precio recomendado con "envío desde $X"**: el envío se decidía con el precio actual. TecnoNova TN-009 ($19.980) recomendaba $22.990 "para ganar 31,8 %", pero a ese precio se paga envío y el margen real era 14,4 %. | `publicaciones.py` (`/precio-recomendado`, `/decision`, `/decision-lote`): el envío se decide con el precio recomendado. Ahora $29.990 (30,7 %). |
| 3 | P1 | **Suspender una cuenta no cortaba la sesión ya abierta** (el cliente suspendido seguía usando la app; solo se bloqueaba el login). | `deps.py`: una sesión de usuario suspendido responde 401. |
| 4 | P1 | **`GET /api/rentabilidad` daba error 500** si había un producto con costo y sin precio (SmartBuy). | `rentabilidad.py`: sin margen calculable va al final de la lista. |
| 5 | P2 | **El importador aceptaba costo o precio negativo** ("-500") como válido, inflando la ganancia; editar el costo a mano ya lo rechazaba. | `catalog_import.py`: negativo = "Costo/Precio no válido" (fila con error). |
| 6 | P2 | **Un vendedor que escribía `#/admin` veía el esqueleto del panel de administrador** con "No encontrado" (el backend ya respondía 404, sin datos). | `router.js`: vuelve a su Dashboard. |

## 3. Regla de rentabilidad

Ganancia = precio − costo − comisión − envío − otros. Conviene si la ganancia es positiva y
alcanza el margen mínimo % **o** la ganancia neta mínima $.

- **1.232 productos de las 4 empresas: 0 diferencias** entre la fórmula recalculada por fuera y
  Nexo, y 0 diferencias entre la regla y la clasificación.
- Oportunidades = decisión en lote = "¿Conviene?" por producto = Dashboard ("Convienen en
  Mercado Libre") en las 4 empresas.

| Caso frontera | Producto | Resultado de Nexo |
|---|---|---|
| Ganancia negativa | TN-005 (−$90), SB-02 (−$8,5) | No conviene ✔ |
| Ganancia = 0 | TN-003 | No conviene ✔ |
| Positiva muy pequeña | TN-004 ($10), SB-03 ($1.051) | No conviene ✔ |
| Margen exactamente igual al mínimo | TN-001 (15 %), SB-05 (20 %) | Conviene ✔ |
| Ganancia exactamente igual al mínimo | TN-002 ($3.000) | Conviene ✔ |
| Margen debajo, ganancia encima | TN-010 (10,6 %, $138.002), SB-07 | Conviene ✔ |
| Margen encima, ganancia debajo | TN-006 (20 %, $1.998) | Conviene ✔ |
| Ambos debajo | TN-007, SB-08 | No conviene ✔ |
| Costos muy altos | TN-011 (costo $250.000, precio $199.990) | No conviene ✔ |
| Costo cero | TN-012 | Conviene (84 %) ✔ |
| Decimales | TN-006 (costo 6.393,6), SB-09 (3.490,5) | Correcto ✔ |
| Precio alto | TN-010 ($1.299.990) | Correcto ✔ |
| Diferencia pequeña cambia todo | TN-008 $19.990 (paga envío, no conviene) vs TN-009 $19.980 (conviene); SB-05 vs SB-06 ($1 de costo: 20 % → 19,98 %) | Correcto ✔ |

Importadora Andes: 111 productos "parecen buenos por precio" y dejan menos de $1.000 y 10 %;
Nexo los marca "no conviene" correctamente.

## 4. Aislamiento multiempresa — sin fugas (0 P0)

- 12 pares de empresas × 27 operaciones con el ID de la otra empresa (ver, editar costo, stock,
  stock ML, código de barras, imágenes, borrar, preparar/validar/confirmar/pausar/eliminar
  publicación, precio recomendado, decisión, competencia, facturas, soporte): **todas 404**.
  Los endpoints en lote responden 200 sin tocar nada ajeno (`actualizados: 0`, `noEncontrados`).
- Los datos del producto de la otra empresa quedaron idénticos después de los intentos.
- 17 listados (productos, rentabilidad, oportunidades, decisión, dashboard, ventas, facturas,
  conciliación, devoluciones, soporte, configuración, suscripción…) con `store_id`/`storeId` en
  la URL y header `X-Store-Id` de otra empresa: se ignoran, ningún dato ajeno.
- Ventas y solicitudes de soporte ficticias por empresa: cada una ve solo las suyas.
- Todas las rutas protegidas sin sesión → 401. Cookie inventada → 401.
- Navegador: URL directa al producto de otra empresa → "Producto no encontrado"; refresh
  mantiene la empresa.

## 5. Administrador de Nexo — OK

ADMIN → TecnoNova → REFRESH → sigue en TecnoNova (aviso naranja persistente, solo productos TN)
→ intento de ver/editar un producto de UrbanMarket → 404 → cambiar a UrbanMarket → SALIR →
vuelve al panel sin datos de clientes. Además:
- No puede "ver como" la empresa de otro administrador (400) ni una inexistente (404).
- Si se le quita el rol de admin mientras mira una empresa, deja de verla al instante.
- Un vendedor recibe 404 en todo `/api/admin/*` (incluido darse rol de admin) y sigue sin serlo.
- Suspender cliente bloquea login y, desde este QA, también la sesión abierta.

## 6. Autenticación y sesiones — OK

Login correcto/incorrecto (mismo mensaje para email inexistente, no enumera), email con
mayúsculas/espacios, bloqueo tras 6 fallos (429), registro duplicado (400), contraseña corta
(422), logout revoca la sesión en el servidor, sesión expirada → 401, cookie `HttpOnly` +
`SameSite=Lax`, 24 h normal / 30 días con "Recordarme", ninguna respuesta expone token, hash ni
secretos. `Secure` está apagado en desarrollo; en producción `SESSION_COOKIE_SECURE=true`
(ya documentado en DEPLOY.md y render.yaml).

## 7. Importador

- Detección de columnas correcta en los 4 formatos, incluido el CSV informal ("Lo compré a",
  "Lo vendo a", "Cuántos tengo") y "Precio retail" sobre "Precio mayorista".
- "$12.990" y "4.500,50" se leen bien. Costo texto ("consultar") y sin nombre → error; sin
  costo o sin precio → para revisar.
- Límite del plan: Andes importó 1.000 de 1.100 con aviso `limitePlan` (100 omitidos).

## 8. Pendiente (no corregido) y observaciones

| Sev. | Hallazgo | Por qué no se corrigió |
|---|---|---|
| **P1** | **Ventas en modo real**: los paneles "Ventas Mercado Libre" (ventas del mes, pedidos, productos vendidos), el gráfico, "Productos más vendidos" y el listado de pedidos muestran $0/vacío fijo (`dataSource.js`, `RESUMEN_ML_VACIO`), aunque haya ventas importadas: el mismo Dashboard dice "Pedidos importados: 1" al lado de "Pedidos: 0". | Requiere endpoints de métricas de ventas (función nueva). Decisión del dueño antes de conectar un cliente con ventas. |
| P3 | SKU repetido en el archivo: se descartan **ambas** filas, también la original. | Conservador y avisado en la revisión; aclarar el texto si molesta. |
| P3 | Stock con texto ("diez") queda vacío con el aviso "Completa el stock al revisar", sin decir que el valor era inválido. | Informativo, no bloquea (decisión previa: el stock nunca bloquea). |
| P3 | Costo $0 → precio recomendado $990 (matemáticamente correcto, llamativo). | Comportamiento esperado. |
| — | Sin probar: OAuth real de Mercado Libre, publicar de verdad, ventas reales, pagos. | Requieren credenciales/OAuth reales. |

## 9. Veredicto del auditor

**Núcleo listo**: rentabilidad, "¿Conviene?", aislamiento multiempresa, autenticación y panel
admin se comportan correctamente con 4 perfiles distintos, después de corregir los 6 bugs.
**No listo para lanzamiento abierto** todavía: falta el deploy real (HTTPS, dominio, cookie
`Secure`), la revisión legal, y resolver el P1 de ventas antes de que un cliente con ventas
reales vea $0. Recomendación: piloto controlado con 1–3 clientes una vez hecho el deploy y
decidido el P1 de ventas.
