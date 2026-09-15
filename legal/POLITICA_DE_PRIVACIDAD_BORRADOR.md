# Política de Privacidad de Nexo — BORRADOR

> **BORRADOR PARA REVISIÓN LEGAL. NO PUBLICAR TAL CUAL.**
> Redactado el 15 de septiembre de 2026 describiendo lo que el código de Nexo guarda hoy.
> Quien lo redactó no es abogado. Un abogado en Chile debe revisarlo frente a la Ley 19.628
> y a la Ley 21.719 (que entra en vigencia en diciembre de 2026) y completar todo lo que
> aparece entre `[CORCHETES]`. Si el código cambia lo que se guarda, este texto debe
> actualizarse.

**Última actualización:** [FECHA DE PUBLICACIÓN]

## 1. Responsable

[RAZÓN SOCIAL], RUT [RUT], domicilio [DOMICILIO], Chile. Contacto para temas de datos
personales: [CORREO DE PRIVACIDAD].

## 2. Qué datos tratamos

### Datos de tu cuenta
- Nombre, correo electrónico y contraseña. La contraseña se guarda solo como hash: nadie
  en Nexo puede leerla.
- Nombre de tu empresa y de tu tienda, y tu configuración (costos, márgenes, avisos).

### Datos de tu negocio
- Catálogo: productos, SKU, precios, costos, stock, categorías y descripciones.
- Imágenes de productos que subes, guardadas en los servidores de Nexo.
- Solicitudes de soporte que nos envías y nuestras respuestas.

### Datos de Mercado Libre (solo si conectas tu cuenta)
- Identificador, alias (nickname) y país de tu cuenta vendedora.
- Credenciales de acceso (tokens OAuth), guardadas cifradas.
- Publicaciones, stock, costos de envío y comisiones de tus productos.
- Ventas: número de pedido, fecha, productos, cantidades, montos y comisión.
- Devoluciones: estado de la devolución y del dinero.
- Cargos que Mercado Libre te facturó por venta.
- Facturas que adjuntas a tus ventas: solo guardamos el nombre del archivo y el
  identificador que devuelve Mercado Libre. El archivo se envía a Mercado Libre y no queda
  guardado en Nexo.

**No guardamos datos personales de tus compradores** (nombre, alias, dirección, correo o
teléfono), aunque Mercado Libre los incluya en sus respuestas.

### Datos de Google Sheets (solo si conectas tu cuenta)
- Credenciales de acceso de solo lectura a hojas de cálculo, guardadas cifradas. Solo
  leemos las hojas que eliges importar.

### Datos de pago
- Identificadores de tu suscripción y de tus pagos en Mercado Pago, y fechas de pago.
  **No guardamos datos de tarjetas**: el pago lo procesa Mercado Pago.

### Datos técnicos y de seguridad
- Una cookie de sesión (HttpOnly) para mantenerte conectado: dura 24 horas, o 30 días si
  marcas "Recordarme". En la base de datos solo se guarda un hash de esa sesión.
- Para frenar intentos de acceso no autorizados, contamos los intentos fallidos de inicio de
  sesión por correo y por dirección IP durante 15 minutos. Ese conteo vive solo en memoria
  del servidor y no se guarda en la base de datos.
- Registros de sincronizaciones con Mercado Libre y de acciones de los administradores de
  Nexo (por ejemplo, cuándo entraron a una cuenta en modo soporte).
- Tu navegador guarda preferencias de visualización (`localStorage`).

## 3. Para qué los usamos

- Prestar el servicio: catálogo, rentabilidad, publicaciones, stock, ventas, devoluciones,
  conciliación de comisiones y facturas.
- Cobrar la suscripción y avisarte por correo antes de un vencimiento.
- Dar soporte y resolver problemas.
- Proteger la seguridad del servicio.
- Ver métricas de uso de la plataforma para administrarla.

No vendemos tus datos ni los usamos para publicidad de terceros.

## 4. Quién más accede

### Equipo de Nexo
Los administradores de Nexo pueden ver métricas y el estado de tu empresa, y entrar a tu
cuenta en **modo soporte** para ayudarte. Cada ingreso queda registrado y se muestra un aviso
visible mientras dura. No es correcto decir que los administradores solo ven números
agregados: en modo soporte ven tu cuenta como la ves tú.

### Proveedores que tratan datos por encargo de Nexo
- Alojamiento del backend: Render [CONFIRMAR región al contratar].
- Base de datos: Supabase (Postgres) [CONFIRMAR región al contratar].
- Envío de correos: Resend.

Algunos de estos proveedores pueden estar fuera de Chile (por ejemplo, en Estados Unidos),
lo que implica una transferencia internacional de datos. [ABOGADO: revisar garantías
exigidas por la Ley 21.719.]

### Servicios que conectas tú
Mercado Libre, Mercado Pago y Google reciben la información necesaria para las acciones que
autorizas (por ejemplo, publicar un producto o importar una hoja). Cada uno trata los datos
según su propia política de privacidad.

## 5. Seguridad

Usamos conexiones cifradas (HTTPS), contraseñas guardadas como hash, tokens de terceros
cifrados, separación estricta de los datos de cada empresa y límite de intentos de inicio de
sesión. Ningún sistema es infalible; si ocurre un incidente que afecte tus datos, te
avisaremos según lo exija la ley.

## 6. Cuánto tiempo los guardamos

Mientras tu cuenta esté activa. [DEFINIR plazo de conservación después de terminar el
servicio y qué se conserva por obligaciones legales o tributarias.]

## 7. Tus derechos

Puedes pedir acceso, rectificación, supresión, oposición, portabilidad y bloqueo de tus datos
personales escribiendo a [CORREO DE PRIVACIDAD]. Responderemos en [PLAZO LEGAL].

Desde la aplicación puedes, además:
- editar los datos de tu empresa y tu configuración;
- desconectar Mercado Libre y Google Sheets, lo que borra las credenciales guardadas;
- eliminar productos e imágenes.

Hoy la eliminación completa de una cuenta se hace a pedido, escribiendo al correo indicado.

Si consideras que no atendimos tu solicitud, puedes reclamar ante la autoridad competente
[ABOGADO: indicar la Agencia de Protección de Datos Personales cuando corresponda].

## 8. Cambios a esta política

Podemos actualizar esta política. Te avisaremos de cambios relevantes con [PLAZO] de
anticipación por correo o dentro de la plataforma.
