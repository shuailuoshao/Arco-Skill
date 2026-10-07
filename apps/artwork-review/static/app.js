'use strict';

const $ = (selector) => document.querySelector(selector);
const h = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clone = (value) => structuredClone(value);
const names = {pending:'待评', reviewed:'已评', deferred:'暂缓'};
const groupNames = {high:'高分组', low:'低分组', middle:'中间分', unscored:'未填总分'};
const priorityNames = {high:'高', medium:'中', low:'低'};
const defaults = {start:'2026-10-03', end:'', q:'', variant:'', status:'', state:'', score:'', versions:'latest'};
const tagDefaults = ['角色偏差','服装偏差','姿态问题','表情问题','画风偏差','构图问题','场景问题','光影问题','手部瑕疵','细节瑕疵'];
const state = {token:'', meta:null, view:'quick', filters:clone(defaults), offset:0, listing:null,
  detail:null, draft:null, dirty:false, seq:0, savePromise:null, saveTimer:null, failed:false,
  queue:[], request:0, high:4, low:2, analysis:null, analysisTab:'high', lastKey:null,
  quick:{bucket:'pending', key:null, detail:null, listing:null, busy:false, imageReady:false, undo:[]}};

async function api(path, body, renewed=false) {
  let response;
  try {
    response = await fetch(path, {method:body === undefined ? 'GET':'POST',
      headers:body === undefined ? {}:{'Content-Type':'application/json','X-Arco-Token':state.token},
      body:body === undefined ? undefined:JSON.stringify(body), signal:AbortSignal.timeout(30000)});
  } catch (cause) {
    throw new Error('无法连接本机服务，草稿仍保留。请重新启动服务后重试。', {cause});
  }
  const data = await response.json();
  if(response.status===403 && body!==undefined && !renewed && data.error?.includes('凭证')) {
    const meta=await api('/api/bootstrap');state.token=meta.token;
    return api(path,body,true);
  }
  if (!response.ok) { const error = new Error(data.error || '请求失败'); error.status = response.status; throw error; }
  return data;
}

