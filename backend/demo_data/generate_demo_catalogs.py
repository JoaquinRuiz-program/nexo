"""
Genera los 5 catálogos de prueba pedidos el 24 de agosto de 2026 para
demostrar que el importador es universal, no solo para una librería.

Cada producto trae su costo Y su precio a propósito, elegidos para que al
pasar por domain/profitability.py + domain/catalog_selection.py el
resultado sea realista y mixto: hay productos rentables, con margen bajo,
con margen NEGATIVO (se vendería más barato de lo que cuesta), sin stock
reservado, y con datos incompletos (sin descripción, sin imagen, sin
costo) — no son solo nombres de ejemplo, los números están pensados para
que el sistema tenga algo real que analizar y descartar.

Uso:
    cd backend
    python -m demo_data.generate_demo_catalogs
"""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl

OUT_DIR = Path(__file__).parent

# Cada tupla: (sku, nombre, marca, categoria, costo, precio, stock, descripcion, imagen_url, codigo_barras)
# costo=None -> "sin costo cargado" a propósito. stock=0 -> "sin stock".
# descripcion/imagen_url = "" -> "falta esa información" a propósito.

LIBRERIA = [
    ("LIB-001", "Cuaderno universitario 100 hojas cuadriculado", "Torre", "Cuadernos", 1200, 3990, 40, "Cuaderno tapa dura, cuadro grande", "https://cdn.demo.test/libreria/cuaderno-torre.png", "7801234500011"),
    ("LIB-002", "Cuaderno college 7 materias", "Torre", "Cuadernos", 2800, 6990, 15, "7 materias con separadores", "https://cdn.demo.test/libreria/cuaderno-college.png", "7801234500028"),
    ("LIB-003", "Lápiz grafito HB caja x12", "Faber-Castell", "Papelería", 900, 2990, 80, "Caja de 12 lápices HB", "https://cdn.demo.test/libreria/lapiz-hb.png", "7801234500035"),
    ("LIB-004", "Goma de borrar blanca", "Faber-Castell", "Papelería", 250, 690, 200, "", "https://cdn.demo.test/libreria/goma.png", "7801234500042"),  # margen alto, sin descripción
    ("LIB-005", "Mochila escolar reforzada", "Jansport", "Mochilas", 18000, 24990, 8, "Mochila con refuerzo lumbar, 3 compartimentos", "", "7801234500059"),  # sin imagen
    ("LIB-006", "Mochila urbana antirrobo", "Totto", "Mochilas", 22000, 21990, 5, "Con puerto USB y cierre antirrobo", "https://cdn.demo.test/libreria/mochila-totto.png", "7801234500066"),  # MARGEN NEGATIVO
    ("LIB-007", "Calculadora científica", "Casio", "Tecnología escolar", 9500, 12990, 12, "570 funciones, pantalla natural display", "https://cdn.demo.test/libreria/calc-casio.png", "7801234500073"),
    ("LIB-008", "Calculadora básica 12 dígitos", "Casio", "Tecnología escolar", 4000, 4300, 0, "Pantalla grande, energía solar", "https://cdn.demo.test/libreria/calc-basica.png", "7801234500080"),  # margen bajo Y sin stock
    ("LIB-009", "Cien años de soledad", "Sudamericana", "Libros", 6500, 12990, 20, "Edición de bolsillo, Gabriel García Márquez", "https://cdn.demo.test/libreria/cien-anos.png", "7801234500097"),
    ("LIB-010", "El principito", "Salamandra", "Libros", 3800, 7990, 30, "Edición ilustrada", "https://cdn.demo.test/libreria/principito.png", "7801234500103"),
    ("LIB-011", "Carpeta archivadora oficio", "Torre", "Oficina", 1800, 3990, 45, "Lomo 7cm, palanca metálica", "https://cdn.demo.test/libreria/carpeta.png", "7801234500110"),
    ("LIB-012", "Carpeta plástica con broche", "Torre", "Oficina", 350, 990, 100, "Tamaño carta, colores surtidos", "https://cdn.demo.test/libreria/carpeta-broche.png", "7801234500127"),
    ("LIB-013", "Set de reglas geométricas", "Maped", "Papelería", 900, 2490, 0, "Escuadra, transportador y regla 30cm", "https://cdn.demo.test/libreria/set-reglas.png", "7801234500134"),  # sin stock
    ("LIB-014", "Agenda semanal 2027", "Torre", "Agendas", None, 8990, 10, "Tapa dura, papel 80gr", "https://cdn.demo.test/libreria/agenda.png", "7801234500141"),  # sin costo
    ("LIB-015", "Diccionario escolar ilustrado", "Larousse", "Libros", 7200, 11990, 6, "", "", "7801234500158"),  # sin descripción ni imagen
]

