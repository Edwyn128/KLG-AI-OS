#!/usr/bin/env python3
"""
KLG Brief Assembly Script

Assembles elevated brief content into a KLG .docx template by:
1. Converting markdown to docx via pandoc
2. Extracting body paragraphs from the pandoc output
3. Remapping pandoc styles to KLG custom styles (context-aware)
4. Splicing the remapped content into the template document.xml

Usage:
    python assemble_brief.py \
        --template <unpacked_template_dir> \
        --content-intro <intro.md> \
        --content-memo <memo.md> \
        --brief-type petition|opening|reply|respondent \
        --output-dir <output_dir> \
        --boundaries "intro_heading:3856,petition_start:4262,memo_pagebreak:5491,cert_pagebreak:7435" \
        --original-docx <original.docx> \
        [--docx-scripts <path_to_docx_skill_scripts>] \
        [--output-docx <output.docx>]

After repacking, always run:
    python /path/to/fix_docx_standalone.py output.docx

KLG Style Mapping (pandoc → KLG Word styles):
    Heading1        → P1Pleading1   (centered, small caps, Century Schoolbook 13pt)
    Heading2        → P2Pleading2   (bold, left-aligned — auto-numbered A. B. C.)
    Heading3 in Argument → P3Pleading3  (bold, auto-numbered 1. 2. 3.)
    Heading3 in Statement of Case → Italic BodyText (narrative subheadings)
    FirstParagraph  → BodyText
    BlockText       → Quote (indented 1440 twips each side — no quotation marks)

Do NOT include <w:numPr numId="0"> on P2Pleading2 or P3Pleading3 paragraphs —
that suppresses automatic numbering. The style definitions carry the list linkage.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile


# ---------------------------------------------------------------------------
# XML Templates for KLG Styles
# ---------------------------------------------------------------------------

P1_HEADING = """    <w:p w14:paraId="{pid}" w14:textId="{tid}" w:rsidR="00A96F5E" w:rsidRDefault="00A96F5E" w:rsidP="00A61E3D">
      <w:pPr>
        <w:pStyle w:val="P1Pleading1"/>
        <w:numPr>
          <w:ilvl w:val="0"/>
          <w:numId w:val="0"/>
        </w:numPr>
        <w:jc w:val="center"/>
      </w:pPr>
      <w:r>
        <w:t>{text}</w:t>
      </w:r>
    </w:p>"""

P2_HEADING = """    <w:p w14:paraId="{pid}" w14:textId="{tid}" w:rsidR="00A96F5E" w:rsidRDefault="00A96F5E" w:rsidP="00A61E3D">
      <w:pPr>
        <w:pStyle w:val="P2Pleading2"/>
      </w:pPr>
      <w:r>
        <w:t>{text}</w:t>
      </w:r>
    </w:p>"""

P3_HEADING = """    <w:p w14:paraId="{pid}" w14:textId="{tid}" w:rsidR="00A96F5E" w:rsidRDefault="00A96F5E" w:rsidP="00A61E3D">
      <w:pPr>
        <w:pStyle w:val="P3Pleading3"/>
      </w:pPr>
      <w:r>
        <w:t>{text}</w:t>
      </w:r>
    </w:p>"""

ITALIC_SUBHEADING = """    <w:p w14:paraId="{pid}" w14:textId="{tid}" w:rsidR="00A96F5E" w:rsidRDefault="00A96F5E">
      <w:pPr>
        <w:pStyle w:val="BodyText"/>
        <w:keepNext/>
        <w:spacing w:before="240"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:i/>
          <w:iCs/>
        </w:rPr>
        <w:t>{text}</w:t>
      </w:r>
    </w:p>"""

PAGE_BREAK = """    <w:p w14:paraId="{pid}" w14:textId="{tid}" w:rsidR="00A96F5E" w:rsidRDefault="00A96F5E">
      <w:pPr>
        <w:spacing w:after="200" w:line="276" w:lineRule="auto"/>
      </w:pPr>
      <w:r>
        <w:br w:type="page"/>
      </w:r>
    </w:p>"""

MEMO_HEADING = """    <w:p w14:paraId="{pid}" w14:textId="{tid}" w:rsidR="00A96F5E" w:rsidRDefault="00A96F5E" w:rsidP="00A61E3D">
      <w:pPr>
        <w:pStyle w:val="P1Pleading1"/>
        <w:numPr>
          <w:ilvl w:val="0"/>
          <w:numId w:val="0"/>
        </w:numPr>
        <w:jc w:val="center"/>
      </w:pPr>
      <w:r>
        <w:lastRenderedPageBreak/>
        <w:t>Memorandum of Points and Authorities</w:t>
      </w:r>
    </w:p>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class IdGenerator:
    def __init__(self, start=0x1000):
        self.counter = start

    def next(self):
        self.counter += 1
        return f"AB{self.counter:06X}", f"CD{self.counter:06X}"