let toastTimer;
function toast(text, failure=false) {
  clearTimeout(toastTimer); $('#toast').textContent = text; $('#toast').hidden = false;
  $('#toast').classList.toggle('failure', failure);
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, failure ? 9000:4200);
}
function report(error) { console.error(error); toast(error.message || String(error), true); }
function media(asset, thumbnail=false) { return asset ? `/media/${asset}${thumbnail ? '?size=thumb':''}` : ''; }
function params(extra={}) { return new URLSearchParams({...state.filters, ...extra}).toString(); }
function analysisParams() { return new URLSearchParams({start:state.filters.start, end:state.filters.end, high:state.high, low:state.low}).toString(); }
function validThresholds() { if (!(1 <= state.low && state.low < state.high && state.high <= 5)) throw new Error('低分上限必须小于高分下限，门槛不能重叠。'); }
function setSaveStatus(text, failure=false) { const el=$('#save-status'); if (el) {el.textContent=text; el.classList.toggle('error-text',failure);} }
function draftKey(key) { return `arco-draft:${key}`; }
function stashDraft() {
  if (!state.detail || !state.draft) return;
  try { localStorage.setItem(draftKey(state.detail.key), JSON.stringify({review:state.draft, revision:state.detail.revision})); }
  catch { toast('浏览器草稿缓存不可用，请保持页面打开并确认本机保存成功。', true); }
}
function remember() {
  const session = {view:state.view, filters:state.filters, key:state.detail?.key || state.lastKey, high:state.high, low:state.low, analysisTab:state.analysisTab,
    quick:{bucket:state.quick.bucket,key:state.quick.key}};
  api('/api/session', session).catch(error => toast(`续评位置未保存：${error.message}`, true));
}
function markDirty() {
  state.seq++; state.dirty=true; state.failed=false; stashDraft();
  setSaveStatus('等待保存…'); clearTimeout(state.saveTimer);
  state.saveTimer=setTimeout(() => saveDraft().catch(report), 550);
}
async function saveDraft() {
  if (state.savePromise) return state.savePromise;
  if (!state.dirty || !state.detail) return true;
  clearTimeout(state.saveTimer);
  const key=state.detail.key, seq=state.seq, review=clone(state.draft), revision=state.detail.revision;
  setSaveStatus('正在保存…');
  state.savePromise=(async () => {
    try {
      const saved=await api(`/api/review/${key}`, {review, revision});
      Object.assign(state.detail, saved); state.analysis=null; state.failed=false;
      if (state.seq === seq) {
        state.dirty=false;
        try { localStorage.removeItem(draftKey(key)); } catch { /* SQLite already committed. */ }
        setSaveStatus(`已保存 ${saved.updated_at.slice(11,19)}`);
      } else { stashDraft(); setSaveStatus('还有新修改待保存…'); }
      updateReviewBadge(); remember(); updateProgress().catch(report);
      return true;
    } catch (error) {
      state.failed=true; state.dirty=true; stashDraft();
      setSaveStatus('保存失败 · 草稿已保留',true);
      const retry=$('#retry-save'); if (retry) retry.hidden=false;
      state.conflict=error.status===409; report(error); return false;
    } finally {
      state.savePromise=null;
      if (state.dirty && !state.failed) { clearTimeout(state.saveTimer); state.saveTimer=setTimeout(() => saveDraft().catch(report),200); }
    }
  })();
  return state.savePromise;
}
async function flush() {
  clearTimeout(state.saveTimer);
  if (state.savePromise && !await state.savePromise) return false;
  return state.dirty ? await saveDraft():true;
}
async function retrySave() {
  if (state.conflict && state.detail) {
    const current=await api(`/api/artworks/${state.detail.key}`);
    if (!current.image_integrity.matches) { toast('成图哈希变化，请先核对归档；草稿仍保留。',true); return; }
    if (!confirm('另一窗口可能已更新此图。是否以当前草稿覆盖最新人评？')) return;
    state.detail.revision=current.revision;
  }
  state.failed=false; state.conflict=false;
  if (await saveDraft()) { const retry=$('#retry-save'); if (retry) retry.hidden=true; }
}
function updateReviewBadge() {
  const badge=$('#human-badge'); if (badge && state.detail) {
    badge.className=`badge ${state.detail.state}`;
    badge.textContent=names[state.detail.state]+(state.draft.deferred && state.detail.state!=='deferred' ? ' · 暂缓':'');
  }
}
async function updateProgress() {
  const listing=await api(`/api/artworks?${params({limit:1,offset:0})}`);
  const reviewed=listing.progress.reviewed || 0;
  $('#progress-text').textContent=`${reviewed} / ${listing.scope_versions} 个版本`;
  $('#progress').max=Math.max(1,listing.scope_versions); $('#progress').value=reviewed;
  $('#progress-meta').textContent=`已填总分 ${listing.scored} · 待评 ${listing.progress.pending || 0} · 暂缓 ${listing.progress.deferred || 0}`;
}
function controlsFromFilters() {
  for (const [field,id] of Object.entries({q:'search',start:'start',end:'end',variant:'variant',status:'status',state:'review-state',score:'score',versions:'versions'})) $( `#${id}`).value=state.filters[field] || '';
  $('#recent').classList.toggle('selected',state.filters.start===defaults.start && !state.filters.end);
  $('#all-dates').classList.toggle('selected',!state.filters.start && !state.filters.end);
}
async function readFilters() {
  if(state.loadingArtwork){controlsFromFilters();return;}
  if (!await flush()) {controlsFromFilters();return;}
  for (const [field,id] of Object.entries({q:'search',start:'start',end:'end',variant:'variant',status:'status',state:'review-state',score:'score',versions:'versions'})) state.filters[field]=$(`#${id}`).value;
  state.offset=0; state.analysis=null; controlsFromFilters(); remember();
  if (state.view==='workbench') await switchView('gallery'); else await renderView();
}
function activeNav() {
  document.body.classList.toggle('quick-mode',state.view==='quick');
  document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('active',button.dataset.view===state.view));
}
async function switchView(view) {
  if(state.loadingArtwork || state.quick.busy)return;
  if (!await flush()) return;
  state.view=view; activeNav(); remember();
  history.replaceState(null,'',state.detail && view==='workbench' ? `#workbench/${state.detail.key}`:`#${view}`);
  await renderView();
  window.scrollTo(0,0);
}
async function renderView() {
  activeNav();
  if (state.view==='quick') {state.detail=null;state.draft=null;await renderQuick();}
  else if (state.view==='gallery') await renderGallery();
  else if (state.view==='analysis') await renderAnalysis();
  else if (state.detail) await openArtwork(state.detail.key, false);
  else if (state.lastKey) await openArtwork(state.lastKey);
  else {
    const listing=await api(`/api/artworks?${params({limit:1})}`); state.queue=listing.keys;
    if (listing.items.length) await openArtwork(listing.items[0].key,false);
    else $('#main').innerHTML='<div class="empty"><h2>当前范围没有作品</h2><p>调整左侧筛选，或切换全部归档。</p></div>';
  }
}
const quickNames={pending:'待判断',keep:'保留',discard:'丢弃',all:'全部'};
function quickButtonsBusy() {
  const q=state.quick;
  document.querySelectorAll('[data-quick-decision]').forEach(b=>b.disabled=q.busy || !q.imageReady || !q.detail?.image_integrity.matches);
}
async function renderQuick(preferred=state.quick.key) {
  const q=state.quick;
  if(q.busy)return;
  q.busy=true;q.imageReady=false;
  $('#main').inert=true;$('#main').setAttribute('aria-busy','true');
  try {
    q.listing=await api(`/api/quick?bucket=${q.bucket}`);
    const keys=q.listing.keys;
    q.key=keys.includes(preferred)?preferred:keys[0] || null;
    q.detail=q.key?await api(`/api/artworks/${q.key}`):null;
    const d=q.detail, counts=q.listing.counts, index=keys.indexOf(q.key);
    $('#main').innerHTML=`<section class="quick-review" aria-label="快速保留或丢弃"><div class="quick-heading"><div><h1>留，还是不留？</h1><p>全库所有版本 · 已判断 ${counts.keep+counts.discard} / ${q.listing.total}</p></div><div class="quick-counts"><span>保留 <strong>${counts.keep}</strong></span><span>丢弃 <strong>${counts.discard}</strong></span><span>待判断 <strong>${counts.pending}</strong></span></div></div>
      <div class="quick-tabs" aria-label="图片分类">${Object.entries(quickNames).map(([bucket,label])=>`<button data-quick-bucket="${bucket}" aria-pressed="${q.bucket===bucket}">${label}${bucket==='all'?'':' · '+counts[bucket]}</button>`).join('')}</div>
      ${d?`<div class="quick-image-wrap"><button class="quick-image" data-zoom="${d.image_asset}" data-title="${h(d.title)} v${d.version}" aria-label="放大当前图片"><img id="quick-image" src="${media(d.image_asset)}" alt="${h(d.title)} v${d.version}"></button><span class="quick-position">${index+1} / ${keys.length}</span></div>
      <div class="quick-caption"><span>${h(d.title)} · v${String(d.version).padStart(2,'0')} · ${h(d.status)}</span><span class="quick-current ${d.review.decision==='discard'?'discard':''}">${quickNames[d.review.decision] || '待判断'}</span></div>
      ${!d.image_integrity.matches?'<p class="error">图片缺失或哈希变化，请先核对归档；可以跳过此图。</p>':''}
      <div class="quick-actions"><button class="quick-choice quick-discard" data-quick-decision="discard" disabled>丢弃 <kbd>← / D</kbd></button><button class="quick-choice quick-keep" data-quick-decision="keep" disabled>保留 <kbd>→ / K</kbd></button></div>
      <p id="quick-save-status" class="quick-status" role="status">正在加载图片…</p>`:`<div class="empty quick-empty"><h2>${q.bucket==='pending'?'全部判断完成':'这一组暂时没有图片'}</h2><p>${q.bucket==='pending'?'可以切换保留或丢弃，回看并修改判断。':'切换其他分类继续查看。'}</p></div>`}
      <div class="quick-tools"><button class="button" id="quick-undo" ${q.undo.length?'':'disabled'}>撤销上一次 <kbd>Z</kbd></button>${d?`<button class="text-button" id="quick-prev" ${index<=0?'disabled':''}>上一张</button><button class="text-button" id="quick-next" ${index>=keys.length-1?'disabled':''}>跳过 / 下一张</button><button class="text-button" id="quick-detail">详细审阅</button>`:''}</div></section>`;
    if(d) {
      const image=$('#quick-image');
      const ready=()=>{if(state.view!=='quick' || q.detail?.key!==d.key)return;q.imageReady=true;quickButtonsBusy();$('#quick-save-status').textContent='点击即保存并进入下一张 · 丢弃只记录分类，不删除原图';};
      const failed=()=>{q.imageReady=false;quickButtonsBusy();$('#quick-save-status').textContent='图片无法加载，请重试或跳过；未改变分类。';};
      image.onload=ready;image.onerror=failed;
      if(image.complete){if(image.naturalWidth)ready();else failed();}
    }
    remember();
  } finally {
    q.busy=false;$('#main').inert=false;$('#main').removeAttribute('aria-busy');quickButtonsBusy();
  }
}
async function classifyQuick(decision) {
  const q=state.quick;
  if(q.busy || !q.detail || !q.imageReady || !['keep','discard'].includes(decision))return;
  q.busy=true;$('#main').inert=true;quickButtonsBusy();
  const d=q.detail, before=clone(d.review), review=clone(d.review);
  review.decision=decision;review.deferred=false;
  const keys=q.listing.keys,index=keys.indexOf(d.key),next=keys[index+1] || keys[index-1];
  $('#quick-save-status').textContent='正在保存…';
  let saved;
  try {
    saved=await api(`/api/review/${d.key}`,{review,revision:d.revision});
    q.undo.push({key:d.key,review:before,revision:saved.revision});
    state.analysis=null;
  } catch(error) {
    $('#quick-save-status').textContent='保存失败，仍在当前图片；请重新点击。';report(error);
    if(error.status===409) {
      // Read the current revision before any subsequent deliberate retry.
      try {q.detail=await api(`/api/artworks/${d.key}`);$('#quick-save-status').textContent='另一窗口已更新此图。已读取最新记录，请重新选择保留或丢弃。';}catch{/* Leave the conflict visible. */}
    }
  } finally {q.busy=false;$('#main').inert=false;quickButtonsBusy();}
  if(saved){await renderQuick(next);toast(`已${quickNames[decision]} · 可按 Z 撤销`);}
}
async function undoQuick() {
  const q=state.quick, previous=q.undo.at(-1);
  if(q.busy || !previous)return;
  q.busy=true;$('#main').inert=true;quickButtonsBusy();
  let saved;
  try {
    saved=await api(`/api/review/${previous.key}`,{review:previous.review,revision:previous.revision});
    q.undo.pop();state.analysis=null;
    // Undo itself creates a new revision; keep earlier undos of the same image usable.
    const earlier=q.undo.findLast(i=>i.key===previous.key);if(earlier)earlier.revision=saved.revision;
    q.bucket=quickNames[previous.review.decision]?previous.review.decision:'pending';
  } finally {q.busy=false;$('#main').inert=false;quickButtonsBusy();}
  if(saved){await renderQuick(previous.key);toast('已撤销上一次判断');}
}
async function navigateQuick(delta) {
  const q=state.quick;if(q.busy || !q.detail)return;
  const next=q.listing.keys[q.listing.keys.indexOf(q.key)+delta];
  if(next)await renderQuick(next);
}
async function renderGallery() {
  const request=++state.request;
  $('#main').innerHTML='<div class="loading">正在整理作品…</div>';
  const listing=await api(`/api/artworks?${params({offset:state.offset,limit:24})}`);
  if (request!==state.request || state.view!=='gallery') return;
  state.listing=listing; state.queue=listing.keys;
  await updateProgress();
  $('#main').innerHTML=`<div class="page-title"><div><p class="eyebrow">ARTWORK LIBRARY</p><h1>逐张看见，逐张判断。</h1><p>先找到作品，再对照原始参考。你的评分与修改方向独立保存。</p></div><span class="count-pill">${listing.total} 个展示项 · ${listing.matched_versions} 个版本</span></div>
    ${listing.total ? `<div class="gallery">${listing.items.map(i=>`<article class="art-card"><button class="art-open" data-artwork="${i.key}" aria-label="审阅 ${h(i.title)} v${i.version}"><div class="card-image"><img src="${media(i.image_asset,true)}" loading="lazy" decoding="async" alt="${h(i.title)}"><span class="version-badge">v${String(i.version).padStart(2,'0')} · ${i.version_count} 版</span></div><div class="card-content"><h2 class="card-title">${h(i.title)}</h2><div class="card-meta"><span>${h(i.variant)}</span><span>${i.created_at.slice(0,10)}</span><span class="${i.status==='失败稿' ? 'badge failed':''}">${h(i.status)}</span></div></div></button><div class="card-bottom"><span class="badge ${i.state}">${names[i.state]}${i.review.deferred && i.state!=='deferred'?' · 暂缓':''}</span><span class="score-indicator">${i.review.scores.overall ?? '—'}<small> / 5</small></span></div></article>`).join('')}</div><div class="pagination"><button class="button" id="prev-page" ${state.offset===0?'disabled':''}>上一页</button><span>${Math.floor(state.offset/24)+1} / ${Math.ceil(listing.total/24)}</span><button class="button" id="next-page" ${state.offset+24>=listing.total?'disabled':''}>下一页</button></div>` : '<div class="empty"><h2>没有符合筛选的作品</h2><p>可以重置筛选，或切换全部归档查看。</p></div>'}`;
}
function referencesHtml(refs, title, open=false) {
  return `<details class="reference-section" ${open?'open':''}><summary>${title} · ${refs.length} 张参考记录</summary><div class="reference-grid">${refs.map(r=>`<article class="reference-card">${r.asset_id ? `<button data-zoom="${r.asset_id}" data-title="${h(r.aliases.join(' / ') || '参考原图')}"><img src="${media(r.asset_id,true)}" loading="lazy" alt="${h(r.aliases.join(' / ') || '参考原图')}"></button>`:'<div class="error">参考未保存图片路径</div>'}<div class="reference-info"><strong>${h(r.aliases.join(' / ') || '未记录参考 ID')}</strong><div>${h(r.duty_labels.join(' · '))}</div><p class="hint">${r.archived_copy?'当次归档副本':'定位后的源文件'} · ${r.sent===null?'调用证据不完整':r.sent?'有实际输入记录':'未在调用路径中找到'}</p>${r.warnings.map(w=>`<p class="error">${h(w)}</p>`).join('')}<details><summary>来源与继承范围</summary><div>${h(r.source_path)}</div><div>继承：${h(r.inherit.join('、')) || '未记录'}</div><div>不继承：${h(r.do_not_inherit.join('、')) || '未记录'}</div></details></div></article>`).join('')}</div></details>`;
}
function scoreRows() {
  return Object.entries(state.meta.scores).map(([key,label])=>`<fieldset class="rating-row"><legend>${h(label)}<button class="score-clear" data-clear="${key}" type="button" aria-label="清空${h(label)}">清空</button></legend><div class="score-buttons" aria-label="${h(label)}">${[1,2,3,4,5].map(n=>`<button type="button" data-score-key="${key}" data-score-value="${n}" aria-pressed="${state.draft.scores[key]===n}" title="${n} 分">${n}</button>`).join('')}</div>${key==='overall'?'<p class="hint">1 很差 · 2 较差 · 3 可用但需改 · 4 满意 · 5 非常满意</p>':key==='quality'?'<p class="hint">分数越高，画面瑕疵越少。</p>':''}</fieldset>`).join('');
}
function renderTags() {
  $('#tags').innerHTML=[...new Set([...tagDefaults,...state.draft.tags])].map(tag=>`<button class="tag" data-tag="${h(tag)}" aria-pressed="${state.draft.tags.includes(tag)}">${h(tag)}</button>`).join('');
}
function renderDirections() {
  $('#directions').innerHTML=state.draft.directions.map((d,index)=>`<div class="direction"><div class="direction-top"><label>优先级 <select data-priority="${index}" aria-label="修改方向 ${index+1} 优先级">${Object.entries(priorityNames).map(([key,label])=>`<option value="${key}" ${key===d.priority?'selected':''}>${label}优先级</option>`).join('')}</select></label><button class="danger-button" data-remove-direction="${index}">删除</button></div><textarea data-direction-text="${index}" aria-label="修改方向 ${index+1}" placeholder="希望怎样修改…">${h(d.text)}</textarea></div>`).join('');
}
async function openArtwork(key, flushFirst=true) {
  if(state.loadingArtwork)return;
  state.loadingArtwork=true;
  $('#main').inert=true;
  $('#main').setAttribute('aria-busy','true');
  try {
  if (flushFirst && !await flush()) return;
  const detail=await api(`/api/artworks/${key}`);
  state.view='workbench'; state.detail=detail; state.lastKey=key; state.draft=clone(detail.review);
  state.dirty=false; state.failed=false; state.conflict=false; state.seq=0;
  let restored=false, conflictingDraft=false;
  try {
    const cached=JSON.parse(localStorage.getItem(draftKey(key)) || 'null');
    if (cached) {
      if (cached.revision===detail.revision) {state.draft=cached.review;state.dirty=true;restored=true;}
      else {conflictingDraft=true;}
    }
  } catch { /* Broken browser cache never replaces persisted data. */ }
  if (!state.queue.length) {const listing=await api(`/api/artworks?${params({limit:1})}`);state.queue=listing.keys;}
  if (!state.queue.includes(key)) {
    const siblings=new Set(detail.versions.map(v=>v.key));
    const position=state.queue.findIndex(k=>siblings.has(k));
    if(position>=0){state.queue=state.queue.filter(k=>!siblings.has(k));state.queue.splice(position,0,...detail.versions.map(v=>v.key));}
    else state.queue.push(key);
  }
  activeNav(); remember(); history.replaceState(null,'',`#workbench/${key}`);
  const d=state.detail, index=state.queue.indexOf(key), ext=d.references.filter(r=>r.scope==='external_how'), other=d.references.filter(r=>r.scope!=='external_how');
  $('#main').innerHTML=`<div class="workbench-header"><div><p class="eyebrow">REVIEW WORKBENCH · ${index+1} / ${state.queue.length}</p><h1>${h(d.title)}</h1><p>${h(d.variant)} · ${d.created_at.slice(0,10)} · v${String(d.version).padStart(2,'0')} · <span class="badge ${d.status==='失败稿'?'failed':''}">${h(d.status)}</span> <span id="human-badge" class="badge ${d.state}">${names[d.state]}</span></p></div><div class="workbench-actions"><button class="button" data-view="gallery">返回图库</button><button class="button" id="previous-artwork" ${index<=0?'disabled':''}>上一张</button><button class="button" id="next-artwork" ${index>=state.queue.length-1?'disabled':''}>下一张</button></div></div>
    ${d.warnings.map(w=>`<p class="error">${h(w)}</p>`).join('')}${!d.image_integrity.matches?'<p class="error">成图缺失或哈希变化：暂停保存评分，请先核对归档。</p>':''}
    ${conflictingDraft?'<p class="error">发现此前未保存的草稿，但本机人评已更新。当前展示本机记录；可下载旧草稿核对。 <button class="button small" id="download-old-draft">下载旧草稿</button></p>':''}
    <div class="workbench"><div><div class="image-panel"><div class="image-toolbar"><span>生成图片 · 点击放大</span><select id="version-select" aria-label="切换作品版本">${d.versions.map(v=>`<option value="${v.key}" ${v.key===d.key?'selected':''}>v${String(v.version).padStart(2,'0')} · ${h(v.status)} · ${names[v.state]} · ${v.review.scores.overall ?? '未填总分'}</option>`).join('')}</select><button class="button small" id="compare" ${d.versions.length<2?'disabled':''}>版本对比</button></div><div class="image-pair"><button class="image-viewer" data-zoom="${d.image_asset}" data-title="${h(d.title)} v${d.version}"><img class="hero-image" src="${media(d.image_asset)}" alt="${h(d.title)} 生成图片"></button>${ext.length?`<section class="external-preview"><label>并排外部参考<select id="primary-reference" aria-label="并排外部参考">${ext.map((r,index)=>`<option value="${index}">${h(r.aliases.join(' / ') || '外部原图 '+(index+1))}</option>`).join('')}</select></label><button class="image-viewer" id="external-preview-button" data-zoom="${ext[0].asset_id || ''}" data-title="${h(ext[0].aliases.join(' / ') || '外部原图')}"><img class="external-hero" id="external-preview-image" src="${media(ext[0].asset_id)}" alt="原始外部参考"></button><p id="external-preview-caption">${h(ext[0].duty_labels.join(' · '))}</p></section>`:''}</div></div><p class="shortcut-tip">快捷键：1–5 打总体分 · 0 清空总分 · ← → 切换图片 · Ctrl / ⌘ + Enter 保存后下一张</p>
    ${referencesHtml(ext,'原始外部参考',true)}${referencesHtml(other,'角色、服装及其他参考')}<details class="request-info"><summary>查看原始生成要求</summary><p>${h(d.prompt) || '历史记录未保存要求'}</p></details></div>
    <section class="rating-panel" aria-label="人工评分"><div class="rating-heading"><h2>你的判断</h2><span id="save-status" class="save-status">${restored?'已恢复未保存草稿':d.updated_at?'已保存 '+d.updated_at.slice(11,19):'尚无人工记录'}</span></div>${scoreRows()}
    <label>人工结论<select id="decision"><option value="">暂未选择</option>${Object.entries(state.meta.decisions).map(([key,label])=>`<option value="${key}" ${key===state.draft.decision?'selected':''}>${h(label)}</option>`).join('')}</select></label>
    <label>问题标签</label><div id="tags" class="tags"></div><div class="custom-tag"><input id="custom-tag" aria-label="自定义问题标签" maxlength="80" placeholder="自定义标签"><button class="button small" id="add-tag">添加</button></div>
    <label>备注<textarea id="notes" maxlength="20000" placeholder="喜欢的地方、问题或下一步判断…">${h(state.draft.notes)}</textarea></label>
    <div class="direction-heading"><span>下一步修改方向</span><button class="text-button" id="add-direction">+ 添加方向</button></div><div id="directions"></div>
    <div class="rating-footer"><button class="button" id="defer">${state.draft.deferred?'取消暂缓':'暂缓此图'}</button><button class="button primary" id="save-next">保存后下一张</button><button class="button" id="retry-save" hidden>重试保存</button><button class="text-button" id="download-draft">下载当前草稿</button><p class="hint">分项可留空。任何有效记录保存后即已评；只浏览不计入已评。</p></div></section></div>`;
  renderTags(); renderDirections(); updateReviewBadge();
  if (restored) state.saveTimer=setTimeout(()=>saveDraft().catch(report),600);
  await updateProgress();
  window.scrollTo(0,0);
  } finally {
    state.loadingArtwork=false;
    $('#main').inert=false;
    $('#main').removeAttribute('aria-busy');
  }
}
function setScore(key, value) {
  state.draft.scores[key]=value;
  document.querySelectorAll(`[data-score-key="${key}"]`).forEach(el=>el.setAttribute('aria-pressed',Number(el.dataset.scoreValue)===value));
  markDirty();
}
async function navigate(delta) {
  if(state.loadingArtwork)return;
  if (!await flush()) return;
  const index=state.queue.indexOf(state.detail.key), next=state.queue[index+delta];
  if (next) await openArtwork(next,false); else toast('已到当前审阅队列末尾。可返回图库调整筛选。');
}
function downloadBlob(body, filename, type='application/json') {
  const url=URL.createObjectURL(new Blob([body],{type})), a=document.createElement('a');
  a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function zoom(asset, title) {
  $('#zoom-title').textContent=title || '原图'; $('#zoom-range').value=100; $('#zoom-value').textContent='100%';
  const img=$('#zoom-image'); img.alt=title || '原图预览'; img.src=media(asset); img.style.width='';
  img.onload=()=>{
    const viewport=$('.zoom-viewport');
    state.zoomBase=Math.min(img.naturalWidth,viewport.clientWidth-40,(viewport.clientHeight-40)*img.naturalWidth/img.naturalHeight);
    img.style.width=state.zoomBase+'px';
  };
  $('#zoom-dialog').showModal();
}
async function compareVersions() {
  if (!await flush()) return;
  const current=state.detail, candidates=current.versions.filter(i=>i.key!==current.key);
  const previous=candidates.find(i=>i.key===current.parent_key) || candidates.at(-1);
  $('#compare-body').innerHTML=`<section><h3>当前 · v${current.version} · ${h(current.status)}</h3><button data-zoom="${current.image_asset}" data-title="${h(current.title)} v${current.version}"><img src="${media(current.image_asset)}" alt="当前版本"></button><p>总分：${state.draft.scores.overall ?? '未填'}</p></section><section><label>对照版本<select id="compare-version">${candidates.map(v=>`<option value="${v.key}" ${v.key===previous.key?'selected':''}>v${v.version} · ${h(v.status)} · 总分 ${v.review.scores.overall ?? '未填'}</option>`).join('')}</select></label><button id="compare-image-button" data-zoom="${previous.image_asset}" data-title="${h(current.title)} v${previous.version}"><img id="compare-image" src="${media(previous.image_asset)}" alt="对照版本"></button><p id="compare-score">总分：${previous.review.scores.overall ?? '未填'}</p></section>`;
  $('#compare-dialog').showModal();
}
function countsHtml(counter) { return Object.entries(counter).map(([key,n])=>`${h(key)} ${n}`).join(' · ') || '暂无样本'; }
async function renderAnalysis() {
  const request=++state.request;
  $('#main').innerHTML='<div class="loading">正在按评分回溯外部原图…</div>';
  validThresholds(); const data=state.analysis || await api(`/api/analysis?${analysisParams()}`);
  if (request!==state.request || state.view!=='analysis') return;
  state.analysis=data; await updateProgress();
  $('#main').innerHTML=`<div class="page-title"><div><p class="eyebrow">REFERENCE INSIGHTS</p><h1>从喜欢的作品，回看参考。</h1><p>全部命中版本参与分析。将高分与低分原图放在一起，寻找值得继续验证的共同点。</p></div><button class="button" data-export="analysis:md">导出分析资料</button></div>
    <div class="analysis-controls"><label>高分下限<select id="high-threshold">${[2,3,4,5].map(n=>`<option ${n===state.high?'selected':''}>${n}</option>`).join('')}</select></label><label>低分上限<select id="low-threshold">${[1,2,3,4].map(n=>`<option ${n===state.low?'selected':''}>${n}</option>`).join('')}</select></label><button id="apply-thresholds" class="button primary">更新集合</button><p class="hint">只使用左侧归档日期范围；图库的搜索、服装、状态、分数和版本折叠不限制分析集合。</p></div>
    <div class="stat-grid">${Object.entries(data.statistics).map(([group,s])=>`<div class="stat-card"><span>${groupNames[group]}</span><strong>${s.versions}<small style="display:inline"> 个版本</small></strong><small>${s.references} 张外部原图 · ${s.chains} 条生成链</small><small>${group==='unscored'?'有备注或分项也可能未填总分':'分数分布：'+countsHtml(s.score_distribution)}</small></div>`).join('')}</div>
    <div class="analysis-note">这里只汇总记录中的用途与评分，不自动判断视觉共性或参考适用性。初次生成与最新已评分版本分别列出；同一参考可同时进入高低分组。<br>每张原图的生成链数量比修订版本数量更能反映证据范围。</div>
    <div class="metadata-summary">${['high','low'].map(g=>`<section><h3>${groupNames[g]} · 已有元数据</h3><p>服装：${countsHtml(data.statistics[g].outfits)}</p><p>原图用途：${countsHtml(data.statistics[g].duties)}</p></section>`).join('')}</div>
    <div class="analysis-tabs" aria-label="选择原图分组">${Object.entries({...groupNames,both:'同时进入高低分'}).map(([key,label])=>`<button data-analysis-tab="${key}" class="${state.analysisTab===key?'selected':''}">${label}</button>`).join('')}</div><div id="analysis-cards"></div>`;
  renderAnalysisCards();
}
function renderAnalysisCards() {
  const data=state.analysis, tab=state.analysisTab;
  const refs=data.references.filter(r=>tab==='both' ? r.groups.high.length && r.groups.low.length:r.groups[tab].length);
  const byKey=Object.fromEntries(Object.values(data.groups).flat().map(i=>[i.key,i]));
  $('#analysis-cards').innerHTML=refs.length ? `<div class="analysis-grid">${refs.map(r=>`<article class="analysis-card"><button class="analysis-image" data-zoom="${r.asset_id}" data-title="${h(r.aliases.join(' / ') || '外部原图')}"><img src="${media(r.asset_id,true)}" loading="lazy" decoding="async" alt="${h(r.aliases.join(' / ') || '外部原图')}"></button><div class="analysis-info"><h3>${h(r.aliases.join(' / ') || r.sha256.slice(0,12))}</h3><div><span class="badge high">高分 ${r.groups.high.length}</span> <span class="badge low">低分 ${r.groups.low.length}</span></div><p>${r.chain_count} 条生成链 · ${r.version_count} 个版本<br>记录用途：${h(r.duties.join(' · ')) || '未记录'}</p>${(r.warnings || []).map(w=>`<p class="error">${h(w)}</p>`).join('')}${r.chain_count===1?'<p>仅一条生成链，证据有限。</p>':''}<details><summary>初次生成与最新已评分对照</summary>${r.initial.map(first=>{const last=r.latest_scored.find(l=>l.chain_key===first.chain_key);return `<div class="stage">首次生成：${first.in_scope?(first.score ?? '未填总分'):'不在日期范围'}<br>最新已评分：${last.score ?? '未填总分'}${last.is_revision?'（修订版）':'（未评分或初次生成）'}</div>`;}).join('')}</details><details><summary>关联作品与人工评分</summary>${Object.entries(r.groups).map(([group,keys])=>keys.map(key=>{const i=byKey[key];return `<button class="evidence-button" data-artwork="${key}">${groupNames[group]} · ${h(i.title)} v${i.version}<br>总分 ${i.review.scores.overall ?? '未填'} · ${h(i.variant)}</button>`;}).join('')).join('')}</details><details><summary>本机原图路径与别名</summary><p>${h(r.path)}</p><p>SHA-256：${r.sha256}</p></details></div></article>`).join('')}</div>` : '<div class="empty"><h2>该组还没有外部原图</h2><p>先给作品填写总体满意度，或调整日期范围和分数门槛。</p></div>';
}
async function exportData(spec) {
  if (!await flush()) return;
  const [kind,format]=spec.split(':'); if (kind==='analysis') validThresholds();
  const exported=await api('/api/export',{kind,format,filters:{start:state.filters.start,end:state.filters.end,high:state.high,low:state.low}});
  const anchor=document.createElement('a');anchor.href=exported.download_url;anchor.download=exported.filename;
  document.body.append(anchor);anchor.click();anchor.remove();
  document.querySelector('.export-menu').open=false;toast(`已保存到本机：${exported.path}，并请求浏览器下载。`);
}
async function restoreFile(file) {
  if (!await flush()) return;
  if (file.size>16*1024*1024) throw new Error('备份文件过大，请选择 16 MB 以内的 JSON。');
  const packet=JSON.parse(await file.text());
  const preview=await api('/api/restore',{packet,dry_run:true});
  $('#restore-summary').textContent=`新增 ${preview.new} · 冲突 ${preview.conflicts} · 相同 ${preview.unchanged} · 无法匹配 ${preview.unknown}`;
  const dialog=$('#restore-dialog');dialog.returnValue='cancel';dialog.showModal();
  const choice=await new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue),{once:true}));
  if (choice==='cancel') return;
  const result=await api('/api/restore',{packet,dry_run:false,overwrite:choice==='overwrite'});
  state.analysis=null;toast(`已恢复 ${result.imported} 条；跳过未知版本 ${result.unknown} 条。`);
  await renderView();
}