ELECTRONICA = [
    ("ELEC-001", "Mouse inalámbrico 2.4GHz", "Logitech", "Periféricos", 5500, 8990, 60, "Sensor óptico 1600 DPI, pila incluida", "https://cdn.demo.test/electro/mouse-logitech.png", "7802345600011"),
    ("ELEC-002", "Mouse gamer RGB", "Redragon", "Periféricos", 9000, 14990, 25, "6 botones programables, iluminación RGB", "https://cdn.demo.test/electro/mouse-redragon.png", "7802345600028"),
    ("ELEC-003", "Teclado mecánico switch red", "Redragon", "Periféricos", 18000, 27990, 10, "Retroiluminado, anti-ghosting", "https://cdn.demo.test/electro/teclado-mecanico.png", "7802345600035"),
    ("ELEC-004", "Teclado membrana USB", "Logitech", "Periféricos", 6000, 6500, 3, "", "https://cdn.demo.test/electro/teclado-membrana.png", "7802345600042"),  # margen bajo, sin descripción
    ("ELEC-005", "Audífonos bluetooth over-ear", "JBL", "Audio", 22000, 34990, 18, "Cancelación de ruido, 20h de batería", "https://cdn.demo.test/electro/audifonos-jbl.png", "7802345600059"),
    ("ELEC-006", "Audífonos in-ear con cable", "Sony", "Audio", 4500, 3990, 40, "Manos libres integrado", "https://cdn.demo.test/electro/audifonos-sony.png", "7802345600066"),  # MARGEN NEGATIVO
    ("ELEC-007", "Cable USB-C a USB-C 1m", "Ugreen", "Cables", 1800, 4990, 90, "Carga rápida 60W", "https://cdn.demo.test/electro/cable-usbc.png", "7802345600073"),
    ("ELEC-008", "Cable HDMI 2.0 2m", "Ugreen", "Cables", 2500, 5990, 0, "4K a 60Hz", "https://cdn.demo.test/electro/cable-hdmi.png", "7802345600080"),  # sin stock
    ("ELEC-009", "Cargador rápido 20W USB-C", "Anker", "Cargadores", 6500, 10990, 35, "Compatible con carga rápida universal", "https://cdn.demo.test/electro/cargador-anker.png", "7802345600097"),
    ("ELEC-010", "Cargador doble puerto pared", "Genérico", "Cargadores", 2000, 2200, 50, "", "", "7802345600103"),  # margen bajo, sin descripción ni imagen
    ("ELEC-011", "Memoria USB 64GB 3.0", "Kingston", "Almacenamiento", 4200, 7990, 70, "Velocidad de lectura 100MB/s", "https://cdn.demo.test/electro/usb-kingston.png", "7802345600110"),
    ("ELEC-012", "Memoria USB 32GB 2.0", "SanDisk", "Almacenamiento", 3000, 4500, 5, "Diseño compacto retráctil", "https://cdn.demo.test/electro/usb-sandisk.png", "7802345600127"),
    ("ELEC-013", "Parlante bluetooth portátil", "JBL", "Audio", 15000, 24990, 22, "Resistente al agua IPX7, 12h batería", "https://cdn.demo.test/electro/parlante-jbl.png", "7802345600134"),
    ("ELEC-014", "Parlante mini USB", "Genérico", "Audio", None, 5990, 15, "Conexión USB, sin baterías", "https://cdn.demo.test/electro/parlante-mini.png", "7802345600141"),  # sin costo
    ("ELEC-015", "Webcam HD 1080p", "Logitech", "Periféricos", 16000, 23990, 0, "Micrófono integrado, enfoque automático", "https://cdn.demo.test/electro/webcam.png", "7802345600158"),  # sin stock
]