def extract_body_paragraphs(xml_content):
    body_match = re.search(r'<w:body>(.*?)</w:body>', xml_content, re.DOTALL)
    if not body_match:
        raise ValueError("Could not find <w:body> in XML")
    body = body_match.group(1)
    body = re.sub(r'<w:sectPr[^>]*>.*?</w:sectPr>\s*$', '', body, flags=re.DOTALL)
    return body.strip()


def split_paragraphs(xml):
    parts = []
    pos = 0
    for m in re.finditer(r'<w:p[ >]', xml):
        if m.start() > pos:
            parts.append(('ws', xml[pos:m.start()]))
        end = xml.find('</w:p>', m.start())
        if end == -1:
            break
        end += len('</w:p>')
        parts.append(('p', xml[m.start():end]))
        pos = end
    if pos < len(xml):
        parts.append(('ws', xml[pos:]))
    return parts


def get_style(p_xml):
    m = re.search(r'<w:pStyle w:val="([^"]+)"', p_xml)
    return m.group(1) if m else None


def get_text(p_xml):
    texts = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', p_xml)
    return ''.join(texts)


def set_style(p_xml, new_style):
    return re.sub(
        r'<w:pStyle w:val="[^"]+"',
        f'<w:pStyle w:val="{new_style}"',
        p_xml
    )


def find_paragraph_start(lines, line_idx):
    while line_idx > 0 and not lines[line_idx].strip().startswith('<w:p '):
        line_idx -= 1
    return line_idx


def convert_md_to_pandoc_xml(md_path, reference_docx, work_dir):
    docx_out = os.path.join(work_dir, os.path.basename(md_path).replace('.md', '.docx'))
    unpack_dir = os.path.join(work_dir, os.path.basename(md_path).replace('.md', '_unpack'))

    subprocess.run([
        'pandoc', md_path, '-o', docx_out,
        f'--reference-doc={reference_docx}'
    ], check=True)

    import zipfile
    os.makedirs(unpack_dir, exist_ok=True)
    with zipfile.ZipFile(docx_out, 'r') as z:
        z.extractall(unpack_dir)

    with open(os.path.join(unpack_dir, 'word', 'document.xml'), 'r') as f:
        return f.read()


# ---------------------------------------------------------------------------
# Style Remapping (Context-Aware)
# ---------------------------------------------------------------------------

def remap_pandoc_styles(body_xml, ids):
    """
    Remap pandoc styles to KLG styles.

    Heading3 maps based on context:
    - In Statement of Case: italic BodyText subheadings
    - In Argument: P3Pleading3 numbered subsections
    """
    parts = split_paragraphs(body_xml)
    in_argument = False
    in_statement = False

    new_parts = []
    for part_type, content in parts:
        if part_type == 'ws':
            new_parts.append(content)
            continue

        style = get_style(content)
        text = get_text(content)
        pid, tid = ids.next()

        if style == 'Heading1':
            text_lower = text.lower()
            if 'statement of the case' in text_lower or 'statement of case' in text_lower:
                in_statement = True
                in_argument = False
            elif 'standard of review' in text_lower:
                in_statement = False
                in_argument = False
            elif 'argument' in text_lower:
                in_statement = False
                in_argument = True
            elif 'conclusion' in text_lower:
                in_statement = False
                in_argument = False
            new_parts.append(P1_HEADING.format(pid=pid, tid=tid, text=text))

        elif style == 'Heading2':
            new_parts.append(P2_HEADING.format(pid=pid, tid=tid, text=text))

        elif style == 'Heading3':
            if in_argument:
                new_parts.append(P3_HEADING.format(pid=pid, tid=tid, text=text))
            else:
                new_parts.append(ITALIC_SUBHEADING.format(pid=pid, tid=tid, text=text))

        elif style == 'FirstParagraph':
            content = set_style(content, 'BodyText')
            new_parts.append(content)

        elif style == 'BlockText':
            content = re.sub(
                r'<w:pStyle w:val="BlockText"/>',
                '<w:pStyle w:val="BodyText"/>\n        <w:ind w:left="1440" w:right="1440"/>',
                content
            )
            new_parts.append(content)

        else:
            new_parts.append(content)

    return ''.join(new_parts)


# ---------------------------------------------------------------------------
# Assembly Logic
# ---------------------------------------------------------------------------

def parse_boundaries(boundary_str):
    boundaries = {}
    for pair in boundary_str.split(','):
        key, val = pair.strip().split(':')
        boundaries[key.strip()] = int(val.strip())
    return boundaries