document.addEventListener('click', event=>{
  if(event.target.closest('.brand')){event.preventDefault();switchView('quick').catch(report);return;}
  const button=event.target.closest('button,[data-zoom]');if (!button) return;
  const run=async()=>{
    if(state.quick.busy)return;
    if(button.dataset.quickDecision)return classifyQuick(button.dataset.quickDecision);
    if(button.dataset.quickBucket){state.quick.bucket=button.dataset.quickBucket;return renderQuick();}
    if (button.dataset.view) return switchView(button.dataset.view);
    if (button.dataset.artwork) {
      if (state.view==='analysis') state.queue=Object.values(state.analysis.groups).flat().map(i=>i.key);
      return openArtwork(button.dataset.artwork);
    }
    if (button.dataset.zoom) return zoom(button.dataset.zoom,button.dataset.title);
    if (button.dataset.export) return exportData(button.dataset.export);
    if (button.dataset.scoreKey) return setScore(button.dataset.scoreKey,Number(button.dataset.scoreValue));
    if (button.dataset.clear) return setScore(button.dataset.clear,null);
    if (button.dataset.tag) {const tag=button.dataset.tag;state.draft.tags=state.draft.tags.includes(tag)?state.draft.tags.filter(t=>t!==tag):[...state.draft.tags,tag];renderTags();return markDirty();}
    if (button.dataset.removeDirection!==undefined) {state.draft.directions.splice(Number(button.dataset.removeDirection),1);renderDirections();return markDirty();}
    if (button.dataset.analysisTab) {state.analysisTab=button.dataset.analysisTab;document.querySelectorAll('[data-analysis-tab]').forEach(b=>b.classList.toggle('selected',b.dataset.analysisTab===state.analysisTab));remember();return renderAnalysisCards();}
    switch (button.id) {
      case 'quick-undo': await undoQuick();break;
      case 'quick-prev': await navigateQuick(-1);break;
      case 'quick-next': await navigateQuick(1);break;
      case 'quick-detail': await openArtwork(state.quick.key);break;
      case 'prev-page': state.offset=Math.max(0,state.offset-24);await renderGallery();window.scrollTo(0,0);break;
      case 'next-page': state.offset+=24;await renderGallery();window.scrollTo(0,0);break;
      case 'previous-artwork': await navigate(-1);break;
      case 'next-artwork': case 'save-next': await navigate(1);break;
      case 'retry-save': await retrySave();break;
      case 'add-tag': {const tag=$('#custom-tag').value.trim();if(tag && !state.draft.tags.includes(tag)){state.draft.tags.push(tag);renderTags();markDirty();}$('#custom-tag').value='';break;}
      case 'add-direction': state.draft.directions.push({text:'',priority:'medium'});renderDirections();$('#directions textarea:last-child').focus();break;
      case 'defer': state.draft.deferred=!state.draft.deferred;button.textContent=state.draft.deferred?'取消暂缓':'暂缓此图';markDirty();break;
      case 'compare': await compareVersions();break;
      case 'zoom-close': $('#zoom-dialog').close();break;
      case 'compare-close': $('#compare-dialog').close();break;
      case 'download-draft': downloadBlob(JSON.stringify({key:state.detail.key,revision:state.detail.revision,review:state.draft},null,2),'arco-unsaved-draft.json');break;
      case 'download-old-draft': downloadBlob(localStorage.getItem(draftKey(state.detail.key)) || '{}','arco-previous-draft.json');break;
      case 'apply-thresholds': {const high=Number($('#high-threshold').value),low=Number($('#low-threshold').value);if(low>=high)throw new Error('低分上限必须小于高分下限，门槛不能重叠。');state.high=high;state.low=low;state.analysis=null;remember();await renderAnalysis();break;}
      case 'restore': if(await flush()){document.querySelector('.export-menu').open=false;$('#restore-file').click();}break;
      case 'stop-service': if(await flush()){await api('/api/shutdown',{});toast('人评已保存，本机服务已停止。下次双击启动器即可继续。');}break;
      case 'refresh': if(await flush()){button.disabled=true;try{const r=await api('/api/refresh',{});state.analysis=null;await loadMeta(false);await renderView();toast(`归档已刷新，共 ${r.versions} 个版本。`);}finally{button.disabled=false;}}break;
      case 'reset-filters': if(await flush()){state.filters=clone(defaults);state.offset=0;state.analysis=null;controlsFromFilters();remember();await switchView('gallery');}break;
      case 'recent': case 'all-dates': if(await flush()){state.filters.start=button.id==='recent'?defaults.start:'';state.filters.end='';state.offset=0;state.analysis=null;controlsFromFilters();remember();await renderView();}break;
    }
  };
  run().catch(report);
});
document.addEventListener('input',event=>{
  const target=event.target;
  if (target.id==='notes') {state.draft.notes=target.value;markDirty();}
  else if (target.dataset.directionText!==undefined) {state.draft.directions[Number(target.dataset.directionText)].text=target.value;markDirty();}
  else if (target.id==='zoom-range') {$('#zoom-value').textContent=target.value+'%';$('#zoom-image').style.width=(state.zoomBase || 800)*Number(target.value)/100+'px';}
});
document.addEventListener('change',event=>{
  const target=event.target;
  const run=async()=>{
    if (target.id==='decision') {state.draft.decision=target.value || null;markDirty();}
    else if (target.dataset.priority!==undefined) {state.draft.directions[Number(target.dataset.priority)].priority=target.value;markDirty();}
    else if (target.id==='version-select') await openArtwork(target.value);
    else if (target.id==='primary-reference') {const r=state.detail.references.filter(r=>r.scope==='external_how')[Number(target.value)];$('#external-preview-image').src=media(r.asset_id);$('#external-preview-button').dataset.zoom=r.asset_id || '';$('#external-preview-button').dataset.title=r.aliases.join(' / ') || '外部原图';$('#external-preview-caption').textContent=r.duty_labels.join(' · ');}
    else if (target.id==='compare-version') {const v=state.detail.versions.find(i=>i.key===target.value);$('#compare-image').src=media(v.image_asset);$('#compare-image-button').dataset.zoom=v.image_asset;$('#compare-image-button').dataset.title=state.detail.title+' v'+v.version;$('#compare-score').textContent='总分：'+(v.review.scores.overall ?? '未填');}
    else if (['start','end','variant','status','review-state','score','versions'].includes(target.id)) await readFilters();
    else if (target.id==='restore-file' && target.files[0]) {try{await restoreFile(target.files[0]);}finally{target.value='';}}
  };run().catch(report);
});
let searchTimer;
$('#search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>readFilters().catch(report),350);});
document.addEventListener('keydown',event=>{
  if(state.loadingArtwork)return;
  if(state.view==='quick' && !$('dialog[open]') && !event.ctrlKey && !event.metaKey && !event.altKey && !/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) && !event.target.isContentEditable){
    const key=event.key.toLowerCase();
    if(['arrowleft','arrowright','d','k','z',' '].includes(key)){
      event.preventDefault();if(event.repeat || state.quick.busy)return;
      const action=key==='z'?undoQuick():key===' '?navigateQuick(1):classifyQuick(['arrowleft','d'].includes(key)?'discard':'keep');
      action.catch(report);
    }
    return;
  }
  if (event.target.id==='custom-tag' && event.key==='Enter') {event.preventDefault();$('#add-tag').click();return;}
  if (state.view!=='workbench' || !state.detail || $('dialog[open]')) return;
  if ((event.ctrlKey || event.metaKey) && event.key==='Enter') {event.preventDefault();navigate(1).catch(report);return;}
  if (event.ctrlKey || event.metaKey || event.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) || event.target.isContentEditable) return;
  if (/^[1-5]$/.test(event.key)) {event.preventDefault();setScore('overall',Number(event.key));}
  else if (event.key==='0') {event.preventDefault();setScore('overall',null);}
  else if (event.key==='ArrowRight' || event.key==='ArrowLeft') {event.preventDefault();navigate(event.key==='ArrowRight'?1:-1).catch(report);}
});
window.addEventListener('beforeunload',event=>{if(state.dirty || state.savePromise || state.quick.busy){stashDraft();event.preventDefault();event.returnValue='';}});
window.addEventListener('online',()=>{if(state.dirty)retrySave().catch(report);});
document.addEventListener('error',event=>{if(event.target.tagName==='IMG'){event.target.alt='图片缺失或暂时无法读取';event.target.classList.add('image-unavailable');}},true);

