"""Minimal .xlsx reader - stdlib only (zipfile + xml.etree).

Reads the first worksheet of a .xlsx file into a list of row dicts keyed by
the header row. Handles shared strings, inline strings, numbers, and Excel's
1900-epoch date serials. Deliberately does not depend on openpyxl (no pip
installs available in this environment) - covers the common case of a plain
data table with a header row, which is what a roster export looks like.
"""
import datetime
import re
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EXCEL_EPOCH = datetime.date(1899, 12, 30)  # Excel's (buggy) day-0, matches real-world behavior


def _col_to_index(cell_ref):
    letters = re.match(r"([A-Z]+)", cell_ref).group(1)
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _excel_serial_to_date(serial):
    try:
        return (EXCEL_EPOCH + datetime.timedelta(days=float(serial))).isoformat()
    except (ValueError, OverflowError):
        return None


DATE_HEADER_HINTS = ("date", "start", "end", "expir")


def _looks_like_date_header(header):
    h = (header or "").lower()
    return any(hint in h for hint in DATE_HEADER_HINTS)


def read_first_sheet(file_bytes):
    """Returns (headers: list[str], rows: list[dict[str,str]])."""
    with zipfile.ZipFile(__import__("io").BytesIO(file_bytes)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{NS}si"):
                text = "".join(t.text or "" for t in si.iter(f"{NS}t"))
                shared.append(text)

        sheet_name = None
        for name in z.namelist():
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                sheet_name = name
                break
        if not sheet_name:
            raise ValueError("No worksheet found in this file - is it a valid .xlsx?")

        root = ET.fromstring(z.read(sheet_name))
        sheet_data = root.find(f"{NS}sheetData")
        if sheet_data is None:
            return [], []

        grid = []
        for row in sheet_data.findall(f"{NS}row"):
            cells = {}
            for c in row.findall(f"{NS}c"):
                ref = c.get("r", "")
                col = _col_to_index(ref) if ref else len(cells)
                cell_type = c.get("t")
                v = c.find(f"{NS}v")
                is_node = c.find(f"{NS}is")
                if is_node is not None:
                    value = "".join(t.text or "" for t in is_node.iter(f"{NS}t"))
                elif v is None:
                    value = ""
                elif cell_type == "s":
                    idx = int(v.text)
                    value = shared[idx] if idx < len(shared) else ""
                else:
                    value = v.text or ""
                cells[col] = value
            grid.append(cells)

        if not grid:
            return [], []

        width = max((max(r.keys()) + 1 if r else 0) for r in grid)
        headers = [str(grid[0].get(i, "")).strip() for i in range(width)]

        rows = []
        for r in grid[1:]:
            if not any((r.get(i, "") or "").strip() for i in range(width)):
                continue
            row_dict = {}
            for i, header in enumerate(headers):
                if not header:
                    continue
                raw = r.get(i, "")
                if _looks_like_date_header(header) and raw and re.match(r"^\d+(\.\d+)?$", str(raw)):
                    raw = _excel_serial_to_date(raw) or raw
                row_dict[header] = raw
            rows.append(row_dict)

        return headers, rows