def assemble_petition(orig_lines, intro_body, memo_body, boundaries, ids):
    intro_head = boundaries['intro_heading']
    petition_start = boundaries['petition_start']
    memo_pb = boundaries['memo_pagebreak']
    cert_pb = boundaries['cert_pagebreak']

    intro_head_end = intro_head
    while intro_head_end < len(orig_lines) and '</w:p>' not in orig_lines[intro_head_end]:
        intro_head_end += 1
    petition_para = find_paragraph_start(orig_lines, petition_start)
    memo_pb_para = find_paragraph_start(orig_lines, memo_pb)
    cert_pb_para = find_paragraph_start(orig_lines, cert_pb)

    print(f"  Intro heading ends at line {intro_head_end + 1}")
    print(f"  Petition para starts at line {petition_para + 1}")
    print(f"  Memo PB para starts at line {memo_pb_para + 1}")
    print(f"  Cert PB para starts at line {cert_pb_para + 1}")

    part1 = ''.join(orig_lines[:intro_head_end + 1])
    part2 = '\n' + intro_body + '\n'
    part3 = ''.join(orig_lines[petition_para:memo_pb_para])

    pid1, tid1 = ids.next()
    pid2, tid2 = ids.next()
    part4 = '\n' + PAGE_BREAK.format(pid=pid1, tid=tid1) + '\n'
    part4 += MEMO_HEADING.format(pid=pid2, tid=tid2) + '\n'
    part4 += memo_body + '\n'

    part5 = ''.join(orig_lines[cert_pb_para:])
    return part1 + part2 + part3 + part4 + part5


def assemble_standard_brief(orig_lines, body_content, boundaries, ids):
    intro_head = boundaries['intro_heading']
    cert_pb = boundaries['cert_pagebreak']

    intro_para = find_paragraph_start(orig_lines, intro_head)
    cert_pb_para = find_paragraph_start(orig_lines, cert_pb)

    print(f"  Intro para starts at line {intro_para + 1}")
    print(f"  Cert PB para starts at line {cert_pb_para + 1}")

    part1 = ''.join(orig_lines[:intro_para])
    part2 = '\n' + body_content + '\n'
    part3 = ''.join(orig_lines[cert_pb_para:])
    return part1 + part2 + part3


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='KLG Brief Assembly')
    parser.add_argument('--template', required=True)
    parser.add_argument('--content-intro')
    parser.add_argument('--content-memo')
    parser.add_argument('--content-body')
    parser.add_argument('--brief-type', required=True,
                        choices=['petition', 'opening', 'reply', 'respondent'])
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--boundaries', required=True)
    parser.add_argument('--original-docx', required=True)
    parser.add_argument('--docx-scripts')
    parser.add_argument('--output-docx')
    args = parser.parse_args()

    ids = IdGenerator()
    boundaries = parse_boundaries(args.boundaries)

    doc_xml_path = os.path.join(args.template, 'word', 'document.xml')
    with open(doc_xml_path, 'r') as f:
        orig_lines = f.readlines()
    print(f"Template: {len(orig_lines)} lines")

    work_dir = tempfile.mkdtemp(prefix='klg_assembly_')

    if args.brief_type == 'petition':
        if not args.content_intro or not args.content_memo:
            parser.error("Petition type requires --content-intro and --content-memo")

        print("Converting Introduction...")
        intro_xml = convert_md_to_pandoc_xml(args.content_intro, args.original_docx, work_dir)
        intro_body = extract_body_paragraphs(intro_xml)
        intro_body = intro_body.replace(
            '<w:pStyle w:val="FirstParagraph"/>',
            '<w:pStyle w:val="BodyText"/>'
        )
        print(f"  {len(re.findall(r'<w:p[ >]', intro_body))} paragraphs")

        print("Converting Memorandum...")
        memo_xml = convert_md_to_pandoc_xml(args.content_memo, args.original_docx, work_dir)
        memo_body = extract_body_paragraphs(memo_xml)
        print(f"  {len(re.findall(r'<w:p[ >]', memo_body))} paragraphs (before remapping)")

        print("Remapping Memorandum styles...")
        memo_body = remap_pandoc_styles(memo_body, ids)

        print("Assembling petition...")
        new_xml = assemble_petition(orig_lines, intro_body, memo_body, boundaries, ids)

    else:
        if not args.content_body:
            parser.error(f"{args.brief_type} type requires --content-body")

        print("Converting body content...")
        body_xml = convert_md_to_pandoc_xml(args.content_body, args.original_docx, work_dir)
        body_content = extract_body_paragraphs(body_xml)
        print(f"  {len(re.findall(r'<w:p[ >]', body_content))} paragraphs (before remapping)")

        print("Remapping styles...")
        body_content = remap_pandoc_styles(body_content, ids)

        print(f"Assembling {args.brief_type} brief...")
        new_xml = assemble_standard_brief(orig_lines, body_content, boundaries, ids)

    if os.path.exists(args.output_dir):
        shutil.rmtree(args.output_dir)
    shutil.copytree(args.template, args.output_dir)
    with open(os.path.join(args.output_dir, 'word', 'document.xml'), 'w') as f:
        f.write(new_xml)
    print(f"Assembly written to {args.output_dir}/word/document.xml")

    if args.output_docx and args.docx_scripts:
        pack_script = os.path.join(args.docx_scripts, 'pack.py')
        if os.path.exists(pack_script):
            print(f"Repacking to {args.output_docx}...")
            subprocess.run([
                sys.executable, pack_script, args.output_dir, args.output_docx,
                '--original', args.original_docx, '--validate', 'false'
            ], check=True)
            print("Done. Run fix_docx_standalone.py on the output next.")
        else:
            print(f"Warning: pack.py not found at {pack_script}")
    elif args.output_docx:
        print("Warning: --docx-scripts not provided, cannot repack automatically.")

    shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
