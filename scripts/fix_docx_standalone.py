"""Fix 'Word found unreadable content' caused by missing standalone="yes".

Post-processing script for .docx files produced by the public docx skill's
pack.py. The pack.py _condense_xml() function uses minidom.toxml() which
silently strips standalone="yes" from XML declarations. Word expects this
attribute on [Content_Types].xml, .rels files, and most internal XML parts.

Usage:
    python fix_docx_standalone.py <input.docx> [output.docx]

If output is omitted, the input file is fixed in place.

This script:
  1. Opens the .docx (zip archive)
  2. Checks each XML/.rels file for a declaration missing standalone="yes"
  3. Adds it back where missing
  4. Re-writes the archive preserving zip entry order and compression
"""

import re
import sys
import shutil
import tempfile
import zipfile
from pathlib import Path

# Pattern matches an XML declaration that does NOT already have standalone
DECL_WITHOUT_STANDALONE = re.compile(
    rb'(<\?xml\s+version="1\.0"\s+encoding="UTF-8")\s*(\?>)'
)
REPLACEMENT = rb'\1 standalone="yes"\2'

# File extensions inside the docx that contain XML declarations
XML_EXTENSIONS = {".xml", ".rels"}


def fix_standalone(input_path: str, output_path: str | None = None) -> tuple[int, str]:
    """Fix standalone="yes" in a .docx file.

    Returns (count_of_files_fixed, message).
    """
    src = Path(input_path)
    if not src.exists():
        return 0, f"Error: {input_path} does not exist"
    if src.suffix.lower() != ".docx":
        return 0, f"Error: {input_path} is not a .docx file"

    dst = Path(output_path) if output_path else src

    fixed_count = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_out = Path(tmp_dir) / "fixed.docx"

        with zipfile.ZipFile(src, "r") as zf_in:
            with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as zf_out:
                for info in zf_in.infolist():
                    data = zf_in.read(info.filename)

                    # Only process XML-like files
                    # Note: Path(".rels").suffix returns "" (Python treats it
                    # as a dotfile), so we also check the filename directly.
                    fname = Path(info.filename).name.lower()
                    ext = Path(info.filename).suffix.lower()
                    if ext in XML_EXTENSIONS or fname.endswith(".rels"):
                        new_data, n = DECL_WITHOUT_STANDALONE.subn(REPLACEMENT, data, count=1)
                        if n > 0:
                            data = new_data
                            fixed_count += 1

                    # Preserve the original ZipInfo metadata
                    zf_out.writestr(info, data)

        # Copy the fixed file to the destination
        shutil.copy2(tmp_out, dst)

    if fixed_count:
        return fixed_count, f'Fixed standalone="yes" in {fixed_count} XML file(s) → {dst}'
    else:
        return 0, f"No fixes needed (standalone already present) → {dst}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.docx> [output.docx]")
        sys.exit(1)

    in_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else None

    count, message = fix_standalone(in_file, out_file)
    print(message)
