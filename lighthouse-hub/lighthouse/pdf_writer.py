"""Minimal PDF generator - stdlib only, no reportlab/fpdf.

Builds a valid (uncompressed) PDF by hand: a handful of indirect objects
(catalog, pages, page(s), content stream(s), font) plus a cross-reference
table. Good enough for a simple title + table report; not a general-purpose
PDF library.
"""

PAGE_W, PAGE_H = 612, 792  # US Letter, points
MARGIN = 40
ROW_H = 16
ROWS_PER_PAGE = int((PAGE_H - MARGIN * 2 - 60) / ROW_H)


def _escape(s):
    return str(s).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(title, subtitle, headers, col_x, rows_slice, page_num, page_count):
    lines = []
    lines.append("BT /F1 16 Tf %d %d Td (%s) Tj ET" % (MARGIN, PAGE_H - MARGIN, _escape(title)))
    lines.append("BT /F1 10 Tf %d %d Td (%s) Tj ET" % (MARGIN, PAGE_H - MARGIN - 18, _escape(subtitle)))
    y = PAGE_H - MARGIN - 46
    lines.append("BT /F2 9 Tf")
    for h, x in zip(headers, col_x):
        lines.append("%d %d Td (%s) Tj %d %d Td" % (x, y, _escape(h), -x, -y))
    lines.append("ET")
    y -= ROW_H
    lines.append("BT /F1 9 Tf")
    for row in rows_slice:
        for val, x in zip(row, col_x):
            lines.append("%d %d Td (%s) Tj %d %d Td" % (x, y, _escape(val), -x, -y))
        y -= ROW_H
    lines.append("ET")
    lines.append("BT /F1 8 Tf %d %d Td (Page %d of %d) Tj ET" % (MARGIN, MARGIN - 10, page_num, page_count))
    return "\n".join(lines).encode("latin-1", errors="replace")


def build_table_pdf(title, subtitle, headers, rows, col_widths=None):
    """headers: list[str], rows: list[list[str]]. Returns PDF bytes."""
    if col_widths is None:
        n = len(headers)
        avail = PAGE_W - MARGIN * 2
        col_widths = [avail // n] * n
    col_x = [MARGIN]
    for w in col_widths[:-1]:
        col_x.append(col_x[-1] + w)

    str_rows = [[str(c) if c is not None else "" for c in row] for row in rows]
    pages = [str_rows[i:i + ROWS_PER_PAGE] for i in range(0, len(str_rows), ROWS_PER_PAGE)] or [[]]
    page_count = len(pages)

    objects = []  # list of bytes, index 0 unused (obj numbers start at 1)

    def add_object(data):
        objects.append(data)
        return len(objects)

    font1 = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font2 = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    pages_obj_num = len(objects) + 1 + (page_count * 2)  # placeholder, computed after we know layout
    # We build page + content objects first, then the Pages tree, then Catalog.
    page_obj_nums = []
    content_obj_nums = []
    for i, page_rows in enumerate(pages):
        content = _content_stream(title, subtitle, headers, col_x, page_rows, i + 1, page_count)
        stream_obj = b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"
        cnum = add_object(stream_obj)
        content_obj_nums.append(cnum)
        page_obj_nums.append(None)  # filled after we know the Pages object number

    pages_num = len(objects) + 1  # next object will be the Pages dict... but pages need /Parent first
    # Reserve object numbers for each page dict up front.
    reserved_page_nums = [pages_num + 1 + i for i in range(page_count)]
    pages_dict = (
        b"<< /Type /Pages /Kids [" +
        " ".join("%d 0 R" % n for n in reserved_page_nums).encode() +
        b"] /Count %d >>" % page_count
    )
    pages_actual_num = add_object(pages_dict)
    assert pages_actual_num == pages_num

    for i in range(page_count):
        page_dict = (
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_num, PAGE_W, PAGE_H, font1, font2, content_obj_nums[i])
        )
        n = add_object(page_dict)
        assert n == reserved_page_nums[i]

    catalog_num = add_object(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_num)

    # Assemble the file.
    out = [b"%PDF-1.4\n"]
    offsets = [0]
    pos = len(out[0])
    for i, obj in enumerate(objects, start=1):
        entry = b"%d 0 obj\n" % i + obj + b"\nendobj\n"
        offsets.append(pos)
        out.append(entry)
        pos += len(entry)

    xref_pos = pos
    xref = [b"xref\n0 %d\n" % (len(objects) + 1), b"0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(b"%010d 00000 n \n" % off)
    trailer = (
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF"
        % (len(objects) + 1, catalog_num, xref_pos)
    )
    out.append(b"".join(xref))
    out.append(trailer)
    return b"".join(out)