FERRETERIA = [
    ("FER-001", "Taladro percutor 750W", "Bosch", "Herramientas eléctricas", 32000, 45990, 6, "Incluye maletín y 2 brocas", "https://cdn.demo.test/ferre/taladro-bosch.png", "7803456700011"),
    ("FER-002", "Taladro inalámbrico 12V", "Black+Decker", "Herramientas eléctricas", 28000, 39990, 4, "Batería de litio, 2 velocidades", "https://cdn.demo.test/ferre/taladro-bd.png", "7803456700028"),
    ("FER-003", "Set destornilladores 6 piezas", "Stanley", "Herramientas manuales", 5500, 9990, 30, "Puntas plana y phillips, mango ergonómico", "https://cdn.demo.test/ferre/destornilladores.png", "7803456700035"),
    ("FER-004", "Destornillador eléctrico recargable", "Genérico", "Herramientas eléctricas", 8000, 7990, 12, "", "https://cdn.demo.test/ferre/destornillador-electrico.png", "7803456700042"),  # MARGEN NEGATIVO, sin descripción
    ("FER-005", "Set de brocas para metal 10pzs", "Bosch", "Accesorios", 4200, 7490, 25, "Acero de alta velocidad HSS", "https://cdn.demo.test/ferre/brocas-metal.png", "7803456700059"),
    ("FER-006", "Set de brocas para concreto 5pzs", "Bosch", "Accesorios", 3800, 4100, 0, "Punta de widia", "https://cdn.demo.test/ferre/brocas-concreto.png", "7803456700066"),  # margen bajo, sin stock
    ("FER-007", "Alicate universal 8 pulgadas", "Stanley", "Herramientas manuales", 3200, 5990, 40, "Mango antideslizante", "https://cdn.demo.test/ferre/alicate.png", "7803456700073"),
    ("FER-008", "Alicate de corte diagonal", "Truper", "Herramientas manuales", 2500, 4490, 18, "Acero al carbono templado", "https://cdn.demo.test/ferre/alicate-corte.png", "7803456700080"),
    ("FER-009", "Cinta métrica 5m", "Stanley", "Medición", 1800, 3490, 60, "Carcasa de goma resistente a impactos", "https://cdn.demo.test/ferre/cinta-metrica.png", "7803456700097"),
    ("FER-010", "Cinta aislante eléctrica", "3M", "Accesorios", 400, 990, 150, "", "", "7803456700103"),  # margen alto, sin descripción ni imagen
    ("FER-011", "Tornillos autorroscantes caja x100", "Genérico", "Fijaciones", None, 3990, 90, "Punta broca, 1 pulgada", "https://cdn.demo.test/ferre/tornillos.png", "7803456700110"),  # sin costo
    ("FER-012", "Nivel de burbuja 60cm", "Truper", "Medición", 4500, 4200, 20, "Estructura de aluminio", "https://cdn.demo.test/ferre/nivel.png", "7803456700127"),  # MARGEN NEGATIVO
]

