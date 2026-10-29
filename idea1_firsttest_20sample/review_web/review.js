/* Offline reviewer. No dependencies, requests, telemetry, or model predictions. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const reasons = ['视角 / 遮挡', '状态看不清', '对象身份不明', '缺少必要证据', '问题有歧义', '参考答案有疑问'];
  const labels = {pending: '未审核', pass: '通过', reject: '不通过'};
  const symbols = {pending: '○', pass: '✓', reject: '×'};
  const header = 'Answer each question using the supplied public history, rules, event, and ordered images. Do not infer hidden simulator metadata. For insufficient evidence answer the string "unknown"; for an inapplicable property answer "not_applicable". For answer_mode change_status, use exactly "changed", "preserved", or "unknown". Return only one JSON object mapping every question id to its answer; arrays are allowed for relation lists. Do not add Markdown or explanations.';
  const mechanismQuestions = {F1:'触发动作的顺序是否改变结果？', F2:'事件的实际作用边界是什么，哪些对象或事实受影响？', F3:'多个对象是否保持各自独立的状态变化？', F4:'温度与熟度是否被分开记录和推断？', F5:'清洁状态与注液状态是否被分开记录和推断？', F6:'咖啡液体相关机制是否受其门控条件约束？', F7:'当前承载关系是否决定对象随承载物变化？', F8:'旋钮操作是否只映射到对应炉头？', F9:'时间推进的背景演化是否与事件直接效果区分？', F10:'本项指定的嵌套关系链是否成立？', F11:'两个可能的支撑来源是否构成替代关系？'};
  let batches = [], current = null, questions = [], selected = null, review = {}, saved = true;
  const json = obj => JSON.stringify(obj, null, 2);
  const canonical = value => Array.isArray(value) ? `[${value.map(canonical).join(',')}]` : value && typeof value==='object' ? `{${Object.keys(value).sort().map(k=>`${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}` : JSON.stringify(value);
  const mediaIssues = item => (item.frames||[]).filter(f=>!f.src || (f.source_status && f.source_status!=='available'));
  function notice(text) { $('notice').textContent = text; $('notice').hidden = !text; }
  function el(tag, text, className) { const node = document.createElement(tag); if(text !== undefined) node.textContent = text; if(className) node.className = className; return node; }
  // Keep every public model_input field. New frozen hard requests are authoritative
  // and must not be rebuilt through the legacy schema adapter.
  function payload(mi) { return mi; }
  function storageKey() { return `scene-review-${current.review_revision || 'v1'}:${current.id}`; }
  function validEntry(value) {
    return value && Object.hasOwn(labels,value.status) && typeof value.reason === 'string' && Array.isArray(value.tags) && value.tags.every(t => typeof t === 'string');
  }
  function loadReview() {
    review = Object.create(null); saved = true;
    try {
      const raw = localStorage.getItem(storageKey());
      if(raw) {
        const data = JSON.parse(raw);
        if(data.batch_id !== current.id) throw Error('批次标识不匹配');
        for(const q of questions) if(validEntry(data.entries?.[q.key])) review[q.key] = data.entries[q.key];
      }
      $('save-state').textContent = '自动保存在本浏览器';
    } catch(e) { saved = false; $('save-state').textContent = '浏览器保存不可用，请导出结果'; notice(`未能读取浏览器审核记录：${e.message}。请使用导出 / 恢复审核。`); }
  }
  function envelope() { return {schema:'scene-review-decisions/v1',batch_id:current.id,batch_name:current.name,review_revision:current.review_revision || 'v1',exported_at:new Date().toISOString(),entries:review}; }
  function persist() {
    try { localStorage.setItem(storageKey(),JSON.stringify(envelope())); saved = true; $('save-state').textContent = '已自动保存 · 结束后可导出'; }
    catch(e) { saved = false; $('save-state').textContent = '保存失败 · 请立即导出'; notice(`浏览器未能保存：${e.message}。当前选择仍在页面中，请导出后再关闭。`); }
  }
  function entry(key) { return review[key] || {status:'pending',reason:'',tags:[]}; }
  function filtered() {
    const term = $('search').value.trim().toLowerCase(), filter = $('filter').value;
    return questions.filter(q => (filter === 'all' || (filter === 'source_problem' ? mediaIssues(q.item).length>0||q.item.kind==='diagnostic' : entry(q.key).status === filter)) && `${q.item.label} ${q.id} ${q.text}`.toLowerCase().includes(term));
  }
  function drawNav() {
    const nav = $('items'); nav.replaceChildren();
    for(const q of filtered()) {
      const e = entry(q.key), button = el('button'); button.type = 'button'; button.setAttribute('aria-current',String(q === selected));
      button.append(el('span',symbols[e.status],`status-symbol ${e.status}`));
      const label = el('span',q.item.presentation?.title || q.item.label,'label'); label.append(el('small',q.item.kind === 'dataset' ? `${q.item.label} · ${q.id}` : q.item.label)); if(q.item.kind==='diagnostic')label.append(el('small','失败诊断 · 未发布正式题目'));if(q.item.request_origin==='prepared')label.append(el('small','待发送 · 尚未调用模型'));const bad=mediaIssues(q.item).length;if(bad)label.append(el('small',`图片来源异常 ${bad} 项`));if(q.item.protocol==='hard-selective-V/v1')label.append(el('small','V 视觉证据 · 主审候选'));if(q.item.protocol==='hard-selective-S/v1')label.append(el('small','S 文本状态诊断 · 配对对照'));button.append(label);
      button.addEventListener('click',() => choose(q)); nav.append(button);
    }
    const counts = {pending:0,pass:0,reject:0}; for(const q of questions) counts[entry(q.key).status]++;
    $('progress').textContent = `${questions.length} 项 · 未审 ${counts.pending} · 通过 ${counts.pass} · 不通过 ${counts.reject}`;
    if(!nav.children.length) nav.append(el('p','没有符合筛选条件的题目。'));
    const visible=filtered(),index=visible.indexOf(selected);$('prev').disabled=index<=0;$('next').disabled=!visible.length||index>=visible.length-1;
  }
  function renderDecisions() {
    if(!selected) return;
    const e = entry(selected.key);
    for(const status of ['pending','pass','reject']) $(status).setAttribute('aria-pressed',String(e.status === status));
    $('decision-status').textContent = labels[e.status];
    $('reason').value = e.reason;
    $('decision-hint').textContent = e.status === 'reject' && !e.reason.trim() && !e.tags.length ? '请补充不通过的原因，方便修订。' : selected.item.kind==='diagnostic' ? '这是生成完整性诊断，不是正式题目；审核意见不会把它变成已发布题目。' : (selected.item.presentation?'审核的是本页场景、候选题意和图片证据；旧版仅看截图的意见仍保留，未自动套用。':'审核意见不会删除原始数据，也不会自动批准模型评测。');
    $('reasons').replaceChildren();
    for(const tag of reasons) {
      const button = el('button',tag); button.type='button'; button.setAttribute('aria-pressed',String(e.tags.includes(tag)));
      button.addEventListener('click',() => { const old = entry(selected.key); const tags = old.tags.includes(tag) ? old.tags.filter(t=>t!==tag) : [...old.tags,tag]; update({tags,status:tags.length?'reject':old.status}); });
      $('reasons').append(button);
    }
  }
  function update(change) {
    if(!selected) return;
    review[selected.key] = {...entry(selected.key), ...change, sample_id:selected.item.label, question_id:selected.id, updated_at:new Date().toISOString()};
    persist(); renderDecisions(); drawNav();
  }
  function drawImages(item) {
    $('images').replaceChildren();
    $('image-title').textContent = item.kind === 'dataset' ? '模型看到的图片（原顺序）' : item.kind==='diagnostic' ? 'agent 主视角诊断采集（不属于模型输入）；同步调试视角见下方分组时间线' : '候选图片与每张图的用途（原顺序）';
    const available=item.frames.filter(f=>!!f.src).length;
    $('image-count').textContent = item.protocol==='hard-selective-S/v1' ? '本条件为文本状态诊断，不提供图像；全过程画面仅在下方私有审计区查看' : `${available} 张可查看 / ${item.frames.length} 个画面项 · 点击看原图`;
    item.frames.forEach((frame,i) => {
      const note=item.presentation?.frame_notes?.[i];
      const boundaries=Array.isArray(frame.boundary_labels)?frame.boundary_labels.filter(Boolean).join(' / '):'';
      const figure=el('figure'),meta=[boundaries,frame.run_length!=null?`原有 ${frame.run_length} 张`:'',frame.duplicate_count!=null?`完全重复 ${frame.duplicate_count} 张`:'',frame.start_step!=null||frame.end_step!=null?`步骤 ${frame.start_step??'?'}–${frame.end_step??'?'}`:'',frame.capture_group_index!=null?`同一时刻组 ${frame.capture_group_index}`:'',frame.view_id?`视角 ${frame.view_id}`:''].filter(Boolean).join(' · ');
      const caption=note ? `${i+1} / ${item.frames.length} · ${note.purpose}${meta?` · ${meta}`:''}` : `${i+1} / ${item.frames.length} · ${frame.stage || '未标注阶段'}${meta?` · ${meta}`:''}`;
      const identityRegions=item.protocol==='hard-selective-V/v1'?(item.model_input?.initial_identity_regions||[]).filter(region=>Number(region.initial_frame_index)===i+1&&region.view_id===frame.view_id&&validIdentityRegion(region)) : [];
      if(frame.src) {
        const button=el('button'), image=el('img'); button.type='button';button.setAttribute('aria-label',`放大：${caption}`);
        image.src=frame.src;image.alt=caption;image.loading='lazy';image.decoding='async';
        image.addEventListener('error',()=>{button.replaceWith(el('div','图片读取失败：请检查审核包是否完整。','missing'));});
        if(identityRegions.length){
          const wrap=el('span',undefined,'frame-image-wrap'),overlay=document.createElementNS('http://www.w3.org/2000/svg','svg');overlay.classList.add('identity-overlay');overlay.setAttribute('aria-hidden','true');
          wrap.append(image,overlay);button.append(wrap);
          const draw=()=>drawIdentityOverlay(overlay,image,identityRegions);image.addEventListener('load',draw);if(image.complete)draw();
        } else button.append(image);
        button.addEventListener('click',()=>{ $('large-image').src=frame.src; $('large-image').alt=caption; $('lightbox-label').textContent=caption; $('lightbox').showModal(); });figure.append(button);
      } else {
        const title=frame.source_status==='generation_failed'?'原始图片生产失败':frame.source_status==='file_missing'?'原始文件缺失':frame.source_status==='invalid_path'?'原始路径不兼容':'原始记录没有可用图片';
        const box=el('div',title,'missing');box.append(el('small',frame.source_message||'此处证据不完整；旧网页包没有记录缺失原因。'));figure.append(box);
      }
      const text=el('figcaption',caption);if(note?.process)text.append(el('span',note.process,'frame-process'));if(identityRegions.length)text.append(el('span',identityRegions.some(r=>r.anchor_kind==='first_public_pickup')?'首次拿取身份框对应公开命名规则，原图未修改。':'初态身份框仅辅助显示输入文本中已有的定位信息，原图未修改。','identity-caption'));figure.append(text);$('images').append(figure);
      const map=item.protocol==='hard-selective-V/v1'?(item.audit_timeline?.public_frame_map||[]).find(m=>m.frame_index===i+1):item.kind==='diagnostic'?frame:null;
      if(map){
        const labels=(item.audit_timeline?.checkpoints||[]).flatMap(cp=>(cp.evidence||[])
          .filter(e=>stepMatches(map,e.global_step)).map(e=>`${cp.id} · ${e.label}`));
        if(labels.length)text.append(el('span',`审核检查点（私有标记）：${[...new Set(labels)].join('；')}`,'checkpoint-badge'));
      }
    });
    if(!item.frames.length) $('images').append(el('div',item.protocol==='hard-selective-S/v1'?'本条件有意不提供图像；S 是文本状态诊断。请勿把私有审计画面当作模型输入。':item.kind==='diagnostic'?`本次尝试在“${item.scene||'未标注阶段'}”停止，状态：${item.status||'未记录'}。${item.error||'未记录具体失败原因。'}${item.timeline_status==='missing'?' 原生时间线缺失，无法确认更具体的停止步骤。':item.timeline_status==='no_frames'?' 已找到时间线，但没有可显示的原生帧。':' 请在下方诊断记录核对停止点及未完成的预定后续步骤。'}`:'此记录没有截图。',item.protocol==='hard-selective-S/v1'?'':'missing'));
  }
  function stepMatches(group,step) {
    if(step==null)return false;
    return Array.isArray(group.step_numbers)&&group.step_numbers.length?group.step_numbers.includes(step):
      group.start_step!=null&&group.end_step!=null&&step>=group.start_step&&step<=group.end_step;
  }
  function drawCheckpoints(item) {
    document.getElementById('checkpoint-review')?.remove();
    const points=item.audit_timeline?.checkpoints||[];if(!points.length)return;
    const panel=el('details');panel.id='checkpoint-review';panel.className='private-audit';panel.open=true;
    panel.append(el('summary','程序检查点与对应图片（私有审核，不属于模型输入）'),
      el('p','按编号对照设计、状态与画面。程序通过仅代表列出的字段和图片完整性通过；杯口、液面、流水位置关系及身份连续性仍需人工审核。未执行的节点没有结果。'));
    const status={passed:'程序通过，视觉待审核',failed:'失败',running:'执行中断',not_executed:'未执行'};
    for(const cp of points){
      const detail=el('details');detail.className='checkpoint-row';detail.open=cp.status==='failed';
      detail.append(el('summary',`${cp.id} · ${cp.title} · ${cp.public?'公开历史/目标':'私有准备'} · ${status[cp.status]||cp.status}`));
      if(cp.error)detail.append(el('p',cp.error,'source-warning'));
      const table=el('table'),head=el('tr');for(const name of ['检查项','预期','实际','结果'])head.append(el('th',name));table.append(head);
      for(const f of cp.facts||[]){const tr=el('tr');for(const value of [f.fact,json(f.expected),json(f.actual),f.passed?'通过':'失败'])tr.append(el('td',value));table.append(tr);}
      if((cp.facts||[]).length)detail.append(table);
      const images=el('div','','checkpoint-images');
      for(const e of cp.evidence||[]){
        const group=(item.audit_timeline.capture_groups||[]).find(g=>stepMatches(g,e.global_step));
        const view=group?.views?.find(v=>v.view_id==='agent');
        const figure=el('figure');figure.append(el('figcaption',`${e.label} · 全局步 ${e.global_step??'?'}${group?.duplicate_count?` · 与同组图片共用文件，重复${group.duplicate_count}次`:''}`));
        if(view?.src){const button=el('button');button.type='button';const img=el('img');img.src=view.src;img.alt=e.label;img.loading='lazy';button.append(img);button.addEventListener('click',()=>{$('large-image').src=view.src;$('lightbox-label').textContent=e.label;$('lightbox').showModal();});figure.append(button);}
        else figure.append(el('p','检查点没有匹配到可用的实际图片，不能用相邻图片补齐。','source-warning'));
        images.append(figure);
      }
      detail.append(images);
      const raw=el('details');raw.append(el('summary','原生回执和完整状态（私有）'),el('pre',json({native_receipts:cp.native_receipts,state:cp.state,inventory:cp.inventory,observation_samples:cp.observation_samples})));detail.append(raw);panel.append(detail);
    }
    $('images').parentElement.insertAdjacentElement('beforebegin',panel);
  }
  function validIdentityRegion(region) {
    const box=region?.pixel_bbox;
    return Array.isArray(box)&&box.length===4&&box.every(Number.isFinite)&&box[2]>box[0]&&box[3]>box[1]&&typeof region.alias==='string'&&region.alias.length>0;
  }
  function drawIdentityOverlay(svg,image,regions) {
    if(!image.naturalWidth||!image.naturalHeight)return;
    svg.replaceChildren();svg.setAttribute('viewBox',`0 0 ${image.naturalWidth} ${image.naturalHeight}`);svg.setAttribute('preserveAspectRatio','xMidYMid meet');
    for(const region of regions){
      if(!validIdentityRegion(region))continue;
      const [x1,y1,x2,y2]=region.pixel_bbox,rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
      rect.setAttribute('x',x1);rect.setAttribute('y',y1);rect.setAttribute('width',x2-x1);rect.setAttribute('height',y2-y1);rect.setAttribute('class','identity-box');svg.append(rect);
      const label=document.createElementNS('http://www.w3.org/2000/svg','text');label.setAttribute('x',x1);label.setAttribute('y',Math.max(14,y1-4));label.setAttribute('class','identity-label');label.textContent=region.alias;svg.append(label);
    }
  }
  function drawScenario(item) {
    const p=item.presentation;$('scenario').hidden=!p;$('raw-panel').hidden=!p;
    if(!p)return;
    $('raw-panel').querySelector('details').hidden=false;
    $('scene-initial').textContent=p.initial;
    $('scene-steps').replaceChildren(...(p.steps||[]).map(s=>el('li',s)));
    $('scene-purpose').textContent='本条要确认：'+p.purpose;
    $('scene-questions').replaceChildren(...(p.questions||[]).map((q,i)=>el('p',`${i+1}. ${q.text}`)));
    $('scene-answer-content').replaceChildren();
    for(const [i,q] of (p.questions||[]).entries()){
      $('scene-answer-content').append(el('p',`${i+1}. ${q.answer_status==='observed'?'本次实测：':'未形成可计分答案：'}${q.answer_text || '没有完成对应测量，不能用设计预期补答案。'}`));
      if(q.answer_basis)$('scene-answer-content').append(el('small','依据：'+q.answer_basis));
    }
    $('scene-answers').open=true;
    $('scene-visual').replaceChildren(...(p.visual_requirements||[]).map(s=>el('li',s)));
    $('raw-note').textContent='下面是本页据以整理说明的原始文件。它们属于私有审核依据，不会因为出现在这里就变成模型可见信息。';
    $('raw-links').replaceChildren();
    for(const file of item.raw_files||[]){const li=el('li'),a=el('a',file.label);a.href=file.path;a.target='_blank';a.rel='noopener';li.append(a);$('raw-links').append(li);}
    $('raw-presentation').textContent=json(p);
    $('raw-panel').open=false;
  }
  function drawHardContext(item,q) {
    document.getElementById('hard-context')?.remove();
    if(item.kind!=='dataset'||!item.protocol?.startsWith('hard-selective-'))return;
    const mi=item.model_input||{}, card=el('section');card.id='hard-context';card.className='hard-context';
    const isS=item.protocol==='hard-selective-S/v1';
    card.append(el('h2',isS?'S 条件：文本状态诊断':'V 条件：视觉证据主审'));
    const objects=(mi.objects||[]).map(o=>`${o.alias}（${o.object_type||'对象'}）`).join('、');
    const state=(mi.state_before_event||[]).length?mi.state_before_event:(mi.initial_state_declarations||[]);
    const describe=x=>typeof x==='string'?x:`${x.subject||'?'} · ${x.predicate||'?'} = ${typeof x.value==='string'?x.value:json(x.value)}`;
    card.append(el('p',`场景：${item.audit_timeline?.title||item.label.replace(/_[VS]$/,'')}。参与对象：${objects||'冻结输入未列出对象'}。`));
    card.append(el('p',`事件前状态：${state.length?state.map(describe).join('；'):'冻结输入未提供结构化事件前状态'}。`));
    const event=mi.event||{};
    card.append(el('p',isS?`目标事件：${event.action||'未记录'}；主体 ${event.subject||'未记录'}；${event.destination?`放置目标 ${event.destination}；`:''}${event.success===true?'记录为成功':event.success===false?'记录为失败':'成功状态未记录'}。`:`目标事件：${event.source||'按冻结视觉输入确定'}。`));
    card.append(el('p',`当前问题：${q.text||q.question||'未记录问题'}${q.fact_id?`（${q.fact_id}）`:''}`));
    const agentOnly=(mi.frames||[]).every(f=>f.view_id==='agent');
    card.append(el('p',isS?'S 是有意设置的纯文本状态诊断：模型输入确实没有图像，也没有历史；下方“精确模型输入”保留冻结文本。私有逐步画面仅供审计，不能算作 S 的模型证据。':agentOnly?'V 是视觉证据主审：上方按模型顺序展示 agent 视角图像；同一时刻的其他视角只在私有同步时间线上用于审核，不能视作模型看过的画面。':'这是旧版多视角 V 输入，公开画面包含第三方视角，不能视为新版纯第一人称数据。原始冻结输入仍完整保留；需重新生成才能满足新的视角要求。'));
    const pair=current?.items?.find(x=>x!==item&&x.kind==='dataset'&&x.label.replace(/_[VS]$/,'')===item.label.replace(/_[VS]$/,''));
    if(pair){const link=el('button',`打开配对 ${pair.protocol==='hard-selective-V/v1'?'V 视觉条件':'S 文本状态诊断'}：${pair.label}`);link.type='button';link.className='pair-link';link.addEventListener('click',()=>{const target=questions.find(row=>row.item===pair);if(target)choose(target);});card.append(link);}
    $('question').parentElement.parentElement.insertAdjacentElement('afterend',card);
  }
  function choose(q) {
    selected=q; $('empty').hidden=true;$('detail').hidden=false;
    const item=q.item, isDataset=item.kind==='dataset', isDiagnostic=item.kind==='diagnostic', p=item.presentation;
    $('item-id').textContent=`${current.name} / ${item.label}${isDataset?' / '+q.id:''}`;
    $('question').textContent=q.text;
    $('decision-title').textContent=isDiagnostic?'这条失败尝试的采集记录是否可读？':isDataset?'这题是否可用？':p?'这条候选题的场景与图片是否足够？':'这组诊断截图是否清楚？';
    $('question-extra').textContent=isDiagnostic ? `case_id: ${item.case_id} · 场景: ${item.scene||'未记录'} · 状态: ${item.status||'未记录'}\n失败原因：${item.error||'没有记录具体原因。'}${item.timeline_status==='missing'?'\n没有找到对应的原生采集时间线。':item.timeline_status==='no_frames'?'\n找到时间线，但没有可用帧。':item.timeline_status==='sample_id_mismatch'?'\n时间线中的 case_id 与本次失败尝试不一致。':''}` : isDataset ? `${q.subject} · ${q.predicate} · answer_mode: ${q.answer_mode}${item.questions.length>1?'\n本次请求共 '+item.questions.length+' 题；下方保留完整输入，未删去其他题。':''}` : p?'下面先说明完整过程，再逐张核对所需证据。':'此条尚缺具体场景说明，请先生成说明包。';
    if(isDiagnostic){const logged=(item.audit_timeline?.steps||[]).filter(s=>s&&typeof s==='object'&&(s.action||s.capture_label));const last=logged.at(-1);const planned=item.planned_next_steps||[];$('question-extra').textContent+=`\n停止位置：${last?`${last.phase_label||''}${last.action?` · ${last.action}`:''}${last.capture_label?` · ${last.capture_label}`:''}`:'没有可确认的最后记录步骤'}。\n预定后续步骤：${planned.length?planned.map(x=>typeof x==='string'?x:json(x)).join('；'):'生成记录未提供预定后续步骤，不能据设计预期补写。'}`;}
    drawHardContext(item,q);
    $('boundary').className='boundary'+(isDataset?'':' warning');
    $('boundary').textContent=isDiagnostic ? '这是生成失败诊断，不是已发布题目；没有模型请求、正式问题或 Gold。下方图片仅用于查看本次尝试保留下来的采集证据。' : isDataset ? (item.request_origin==='prepared'?'逐字冻结的待发送输入，且对应公开记录与图片哈希均匹配。状态为 prepared_not_sent：尚未调用模型。':item.request_origin==='recorded'?'已有本次运行保存的请求文本；图片按保存的公开输入顺序排列。':'此旧批次未保存最终请求文本。下方按当前 runner 重建，不能视为历史逐字原文。') : '本批次没有调用模型，没有 prompt 或正式问题。以下只审核诊断截图，不能据此批准一条正式模型题。';
    if(p)$('boundary').textContent=p.draft_warning;
    if(isDataset&&item.request_origin==='prepared') {
      $('boundary').classList.add('warning');
      $('boundary').textContent=`${item.protocol==='hard-selective-S/v1'?'S 文本状态诊断':'V 视觉历史条件'} · 待发送输入已冻结并通过哈希核对；prepared_not_sent 表示没有模型调用，当前需要人工逐题审核。`;
    } else if(isDataset&&item.request_origin==='recorded'&&item.request_run_status!=='complete') {
      $('boundary').classList.add('warning');
      $('boundary').textContent='该次运行没有完成。下方是已留档的请求构造文本，不能由此证明模型已经成功收到或处理这些输入。';
    }
    const issues=mediaIssues(item), generated=issues.filter(f=>f.source_status==='generation_failed').length;
    const invalidNative=item.native_measurement_valid===false;
    const missingDiagnosticFilm=isDiagnostic&&(!item.frames.length||item.timeline_status!=='available');
    const intentionalS=isDataset&&item.protocol==='hard-selective-S/v1';
    $('media-warning').hidden=!issues.length&&!invalidNative&&!missingDiagnosticFilm&&!intentionalS;
    $('media-warning').textContent=(intentionalS?'S 条件按设计不含图像；这是文本状态诊断，不表示采集故障。':'')+(issues.length?`源数据图片不完整：本条 ${issues.length} 个画面项异常${generated?`，其中 ${generated} 项为服务器未能生成/采纳图片`:''}。重建网页不能补出未生成的图。`:'')+(missingDiagnosticFilm?' 生成失败诊断缺少完整原生采集时间线或帧，批次已标记为 source_incomplete。':'')+(invalidNative?' 本条原生机制测量也被运行记录标记为无效，不能采用这里的结果作为机制标准答案。':'');
    drawScenario(item);
    if(isDiagnostic){
      $('raw-panel').hidden=false;$('raw-panel').open=false;
      $('raw-panel').querySelector('summary').textContent='私有采集时间线与逐步动作（按需查看）';
      $('raw-note').textContent='以下内容只用于检查失败尝试的原生采集过程，不属于正式题目或模型输入。';
      $('raw-links').replaceChildren();
      $('raw-panel').querySelector('details').hidden=true;$('raw-presentation').textContent='';
    }
    drawImages(item);
    drawCheckpoints(item);
    $('prompt-panel').hidden=isDiagnostic||(!isDataset&&!p);
    $('prompt-panel').open=isDataset;
    $('prompt-title').textContent=p?'候选模型输入全文（新整理的文本，可直接审阅）':item.request_origin==='prepared'?'冻结的完整模型输入文本':item.request_origin==='recorded'?'模型输入原文':'模型输入（当前 runner 重建）';
    $('prompt-note').textContent=isDataset ? (item.protocol==='hard-selective-S/v1'?'S 条件的冻结文本状态输入；不提供图像。下方私有采集轨迹已折叠，不属于模型输入。':item.request_origin==='prepared'?'以下为冻结的完整公开输入文本；上方按原顺序展示公开模型图片。下方私有采集轨迹不属于模型输入。':'请求顺序：全部图片在前，以下文本在后。含公开历史、规则、事件和全部问题；不含隐藏模拟器状态。未展示 processor 缩放、patch 或聊天模板展开。') : '';
    if(p)$('prompt-note').textContent='尚未实际调用模型，也不要求先调用模型。此草案列出随题提供的初态和操作，不包含下面的参考答案；全部候选图片按页面顺序提供。未完成的探测暂不形成正式题。';
    $('prompt').textContent=p?p.draft_prompt:item.request_text || (item.request_origin==='prepared'?json(item.model_input):'');
    drawAuditTimeline(item,isDiagnostic?$('raw-panel'):$('prompt-panel'));
    $('reference-panel').open=false;
    $('reference-panel').hidden=false;
    $('reference').replaceChildren();
    if(isDiagnostic){
      $('reference-panel').hidden=true;
    }else if(p){
      $('reference-panel').querySelector('summary').textContent='本次机制观察与限制（按需查看）';
      $('reference').append(...(p.observed||[]).map(s=>el('p',s)));
    }else if(!isDataset) {
      $('reference-panel').hidden=false;
      $('reference-panel').querySelector('summary').textContent='机制脚本结果（按需查看，不代表人工通过）';
      $('reference').append(el('p',`原始状态：${item.status || '未记录'}`),el('p',item.error || ''),el('pre',json(item.checks || [])));
    } else {
      $('reference-panel').hidden=false;
      $('reference-panel').querySelector('summary').textContent='核对参考答案（不属于模型输入）';
      const answer=item.references?.find(a=>a.question_id===q.id);
      if(answer) $('reference').append(el('p',`参考答案：${json(answer.expected_answer)}`),el('p','来源：对应 hidden_gold.query_targets。它是待审核标签；仅凭标签本身不能证明题目有足够证据。'));
      else $('reference').append(el('p','本包没有附上该题参考答案。可以先审查输入是否足以推出答案；要完成标签正确性审核，还需核对对应 Gold。'));
    }
    renderDecisions(); drawNav();
    const visible=filtered(), index=visible.indexOf(q);$('prev').disabled=index<=0;$('next').disabled=index<0||index===visible.length-1;
  }
  function drawAuditTimeline(item,target=$('prompt-panel')) {
    document.getElementById('private-audit')?.remove();
    if(!item.audit_timeline)return;
    const details=el('details');details.id='private-audit';details.className='private-audit';
    details.append(el('summary',item.protocol?.startsWith('hard-selective-')?'私有同步时间线与全程采集（不属于模型输入）':'完整私有采集轨迹（不属于模型输入）'));
    details.append(el('p','这里保留准备/校准、公开历史、目标事件和观察窗口的过程标记、逐步动作记录及精确去重信息。默认折叠；不得将这些私有动作转录当作 V 条件的模型可见历史。'));
    const timeline=item.audit_timeline;
    details.open=!!((item.protocol?.startsWith('hard-selective-')||item.kind==='diagnostic')&&(timeline.capture_groups||[]).length);
    if((timeline.capture_groups||[]).length){
      details.append(el('h3','同步视角 · 按同一时刻成组展示'));
      details.append(el('p','每张卡片对应同一全局步的同步采集。左右并列视角不是连续视频帧；只有 agent 视角属于 V 的模型输入，其余视角仅供人工审计。'));
      for(const [i,group] of timeline.capture_groups.entries()){
        const section=el('section','','capture-group');
        const phase=group.phase_label?` · ${group.phase_public?'公开历史/目标':'私有准备'}${group.phase_kind?`/${group.phase_kind}`:''} · ${group.phase_label}`:'';
        section.append(el('h4',`时刻组 ${group.capture_group_index??i} · 全局步 ${group.global_step??group.start_step??'?'}${phase}`));
        if(group.frame_status) section.append(el('p',`采集状态：${group.frame_status}${group.run_length?` · 稳定去重 ${group.run_length} 次、重复 ${group.duplicate_count??0} 次`:''}`));
        const views=el('div','','capture-views');
        for(const view of group.views||[]){
          const figure=el('figure','',`capture-view ${view.view_id==='agent'?'agent-view':'debug-view'}`);
          const viewName=view.view_id==='agent'?(item.protocol==='hard-selective-V/v1'&&group.phase_public?'第一人称（V公开输入）':'第一人称（调试采集）'):view.purpose==='distant_room_overview'?'远景（仅调试）':view.purpose==='H03_stovetop_detail'?'灶台局部（仅调试）':view.purpose==='H05_contents_oblique_detail'?'微波炉与土豆局部（仅调试）':'补充视角（仅调试）';
          figure.append(el('strong',viewName));
          if(view.src){const img=el('img');img.src=view.src;img.alt=`时刻组 ${group.capture_group_index??i} ${view.view_id||''}`;img.loading='lazy';figure.append(img);}else figure.append(el('div',view.status||'该同步视角没有可用图像','missing'));
          if(view.sha256)figure.append(el('small',`SHA-256 ${view.sha256}`));views.append(figure);
        }
        section.append(views);details.append(section);
      }
    }
    for(const [i,frame] of ((timeline.capture_groups||[]).length?[]:(timeline.frames||[])).entries()) {
      const figure=el('figure','', 'audit-frame'),caption=`私有帧 ${i+1} · ${frame.stage||'未标注阶段'}${frame.view_id?` · 视角 ${frame.view_id}`:''}`;
      if(frame.src){const img=el('img');img.src=frame.src;img.alt=caption;img.loading='lazy';figure.append(img);} else figure.append(el('div','审计帧文件缺失','missing'));
      const meta=[frame.start_step!=null||frame.end_step!=null?`步骤 ${frame.start_step??'?'}–${frame.end_step??'?'}`:'',frame.run_length!=null?`原有 ${frame.run_length} 张`:'',frame.duplicate_count!=null?`重复 ${frame.duplicate_count} 张`:''].filter(Boolean).join(' · ');
      figure.append(el('figcaption',meta?`${caption} · ${meta}`:caption));details.append(figure);
    }
    if((timeline.boundaries||[]).length){details.append(el('h3','阶段与动作边界'));const list=el('ul');for(const b of timeline.boundaries)list.append(el('li',`步骤 ${b.step_index??b.global_step??'?'} · ${b.label||''}${b.kind?`（${b.kind}）`:''}`));details.append(list);}
    if((timeline.steps||[]).length){
      details.append(el('h3','逐步动作记录'));const list=el('ol');
      for(const step of timeline.steps){
        if(typeof step==='string'){list.append(el('li',step));continue;}
        if(step&&typeof step==='object'&&('global_step'in step||'action'in step||'capture_label'in step)){
          const phase=step.phase_label?`${step.phase_public?'公开':'私有'} · ${step.phase_label} · `:'';
          const action=step.action?`${step.action}${Object.keys(step.action_kwargs||{}).length?` ${json(step.action_kwargs)}`:''}`:'';
          const outcome=step.lastActionSuccess===false?' · 原生动作失败':step.native_exception?' · 原生异常':step.frame_status&&step.frame_status!=='captured'?` · 采集状态 ${step.frame_status}`:'';
          list.append(el('li',`步骤 ${step.global_step??'?'} · ${phase}${step.capture_label||action||'检查点'}${step.capture_label&&action?` · ${action}`:''}${outcome}`));
        } else list.append(el('li',json(step)));
      }
      details.append(list);
    }
    target.append(details);
  }
  function move(delta) { const list=filtered(); if(!list.length)return;const index=list.indexOf(selected), next=index+delta; if(next>=0&&next<list.length) {choose(list[next]);window.scrollTo({top:0,behavior:'instant'});} }
  function normalizeBatch(batch) {
    if(batch.schema!=='scene-review-batch/v1'||!batch.id||!Array.isArray(batch.items)) throw Error('不支持的批次格式');
    const seen=new Set();
    for(const item of batch.items) {
      if(!item.id||seen.has(item.id))throw Error('记录标识缺失或重复');seen.add(item.id);
      if(item.kind==='dataset') {
        const built=payload(item.model_input);
        if(item.request_origin!=='recorded'&&item.request_origin!=='prepared') {item.request_origin='reconstructed'; item.request_text=header+'\n\n'+json(built);}
        item.questions=(built.questions||[]).map((q,i)=>({...q,id:q.id||q.question_id||`q${String(i+1).padStart(3,'0')}`,question:q.question||q.text||''}));
      } else if(item.kind==='mechanism'||item.kind==='diagnostic') item.questions=[];
      else throw Error('未知记录类型');
    }
    return batch;
  }
  function addBatch(batch) {
    batch=normalizeBatch(batch);
    const existing=batches.findIndex(b=>b.id===batch.id);
    if(existing>=0){if(batch._objectURLs)batch._objectURLs.forEach(URL.revokeObjectURL);switchBatch(batch.id);return;}
    batches.push(batch);const option=el('option',batch.name);option.value=batch.id;$('batch').append(option);switchBatch(batch.id);
  }
  function switchBatch(id) {
    current=batches.find(b=>b.id===id);$('batch').value=id;questions=[];
    if(!current)return;
    for(const item of [...current.items].sort((a,b)=>({'hard-selective-V/v1':0,'hard-selective-S/v1':1}[a.protocol]??2)-({'hard-selective-V/v1':0,'hard-selective-S/v1':1}[b.protocol]??2))) {
      if(item.kind==='dataset') for(const q of item.questions) questions.push({...q,text:q.question,key:`${item.id}/${q.id}`,item});
      else if(item.kind==='diagnostic') questions.push({id:'diagnostic',text:'生成尝试未发布为正式题目',key:`${item.id}/diagnostic`,item});
      else questions.push({id:item.presentation?'scenario-v2':'visual',text:item.presentation?.title||mechanismQuestions[item.fact_id]||'检查本项诊断截图是否足以看清目标状态。',key:`${item.id}/${item.presentation?'scenario-v2':'visual'}`,item});
    }
    $('search').value='';$('filter').value='all';notice('');loadReview();
    const broken=current.items.reduce((n,item)=>n+mediaIssues(item).length,0), invalidNative=current.items.filter(item=>item.native_measurement_valid===false).length;
    const diagnosticCount=current.items.filter(item=>item.kind==='diagnostic').length;
    if(diagnosticCount)notice(`source_incomplete：当前批次有 ${diagnosticCount} 次未发布生成尝试。每页会说明停止阶段、已记录的失败原因和未完成的采集步骤；这些诊断不计入正式题目。${broken?`另有 ${broken} 个原始媒体异常。`:''}${invalidNative?`另有 ${invalidNative} 条原生测量被记录为无效。`:''}`);
    else if(current.source_media_status==='source_incomplete')notice('source_incomplete：该批次存在未完成的源数据或生成尝试。查看具体诊断页中的停止阶段、失败原因和缺失的后续采集步骤；不要将批次视为已完整生成。');
    else if(broken||invalidNative)notice(`当前批次原始媒体异常 ${broken} 项${invalidNative?`，另有 ${invalidNative} 条原生测量被记录为无效`:''}。页面用于诊断，不能当作完整可用数据。请看每条顶部和图片框内的具体原因。`);
    else if(current.review_revision)notice('本版新增了具体场景和候选问题，审核范围已扩大。旧版截图意见保留在原浏览器存储中；本版单独记录，不自动当作题目通过。');
    selected=null;
    if(questions.length)choose(questions[0]);else{$('detail').hidden=true;$('empty').hidden=false;drawNav();}
  }
  async function sha(bytes) {
    if(!globalThis.crypto?.subtle) throw Error('浏览器不支持本地 SHA-256，请用新版 Chrome / Edge 打开');
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  }
  function safeRelative(base,relative,boundary) {
    if(typeof relative!=='string'||!relative||/^([a-z]:|[\\/])/i.test(relative))return null;
    const parts=(base+relative.replaceAll('\\','/')).split('/'), stack=[];
    for(const p of parts){if(!p||p==='.')continue;if(p==='..'){if(!stack.length)return null;stack.pop();}else stack.push(p);}
    const path=stack.join('/');return path.startsWith(boundary)?path:null;
  }
  async function openFolder(files) {
    notice('正在读取本地文件…');
    const map=new Map(Array.from(files,f=>[f.webkitRelativePath.replaceAll('\\','/'),f]));
    const paths=Array.from(map.keys()), datasetFiles=paths.filter(p=>/\/data\/input\/[^/]+\.json$/i.test(p)).sort();
    const mechanismFiles=paths.filter(p=>/\/observations\/attempts\/[^/]+\/[^/]+\/result\.json$/i.test(p)).sort();
    const roots=new Set(datasetFiles.map(p=>p.slice(0,p.indexOf('/data/input/'))).concat(mechanismFiles.map(p=>p.slice(0,p.indexOf('/observations/attempts/')))));
    if(roots.size!==1)throw Error('请选择一个批次的根目录（不要选择含多个批次的总目录）。');
    const root=[...roots][0], isDataset=datasetFiles.length>0;
    if(isDataset&&mechanismFiles.length)throw Error('一个目录同时含正式题目和机制探测，请分别选择。');
    const sceneIndexPath=root+'/review_presentation.json';
    if(!isDataset&&!map.has(sceneIndexPath))throw Error('这个机制目录尚未附上逐条场景说明。请先用 New-WebReview.ps1 为该批次生成网页包，再打开生成的 index.html；只有截图不足以审题。');
    const items=[], fingerprints=[], urls=[]; const hashes=new Map();
    async function read(path){const f=map.get(path);if(!f)throw Error('缺少记录：'+path);const bytes=await f.arrayBuffer();fingerprints.push([path.slice(root.length+1),await sha(bytes)]);return JSON.parse(new TextDecoder().decode(bytes));}
    async function frame(path,stage,metadata={}){if(!path||!map.has(path))return {stage,src:null,sha256:null,...metadata};let h=hashes.get(path);if(!h){h=await sha(await map.get(path).arrayBuffer());hashes.set(path,h);} fingerprints.push([path.slice(root.length+1),h]);const src=URL.createObjectURL(map.get(path));urls.push(src);return {stage,src,sha256:h,...metadata};}
    try {
      if(isDataset) {
        for(const path of datasetFiles) {
          const record=await read(path);if(!record.model_input||!Array.isArray(record.model_input.questions)||!record.model_input.questions.length||!Array.isArray(record.model_input.frames))throw Error('缺少 model_input / 非空 questions / frames：'+path);
          const frames=[];for(const f of record.model_input.frames)frames.push(await frame(safeRelative(root+'/',f.path,root+'/data/media/'),f.stage,{...Object.fromEntries(['run_length','duplicate_count','start_step','end_step','capture_group_index','view_id','boundary_labels'].filter(k=>Object.hasOwn(f,k)).map(k=>[k,f[k]]))}));
          const sample=record.sample_id||path.split('/').at(-1).replace(/\.json$/i,''),preparedPath=root+'/prepared_requests/'+sample+'.json';let prepared=null,requestOrigin='reconstructed',requestText=null,protocol='',requestStatus=null,auditTimeline=null;
          if(map.has(preparedPath)) {
            prepared=await read(preparedPath);if(prepared.schema!=='hard-request/v1')throw Error('不支持的冻结请求格式：'+preparedPath);
            const inputFingerprint=fingerprints.find(([p])=>p===path.slice(root.length+1))?.[1],mediaHashes=frames.map(f=>f.sha256);
            if(prepared.model_input_sha256!==inputFingerprint||JSON.stringify(prepared.media_sha256||[])!==JSON.stringify(mediaHashes))throw Error('冻结请求与公开题目或图片哈希不匹配：'+sample);
            if(prepared.status!=='prepared_not_sent'||!['hard-selective-V/v1','hard-selective-S/v1'].includes(prepared.protocol)||typeof prepared.request_text!=='string'||!prepared.request_text)throw Error('冻结请求状态或内容不合法：'+sample);
            if(prepared.protocol!==record.model_input.protocol)throw Error('冻结请求协议与 model_input.protocol 不匹配：'+sample);
            if(Object.hasOwn(prepared,'model_input')&&canonical(prepared.model_input)!==canonical(record.model_input))throw Error('冻结请求中的 model_input 与公开记录不一致：'+sample);
            protocol=prepared.protocol;requestStatus=prepared.status;requestOrigin='prepared';requestText=prepared.request_text;
            if((protocol==='hard-selective-S/v1'&&frames.length)||(protocol==='hard-selective-V/v1'&&!frames.length))throw Error('冻结请求协议与公开图片数量不一致：'+sample);
            if(prepared.audit_timeline_path) {
              const timelinePath=safeRelative(root+'/',prepared.audit_timeline_path,root+'/');if(!timelinePath||!map.has(timelinePath))throw Error('私有审计时间线缺失或路径越界：'+sample);
              const timeline=await read(timelinePath),timelineRoot=timelinePath.slice(0,timelinePath.lastIndexOf('/')+1),baseSample=sample.replace(/_[VS]$/,'');
              if(timeline.sample_id!==baseSample)throw Error('私有审计时间线题号不匹配：'+sample);
              const privateFrames=[];for(const tf of timeline.frames||[]){const privatePath=safeRelative(timelineRoot,tf.path,timelineRoot);if(!privatePath)throw Error('私有审计帧路径越界：'+sample);privateFrames.push(await frame(privatePath,tf.stage,{...Object.fromEntries(['run_length','duplicate_count','start_step','end_step','view_id'].filter(k=>Object.hasOwn(tf,k)).map(k=>[k,tf[k]]))}));}
              auditTimeline={frames:privateFrames,boundaries:timeline.boundaries||[],steps:timeline.steps||[]};
            }
          } else if(!frames.length) throw Error('无公开图片的题目必须有哈希匹配的冻结 S 请求：'+sample);
          items.push({id:path.slice(root.length+1),label:sample,kind:'dataset',model_input:record.model_input,frames,request_origin:requestOrigin,request_text:requestText,request_run_status:requestStatus,protocol,audit_timeline:auditTimeline,questions:record.model_input.questions.map((q,i)=>({...q,id:q.id||q.question_id||`q${String(i+1).padStart(3,'0')}`,question:q.question||q.text||''}))});
        }
      } else {
        const sceneIndex=await read(sceneIndexPath);
        for(const path of mechanismFiles) {
          const r=await read(path), base=path.slice(0,-'result.json'.length), captures=await read(base+'capture_index.json'), frames=[];
          for(const c of captures) {
            const views=Array.isArray(c.view_frames)&&c.view_frames.length?c.view_frames:[c];
            for(const v of views)frames.push(await frame(safeRelative(base,v.rgb_path,base),c.label));
          }
          const id=path.slice(root.length+1),presentation=sceneIndex.items?.[id];if(!presentation)throw Error('缺少该条具体场景说明：'+id);
          items.push({id,label:`${r.case_id} / ${r.scene}`,kind:'mechanism',fact_id:r.fact_id,status:r.status,error:r.error,checks:(r.checks||[]).map(c=>({name:c.name,passed:c.passed})),frames,presentation});
        }
      }
      const id=await sha(new TextEncoder().encode(json(fingerprints.sort((a,b)=>a[0].localeCompare(b[0])))));
      addBatch({schema:'scene-review-batch/v1',id:'folder-'+id,name:root.split('/').at(-1),items,_objectURLs:urls,...(!isDataset?{review_revision:'scene-v2'}:{})});notice('');
    } catch(e){urls.forEach(URL.revokeObjectURL);throw e;}
  }
  function download(name,text,type) {
    const url=URL.createObjectURL(new Blob([text],{type})),a=el('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);
  }
  $('folder').addEventListener('change',async e=>{try{if(e.target.files.length)await openFolder(e.target.files);}catch(error){notice('打开失败：'+error.message);}finally{e.target.value='';}});
  $('batch').addEventListener('change',e=>switchBatch(e.target.value));
  for(const id of ['search','filter'])$(id).addEventListener('input',()=>{drawNav();const list=filtered();if(list.length&&!list.includes(selected))choose(list[0]);});
  $('prev').addEventListener('click',()=>move(-1));$('next').addEventListener('click',()=>move(1));
  for(const status of ['pending','pass','reject'])$(status).addEventListener('click',()=>update(status==='pass'?{status,tags:[]}:{status}));
  $('reason').addEventListener('input',()=>{if(!selected)return;review[selected.key]={...entry(selected.key),reason:$('reason').value,sample_id:selected.item.label,question_id:selected.id,updated_at:new Date().toISOString()};persist();$('decision-hint').textContent='备注已记录；可继续切题。';});
  $('export').addEventListener('click',()=>{if(!current){notice('请先打开批次。');return;}const data=envelope();for(const q of questions)if(!data.entries[q.key])data.entries[q.key]={...entry(q.key),sample_id:q.item.label,question_id:q.id};download(`审核结果_${current.id.slice(0,22)}_${new Date().toISOString().replace(/[:.]/g,'-')}.json`,json(data),'application/json;charset=utf-8');});
  $('restore').addEventListener('change',async e=>{
    try{
      if(!current)throw Error('请先打开对应批次');const file=e.target.files[0];if(!file)return;const data=JSON.parse(await file.text());
      if(data.schema!=='scene-review-decisions/v1'||data.batch_id!==current.id)throw Error('审核文件与当前批次不匹配，未导入任何意见');
      if((data.review_revision||'v1')!==(current.review_revision||'v1'))throw Error('这是旧版或不同审核范围的意见；原文件保留，不能自动作为本版题目审核结果');
      if(!data.entries||typeof data.entries!=='object'||Array.isArray(data.entries))throw Error('审核条目格式错误');
      const keys=new Set(questions.map(q=>q.key));for(const [key,value]of Object.entries(data.entries))if(!keys.has(key)||!validEntry(value))throw Error('审核条目与题目不匹配或格式错误');
      const incoming=Object.entries(data.entries).filter(([key,value])=>{const old=review[key];return !old||!old.updated_at||(value.updated_at&&Date.parse(value.updated_at)>Date.parse(old.updated_at));});
      for(const[key,value]of incoming)review[key]=value;persist();if(selected)choose(selected);notice(`已恢复 ${incoming.length} 条较新的审核记录；本地较新的意见已保留。`);
    }catch(error){notice('恢复失败：'+error.message);}finally{e.target.value='';}
  });
  document.addEventListener('keydown',e=>{if(!e.altKey||e.ctrlKey||e.metaKey||['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName))return;if(e.key==='ArrowLeft'){e.preventDefault();move(-1);}if(e.key==='ArrowRight'){e.preventDefault();move(1);}if(e.key==='1'){e.preventDefault();update({status:'pass'});}if(e.key==='2'){e.preventDefault();update({status:'reject'});}});
  window.addEventListener('beforeunload',e=>{if(!saved&&Object.keys(review).length){e.preventDefault();e.returnValue='';}});
  for(const batch of window.REVIEW_BATCHES||[])try{addBatch(batch);}catch(e){notice('预载批次读取失败：'+e.message);}
  if(batches.length)switchBatch(batches[0].id);
})();
