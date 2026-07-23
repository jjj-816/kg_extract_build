"""Build a self-contained HTML viewer for document-level KG Gold annotations."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


PAGE = r'''<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}} · Gold 标注可视化</title>
<style>
:root { --ink:#18212f; --muted:#64748b; --paper:#fff; --bg:#f3f6fa; --line:#dce4ef; --accent:#2563eb; }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.65 system-ui,"Microsoft YaHei",sans-serif; }
header { position:sticky; top:0; z-index:5; padding:14px 24px; background:#ffffffed; backdrop-filter:blur(8px); border-bottom:1px solid var(--line); display:flex; gap:18px; align-items:center; }
h1 { margin:0; font-size:18px; } .stats { margin-left:auto; color:var(--muted); white-space:nowrap; }
.layout { display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:18px; max-width:1660px; margin:18px auto; padding:0 18px; }
.document { position:relative; min-width:0; background:var(--paper); border:1px solid var(--line); box-shadow:0 3px 15px #243b5310; }
#content { position:relative; padding:30px 38px 80px; white-space:pre-wrap; overflow-wrap:anywhere; font:15px/1.9 ui-monospace,"Cascadia Mono","Microsoft YaHei",monospace; }
.line { position:relative; display:block; min-height:1.9em; } .ln { display:inline-block; width:46px; margin-right:16px; text-align:right; user-select:none; color:#94a3b8; border-right:1px solid #e7edf5; font-size:12px; }
.mention { border-radius:3px; padding:1px 0; cursor:pointer; box-decoration-break:clone; -webkit-box-decoration-break:clone; transition:filter .15s,outline .15s; }
.mention:hover { filter:saturate(1.45) brightness(.94); } .mention.focus { outline:2px solid #172554; outline-offset:2px; }
#links { position:absolute; inset:0; z-index:2; pointer-events:none; overflow:visible; } #content { z-index:1; }
.side { align-self:start; position:sticky; top:72px; background:var(--paper); border:1px solid var(--line); padding:18px; max-height:calc(100vh - 88px); overflow:auto; }
h2 { font-size:15px; margin:0 0 10px; } label { display:block; margin:14px 0 5px; font-weight:650; } select,input { width:100%; padding:8px 10px; border:1px solid #cbd5e1; border-radius:6px; background:white; color:var(--ink); }
.legend { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; margin-top:8px; } .key { padding:3px 6px; border-radius:4px; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.relation { margin-top:16px; padding:12px; background:#f8fafc; border-left:3px solid var(--accent); border-radius:4px; } .relation strong { color:#1d4ed8; } .help { color:var(--muted); font-size:12px; } button { margin-top:12px; padding:7px 11px; border:0; border-radius:6px; color:#fff; background:#475569; cursor:pointer; }
@media(max-width:920px) { .layout { grid-template-columns:1fr; } .side { position:static; max-height:none; } header { padding:12px; } .stats { display:none; } #content { padding:20px 14px 55px; font-size:13px; } }
</style>
<header><h1>{{TITLE}} · Gold 标注可视化</h1><span class="stats" id="stats"></span></header>
<main class="layout"><section class="document"><svg id="links" aria-hidden="true"></svg><div id="content"></div></section>
<aside class="side"><h2>查看关系</h2><p class="help">选择一条关系，将在原文中高亮两端实体，并以连线表示它们的知识图谱关联。</p>
<label for="relationSelect">关系（三元组）</label><select id="relationSelect"></select><div class="relation" id="relationInfo">请选择关系。</div>
<button id="clear">清除选择</button><label>实体类型图例</label><div class="legend" id="legend"></div><p class="help">实体按原始字符偏移量标注；重叠实体采用叠加数据并以其中一种类型显示颜色。</p></aside></main>
<script>
const source = {{SOURCE}};
const data = {{DATA}};
const colors = ['#fef08a','#bae6fd','#bbf7d0','#fecaca','#ddd6fe','#fed7aa','#a7f3d0','#fbcfe8','#bfdbfe','#fde68a','#d9f99d','#e9d5ff','#cffafe','#f5d0fe','#e5e7eb'];
const typeColor = new Map(); [...new Set(data.entity_mentions.map(x=>x.type))].forEach((x,i)=>typeColor.set(x,colors[i%colors.length]));
const content=document.querySelector('#content'), svg=document.querySelector('#links'), select=document.querySelector('#relationSelect'), info=document.querySelector('#relationInfo');
const enc = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mentions=data.entity_mentions.filter(m=>Number.isInteger(m.start)&&Number.isInteger(m.end)&&m.end>m.start&&m.end<=source.length);
function render(){
 const bounds=new Set([0,source.length]); mentions.forEach(m=>{bounds.add(m.start);bounds.add(m.end)}); const points=[...bounds].sort((a,b)=>a-b);
 let out='', line=1, atLineStart=true; function prefix(){return `<span class="ln">${line}</span>`}; out+=`<span class="line">${prefix()}`;
 for(let i=0;i<points.length-1;i++) { const a=points[i],b=points[i+1], text=source.slice(a,b), active=mentions.filter(m=>m.start<=a&&m.end>=b);
  const put=t=>{const parts=t.split('\n'); for(let j=0;j<parts.length;j++){if(j){out+=`</span><span class="line">`;line++;out+=prefix();} out+=enc(parts[j]);}};
  if(active.length){const ids=active.map(m=>m.canonical_id).filter(Boolean).join('|');const primary=active[0];out+=`<span class="mention" data-ids="${enc(ids)}" title="${enc(active.map(m=>`${m.mention}（${m.type}）`).join('；'))}" style="background:${typeColor.get(primary.type)}">`;put(text);out+='</span>';} else put(text);
 } out+='</span>'; content.innerHTML=out;
}
function draw(idA,idB){ svg.innerHTML=''; document.querySelectorAll('.mention.focus').forEach(e=>e.classList.remove('focus')); const find=id=>[...document.querySelectorAll('.mention')].filter(e=>(e.dataset.ids||'').split('|').includes(id)); const a=find(idA),b=find(idB); [...a,...b].forEach(e=>e.classList.add('focus')); if(!a.length||!b.length)return;
 const start=a[0].getBoundingClientRect(), end=b[0].getBoundingClientRect(), box=content.parentElement.getBoundingClientRect(); const x1=start.left-box.left+start.width/2,y1=start.top-box.top+start.height/2,x2=end.left-box.left+end.width/2,y2=end.top-box.top+end.height/2; svg.setAttribute('width',box.width);svg.setAttribute('height',box.height); const bend=Math.max(45,Math.abs(x2-x1)*.25);svg.innerHTML=`<path d="M ${x1} ${y1} C ${x1+bend} ${y1}, ${x2-bend} ${y2}, ${x2} ${y2}" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-dasharray="6 4"/>`;
}
function pick(i){const t=data.triplets[i];if(!t){info.textContent='请选择关系。';svg.innerHTML='';document.querySelectorAll('.mention.focus').forEach(e=>e.classList.remove('focus'));return;} info.innerHTML=`<strong>${enc(t.head_name)}</strong><br><span>${enc(t.head_type)}</span> — <strong>${enc(t.relation)}</strong> →<br><strong>${enc(t.tail_name)}</strong><br><span>${enc(t.tail_type)}</span>`;draw(t.head_id,t.tail_id);}
render(); data.triplets.forEach((t,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${t.head_name} — ${t.relation} → ${t.tail_name}`;select.appendChild(o)}); select.insertAdjacentHTML('afterbegin','<option value="">请选择一条关系</option>');select.addEventListener('change',()=>pick(select.value));document.querySelector('#clear').onclick=()=>{select.value='';pick('')};window.addEventListener('resize',()=>{if(select.value!=='')pick(select.value)});
document.querySelector('#stats').textContent=`${mentions.length} 个实体提及 · ${data.triplets.length} 条关系`;
const legend=document.querySelector('#legend');typeColor.forEach((color,type)=>legend.insertAdjacentHTML('beforeend',`<span class="key" style="background:${color}">${enc(type)}</span>`));
</script></html>'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown", type=Path)
    parser.add_argument("gold", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.markdown.read_text(encoding="utf-8")
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    required = {"entity_mentions", "triplets"}
    if not required.issubset(gold):
        raise ValueError(f"Gold 文件缺少字段：{', '.join(sorted(required - gold.keys()))}")
    title = gold.get("document", {}).get("title", args.markdown.stem)
    page = PAGE.replace("{{TITLE}}", html.escape(str(title)))
    page = page.replace("{{SOURCE}}", json.dumps(source, ensure_ascii=False))
    page = page.replace("{{DATA}}", json.dumps({"entity_mentions": gold["entity_mentions"], "triplets": gold["triplets"]}, ensure_ascii=False))
    args.output.write_text(page, encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