# Ropa: cada producto tiene varias filas (una por talla/color) — cada fila
# es su propio SKU, sin agrupamiento automático de variantes (limitación
# conocida del importador en esta primera versión, ver catalog_import.py).
ROPA = [
    ("ROPA-001-S-AZ", "Polera básica algodón - Talla S Azul", "Rotter", "Poleras", 3200, 6990, 25, "Algodón 100%, corte regular", "https://cdn.demo.test/ropa/polera-azul.png", "7804567800011"),
    ("ROPA-001-M-AZ", "Polera básica algodón - Talla M Azul", "Rotter", "Poleras", 3200, 6990, 30, "Algodón 100%, corte regular", "https://cdn.demo.test/ropa/polera-azul.png", "7804567800028"),
    ("ROPA-001-L-AZ", "Polera básica algodón - Talla L Azul", "Rotter", "Poleras", 3200, 6990, 0, "Algodón 100%, corte regular", "https://cdn.demo.test/ropa/polera-azul.png", "7804567800035"),  # sin stock
    ("ROPA-001-M-NG", "Polera básica algodón - Talla M Negro", "Rotter", "Poleras", 3200, 6990, 18, "Algodón 100%, corte regular", "https://cdn.demo.test/ropa/polera-negra.png", "7804567800042"),
    ("ROPA-002-38", "Pantalón jeans clásico - Talla 38", "Wrangler", "Pantalones", 12000, 22990, 10, "Corte recto, denim resistente", "https://cdn.demo.test/ropa/jeans-38.png", "7804567800059"),
    ("ROPA-002-40", "Pantalón jeans clásico - Talla 40", "Wrangler", "Pantalones", 12000, 22990, 8, "Corte recto, denim resistente", "https://cdn.demo.test/ropa/jeans-40.png", "7804567800066"),
    ("ROPA-003-M", "Polerón con capucha - Talla M", "Rotter", "Polerones", 8500, 17990, 15, "Felpa interior, bolsillo canguro", "https://cdn.demo.test/ropa/poleron-m.png", "7804567800073"),
    ("ROPA-003-L", "Polerón con capucha - Talla L", "Rotter", "Polerones", 8500, 17990, 0, "Felpa interior, bolsillo canguro", "https://cdn.demo.test/ropa/poleron-l.png", "7804567800080"),  # sin stock
    ("ROPA-004-M-NG", "Chaqueta cortavientos - Talla M Negro", "The North Face", "Chaquetas", 28000, 26990, 6, "Impermeable, plegable", "https://cdn.demo.test/ropa/chaqueta-negra.png", "7804567800097"),  # MARGEN NEGATIVO
    ("ROPA-004-L-AZ", "Chaqueta cortavientos - Talla L Azul", "The North Face", "Chaquetas", 28000, 44990, 4, "Impermeable, plegable", "https://cdn.demo.test/ropa/chaqueta-azul.png", "7804567800103"),
    ("ROPA-005-40", "Zapatillas urbanas - Talla 40", "Adidas", "Calzado", 25000, 39990, 12, "Suela de goma antideslizante", "https://cdn.demo.test/ropa/zapatillas-40.png", "7804567800110"),
    ("ROPA-005-42", "Zapatillas urbanas - Talla 42", "Adidas", "Calzado", 25000, 39990, 9, "Suela de goma antideslizante", "https://cdn.demo.test/ropa/zapatillas-42.png", "7804567800127"),
    ("ROPA-006-38", "Zapatillas running - Talla 38", "Nike", "Calzado", 30000, 31500, 0, "", "", "7804567800134"),  # margen bajo, sin stock, sin descripción ni imagen
]

# Excel "desordenado" — simula un negocio que no está preparado para el
# sistema: columnas con nombres distintos, algunos datos faltantes, sin
# columna de descripción ni imagen (a propósito).
DESORDENADO_HEADERS = ["Producto", "Codigo", "Precio venta", "Existencia", "Marca", "costo compra"]
DESORDENADO_ROWS = [
    ("Set de ollas antiadherentes 5 piezas", "HOG-001", "39990", "7", "Tramontina", "24000"),
    ("Sartén antiadherente 24cm", "HOG-002", "12990", "15", "Tramontina", "7500"),
    ("Juego de cuchillos cocina", "HOG-003", "8990", "0", "Genérico", "9500"),  # MARGEN NEGATIVO y sin stock
    ("Termo acero inoxidable 1L", "HOG-004", "9990", "20", "Stanley", "5200"),
    ("Licuadora 600W", "HOG-005", "", "5", "Oster", "18000"),  # sin precio -> revisión
    ("Hervidor eléctrico 1.7L", "HOG-006", "14990", "12", "", "8000"),  # sin marca
    ("Tostadora 2 rebanadas", "HOG-007", "13990", "", "Oster", "9000"),  # sin stock informado
    ("Plancha a vapor", "HOG-008", "16990", "9", "Philips", ""),  # sin costo
    ("Batidora de mano", "HOG-009", "11990", "14", "Oster", "6500"),
    ("Cafetera de goteo", "HOG-010", "19990", "3", "Oster", "13500"),
    ("", "HOG-011", "5990", "8", "Genérico", "3000"),  # sin nombre -> bloqueante
]


