/* Local SVG explorer. Data is embedded so it also works directly from file://. */
const MEADExplorer = (() => {
  function seriesValue(series, x) {
    if (!series.x.length || x < series.x[0] || x > series.x.at(-1)) return null;
    let low = 0, high = series.x.length;
    while (low < high) { const mid = (low + high) >> 1; if (series.x[mid] <= x) low = mid + 1; else high = mid; }
    return series.y[low - 1];
  }
  function panelGroups(series, selection) {
    const filtered = series.filter(s => (s.mode || 'levels') === (selection.mode || 'levels') && s.metric === selection.metric && selection.models.includes(s.model) && selection.axes.includes(s.axis) && selection.conditions.includes(s.condition));
    const groups = [];
    if (selection.layout === 'overlay') {
      for (const axis of selection.axes) {
        const items = filtered.filter(s => s.axis === axis);
        if (items.length) groups.push({key:axis, axis, model:null, series:items});
      }
    } else {
      for (const model of selection.models) for (const axis of selection.axes) {
        const items = filtered.filter(s => s.model === model && s.axis === axis);
        if (items.length) groups.push({key:`${model}-${axis}`,axis,model,series:items});
      }
    }
    return groups;
  }
  return {seriesValue, panelGroups};
})();
if (typeof document !== 'undefined') {
  const data = JSON.parse(document.getElementById('chart-data').textContent);
  const metricControl = document.getElementById('select-metric');
  const layoutControl = document.getElementById('select-layout');
  const contrastControl = document.getElementById('select-contrast');
  const inputs = Array.from(document.querySelectorAll('input[data-filter]'));
  const container = document.getElementById('live-charts');
  const colors = ['#075C78','#C16D21','#7C569B','#33865E','#B34963','#497EC6','#737D30'];
  const hidden = new Set(), zooms = new Map();
  const cap = text => data.model_labels?.[text] || (text === 'delta' ? 'Interact − Control' : text.charAt(0).toUpperCase() + text.slice(1));
  const color = model => colors[data.models.indexOf(model) % colors.length];
  const seriesKey = s => `${s.model}-${s.condition}`;
  function selected(group) { return inputs.filter(i => i.dataset.filter === group && (group !== 'model' || !i.disabled) && i.checked).map(i => i.value); }
  function choose(group, values) { inputs.filter(i => i.dataset.filter === group).forEach(i => {i.checked = (group !== 'model' || !i.disabled) && values.includes(i.value);}); }
  function state() { return {metric:metricControl.value,layout:layoutControl.value,mode:contrastControl.value,models:selected('model'),axes:selected('axis'),conditions:contrastControl.value==='delta'?['delta']:selected('condition')}; }
  const saved = new URLSearchParams(location.hash.slice(1));
  if (['levels','delta'].includes(saved.get('mode'))) contrastControl.value=saved.get('mode');
  if (data.metrics[saved.get('metric')]) metricControl.value = saved.get('metric');
  if (['overlay','panels'].includes(saved.get('layout'))) layoutControl.value = saved.get('layout');
  for (const [group, param] of [['model','model'],['axis','axis'],['condition','condition']]) {
    if (saved.has(param)) {
      const value = saved.get(param);
      choose(group,value === '*' ? inputs.filter(i=>i.dataset.filter===group).map(i=>i.value) : value.split(','));
    }
  }
  function svgElement(tag, attrs={}, text) {
    const el=document.createElementNS('http://www.w3.org/2000/svg',tag);
    for(const [key,value] of Object.entries(attrs)) el.setAttribute(key,value);
    if(text!==undefined)el.textContent=text;
    return el;
  }
  function formatValue(value, metric, mode='levels') {
    if (value === null) return '—';
    if(metric.startsWith('discovered_')) return `${(value*100).toFixed(1)}${mode==='delta'?' pp':'%'}`;
    if(metric==='cost_usd')return `$${value.toFixed(4)}`;
    return value.toFixed(metric.endsWith('best')?4:2);
  }
  function xLabel(x, axis) {return axis==='step'?Number(x.toFixed(1)).toString():`${(x*100).toFixed(1)}%`;}
  function render() {
    const selection=state();
    inputs.filter(i=>i.dataset.filter==='condition').forEach(i=>{i.disabled=selection.mode==='delta';});
    document.getElementById('contrast-note').textContent=selection.mode==='delta'?data.delta_definition:'Observed outcomes for Control and Interact.';
    const groups=MEADExplorer.panelGroups(data.series,selection);
    container.replaceChildren();
    container.classList.toggle('overlay',selection.layout==='overlay');
    document.getElementById('result-count').textContent=groups.length?`${data.metrics[selection.metric]} · ${groups.length} chart${groups.length===1?'':'s'}`:'Select at least one model, time axis, and condition.';
    const params=new URLSearchParams({metric:selection.metric,model:selection.models.join(','),axis:selection.axes.join(','),condition:selected('condition').join(','),layout:selection.layout,mode:selection.mode});
    history.replaceState(null,'',`#${params}`);
    for(const card of document.querySelectorAll('#static-exports article')) {
      card.hidden=selection.mode==='delta'||!(card.dataset.metric===selection.metric && selection.models.includes(card.dataset.model) && selection.axes.includes(card.dataset.axis));
    }
    for(const group of groups)drawChart(group,selection);
  }
  function drawChart(group,selection) {
    const metric=selection.metric;
    const delta=selection.mode==='delta';
    const scale=(delta?data.delta_scales:data.scales)[metric];
    const card=document.createElement('section');card.className='chart-card';
    const head=document.createElement('div');head.className='chart-head';
    const heading=document.createElement('h2');heading.textContent=`${group.model?cap(group.model):'All selected models'} · ${data.axes[group.axis]}`;
    const exports=document.createElement('div');exports.style.whiteSpace='nowrap';
    head.append(heading,exports);card.append(head);
    const legend=document.createElement('div');legend.className='legend';
    for(const series of group.series) {
      const btn=document.createElement('button');btn.textContent=`${series.condition==='interact'?'┄':'━'} ${cap(series.model)} · ${cap(series.condition)}`;
      btn.style.color=color(series.model);btn.style.opacity=hidden.has(seriesKey(series))?'0.4':'1';
      btn.setAttribute('aria-pressed',String(!hidden.has(seriesKey(series))));
      btn.addEventListener('click',()=>{const key=seriesKey(series);hidden.has(key)?hidden.delete(key):hidden.add(key);render();});legend.append(btn);
    }
    card.append(legend);
    const active=group.series.filter(s=>!hidden.has(seriesKey(s)));
    const legendRows=Math.max(2,Math.ceil(active.length/3));
    const W=760,H=484+18*legendRows,L=78,R=24,T=28,B=124+18*legendRows,plotW=W-L-R,plotH=H-T-B;
    const maxStep=Math.max(2,...group.series.flatMap(s=>s.x));
    const full=group.axis==='step'?[1,maxStep]:[0,1];
    const domain=zooms.get(`${metric}-${selection.mode}-${group.key}`)||full;
    const [ymin,ymax]=scale.limits;
    const X=x=>L+(x-domain[0])/(domain[1]-domain[0])*plotW;
    const Y=y=>T+(ymax-y)/(ymax-ymin)*plotH;
    const svg=svgElement('svg',{viewBox:`0 0 ${W} ${H}`,xmlns:'http://www.w3.org/2000/svg',role:'img','aria-label':`${data.metrics[metric]}: ${heading.textContent}`,style:'font-family:system-ui,sans-serif;background:#fff'});
    svg.append(svgElement('title',{},`${data.metrics[metric]}: ${heading.textContent}`));
    svg.append(svgElement('rect',{width:W,height:H,fill:'#fff'}));
    svg.append(svgElement('text',{x:W/2,y:17,'text-anchor':'middle','font-size':13,fill:'#222'},(delta?'Δ Interact − Control: ':'')+data.metrics[metric]));
    const clipId=`clip-${group.key}`;
    const defs=svgElement('defs'),clip=svgElement('clipPath',{id:clipId});clip.append(svgElement('rect',{x:L,y:T,width:plotW,height:plotH}));defs.append(clip);svg.append(defs);
    for(const y of scale.ticks) {
      svg.append(svgElement('line',{x1:L,x2:W-R,y1:Y(y),y2:Y(y),stroke:'#e4e8eb'}));
      svg.append(svgElement('text',{x:L-10,y:Y(y)+4,'text-anchor':'end','font-size':12,fill:'#333'},formatValue(y,metric,selection.mode)));
    }
    const ticks=group.axis==='step'?Array.from({length:Math.floor(domain[1])-Math.ceil(domain[0])+1},(_,i)=>Math.ceil(domain[0])+i):Array.from({length:6},(_,i)=>domain[0]+i*(domain[1]-domain[0])/5);
    for(const x of ticks)svg.append(svgElement('text',{x:X(x),y:H-B+24,'text-anchor':'middle','font-size':12,fill:'#333'},xLabel(x,group.axis)));
    svg.append(svgElement('text',{x:L+plotW/2,y:H-B+50,'text-anchor':'middle','font-size':13,fill:'#333'},data.axes[group.axis]));
    const ylabel=(delta?'Δ Interact − Control · ':'')+(metric.startsWith('discovered_')?'Share of agents':metric==='cost_usd'?'Mean cumulative cost per run (USD)':['mean_agent_best','maximum_agent_best'].includes(metric)?'Noiseless score':'Mean cumulative count per run');
    svg.append(svgElement('text',{transform:`translate(16 ${T+plotH/2}) rotate(-90)`,'text-anchor':'middle','font-size':13,fill:'#333'},ylabel));
    const curves=svgElement('g',{'clip-path':`url(#${clipId})`});
    for(const series of active) {
      let path='';
      series.x.forEach((x,i)=>{path+=i?`H${X(x)}V${Y(series.y[i])}`:`M${X(x)},${Y(series.y[i])}`;});
      curves.append(svgElement('path',{d:path,fill:'none',stroke:color(series.model),'stroke-width':2.4,'stroke-dasharray':series.condition==='interact'?'7 5':'none','stroke-linejoin':'round'}));
    }
    svg.append(curves);
    if(active.length && active.every(series=>series.x.length===0))
      svg.append(svgElement('text',{x:L+plotW/2,y:T+plotH/2,'text-anchor':'middle','font-size':14,fill:'#666'},'No defined values; see run completion.'));
    if(delta)svg.append(svgElement('line',{x1:L,x2:W-R,y1:Y(0),y2:Y(0),stroke:'#666','stroke-width':1.2,'stroke-dasharray':'3 3','data-zero-line':'true'}));
    active.forEach((series,index)=>{
      const x=L+(index%3)*plotW/3,y=H-46-legendRows*18+Math.floor(index/3)*18;
      svg.append(svgElement('line',{x1:x,x2:x+22,y1:y-4,y2:y-4,stroke:color(series.model),'stroke-width':2,'stroke-dasharray':series.condition==='interact'?'6 4':'none'}));
      svg.append(svgElement('text',{x:x+28,y,'font-size':11,fill:color(series.model)},`${cap(series.model)} · ${cap(series.condition)}`));
    });
    const note=delta?'Paired Interact − Control, then averaged. Positive means Interact is higher.':group.axis==='step'?'All agents included; finished agents carry terminal values through unused steps.':['mean_agent_best','maximum_agent_best'].includes(metric)?'Agents with completed measurements only.':'';
    if(note)svg.append(svgElement('text',{x:L,y:H-32,'font-size':11,fill:'#666'},note));

    const crosshair=svgElement('line',{x1:L,x2:L,y1:T,y2:H-B,stroke:'#777','stroke-dasharray':'3 3',visibility:'hidden'});
    const dots=svgElement('g');svg.append(crosshair,dots);
    const brush=svgElement('rect',{x:L,y:T,width:0,height:plotH,fill:'#075c7820',stroke:'#075c78',visibility:'hidden'});svg.append(brush);
    const hit=svgElement('rect',{x:L,y:T,width:plotW,height:plotH,fill:'transparent',cursor:'crosshair'});svg.append(hit);
    card.append(svg);
    const tooltip=document.createElement('div');tooltip.className='tooltip';tooltip.hidden=true;card.append(tooltip);
    const plotPixel=event=>Math.max(L,Math.min(W-R,(event.clientX-svg.getBoundingClientRect().left)*W/svg.getBoundingClientRect().width));
    const dataX=pixel=>domain[0]+(pixel-L)/plotW*(domain[1]-domain[0]);
    let dragging=null;
    hit.addEventListener('pointerdown',event=>{dragging=plotPixel(event);hit.setPointerCapture(event.pointerId);tooltip.hidden=true;});
    hit.addEventListener('pointermove',event=>{
      const pixel=plotPixel(event);
      if(dragging!==null){brush.setAttribute('x',Math.min(dragging,pixel));brush.setAttribute('width',Math.abs(pixel-dragging));brush.setAttribute('visibility','visible');return;}
      let x=dataX(pixel);if(group.axis==='step')x=Math.round(x);
      crosshair.setAttribute('x1',X(x));crosshair.setAttribute('x2',X(x));crosshair.setAttribute('visibility','visible');
      tooltip.replaceChildren();const label=document.createElement('strong');label.textContent=`${data.axes[group.axis]}: ${xLabel(x,group.axis)}`;tooltip.append(label);
      const table=document.createElement('table');dots.replaceChildren();
      for(const series of active){const value=MEADExplorer.seriesValue(series,x),row=document.createElement('tr'),name=document.createElement('td'),number=document.createElement('td');name.textContent=`${cap(series.model)} · ${cap(series.condition)}`;if(delta && value!==null){const n=MEADExplorer.seriesValue({...series,y:series.matched_pairs},x);name.textContent+=` (${n} ${n===1?'pair':'pairs'})`;}name.style.color=color(series.model);number.textContent=formatValue(value,metric,selection.mode);row.append(name,number);table.append(row);if(value!==null)dots.append(svgElement('circle',{cx:X(x),cy:Y(value),r:4,fill:color(series.model),stroke:'#fff','stroke-width':1}));}
      tooltip.append(table);tooltip.hidden=false;const rect=card.getBoundingClientRect();tooltip.style.left=`${Math.max(8,Math.min(event.clientX-rect.left+12,rect.width-tooltip.offsetWidth-12))}px`;tooltip.style.top=`${Math.max(8,event.clientY-rect.top-tooltip.offsetHeight-12)}px`;
    });
    hit.addEventListener('pointerleave',()=>{if(dragging===null){tooltip.hidden=true;crosshair.setAttribute('visibility','hidden');dots.replaceChildren();}});
    hit.addEventListener('pointerup',event=>{if(dragging===null)return;const pixel=plotPixel(event);if(Math.abs(pixel-dragging)>12){const range=[dataX(Math.min(pixel,dragging)),dataX(Math.max(pixel,dragging))];if(group.axis!=='step'||range[1]-range[0]>=1)zooms.set(`${metric}-${selection.mode}-${group.key}`,range);}dragging=null;render();});
    hit.addEventListener('pointercancel',()=>{dragging=null;brush.setAttribute('visibility','hidden');});
    hit.addEventListener('dblclick',()=>{zooms.delete(`${metric}-${selection.mode}-${group.key}`);render();});
    function saveBlob(blob,filename){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    for(const type of ['SVG','PNG']){const button=document.createElement('button');button.textContent=type;button.setAttribute('aria-label',`Export ${heading.textContent} as ${type}`);button.addEventListener('click',()=>{const clone=svg.cloneNode(true);clone.querySelectorAll('[visibility="visible"]').forEach(el=>el.setAttribute('visibility','hidden'));const blob=new Blob([new XMLSerializer().serializeToString(clone)],{type:'image/svg+xml;charset=utf-8'}),filename=`${metric}-${selection.mode}-${group.key}`;if(type==='SVG'){saveBlob(blob,`${filename}.svg`);return;}const image=new Image(),url=URL.createObjectURL(blob);image.onload=()=>{const canvas=document.createElement('canvas');canvas.width=W*2;canvas.height=H*2;canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);URL.revokeObjectURL(url);canvas.toBlob(result=>{if(result)saveBlob(result,`${filename}.png`);});};image.src=url;});exports.append(button);}
    container.append(card);
  }
  metricControl.addEventListener('change',()=>{zooms.clear();render();});
  layoutControl.addEventListener('change',render);
  contrastControl.addEventListener('change',()=>{zooms.clear();render();});
  inputs.forEach(i=>i.addEventListener('change',render));
  document.getElementById('compare-models').addEventListener('click',()=>{layoutControl.value='panels';if(!selected('axis').length||selected('axis').length>1)choose('axis',['budget']);render();});
  document.getElementById('compare-times').addEventListener('click',()=>{choose('axis',Object.keys(data.axes));if(selected('model').length!==1)choose('model',[selected('model')[0]||data.models[0]]);layoutControl.value='panels';render();});
  document.getElementById('overlay-models').addEventListener('click',()=>{layoutControl.value='overlay';render();});
  document.getElementById('reset-zoom').addEventListener('click',()=>{zooms.clear();render();});
  render();
}