async function loadMeta(useSession=true) {
  state.meta=await api('/api/bootstrap');state.token=state.meta.token;
  $('#variant').innerHTML='<option value="">全部服装</option>'+Object.entries(state.meta.variants).map(([k,v])=>`<option value="${h(k)}">${h(v)}</option>`).join('');
  $('#status').innerHTML='<option value="">全部状态</option>'+state.meta.statuses.map(v=>`<option>${h(v)}</option>`).join('');
  $('#refresh-time').textContent='上次读取 '+state.meta.refreshed_at.slice(0,16).replace('T',' ');
  if (useSession && state.meta.session) {
    const s=state.meta.session;state.filters={...defaults,...s.filters};state.lastKey=s.key;
    state.high=s.high || 4;state.low=s.low || 2;state.analysisTab=s.analysisTab || 'high';
    state.view=['quick','gallery','workbench','analysis'].includes(s.view)?s.view:'quick';
    if(s.quick){state.quick.bucket=quickNames[s.quick.bucket]?s.quick.bucket:'pending';state.quick.key=s.quick.key;}
  }
  const hash=location.hash.slice(1).split('/');
  if(useSession && ['quick','gallery','workbench','analysis'].includes(hash[0])){state.view=hash[0];if(hash[1])state.lastKey=hash[1];}
  controlsFromFilters();
  if(state.meta.problems.length)toast(`有 ${state.meta.problems.length} 条归档记录无法读取，详情中可查看。`,true);
}
async function boot() {
  await loadMeta();
  if(state.view==='workbench' && state.lastKey){try{await openArtwork(state.lastKey);return;}catch(error){state.lastKey=null;state.view='gallery';report(error);}}
  await renderView();
}
boot().catch(error=>{$('#main').innerHTML=`<div class="error">${h(error.message)}<p>请确认本机服务正在运行，再刷新页面。</p></div>`;report(error);});