# ---------------------------------------------------------------------------
# Escenarios agregados el 24 de agosto de 2026 (pivote a plataforma
# universal, segunda ronda) — cuatro comercios más, con estructuras de
# columnas realmente distintas entre sí, no solo nombres de producto
# distintos con las mismas 10 columnas de siempre.
# ---------------------------------------------------------------------------

# Escenario 6 — bazar/tienda variada. Trae "Código" (interno, de bodega) Y
# "SKU" a la vez — el mismo caso real que hizo encontrar el bug de
# detección del 24 de agosto (ver test_cuando_hay_dos_columnas_candidatas_
# gana_el_sinonimo_mas_especifico). Sin columna de categoría a propósito.
TIENDA_VARIADA_HEADERS = ["Código", "SKU", "Producto", "Marca", "Precio compra", "Precio venta", "Cantidad", "Descripción", "EAN", "Imagen"]
TIENDA_VARIADA_ROWS = [
    ("BOD-0001", "VAR-001", "Termo acero inoxidable 750ml", "Stanley", 9500, 15990, 22, "Mantiene temperatura 12 horas", "7805670900011", "https://cdn.demo.test/variada/termo.png"),
    ("BOD-0002", "VAR-002", "Set de vasos térmicos x4", "Genérico", 6000, 9990, 14, "Vidrio templado, 350ml c/u", "7805670900028", "https://cdn.demo.test/variada/vasos.png"),
    ("BOD-0003", "VAR-003", "Paraguas plegable automático", "Totto", 5200, 8990, 30, "Resistente al viento, apertura automática", "7805670900035", "https://cdn.demo.test/variada/paraguas.png"),
    ("BOD-0004", "VAR-004", "Mochila térmica para almuerzo", "Genérico", 4800, 4500, 9, "Compartimento aislado, capacidad 6L", "7805670900042", "https://cdn.demo.test/variada/mochila-termica.png"),  # margen negativo
    ("BOD-0005", "VAR-005", "Set organizadores de cocina x3", "Rubbermaid", 7200, 12990, 18, "Herméticos, aptos microondas", "7805670900059", "https://cdn.demo.test/variada/organizadores.png"),
    ("BOD-0006", "VAR-006", "Linterna LED recargable", "Genérico", 3500, 6990, 0, "USB-C, 3 modos de luz", "7805670900066", "https://cdn.demo.test/variada/linterna.png"),  # sin stock
    ("BOD-0007", "VAR-007", "Set de destapadores y utensilios bar", "Genérico", 2200, 4990, 25, "", "7805670900073", "https://cdn.demo.test/variada/utensilios-bar.png"),  # sin descripción
    ("BOD-0008", "VAR-008", "Cojín decorativo 45x45", "Genérico", None, 7990, 16, "Funda desmontable, relleno incluido", "7805670900080", "https://cdn.demo.test/variada/cojin.png"),  # sin costo
]

# Escenario 7 — comercio de cosmética/cuidado personal, con nombres de
# columna completamente distintos otra vez (ninguno coincide literal con
# los de los escenarios anteriores). Tampoco trae columna de categoría.
FORMATO_DIFERENTE_HEADERS = ["Código interno", "Nombre artículo", "Fabricante", "Costo neto", "PVP", "Existencias", "Código de barras", "Foto"]
FORMATO_DIFERENTE_ROWS = [
    ("COS-001", "Crema hidratante facial 50ml", "Nivea", 3800, 7990, 45, "7806780100011", "https://cdn.demo.test/cosmetica/crema-facial.png"),
    ("COS-002", "Protector solar FPS 50 150ml", "La Roche-Posay", 9500, 15990, 20, "7806780100028", "https://cdn.demo.test/cosmetica/protector-solar.png"),
    ("COS-003", "Shampoo anticaspa 400ml", "Head & Shoulders", 2900, 4990, 60, "7806780100035", "https://cdn.demo.test/cosmetica/shampoo.png"),
    ("COS-004", "Set de brochas de maquillaje x12", "Genérico", 8000, 6990, 12, "7806780100042", "https://cdn.demo.test/cosmetica/brochas.png"),  # margen negativo
    ("COS-005", "Perfume mujer 100ml", "Carolina Herrera", 32000, 54990, 5, "7806780100059", "https://cdn.demo.test/cosmetica/perfume.png"),
    ("COS-006", "Esmalte de uñas larga duración", "OPI", 4200, 4500, 0, "7806780100066", "https://cdn.demo.test/cosmetica/esmalte.png"),  # margen bajo y sin stock
    ("COS-007", "Jabón líquido corporal 500ml", "Dove", None, 5990, 38, "7806780100073", "https://cdn.demo.test/cosmetica/jabon.png"),  # sin costo
    ("COS-008", "Desodorante roll-on 50ml", "Rexona", 1800, 3490, 55, "7806780100080", ""),  # sin foto
]

