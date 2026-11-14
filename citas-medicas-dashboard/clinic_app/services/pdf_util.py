"""Generación simple de PDF (texto) sin dependencias externas."""

from datetime import datetime
from textwrap import wrap


def _escape(text):
    return (text or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_texto(titulo, lineas):
    """Devuelve bytes de un PDF A4 con texto ajustado y páginas múltiples."""
    lineas_ajustadas = []
    for linea in lineas:
        for parte in str(linea).splitlines() or [""]:
            lineas_ajustadas.extend(wrap(parte, width=85) if parte else [""])

    lineas_por_pagina = 42
    paginas = [
        lineas_ajustadas[inicio:inicio + lineas_por_pagina]
        for inicio in range(0, len(lineas_ajustadas), lineas_por_pagina)
    ] or [[]]
    cantidad_paginas = len(paginas)
    ids_pagina = [3 + 2 * indice for indice in range(cantidad_paginas)]
    ids_contenido = [identificador + 1 for identificador in ids_pagina]
    id_fuente = 3 + cantidad_paginas * 2
    objetos = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        (
            f"2 0 obj << /Type /Pages /Kids [{' '.join(f'{id_pagina} 0 R' for id_pagina in ids_pagina)}] "
            f"/Count {cantidad_paginas} >> endobj\n"
        ).encode(),
    ]

    for numero, (id_pagina, id_stream, lineas_pagina) in enumerate(zip(ids_pagina, ids_contenido, paginas), start=1):
        y = 700
        contenido = [
            "0.07 0.15 0.32 rg 0 738 595 104 re f",
            "0.83 0.65 0.25 rg 44 733 68 4 re f",
            "BT /F1 9 Tf 1 1 1 rg 44 812 Td (CLÍNICA SAN JOSÉ  ·  DOCUMENTO ELECTRÓNICO) Tj ET",
            f"BT /F1 20 Tf 1 1 1 rg 44 773 Td ({_escape(titulo)}) Tj ET",
            f"BT /F1 9 Tf 0.86 0.89 0.94 rg 360 778 Td ({datetime.now().strftime('%d/%m/%Y %H:%M')}) Tj ET",
        ]
        for linea in lineas_pagina:
            if linea.startswith("---"):
                contenido.append(f"0.83 0.65 0.25 RG 44 {y + 9} m 551 {y + 9} l S")
            else:
                contenido.append(f"BT /F1 10 Tf 0.12 0.18 0.28 rg 50 {y} Td ({_escape(linea)}) Tj ET")
            y -= 16
        contenido.extend([
            "0.88 0.90 0.93 RG 44 48 m 551 48 l S",
            f"BT /F1 8 Tf 0.40 0.45 0.53 rg 44 30 Td (Clínica San José  ·  Página {numero} de {cantidad_paginas}) Tj ET",
        ])

        stream = "\n".join(contenido).encode("cp1252", "replace")
        objetos.append(
            (
                f"{id_pagina} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Contents {id_stream} 0 R /Resources << /Font << /F1 {id_fuente} 0 R >> >> >> endobj\n"
            ).encode()
        )
        objetos.append(
            f"{id_stream} 0 obj << /Length {len(stream)} >> stream\n".encode()
            + stream
            + b"\nendstream endobj\n"
        )
    objetos.append(
        f"{id_fuente} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n".encode()
    )

    salida = b"%PDF-1.4\n"
    offsets = [0]
    for objeto in objetos:
        offsets.append(len(salida))
        salida += objeto
    xref_pos = len(salida)
    salida += f"xref\n0 {len(objetos)+1}\n".encode()
    salida += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        salida += f"{off:010d} 00000 n \n".encode()
    salida += (
        f"trailer << /Size {len(objetos)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
    ).encode()
    return salida


