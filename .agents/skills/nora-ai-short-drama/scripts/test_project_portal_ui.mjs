// Pure UI-logic and template checks only. No browser or simulated DOM.
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import vm from 'node:vm';

const template = readFileSync(new URL('../references/模板/项目总览模板.html', import.meta.url), 'utf8');
const source = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
function loadFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1);
  const next = source.indexOf(name === 'catalogueMatches' ? '\nfunction saveCataloguePosition(' : '\nfunction ', start + 1);
  const code = source.slice(start, next < 0 ? undefined : next);
  // Selected helpers have no top-level calls after their declaration.
  return vm.runInNewContext(`(${code.trim()})`);
}
test('segment video prompts render Chinese then execution English as plain text', () => {
  const media=source.slice(source.indexOf('function showMedia('),source.indexOf('function catalogueMatches('));
  assert.doesNotMatch(media,/点击播放；已加载首帧，不自动播放、转换或分析内容/);
  assert.match(media,/if\(item.kind==="video"&&item.prompts\)/);
  assert.ok(media.indexOf('中文参考提示词')<media.indexOf('英文执行提示词'));
  assert.match(media,/textNode\(item.prompts\[key\]\?"pre":"p",item.prompts\[key\]\|\|missing\)/);
  assert.doesNotMatch(media,/innerHTML/);
  assert.match(media,/if\(!player.hidden\)hint.hidden=true/);
  assert.match(media,/"error",\(\)=>\{hint.hidden=false/);
});

const paging = loadFunction('paginationState');
const pageLabel = loadFunction('paginationLabel');
const categories = loadFunction('catalogueCategories');
const path = loadFunction('navigationPath');
const matches = loadFunction('catalogueMatches');
const clearance = loadFunction('paginationClearance');
const chapterVisible = loadFunction('chapterDockVisible');
const chapterLayout = loadFunction('chapterDockLayout');

test('compact rows cover outlines and production entry lists', () => {
  const list=source.slice(source.indexOf('function renderCatalogueList('),source.indexOf('function changeCataloguePage('));
  assert.match(list,/const productionRows=catalogueRoot==="09-剧集制作"&&catalogueStack.length===1/);
  assert.match(list,/const outlineRows=catalogueRoot==="06-分集大纲"\|\|productionRows;grid.classList.toggle\("outline-rows",outlineRows\)/);
  assert.match(template,/\.catalogue-grid\.outline-rows\{grid-template-columns:minmax\(0,1fr\)/);
  assert.match(template,/\.outline-rows \.catalogue-card\{display:grid;grid-template-columns:minmax\(0,1fr\) auto/);
  assert.match(template,/\.outline-row-actions\{display:flex;flex-direction:column;align-items:flex-end/);
  assert.match(template,/\.outline-rows \.catalogue-card\{[^}]*align-items:start/);
  assert.match(template,/\.outline-rows \.outline-row-actions \.outline\{[^}]*border:0;background:transparent/);
  assert.match(template,/\.outline-rows \.outline-row-actions \.outline:focus-visible\{outline:2px solid var\(--green\)/);
  assert.match(list,/outlineRows\?"阅读原文 →":"阅读文档 →"/);
  assert.match(list,/addEventListener\("click",\(\)=>openCatalogueItem\(item\)\);actions.append\(b\)/);
  assert.match(list,/if\(outlineRows\)box.append\(actions\)/);
  assert.match(list,/if\(item.summary\)copy.append\(textNode\("p",item.summary\)\)/);
  assert.match(list,/status.innerHTML=item.statusHtml;\(productionRows&&slideCard\?heading:copy\).append\(status\)/);
  assert.match(list,/if\(productionRows&&slideCard\)heading.classList.add\("production-heading"\)/);
  assert.match(template,/\.outline-row-heading\.production-heading\{align-items:center;column-gap:10px\}/);
  assert.match(template,/@media\(max-width:650px\)\{\.outline-rows \.catalogue-card\{grid-template-columns:minmax\(0,1fr\)/);
});

test('outline reading rail slides in on hover or keyboard focus without covering text', () => {
  assert.match(source,/if\(slideCard\)box.classList.add\("outline-slide"\)/);
  assert.match(source,/box.tabIndex=0;box.dataset.key=item.key;box.setAttribute\("role","button"\)/);
  assert.match(source,/actions.setAttribute\("aria-hidden","true"\);actions.append\(textNode\("span",actionLabel,"outline-read-hint"\)\)/);
  assert.match(source,/box.addEventListener\("click",event=>\{if\(!event.target.closest\("a"\)\)openCatalogueItem\(item\)\}/);
  assert.match(source,/event.target===box&&\(event.key==="Enter"\|\|event.key===" "\)/);
  assert.match(source,/querySelectorAll\("\[data-key\]"\)/);
  assert.match(template,/\.outline-rows \.catalogue-card\.outline-slide\{[^}]*overflow:hidden;[^}]*padding-right:64px/);
  assert.match(template,/\.outline-slide \.outline-row-actions\{[^}]*inset:2px 2px 2px auto;[^}]*pointer-events:none;background:inherit/);
  assert.match(template,/\.outline-rows \.catalogue-card\.outline-slide:hover,[^{]+\{border-color:var\(--green\);background:#edf6f2/);
  assert.match(template,/\.outline-slide:hover \.outline-row-actions,\.outline-slide:focus-within \.outline-row-actions\{transform:translateX\(0\)\}/);
  assert.match(template,/writing-mode:vertical-rl;text-orientation:upright/);
  assert.match(template,/@media\(hover:none\)\{\.outline-slide \.outline-row-actions\{transform:translateX\(0\)\}/);
  assert.match(template,/@media\(prefers-reduced-motion:reduce\)\{[^}]*transition:none/);
});

test('whole-card entry is restricted to outlines and top-level episode directories', () => {
  const expression=source.match(/const slideCard=([^;]+);/)[1];
  const cases=[
    [true,false,{kind:'outline',key:'06-分集大纲/EP001-分集大纲.md'},true],
    [true,true,{kind:'group',key:'09-剧集制作/EP001'},true],
    [true,true,{kind:'group',key:'09-剧集制作/EP001/03-分镜脚本'},false],
    [true,true,{kind:'document',key:'09-剧集制作/EP001/说明.md'},false],
    [false,false,{kind:'group',key:'历史版本/EP001'},false],
    [false,false,{kind:'group',key:'09-剧集制作/EP001'},false],
  ];
  for(const [outlineRows,productionRows,item,expected] of cases){
    assert.equal(vm.runInNewContext(expression,{outlineRows,productionRows,item}),expected);
  }
  assert.match(source,/const actionLabel=item.kind==="outline"\?"阅读原文":"进入查看"/);
});

test('boxed disclosures keep open borders green and retain hover and keyboard styles', () => {
  assert.match(template,/details:is\(\.folder,\.candidate-group,\.pending\)\[open\],details:is/);
  assert.match(template,/details\.intro>summary:hover,details\.intro>summary:focus-visible,details\.intro\[open\]>summary\{color:var\(--green\);text-decoration:underline;text-decoration-color:currentColor;text-underline-offset:4px\}/);
  assert.match(template,/\.catalogue-card:hover,\.catalogue-card:focus-within\{border-color:var\(--green\)\}/);
  assert.match(template,/details:is\(\.folder,\.candidate-group,\.pending\):hover:not\(:has\(details:hover\)\),details:is\(\.folder,\.candidate-group,\.pending\):has\(>summary:focus-visible\)\{border-color:var\(--green\)\}/);
});

test('episode directories use nested lazy folders and retain shared file preview actions', () => {
  const folders=source.slice(source.indexOf('function renderEpisodeFolders('),source.indexOf('function renderCatalogueList('));
  assert.match(folders,/textNode\("details","","folder"\)/);
  assert.match(folders,/textNode\("summary",item.name\)/);
  assert.match(folders,/addEventListener\("toggle"/);
  assert.match(folders,/renderEpisodeFolders\(detail,item.children\)/);
  assert.match(folders,/previewFile\(item\)/);
  assert.match(folders,/rawFileLink\(item.url\)/);
  const list=source.slice(source.indexOf('function renderCatalogueList('),source.indexOf('function changeCataloguePage('));
  assert.match(list,/catalogueRoot==="09-剧集制作"&&catalogueStack.length>1/);
  assert.match(list,/if\(folders\)\{renderEpisodeFolders\(grid,items.slice\(paging.start,paging.end\)\);return\}/);
  assert.match(template,/\.catalogue-grid\.episode-folders\{display:block\}/);
});

test('file preview routing covers all supported types with a non-navigating fallback', () => {
  const mode=loadFunction('filePreviewMode');
  for(const kind of ['document','text','image','audio','video']) assert.equal(mode(kind),kind);
  for(const kind of ['file','html','zip',undefined]) assert.equal(mode(kind),'unsupported');
});

test('video previews preload the first frame and use intrinsic proportions without autoplay', () => {
  const media=source.slice(source.indexOf('function showMedia('),source.indexOf('function catalogueMatches('));
  assert.match(media,/player.preload=item.kind==="video"\?"auto":"none"/);
  assert.match(media,/addEventListener\("loadedmetadata"/);
  assert.match(media,/player.style.setProperty\("--video-ratio",String\(player.videoWidth\/player.videoHeight\)\)/);
  assert.match(media,/player.hidden=true;player.addEventListener\("loadedmetadata"/);
  assert.match(media,/String\(player.videoWidth\/player.videoHeight\)\);player.hidden=false/);
  assert.doesNotMatch(template,/--video-ratio:\s*[\d.]+/);
  assert.match(media,/addEventListener\("loadeddata"/);
  assert.ok(media.indexOf('"loadedmetadata"') < media.indexOf('player.src=item.url'));
  assert.doesNotMatch(media,/\.play\(|autoplay\s*=|currentTime\s*=/);
  assert.match(template,/video\.media-player\{[^}]*width:min\(100%,calc\(65vh \* var\(--video-ratio\)\)\);[^}]*aspect-ratio:var\(--video-ratio\);object-fit:contain/);
  assert.match(source,/function stopMedia\(\)\{[^\n]*media.pause\(\)/);
});

test('explicit new-tab and download links are never intercepted as document previews', () => {
  const preview=loadFunction('shouldPreviewDocumentLink');
  assert.equal(preview('',false,true,false),true);
  for(const args of [['_blank',false,true,false],['named-tab',false,true,false],['',true,true,false],['',false,false,false],['',false,true,true]]) assert.equal(preview(...args),false);
});

test('raw links retain new-tab semantics and filename buttons use the common preview', () => {
  for(const [,tag] of template.matchAll(/(<a\b[^>]*id="[^"]*-raw"[^>]*>)/g)) {
    assert.match(tag,/target="_blank"/);
    assert.match(tag,/rel="[^"]*noopener/);
  }
  const raw=source.slice(source.indexOf('function rawFileLink('),source.indexOf('function filePreviewMode('));
  assert.match(raw,/link.target="_blank"/);
  assert.match(raw,/noopener/);
  const folders=source.slice(source.indexOf('function renderFolders('),source.indexOf('renderFolders(el("folders")'));
  assert.match(folders,/previewFile\(file\)/);
  assert.match(folders,/rawFileLink\(file.url\)/);
  assert.doesNotMatch(folders,/textNode\("a",file.name\)/);
  const preview=source.slice(source.indexOf('function previewFile('),source.indexOf('function showMedia('));
  assert.match(preview,/textNode\("pre",snapshot.text\)/);
  assert.doesNotMatch(preview,/innerHTML|location\.(?:href|assign|replace)/);
});

test('chapter dock appears only after the active navigation has left the viewport', () => {
  assert.equal(chapterVisible(true, 1, false, 5), false);
  assert.equal(chapterVisible(true, 0, false, 5), true);
  assert.equal(chapterVisible(true, -200, false, 9), true);
  assert.equal(chapterVisible(false, -200, false, 9), false);
  assert.equal(chapterVisible(true, -200, true, 9), false);
  assert.equal(chapterVisible(true, -200, false, 0), false);
});

test('chapter dock is vertically centered with a fixed five-row panel', () => {
  for(const viewport of [747,830,1080]) {
    const layout=chapterLayout(viewport,140,viewport);
    assert.equal(layout.height,224);
    assert.equal(layout.top,(viewport-224)/2);
  }
});

test('chapter dock respects upper navigation and lower pagination in short viewports', () => {
  for(const [viewport,top,bottom] of [[500,160,450],[400,180,360],[300,220,270],[200,210,190]]) {
    const layout=chapterLayout(viewport,top,bottom);
    assert(layout.height>=0 && layout.height<=224);
    assert(layout.top>=top+12);
    if(layout.height) assert(layout.top+layout.height<=Math.min(viewport-12,bottom-12));
  }
});

test('chapter rows avoid inline line-box expansion and five rows fit the panel budget', () => {
  const rule=selector=>{
    const blocks=[...template.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
    const match=blocks.find(([_,selectors])=>selectors.trim()===selector);
    assert(match,`Missing CSS rule: ${selector}`);
    return Object.fromEntries(match[2].split(';').filter(Boolean).map(pair=>pair.split(':').map(s=>s.trim())));
  };
  const rows=rule('.chapter-dock-list li'),links=rule('.chapter-dock-list a');
  assert.equal(rows.display,'grid');
  assert.equal(rows.margin,'0');
  assert.equal(links.display,'block');
  assert.equal(links.height,'32px');
  const panel=rule('.chapter-dock-panel.chapter-nav'),heading=rule('.chapter-dock-panel h3');
  const padding=parseFloat(panel.padding)*2,borders=2;
  const title=parseFloat(heading.height),gap=Number.parseFloat(heading.margin.split(' ').at(-1));
  const space=chapterLayout(830,140,830).height-padding-borders-title-gap;
  assert(space>=5*32,'Five rows must fit without overflow');
  assert(space<6*32,'A sixth row should scroll, not expand the dock');
  assert.equal(rule('.chapter-dock-handle').position,'absolute');
  assert(!rule('.chapter-dock-handle')['writing-mode'],'No protruding vertical text handle');
});

test('floating pagination reserves footer space and lifts narrow-screen back-to-top', () => {
  assert.equal(clearance(0).bottomPadding,64);
  assert.equal(clearance(0).backTopBottom,14);
  for(const height of [64,112,180]) {
    assert.equal(clearance(height).bottomPadding,height+48);
    assert.equal(clearance(height).backTopBottom,height+38);
  }
});

test('page script parses and every literal element reference exists', () => {
  new vm.Script(source);
  const markup = template.slice(0, template.indexOf('<script type="application/json"'));
  const ids = [...markup.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const [, id] of source.matchAll(/el\("([^"]+)"\)/g)) assert(ids.includes(id), `Missing ${id}`);
});

test('pagination clamps empty, first, last and out-of-range pages', () => {
  for (const [total, requested, size, page, pages, start, end] of [
    [0, 1, 20, 1, 0, 0, 0], [1, 1, 20, 1, 1, 0, 1],
    [20, 1, 20, 1, 1, 0, 20], [21, 2, 20, 2, 2, 20, 21],
    [81, 5, 20, 5, 5, 80, 81], [81, 9, 20, 5, 5, 80, 81],
    [81, -1, 20, 1, 5, 0, 20], [81, 4, 'all', 1, 1, 0, 81],
    [0, 5, 'all', 1, 0, 0, 0], [250, 1, 'all', 1, 1, 0, 250],
  ]) {
    assert.deepEqual(JSON.parse(JSON.stringify(paging(total, requested, size))), {page, pages, size, start, end});
  }
  assert.equal(paging(81, 1, '10').size, 10);
  assert.equal(paging(81, 1, undefined).size, 20);
  assert.equal(paging(81, 1, 100).size, 20);
});

test('pagination label uses requested order and all covers current filtered result', () => {
  assert.equal(pageLabel(81,paging(81,2,20)), '第 2 页 · 21-40 · 共 5 页 · 共 81 项');
  assert.equal(pageLabel(81,paging(81,5,'all')), '第 1 页 · 1-81 · 共 1 页 · 共 81 项');
  assert.equal(pageLabel(3,paging(3,1,'all')), '第 1 页 · 1-3 · 共 1 页 · 共 3 项');
  assert.equal(pageLabel(0,paging(0,1,'all')), '第 0 页 · 0-0 · 共 0 页 · 共 0 项');
});

test('stage-less outlines offer no invented stage; media categories remain intact', () => {
  const node = {children: [{category:''}, {category:'未记录'}, {category:'待确认'}, {category:'不适用'}]};
  assert.equal(categories(node, true).length, 0);
  node.children.push({category:'第一阶段'}, {category:'第一阶段'});
  assert.deepEqual(Array.from(categories(node, true)), ['第一阶段']);
  assert.deepEqual(Array.from(categories({categories:['人物声音','环境声音','动作与物件声音'],children:[]}, false)), ['人物声音','环境声音','动作与物件声音']);
});

test('navigation paths cover top-level, asset detail and nested catalogue', () => {
  assert.deepEqual(Array.from(path('项目定位','',[])), ['项目定位']);
  assert.deepEqual(Array.from(path('人物资料','CH001 · 小林',[])), ['人物资料','CH001 · 小林']);
  const stack = ['剧集制作','EP001','C001','P001'].map(name => ({node:{name}}));
  assert.deepEqual(Array.from(path('剧集制作','',stack)), ['剧集制作','EP001','C001','P001']);
  assert.equal(path('分集大纲','',[{node:{name:'分集大纲'}}]).length, 1);
});

test('search and filter happen before pagination and preserve unclassified entries in all', () => {
  const node = {children:Array.from({length:81}, (_,i) => ({key:`EP${i+1}`,name:`EP${i+1}`,category:i<30?'开篇':''}))};
  assert.equal(matches(node,'','').length,81);
  const filtered = matches(node,'','开篇');
  assert.equal(filtered.length,30);
  assert.equal(paging(filtered.length,5,20).page,2);
  const searched = matches(node,'EP81','');
  assert.equal(searched.length,1);
  assert.equal(paging(searched.length,1,20).pages,1);
});

test('candidate review labels keep technical gate, nonblocking findings, user and legacy distinct', () => {
  const fields=loadFunction('candidateReviewFields');
  const fresh=fields({twoStageReview:true,technicalHtml:'不通过',contentHtml:'未进行',contentFindingsHtml:'未审',userHtml:'待确认'});
  assert.deepEqual(Array.from(fresh,row=>Array.from(row)),[['技术审查（生成条目）','不通过'],['内容审查（非阻塞）','未进行'],['内容发现','未审'],['用户采用（生成条目）','待确认']]);
  const legacy=fields({agentHtml:'历史不通过',userHtml:'批准采用'});
  assert.equal(legacy.length,2);
  assert.equal(legacy[0][0],'历史agent初审（生成条目）');
  assert.equal(legacy[1][1],'批准采用');
});

const personGroups = loadFunction('personAssetGroups');
test('person stage groups keep card order and all registered assets', () => {
  const formal=[{stage:'少年',id:1},{stage:'成年',id:2},{stage:'少年',id:3},{stage:'',id:4}];
  const groups=personGroups({stages:['成年','少年'],formal});
  assert.deepEqual(Array.from(groups,g=>g.label),['成年','少年','未归入阶段']);
  assert.deepEqual(Array.from(groups,g=>Array.from(g.assets,a=>a.id)),[[2],[1,3],[4]]);
  assert.equal(personGroups({stages:[],formal}).length,0);
});

const personSlots = loadFunction('personAssetSlots');
test('formal portrait, body, clothes and character slots keep fixed order and missing slots', () => {
  const assets=[{type:'服装参考图',id:3},{type:'人物上半身正面肖像图',id:1},{type:'服装参考图',id:4},{type:'人物多视角参考图',id:2}];
  const slots=personSlots(assets);
  assert.deepEqual(Array.from(slots,s=>s.type),['人物上半身正面肖像图','人物多视角参考图','服装参考图','角色多视角参考图']);
  assert.deepEqual(Array.from(slots,s=>Array.from(s.assets,a=>a.id)),[[1],[2],[3,4],[]]);
  assert.equal(personSlots([]).length,4);
  assert.ok(personSlots([]).every(s=>s.assets.length===0));
  assert.deepEqual(assets.map(a=>a.id),[3,1,4,2]);
});

const candidateStages = loadFunction('personCandidateStages');
const candidateGroups = loadFunction('personCandidateGroups');
test('candidate tabs use card stages even without adopted images and preserve unmatched records', () => {
  const candidates=[{state:'少年',id:1},{state:'成年',id:2},{state:'未知',id:3},{state:'少年',id:4}];
  const groups=candidateStages({candidateStages:['成年','少年','老年'],candidates});
  assert.deepEqual(Array.from(groups,g=>g.label),['成年','少年','未归入阶段']);
  assert.deepEqual(Array.from(groups,g=>Array.from(g.assets,a=>a.id)),[[2],[1,4],[3]]);
  assert.equal(candidateStages({candidateStages:[],candidates}).length,0);
  assert.equal(candidateStages({candidateStages:['少年'],candidates:[]}).length,0);
});
test('candidate types follow formal order, combine the explicit body alias, and retain unknown types', () => {
  const assets=[{type:'服装参考图',id:1},{type:'角色多视角参考图',id:2},
    {type:'人物多视角参考图（人物本体六视图）',id:3},{type:'人物上半身正面肖像图',id:4},
    {type:'人物多视角参考图',id:5},{type:'其他测试',id:6},{type:'服装参考图',id:7}];
  const groups=candidateGroups(assets);
  assert.deepEqual(Array.from(groups,g=>g.type),['人物上半身正面肖像图','人物多视角参考图','服装参考图','角色多视角参考图','其他测试']);
  assert.deepEqual(Array.from(groups,g=>Array.from(g.assets,a=>a.id)),[[4],[3,5],[1,7],[2],[6]]);
  assert.equal(assets[2].type,'人物多视角参考图（人物本体六视图）');
  assert.deepEqual(assets.map(a=>a.id),[1,2,3,4,5,6,7]);
  assert.equal(candidateGroups([]).length,0);
});

test('formal and candidate cards both pass their generation section URL', () => {
  for(const owner of ['person','scene','prop']){
    const statement=source.match(new RegExp('if\\('+owner+'\\.recordKey\\)links\\.append\\(docLink\\([^;]+;'))[0];
    const recordKey='reference/generation.md',asset={generation:'生成记录-026',recordUrl:'reference/generation.md#生成记录-026'};
    for(const candidate of [false,true]){
      const links=[];
      vm.runInNewContext(statement,{[owner]:{recordKey},asset,candidate,links:{append:link=>links.push(link)},docLink:(key,label,url)=>({key,label,url})});
      assert.deepEqual(links,[{key:recordKey,label:candidate?'生成记录-026':'生成记录',url:asset.recordUrl}]);
    }
  }
});


test('all folder and candidate lists share the same sibling accordion', () => {
  assert.match(source,/document\.addEventListener\("toggle",handleListToggle,true\)/);
  const toggle=loadFunction('handleListToggle');
  for(const kind of ['folder','candidate-group']){
    const child={open:true}, grandchild={open:true}, siblingChild={open:true}, ancestor={open:true};
    const sibling={open:true,querySelectorAll(selector){assert.equal(selector,'details[open]');return [siblingChild]}};
    let queries=0, peerQueries=0;
    const detail={open:false,matches(selector){assert.equal(selector,'details.folder,details.candidate-group');return ['folder','candidate-group'].includes(kind)},querySelectorAll(selector){
      assert.equal(selector,'details[open]');queries++;return [child,grandchild];
    }};
    detail.parentElement={querySelectorAll(selector){
      assert.equal(selector,':scope > details:is(.folder,.candidate-group)[open]');peerQueries++;return [detail,sibling].filter(node=>node.open);
    }};
    toggle({target:detail});
    assert.equal(child.open,false);assert.equal(grandchild.open,false);assert.equal(sibling.open,true);assert.equal(peerQueries,0);
    detail.open=true;toggle({target:detail});
    assert.equal(detail.open,true);assert.equal(sibling.open,false);assert.equal(siblingChild.open,false);
    assert.equal(ancestor.open,true);assert.equal(queries,1);
    assert.equal(child.open,false);assert.equal(grandchild.open,false);
    sibling.open=true;siblingChild.open=true;toggle({target:detail});
    assert.equal(sibling.open,false);assert.equal(siblingChild.open,false);assert.equal(peerQueries,2);
  }
  toggle({target:{matches(){return false}}});
});