# Escenario 8 — catálogo imperfecto de jugueteria/deportes: SKU duplicado,
# precio inválido, stock 0, costo mayor que precio, campos vacíos, nombres
# poco descriptivos, sin imagen, sin descripción — todo junto, a propósito.
IMPERFECTO_HEADERS = ["SKU", "Nombre", "Marca", "Categoría", "Costo", "Precio", "Stock", "Descripción", "Imagen", "Código de barras"]
IMPERFECTO_ROWS = [
    ("JUG-001", "Pelota de fútbol N°5", "Nike", "Deportes", 8500, 14990, 20, "Cosida a mano, uso profesional", "https://cdn.demo.test/imperfecto/pelota.png", "7807890200011"),
    ("JUG-002", "Set de pesas ajustables 10kg", "Genérico", "Deportes", 15000, 12000, 8, "Par de mancuernas regulables", "https://cdn.demo.test/imperfecto/pesas.png", "7807890200028"),  # costo > precio, deliberado
    ("JUG-003", "Bicicleta aro 20 infantil", "Oxford", "Deportes", 45000, "no disponible", 6, "Con rueditas de apoyo", "https://cdn.demo.test/imperfecto/bicicleta.png", "7807890200035"),  # precio inválido
    ("JUG-004", "Muñeca articulada 30cm", "Mattel", "Juguetes", 6500, 11990, 0, "Con accesorios incluidos", "", "7807890200042"),  # sin stock, sin imagen
    ("JUG-005", "Auto a control remoto", "Genérico", "Juguetes", 9000, 15990, 12, "", "", "7807890200059"),  # sin descripción ni imagen
    ("JUG-006", "Producto 1", "", "Juguetes", 3000, 5990, 25, "", "", ""),  # nombre poco descriptivo, sin marca/descripción/imagen/código
    ("JUG-007", "Set de bloques de construcción", "Lego", "Juguetes", 18000, 29990, 10, "150 piezas compatibles", "https://cdn.demo.test/imperfecto/bloques.png", "7807890200066"),
    ("JUG-007", "Set de bloques de construcción (duplicado de carga)", "Lego", "Juguetes", 18000, 29990, 10, "150 piezas compatibles", "https://cdn.demo.test/imperfecto/bloques.png", "7807890200066"),  # SKU duplicado a propósito
    ("JUG-008", "Patineta de madera", "Genérico", "Deportes", None, "", 0, "", "", ""),  # casi todos los campos vacíos
]

