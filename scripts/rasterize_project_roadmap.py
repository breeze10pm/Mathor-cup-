"""用文档技能捆绑的pypdfium2栅格化原生Word导出的PDF，供逐页QA。"""
from pathlib import Path
import json

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / 'output/document_qa/project_roadmap'
with pdfium.PdfDocument(QA / 'project-roadmap.pdf') as document:
    pages=[]
    for i in range(len(document)):
        page=document[i]
        path=QA/f'page-{i+1}.png'
        page.render(scale=2).to_pil().save(path)
        pages.append(str(path))
    print(json.dumps({'pages':len(document),'images':pages},ensure_ascii=False))
