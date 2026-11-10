'use strict';
const $ = (id) => document.getElementById(id);
const state = {suite: null, run: null, specification: null, operations: [], dirty: false, editorIndex: null};
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const titles = {dashboard:'Overview',new:'New API test',suites:'Test suites',review:'Suite review',execute:'Test execution',results:'Results & analysis',history:'Run history',reports:'Reports',settings:'Settings & help'};

function el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
}
function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').className = 'notice' + (error ? ' error' : '');
  $('notice').setAttribute('role', error ? 'alert' : 'status');
}
function clearNotice() { $('notice').classList.add('hidden'); }
async function api(url, options = {}) {
  const headers = {'X-CSRF-Token': csrf, ...options.headers};
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(url, {...options, headers});
  let data;
  try { data = await response.json(); } catch { throw new Error('The server returned an unreadable response. Check that the app is running.'); }
  if (!response.ok) {
    const details = data.details?.map(item => `${item.field}: ${item.message}`).join('\n');
    throw new Error([data.error || 'The request failed.', details].filter(Boolean).join('\n'));
  }
  return data;
}
function jsonInput(id, label) {
  try { return JSON.parse($(id).value); }
  catch { throw new Error(`${label} must be valid JSON. Use double quotes for property names and text.`); }
}
async function busy(button, message, task) {
  if (button.disabled) return;
  const original = button.textContent;
  button.disabled = true; button.textContent = message; clearNotice();
  try { return await task(); }
  catch (error) { notice(error.message, true); }
  finally { button.disabled = false; button.textContent = original; }
}
async function download(url, filename) {
  try {
    const response = await fetch(url);
    if (!response.ok) { const data = await response.json(); throw new Error(data.error); }
    const blob = await response.blob();
    const link = el('a'); const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 20000);
  } catch (error) { notice(error.message, true); }
}
function date(value) { return new Date(value).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); }
function badge(status) { return el('span', 'badge ' + status, status === 'error' ? 'Execution error' : status.charAt(0).toUpperCase() + status.slice(1)); }
function button(text, className, action) { const b = el('button',className,text); b.type='button'; b.addEventListener('click', action); return b; }
function empty(container, title, description, href, linkText) {
  const wrapper=el('div','empty-state'); wrapper.append(el('span','empty-icon','↗'),el('h3','',title),el('p','',description));
  if(href){const link=el('a','subtle-link',linkText);link.href=href;wrapper.append(link);}
  container.replaceChildren(wrapper);
}
function stat(label, value, detail, tone='') { const card=el('div','stat'); const heading=el('div','stat-label',label); heading.append(el('span','stat-icon','↗'));card.append(heading,el('div','stat-value '+tone,value),el('div','stat-detail',detail));return card; }
function makeTable(headers) {
  const wrapper=el('div','table-wrap'),table=el('table'),thead=el('thead'),row=el('tr'),body=el('tbody');
  headers.forEach(h=>row.append(el('th','',h)));thead.append(row);table.append(thead,body);wrapper.append(table);return {wrapper,body};
}
function suiteCards(container, suites) {
  container.replaceChildren();
  if (!suites.length) return empty(container,'Your first suite starts here','Turn a documented API contract into a reviewed, executable test suite.','#new','Create a test suite ↗');
  suites.slice(0,3).forEach(suite=>{
    const card=el('a','suite-card');card.href='#review/'+suite.id;
    const foot=el('div','suite-card-foot');foot.append(el('span','',suite.case_count+' test cases'),el('span','',suite.reviewed?'Reviewed ↗':'Needs review ↗'));
    card.append(el('span','pill',suite.source),el('h3','',suite.name),el('small','',date(suite.created_at)),foot);container.append(card);
  });
}
function runsTable(container, runs, reports=false) {
  if(!runs.length)return empty(container,'No executions yet','Run a reviewed suite to see real results, history and downloadable reports.','#suites','Browse test suites ↗');
  const {wrapper,body}=makeTable(reports?['PROJECT / RUN','EXECUTED','REPORTS']:['PROJECT / RUN','OUTCOME','EXECUTED','']);
  runs.forEach(run=>{
    const row=el('tr'),name=el('td');const link=el('a','table-link',run.name || 'Run #'+run.id);link.href='#results/'+run.id;name.append(link,el('small','',`Run #${run.id} · Suite #${run.suite_id}`));row.append(name);
    if(!reports){const cell=el('td');if(run.state==='running')cell.append(badge('running'));else{const s=run.data.summary;cell.append(el('span','',`${s.passed} passed · ${s.failed} failed`),el('small','',`${s.skipped} skipped · ${s.error} errors`));}row.append(cell);}
    row.append(el('td','',date(run.created_at)));
    const last=el('td');
    if(reports && run.state==='completed'){const actions=el('div','actions');actions.append(button('↓ JSON','button small secondary',()=>download(`/api/runs/${run.id}/export.json`,`testpilot_run_${run.id}.json`)),button('↓ PDF','button small secondary',()=>download(`/api/runs/${run.id}/export.pdf`,`testpilot_run_${run.id}.pdf`)));last.append(actions);}
    else {const link=el('a','subtle-link',run.state==='running'?'In progress':'View ↗');link.href='#results/'+run.id;last.append(link);}
    row.append(last);body.append(row);
  });container.replaceChildren(wrapper);
}
function drawTrend(trends) {
  const container=$('trendChart');container.replaceChildren();
  if(!trends.length)return empty(container,'Your activity will appear here','Daily outcomes are calculated from saved runs. There is no sample data.');
  const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 440 180');svg.setAttribute('role','img');svg.setAttribute('aria-label','Daily passed and failed test counts');
  const max=Math.max(1,...trends.map(t=>t.passed+t.failed));
  const width=360/trends.length;
  function part(tag,attrs,text){const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;svg.append(n);return n;}
  [0,.5,1].forEach(r=>{const y=140-r*115;part('line',{x1:34,x2:425,y1:y,y2:y,stroke:'#2a3037','stroke-dasharray':'3 5'});part('text',{x:25,y:y+3,fill:'#7f8996','font-size':9,'text-anchor':'end'},Math.round(max*r));});
  trends.forEach((t,i)=>{const x=45+i*width,w=Math.min(35,width-8),passed=t.passed/max*115,failed=t.failed/max*115;part('rect',{x,y:140-passed,width:w,height:passed,fill:'#d5ed91',rx:2});part('rect',{x,y:140-passed-failed,width:w,height:failed,fill:'#e68a99',rx:2});const title=document.createElementNS(ns,'title');title.textContent=`${t.day}: ${t.passed} passed, ${t.failed} failed, ${t.runs} runs`;svg.lastChild.append(title);if(i%Math.max(1,Math.ceil(trends.length/5))===0)part('text',{x:x+w/2,y:162,fill:'#8f99a7','font-size':9,'text-anchor':'middle'},t.day.slice(5));});
  container.append(svg,el('small','', 'Lime: passed · Rose: failed. Skips and execution errors are excluded from bars.'));
}
async function loadDashboard() {
  const data=await api('/api/dashboard'),t=data.totals;
  $('dashboardStats').replaceChildren(stat('Total test runs',t.runs,'Saved execution history'),stat('AI cases generated',t.generated_cases,`${t.projects} API projects · ${t.suites} suite revisions`),stat('Tests passed',t.passed,'Verified assertions','green'),stat('Tests failed',t.failed,`${t.error} execution errors · ${t.skipped} skipped`,'red'));
  runsTable($('recentRuns'),data.recent.slice(0,4));suiteCards($('recentSuites'),data.suites);drawTrend(data.trends);
}
async function loadSuites() {
  const {suites}=await api('/api/suites');if(!suites.length)return empty($('suiteLibrary'),'No test suites yet','Generate your first suite, or create one manually.','#new','Create a test suite ↗');
  const {wrapper,body}=makeTable(['API / SUITE','TEST CASES','SOURCE','SAVED','']);
  suites.forEach(s=>{const row=el('tr'),name=el('td'),link=el('a','table-link',s.name);link.href='#review/'+s.id;name.append(link,el('small','',`Suite #${s.id} · ${s.reviewed?'Reviewed':'Needs review'}`));row.append(name,el('td','',s.case_count),el('td','',s.source),el('td','',date(s.created_at)));const last=el('td'),a=el('a','subtle-link','Open ↗');a.href=link.href;last.append(a);row.append(last);body.append(row);});$('suiteLibrary').replaceChildren(wrapper);
}
function renderReview() {
  if(!state.suite)return;
  const suite=state.suite.data;
  $('suiteTitle').textContent=suite.api_name;
  $('suiteMeta').textContent=`Suite #${state.suite.id} · ${state.suite.source} · ${state.dirty?'Unsaved edits':state.suite.reviewed?'Reviewed revision':'Review required'} · ${suite.summary || 'Review requests and expectations before executing.'}`;
  const assumptions=$('suiteAssumptions');assumptions.replaceChildren(el('h3','', 'Review before execution'));
  assumptions.append(el('p','', 'Verify expected status codes, payloads and preconditions. Configure unknown behaviour and mark eligible only when the contract supports it. Saving creates a new, immutable reviewed revision.'));
  if(suite.assumptions?.length || suite.clarification_questions?.length){const list=el('ul');[...(suite.assumptions||[]),...(suite.clarification_questions||[])].forEach(a=>list.append(el('li','',a)));assumptions.append(list);}
  const eligible=suite.test_cases.filter(c=>c.eligible).length;$('suiteCount').textContent=`${suite.test_cases.length} test cases · ${eligible} eligible · ${suite.test_cases.length-eligible} need configuration`;
  $('exportPytest').disabled=!state.suite.reviewed || state.dirty;
  $('goExecute').disabled=!state.suite.reviewed || state.dirty;
  $('caseList').replaceChildren();
  suite.test_cases.forEach((c,index)=>{const card=el('article','case-card'),top=el('div','case-top'),main=el('div','case-main'),tags=el('div','case-tags');tags.append(el('span','case-id',c.id),el('span','tag',c.category),el('span','tag',c.priority+' priority'),badge(c.eligible?'passed':'skipped'));tags.lastChild.textContent=c.eligible?'Eligible':'Configure';main.append(tags,el('h3','',c.scenario),el('p','',c.description));top.append(main,button('Edit','button small secondary',()=>openEditor(index)));const bottom=el('div','case-bottom'),endpoint=el('span');endpoint.append(el('span','method',c.method),el('span','endpoint',c.endpoint));bottom.append(endpoint,el('span','',`Expected ${c.expected.status_code??'not configured'} · ${c.repeat || 1} request(s)`));const details=el('details');details.append(el('summary','', 'Request, rules & assumptions'),el('pre','',JSON.stringify(c,null,2)));card.append(top,bottom,details);$('caseList').append(card);});
}
function openEditor(index) {state.editorIndex=index;$('editorTitle').textContent=index===null?'Edit complete suite':'Edit '+state.suite.data.test_cases[index].id;$('jsonEditor').value=JSON.stringify(index===null?state.suite.data:state.suite.data.test_cases[index],null,2);$('editorError').textContent='';$('editorDialog').showModal();}
function prepareExecution() {
  if(!state.suite || !state.suite.reviewed || state.dirty){location.hash=state.suite?'#review/'+state.suite.id:'#suites';return;}
  $('executionSuite').textContent=`${state.suite.data.api_name} · Reviewed suite #${state.suite.id} · ${state.suite.data.test_cases.length} tests`;
  const endpoint=state.suite.data.test_cases[0].endpoint;
  if(endpoint.startsWith('http'))$('baseUrl').value=new URL(endpoint).origin;
  const names=[...new Set([...JSON.stringify(state.suite.data).matchAll(/\$\{([A-Z][A-Z0-9_]+)\}/g)].map(m=>m[1]))];
  $('requiredSecrets').textContent=names.length?'Referenced placeholders: '+names.join(', '):'No credential placeholders referenced by this suite.';
  $('authorized').checked=false;
}
function renderAnalysis() {
  const area=$('analysisContent'),analysis=state.run.analysis;area.replaceChildren();
  if(!analysis){area.append(el('p','muted','Analyse this run with Adaption for possible causes and next debugging steps. Redacted execution evidence is sent to the provider.'));return;}
  area.append(el('span','pill violet',analysis.source==='adaption'?'AI-GENERATED · UNCONFIRMED HYPOTHESES':'DETERMINISTIC EVIDENCE SUMMARY'),el('p','',analysis.summary));
  analysis.hypotheses.forEach(h=>{area.append(el('h3','',h.test_id+': '+h.hypothesis));const list=el('ol');h.debugging_steps.forEach(step=>list.append(el('li','',step)));area.append(list);});
}
function renderResults() {
  const run=state.run;if(!run)return;
  $('resultsTitle').textContent=run.suite.api_name;
  $('resultsMeta').textContent=`Run #${run.id} · ${date(run.created_at)} · ${run.target}`;
  if(run.state!=='completed'){$('resultStats').replaceChildren();$('analyseBtn').disabled=true;empty($('resultList'),'Run is still recorded as active','Refresh after execution finishes. If the app restarted mid-run, no completed outcome is available.');return;}
  const s=run.data.summary;$('analyseBtn').disabled=false;
  $('resultStats').replaceChildren(stat('Total tests',s.total,(s.duration_ms/1000).toFixed(2)+' seconds'),stat('Passed',s.passed,'Assertions satisfied','green'),stat('Failed',s.failed,'Assertion mismatches','red'),stat('Skipped',s.skipped,'Not executed'),stat('Errors',s.error,'Execution could not complete','red'));
  renderAnalysis();renderOutcomes();
}
function renderOutcomes() {
  if(!state.run?.data?.results)return;
  const filter=$('resultFilter').value,results=state.run.data.results.filter(r=>filter==='all'||r.status===filter),list=$('resultList');list.replaceChildren();
  if(!results.length)return empty(list,'No matching outcomes','Choose another status to inspect this run.');
  results.forEach(result=>{const card=el('article','case-card'),top=el('div','case-top'),main=el('div','case-main'),tags=el('div','case-tags');tags.append(el('span','case-id',result.id),badge(result.status));main.append(tags,el('h3','',result.scenario));if(result.reason)main.append(el('p',result.status==='error'?'failure-text':'',result.reason));result.failures.forEach(f=>main.append(el('p','failure-text',f)));top.append(main);const bottom=el('div','case-bottom');bottom.append(el('span','endpoint',result.method+' '+result.endpoint),el('span','',`Expected ${result.expected.status_code??'unknown'} · Actual ${result.actual?.status_code??'—'}${result.actual?' · '+result.actual.elapsed_ms+' ms':''}`));const details=el('details');details.append(el('summary','', 'Expected vs actual · recorded evidence'),el('pre','',JSON.stringify({expected:result.expected,actual:result.actual,attempts:result.attempts},null,2)));card.append(top,bottom,details);list.append(card);});
}
async function settings() {
  const data=await api('/api/settings');$('providerStatus').textContent=data.configured?'Key configured · connection on request':'API key not configured';
  const entries={'AI provider':data.provider,'Model':data.model,'API key':data.configured?'Configured locally (not displayed)':'Missing — set ADAPTION_API_KEY in .env','Storage':data.storage,'Suite / repeat limits':`${data.max_cases} cases / ${data.max_repeats} repetitions`,'Run deadline':data.worker_timeout+' seconds','Response limit':data.max_response_kb+' KB','Local fixture exceptions':data.local_origins.join(', ')||'None — private networks blocked','Credentials':data.secrets};
  $('settingsList').replaceChildren();Object.entries(entries).forEach(([key,value])=>$('settingsList').append(el('dt','',key),el('dd','',value)));
}
let navigation=0;
async function navigate() {
  const current=++navigation;clearNotice();
  let [view,id]=(location.hash.slice(1)||'dashboard').split('/');if(!titles[view])view='dashboard';
  document.querySelectorAll('.view').forEach(section=>section.classList.toggle('hidden',section.id!=='view-'+view));
  document.querySelectorAll('[data-nav]').forEach(a=>{const active=a.dataset.nav===view || a.dataset.nav==='suites'&&['review','execute'].includes(view) || a.dataset.nav==='history'&&view==='results';a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  $('breadcrumb').textContent=titles[view];document.title=titles[view]+' · TestPilot AI';
  try {
    if(view==='dashboard')await loadDashboard();
    if(view==='suites')await loadSuites();
    if(view==='review'){
      if(!/^\d+$/.test(id||'')){location.hash='#suites';return;}
      if(!state.suite || state.suite.id!==Number(id)){const suite=await api('/api/suites/'+id);if(current!==navigation)return;state.suite=suite;state.dirty=false;}
      renderReview();
    }
    if(view==='execute')prepareExecution();
    if(view==='results'){
      if(!/^\d+$/.test(id||'')){location.hash='#history';return;}
      const run=await api('/api/runs/'+id);if(current!==navigation)return;state.run=run;$('resultFilter').value='all';renderResults();
    }
    if(view==='history'||view==='reports'){const data=await api('/api/runs');runsTable($(view==='history'?'historyList':'reportList'),data.runs,view==='reports');}
    if(view==='settings')await settings();
  }catch(error){notice(error.message,true);}
  window.scrollTo({top:0,behavior:'instant'});
}

$('generateForm').addEventListener('submit',event=>{event.preventDefault();busy($('generateBtn'),'Generating validated tests…',async()=>{
  const payload={project_name:$('projectName').value,api_description:$('apiDescription').value,method:$('method').value,endpoint:$('endpoint').value,request:{headers:jsonInput('requestHeaders','Headers'),query:jsonInput('queryParams','Query parameters'),body:jsonInput('requestBody','Request body'),body_type:$('bodyType').value},specification:state.specification};
  const result=await api('/generate',{method:'POST',body:JSON.stringify(payload)});state.suite=result.suite;state.dirty=false;location.hash='#review/'+result.suite.id;
});});
$('manualBtn').addEventListener('click',()=>busy($('manualBtn'),'Creating…',async()=>{
  const suite={api_name:$('projectName').value.trim()||'Manual API suite',summary:'Manually created. Configure expected results before execution.',assumptions:['Expected behaviour must be supplied from your API contract.'],clarification_questions:[],test_cases:[{id:'TC-001',category:'functional',scenario:'Baseline request',description:$('apiDescription').value,method:$('method').value,endpoint:$('endpoint').value,request:{headers:jsonInput('requestHeaders','Headers'),query:jsonInput('queryParams','Query'),body:jsonInput('requestBody','Body'),body_type:$('bodyType').value},expected:{status_code:null},priority:'high',eligible:false,skip_reason:'Set a documented expected status and eligible=true.'}]};
  state.suite=await api('/api/suites',{method:'POST',body:JSON.stringify(suite)});state.dirty=false;location.hash='#review/'+state.suite.id;
}));
$('openapiFile').addEventListener('change',async()=>{const file=$('openapiFile').files[0];if(!file)return;clearNotice();try{if(file.size>256000)throw new Error('OpenAPI files must be smaller than 256 KB.');const data=new FormData();data.append('file',file);$('importStatus').textContent='Validating specification…';const result=await api('/api/openapi',{method:'POST',body:data});state.specification=result.specification;state.operations=result.operations;$('operation').replaceChildren();result.operations.forEach((operation,index)=>{const option=el('option','',operation.method+' '+operation.endpoint+(operation.summary?' · '+operation.summary:''));option.value=index;$('operation').append(option);});$('operationWrap').classList.remove('hidden');$('importStatus').textContent=`Imported ${result.operations.length} operations. Select the operation to test.`;if(!$('projectName').value)$('projectName').value=result.specification.info?.title||'Imported API';selectOperation();}catch(error){$('importStatus').textContent='Import failed.';notice(error.message,true);}});
function selectOperation(){const operation=state.operations[Number($('operation').value)];if(!operation)return;$('method').value=operation.method;$('endpoint').value=operation.endpoint;}
$('operation').addEventListener('change',selectOperation);
$('clearImport').addEventListener('click',()=>{state.specification=null;state.operations=[];$('openapiFile').value='';$('operationWrap').classList.add('hidden');$('importStatus').textContent='Import removed.';});
$('editSuite').addEventListener('click',()=>openEditor(null));
['closeEditor','cancelEditor'].forEach(id=>$(id).addEventListener('click',()=>$('editorDialog').close()));
$('editorForm').addEventListener('submit',async event=>{event.preventDefault();const submit=event.submitter;submit.disabled=true;try{const value=jsonInput('jsonEditor','Editor');if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('The editor requires a JSON object.');const candidate=state.editorIndex===null?value:structuredClone(state.suite.data);if(state.editorIndex!==null)candidate.test_cases[state.editorIndex]=value;state.suite.data=await api('/api/validate-suite',{method:'POST',body:JSON.stringify(candidate)});state.dirty=true;renderReview();$('editorDialog').close();}catch(error){$('editorError').textContent=error.message;}finally{submit.disabled=false;}});
$('copySuite').addEventListener('click',()=>busy($('copySuite'),'Copying…',async()=>{await navigator.clipboard.writeText(JSON.stringify(state.suite.data,null,2));notice('Suite JSON copied.');}));
$('saveReview').addEventListener('click',()=>busy($('saveReview'),'Validating & saving…',async()=>{const saved=await api('/api/suites/'+state.suite.id,{method:'PUT',body:JSON.stringify(state.suite.data)});state.suite=saved;state.dirty=false;location.hash='#review/'+saved.id;renderReview();}));
$('exportPytest').addEventListener('click',()=>download('/api/suites/'+state.suite.id+'/export.py','test_suite_'+state.suite.id+'.py'));
$('goExecute').addEventListener('click',()=>{location.hash='#execute';});
$('backReview').addEventListener('click',()=>{location.hash='#review/'+state.suite.id;});
$('executeForm').addEventListener('submit',event=>{event.preventDefault();busy($('runBtn'),'Running tests…',async()=>{
  if(!state.suite?.reviewed||state.dirty)throw new Error('Save a reviewed suite before execution.');
  const payload={base_url:$('baseUrl').value.trim(),authorized:$('authorized').checked,secrets:jsonInput('runSecrets','Execution secrets'),headers:jsonInput('runHeaders','Shared headers'),timeout_seconds:Number($('timeout').value)};
  $('runProgress').classList.remove('hidden');
  try{state.run=await api('/api/suites/'+state.suite.id+'/run',{method:'POST',body:JSON.stringify(payload)});location.hash='#results/'+state.run.id;}
  finally{$('runProgress').classList.add('hidden');$('runSecrets').value='{}';$('runHeaders').value='{}';}
});});
$('analyseBtn').addEventListener('click',()=>busy($('analyseBtn'),'Analysing evidence…',async()=>{const runId=state.run.id;const analysis=await api('/api/runs/'+runId+'/analyse',{method:'POST',body:'{}'});if(state.run?.id===runId){state.run.analysis=analysis;renderAnalysis();}}));
$('downloadJson').addEventListener('click',()=>download('/api/runs/'+state.run.id+'/export.json','testpilot_run_'+state.run.id+'.json'));
$('downloadPdf').addEventListener('click',()=>download('/api/runs/'+state.run.id+'/export.pdf','testpilot_run_'+state.run.id+'.pdf'));
$('resultFilter').addEventListener('change',renderOutcomes);
$('refreshHistory').addEventListener('click',()=>busy($('refreshHistory'),'Refreshing…',navigate));
window.addEventListener('hashchange',navigate);
window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
settings().catch(error=>notice(error.message,true));
navigate();