# Escenario 9 — un solo comercio con categorías radicalmente distintas en
# el mismo archivo, para demostrar que el sistema no asume ningún rubro.
MULTI_CATEGORIA_HEADERS = ["SKU", "Nombre", "Marca", "Categoría", "Costo", "Precio", "Stock", "Descripción", "Imagen", "Código de barras"]
MULTI_CATEGORIA_ROWS = [
    ("MULTI-001", "Audífonos inalámbricos deportivos", "JBL", "Electrónica", 14000, 22990, 25, "Resistentes al sudor, 8h de batería", "https://cdn.demo.test/multi/audifonos.png", "7808900300011"),
    ("MULTI-002", "Rodillo de yoga para masajes", "Genérico", "Deportes", 4500, 8990, 18, "Espuma de alta densidad", "https://cdn.demo.test/multi/rodillo.png", "7808900300028"),
    ("MULTI-003", "Set de maquillaje profesional", "Maybelline", "Cosmética", 9800, 16990, 14, "Incluye paleta de sombras y labiales", "https://cdn.demo.test/multi/maquillaje.png", "7808900300035"),
    ("MULTI-004", "Organizador de escritorio de bambú", "Genérico", "Oficina", 5200, 8990, 20, "Compartimentos para lápices y documentos", "https://cdn.demo.test/multi/organizador.png", "7808900300042"),
    ("MULTI-005", "Peluche oso 40cm", "Genérico", "Juguetes", 3800, 6990, 30, "Felpa suave, apto desde 0 meses", "https://cdn.demo.test/multi/peluche.png", "7808900300059"),
    ("MULTI-006", "Cargador solar portátil 10000mAh", "Anker", "Electrónica", 12000, 19990, 15, "Panel solar integrado, resistente al agua", "https://cdn.demo.test/multi/cargador-solar.png", "7808900300066"),
    ("MULTI-007", "Set de té gourmet x6 variedades", "Genérico", "Hogar", 6000, 5500, 22, "Cajas individuales, orgánico", "https://cdn.demo.test/multi/te-gourmet.png", "7808900300073"),  # margen negativo
    ("MULTI-008", "Guantes de boxeo 12oz", "Everlast", "Deportes", 15000, 24990, 9, "Cuero sintético, acolchado premium", "https://cdn.demo.test/multi/guantes-boxeo.png", "7808900300080"),
    ("MULTI-009", "Difusor de aromas ultrasónico", "Genérico", "Hogar", 8500, 13990, 0, "Luz LED, 300ml", "https://cdn.demo.test/multi/difusor.png", "7808900300097"),  # sin stock
    ("MULTI-010", "Silla ergonómica de oficina", "Ergohuman", "Oficina", 85000, 129990, 4, "Ajuste lumbar y de altura", "https://cdn.demo.test/multi/silla-oficina.png", "7808900300103"),
]


def _write_xlsx(path: Path, headers: list[str], rows: list[tuple]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Productos"
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    print(f"Escrito: {path} ({len(rows)} filas)")


def _write_csv(path: Path, headers: list[str], rows: list[tuple]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"Escrito: {path} ({len(rows)} filas)")


STANDARD_HEADERS = ["SKU", "Nombre", "Marca", "Categoría", "Costo", "Precio", "Stock", "Descripción", "Imagen", "Código de barras"]


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    _write_xlsx(OUT_DIR / "01-libreria.xlsx", STANDARD_HEADERS, LIBRERIA)
    _write_xlsx(OUT_DIR / "02-electronica.xlsx", STANDARD_HEADERS, ELECTRONICA)
    _write_xlsx(OUT_DIR / "03-ferreteria.xlsx", STANDARD_HEADERS, FERRETERIA)
    _write_xlsx(OUT_DIR / "04-ropa-con-variantes.xlsx", STANDARD_HEADERS, ROPA)
    _write_csv(OUT_DIR / "05-hogar-desordenado.csv", DESORDENADO_HEADERS, DESORDENADO_ROWS)
    _write_csv(OUT_DIR / "06-tienda-variada.csv", TIENDA_VARIADA_HEADERS, TIENDA_VARIADA_ROWS)
    _write_xlsx(OUT_DIR / "07-cosmetica-formato-diferente.xlsx", FORMATO_DIFERENTE_HEADERS, FORMATO_DIFERENTE_ROWS)
    _write_xlsx(OUT_DIR / "08-jugueteria-imperfecto.xlsx", IMPERFECTO_HEADERS, IMPERFECTO_ROWS)
    _write_xlsx(OUT_DIR / "09-multi-categoria.xlsx", MULTI_CATEGORIA_HEADERS, MULTI_CATEGORIA_ROWS)

    todas = [LIBRERIA, ELECTRONICA, FERRETERIA, ROPA, DESORDENADO_ROWS, TIENDA_VARIADA_ROWS, FORMATO_DIFERENTE_ROWS, IMPERFECTO_ROWS, MULTI_CATEGORIA_ROWS]
    total = sum(len(r) for r in todas)
    print(f"\nTotal: {total} filas en {len(todas)} archivos.")


if __name__ == "__main__":
    main()