def pdf_tabla(titulo, columnas, filas, subtitulo=None):
    """PDF horizontal con encabezado institucional y tabla clara para exportaciones."""
    ancho, alto = 842, 595
    margen = 36
    ancho_tabla = ancho - margen * 2
    columnas = [str(columna) for columna in columnas]
    filas = [[str(valor or "").replace("\n", " ") for valor in fila] for fila in filas]
    if not columnas:
        columnas = ["Registro"]
    ancho_columna = ancho_tabla / len(columnas)
    alto_fila = 26
    subtitulos = subtitulo if isinstance(subtitulo, (list, tuple)) else [subtitulo]
    subtitulos = [str(linea)[:150] for linea in subtitulos if linea]
    por_pagina = max(1, int((alto - 190) // alto_fila))
    paginas = [filas[inicio:inicio + por_pagina] for inicio in range(0, len(filas), por_pagina)] or [[]]
    operaciones = []
    fecha_generacion = datetime.now().strftime("%d/%m/%Y, %H:%M")

    def texto(x, y, contenido, tamano=9, color="0.08 0.16 0.31", negrita=False):
        fuente = "F2" if negrita else "F1"
        return f"BT /{fuente} {tamano} Tf {color} rg {x:.2f} {y:.2f} Td ({_escape(contenido)}) Tj ET"

    for numero_pagina, registros in enumerate(paginas, start=1):
        ops = [
            "1 1 1 rg 0 0 842 595 re f",
            texto(margen, 557, "Clínica San José", 19, "0.08 0.16 0.31", True),
            texto(margen, 535, str(titulo)[:110], 11, "0.08 0.16 0.31", True),
        ]
        if not subtitulos:
            subtitulos = [f"Generado {fecha_generacion} · Administración Clínica San José"]
        for indice, linea_subtitulo in enumerate(subtitulos[:2]):
            ops.append(texto(margen, 519 - 13 * indice, linea_subtitulo, 8, "0.34 0.43 0.57"))
        y_linea = 505 - 13 * (min(len(subtitulos), 2) - 1)
        ops.append(f"0.00 0.53 0.68 RG 36 {y_linea} m 806 {y_linea} l S")
        y = y_linea - 20
        filas_pagina = [[columnas] + registros]
        for grupo in filas_pagina:
            for indice_fila, fila in enumerate(grupo):
                es_encabezado = indice_fila == 0
                es_total = not es_encabezado and str(fila[0] if fila else "").upper().startswith("TOTAL")
                color_fondo = "0.91 0.96 0.98" if es_encabezado else ("0.08 0.16 0.31" if es_total else ("0.97 0.98 0.99" if indice_fila % 2 == 0 else "1 1 1"))
                ops.append(f"{color_fondo} rg {margen} {y - alto_fila + 4} {ancho_tabla} {alto_fila} re f")
                ops.append(f"0.81 0.87 0.92 RG {margen} {y - alto_fila + 4} m {ancho - margen} {y - alto_fila + 4} l S")
                for indice_columna in range(len(columnas)):
                    x = margen + indice_columna * ancho_columna
                    ops.append(f"0.81 0.87 0.92 RG {x:.2f} {y - alto_fila + 4} m {x:.2f} {y + 4} l S")
                    valor = fila[indice_columna] if indice_columna < len(fila) else ""
                    limite = max(5, int((ancho_columna - 14) / 5.2))
                    valor = valor if len(valor) <= limite else valor[:limite - 1] + "…"
                    color_texto = "1 1 1" if es_total else "0.08 0.16 0.31"
                    ops.append(texto(x + 8, y - 13, valor, 9, color_texto, es_encabezado or es_total))
                ops.append(f"0.81 0.87 0.92 RG {ancho - margen} {y - alto_fila + 4} m {ancho - margen} {y + 4} l S")
                y -= alto_fila
        ops.extend([
            "0.81 0.87 0.92 RG 36 40 m 806 40 l S",
            texto(margen, 24, "Documento confidencial · Clínica San José", 8, "0.34 0.43 0.57"),
            texto(740, 24, f"{numero_pagina}/{len(paginas)}", 8, "0.34 0.43 0.57"),
        ])
        operaciones.append("\n".join(ops))

    objetos = [b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"]
    ids_pagina = [3 + 2 * indice for indice in range(len(paginas))]
    ids_contenido = [identificador + 1 for identificador in ids_pagina]
    objetos.append((f"2 0 obj << /Type /Pages /Kids [{' '.join(f'{identificador} 0 R' for identificador in ids_pagina)}] /Count {len(paginas)} >> endobj\n").encode())
    for id_pagina, id_stream, contenido in zip(ids_pagina, ids_contenido, operaciones):
        stream = contenido.encode("cp1252", "replace")
        objetos.append((f"{id_pagina} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 {ancho} {alto}] /Contents {id_stream} 0 R /Resources << /Font << /F1 {3 + 2 * len(paginas)} 0 R /F2 {4 + 2 * len(paginas)} 0 R >> >> >> endobj\n").encode())
        objetos.append(f"{id_stream} 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream endobj\n")
    id_fuente = 3 + 2 * len(paginas)
    objetos.extend([
        f"{id_fuente} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n".encode(),
        f"{id_fuente + 1} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >> endobj\n".encode(),
    ])
    salida, offsets = b"%PDF-1.4\n", [0]
    for objeto in objetos:
        offsets.append(len(salida))
        salida += objeto
    posicion_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode() + b"0000000000 65535 f \n"
    salida += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return salida + f"trailer << /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{posicion_xref}\n%%EOF".encode()


def pdf_factura(datos):
    """Factura vertical de una página con datos fiscales, detalle y pago."""
    monto = float(datos.get("monto") or 0)
    impuestos = float(datos.get("impuestos") or 0)
    descuentos = float(datos.get("descuentos") or 0)
    copago = float(datos.get("copago") or 0)
    total = monto + impuestos - descuentos + copago
    fecha_emision = datetime.now().strftime("%d/%m/%Y")
    numero = f"SJ-{int(datos.get('id') or 0):06d}"
    cliente = str(datos.get("paciente") or "Paciente particular")
    fiscales = str(datos.get("datos_fiscales") or "Consumidor final")
    servicio = str(datos.get("servicio") or "Consulta médica")
    especialidad = str(datos.get("especialidad") or "Consulta")
    medico = str(datos.get("medico") or "No registrado")
    estado = str(datos.get("estado") or "pendiente").replace("_", " ").upper()
    metodo = str(datos.get("metodo_pago") or "No especificado").replace("_", " ").title()
    fecha_atencion = f"{datos.get('fecha_cita') or '—'}  {datos.get('hora_cita') or ''}".strip()

    navy = "0.08 0.16 0.31"
    ink = "0.12 0.15 0.20"
    muted = "0.38 0.42 0.48"
    accent = "0.75 0.23 0.22"
    pale = "0.94 0.96 0.98"
    ops = []

    def txt(x, y, value, size=10, color=ink, bold=False):
        font = "F2" if bold else "F1"
        return f"BT /{font} {size} Tf {color} rg {x} {y} Td ({_escape(value)}) Tj ET"

    def rule(x1, y1, x2, y2, color=accent, width=0.8):
        return f"{color} RG {width} w {x1} {y1} m {x2} {y2} l S"

    # Emisor y sello de marca (monograma; no se inventa un logotipo externo).
    ops.extend([
        txt(34, 790, "FACTURA", 31, navy, True),
        txt(36, 764, "CLÍNICA SAN JOSÉ", 11, ink, True),
        txt(36, 748, "Servicios de atención médica", 8, muted),
        "0.72 0.73 0.76 rg 493 775 m 493 793 508 808 526 808 c 544 808 559 793 559 775 c 559 757 544 742 526 742 c 508 742 493 757 493 775 c f",
        txt(511, 772, "SJ", 13, "1 1 1", True),
        txt(36, 715, "FACTURAR A", 8, accent, True),
        txt(36, 696, cliente[:56], 11, navy, True),
        txt(36, 680, f"NIT / Datos fiscales: {fiscales}"[:72], 8, muted),
        txt(36, 664, f"Médico: {medico}"[:72], 8, muted),
        txt(36, 648, f"Especialidad: {especialidad}"[:72], 8, muted),
        txt(348, 715, "N.º DE FACTURA", 8, accent, True),
        txt(348, 697, numero, 11, navy, True),
        txt(348, 677, "FECHA DE EMISIÓN", 8, accent, True),
        txt(348, 660, fecha_emision, 9, ink),
        txt(348, 640, "FECHA DE ATENCIÓN", 8, accent, True),
        txt(348, 623, fecha_atencion[:34], 8, ink),
        rule(36, 600, 559, 600, accent, 1.2),
        "0.94 0.96 0.98 rg 36 568 523 25 re f",
        txt(46, 577, "CANT.", 8, navy, True),
        txt(91, 577, "DESCRIPCIÓN", 8, navy, True),
        txt(380, 577, "PRECIO UNITARIO", 8, navy, True),
        txt(500, 577, "IMPORTE", 8, navy, True),
        txt(48, 545, "1", 9, ink),
        txt(91, 549, servicio[:48], 9, ink, True),
        txt(91, 533, especialidad[:48], 8, muted),
        txt(392, 545, f"Q {monto:,.2f}", 9, ink),
        txt(500, 545, f"Q {monto:,.2f}", 9, ink),
        rule(36, 519, 559, 519, "0.82 0.85 0.89", 0.6),
    ])

    # Resumen de cantidades al estilo de una factura comercial.
    ops.extend([
        txt(360, 492, "Subtotal", 9, muted), txt(485, 492, f"Q {monto:,.2f}", 9, ink),
        txt(360, 472, "Impuestos", 9, muted), txt(485, 472, f"Q {impuestos:,.2f}", 9, ink),
        txt(360, 452, "Descuentos", 9, muted), txt(485, 452, f"- Q {descuentos:,.2f}", 9, ink),
        txt(360, 432, "Copago", 9, muted), txt(485, 432, f"Q {copago:,.2f}", 9, ink),
        rule(354, 416, 559, 416, accent, 0.8),
        "0.08 0.16 0.31 rg 354 379 205 31 re f",
        txt(365, 390, "TOTAL A PAGAR", 9, "1 1 1", True),
        txt(471, 388, f"Q {total:,.2f}", 12, "1 1 1", True),
        txt(36, 390, "Gracias por su preferencia", 14, navy, True),
        txt(36, 371, "Clínica San José", 9, muted),
        rule(36, 103, 559, 103, "0.82 0.85 0.89", 0.6),
        rule(36, 103, 36, 57, navy, 1.2),
        txt(48, 86, "CONDICIONES Y FORMA DE PAGO", 8, accent, True),
        txt(48, 68, f"Estado: {estado}   ·   Método: {metodo}"[:90], 8, ink),
        txt(48, 53, f"Referencia: {datos.get('referencia_pago') or '—'}"[:90], 8, muted),
        txt(36, 28, "Documento electrónico · Clínica San José", 7, muted),
    ])

    stream = "\n".join(ops).encode("cp1252", "replace")
    objetos = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >> endobj\n",
        f"4 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream endobj\n",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n",
        b"6 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >> endobj\n",
    ]
    salida, offsets = b"%PDF-1.4\n", [0]
    for objeto in objetos:
        offsets.append(len(salida))
        salida += objeto
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode() + b"0000000000 65535 f \n"
    salida += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return salida + f"trailer << /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
