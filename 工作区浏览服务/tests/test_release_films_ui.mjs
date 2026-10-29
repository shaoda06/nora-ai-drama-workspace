// Real Project and delivery components; local fixtures never write project files.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { createServer } = await import(require.resolve('vite'));
const react = (await import(require.resolve('@vitejs/plugin-react'))).default;
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-delivery-'));
const sample = await readFile(new URL('../frontend/public/component-samples/video.webm', import.meta.url));
const file = (name, parent) => ({ kind: 'video', name, key: `98-成片交付/${parent}/${name}`, url: `/api/projects/fixture/files/${encodeURIComponent(parent + '/' + name)}` });
const group = (name, children) => ({kind:'group', name, children});
const doc = {kind:'document', name:'发布文案.md', key:'98-成片交付/EP003/发布文案.md', url:'/api/projects/fixture/files/发布文案.md'};
const children = [group('片头',[file('片头.webm','片头')]),group('片尾',[]),
 group('EP003',[group('成片',Array.from({length:6},(_,i)=>file(`版本${i+1}.webm`,'EP003/成片'))),doc]),group('EP004',[group('成片',[])])].reverse();
const social = {kind:'social', children:[], accounts:{items:[],groups:[],issues:[]}, covers:{assets:[],unassigned:[],groups:[]}};
let mode='normal', writes=[], unexpected=[];
const server = await createServer({configFile:false, root:fileURLToPath(new URL('../frontend',import.meta.url)),
 define:{__APP_VERSION__:JSON.stringify('delivery-fixture')},server:{host:'127.0.0.1',port:0},plugins:[react(),{name:'delivery-fixture',configureServer(vite){
 vite.middlewares.use((req,res,next)=>{
  const url=new URL(req.url,'http://fixture.invalid'), pathname=decodeURIComponent(url.pathname);
  if(!pathname.startsWith('/api/'))return next();
  if(req.method!=='GET'){writes.push(req.url);res.writeHead(405);return res.end();}
  if(pathname.includes('/files/')){res.setHeader('Content-Type','video/webm');if(url.searchParams.has('download'))res.setHeader('Content-Disposition','attachment; filename="sample.webm"');return res.end(sample);}
  let data;
  if(pathname.endsWith('/status'))data={revision:1,updating:false,checking:false};
  else if(pathname.endsWith('/overview'))data={project:'发布目录示例',active:[],warnings:[],directories:[{name:'00-项目定位',label:'项目定位'},...(mode==='none'?[]:[{name:'98-成片交付',label:'成片交付'},{name:'10-社交媒体资料',label:'社交媒体资料'}])]};
  else if(pathname.endsWith('/sections/00-项目定位'))data={exists:false,groups:[]};
  else if(pathname.endsWith('/sections/10-社交媒体资料'))data=social;
  else if(pathname.endsWith('/sections/98-成片交付')){if(mode==='error'){res.statusCode=503;data={detail:'本地模拟读取失败'};}else data={kind:'group',children:mode==='empty'?[]:children};}
  else{unexpected.push(pathname);res.statusCode=404;data={};}
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));
 });}}]});
await server.listen();
const base=`http://127.0.0.1:${server.httpServer.address().port}`;
let browser;
try{
 browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL||'chrome',headless:true});
 for(const viewport of [{width:1362,height:918},{width:390,height:844},{width:320,height:740}]){
  const context=await browser.newContext({viewport}),page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(String(error)));mode='normal';writes=[];unexpected=[];
  await page.goto(base+'/tests/release-films.html');
  const entry=page.getByRole('combobox',{name:'发布资料',exact:true});
  const open=async label=>{await entry.click();await page.getByRole('option',{name:new RegExp('^'+label+'(?:\\s+当前)?$')}).click();};
  await entry.click();assert.deepEqual(await page.getByRole('listbox',{name:'发布资料'}).locator('[role=option] > span:first-child').allTextContents(),['社交媒体资料','成片交付']);await entry.press('Escape');
  await open('社交媒体资料');
  const socialTabs=page.getByRole('navigation',{name:'社交媒体资料分类'});
  await socialTabs.getByRole('button',{name:'个人页资料',exact:true}).click();await page.getByText('尚无已登记的采用头像或主页背景图，可在制作记录中查看现有资料。').waitFor();
  await socialTabs.getByRole('button',{name:'封面资料',exact:true}).click();await page.getByText('通用暂无已登记的封面。').waitFor();
  await open('成片交付');
  const categories=page.getByRole('navigation',{name:'成片交付分类',exact:true});await categories.waitFor();
  assert.deepEqual(await categories.getByRole('button').allTextContents(),['片头','片尾','EP004','EP003']);
  const panel=page.locator('section.panel:not([hidden])'), player=panel.locator('video.release-films-player');
  await player.waitFor();assert.equal(await player.getAttribute('autoplay'),null);
  await categories.getByRole('button',{name:'EP003',exact:true}).click();
  const selector=panel.getByRole('navigation',{name:'成片交付选集',exact:true});
  assert.equal(await selector.getByRole('button').count(),5);
  await panel.getByRole('button',{name:'下一页',exact:true}).click();await selector.getByRole('button',{name:'版本6',exact:true}).waitFor();
  assert.match(await player.getAttribute('src'),/版本6|%E7%89%88%E6%9C%AC6/);
  await panel.getByText('发布文案.md',{exact:true}).waitFor();
  await page.screenshot({path:path.join(screenshots,`${viewport.width}-episode.png`),animations:'disabled'});
  await categories.getByRole('button',{name:'EP004',exact:true}).click();assert.equal(await player.count(),0);await panel.getByText('暂无EP004视频。').waitFor();
  await categories.getByRole('button',{name:'EP003',exact:true}).click();await selector.getByRole('button',{name:'版本1',exact:true}).waitFor();
  await player.dispatchEvent('error');await page.getByRole('button',{name:'重新加载视频',exact:true}).click();
  await open('社交媒体资料');assert.equal(await page.locator('video.release-films-player').count(),0);
  mode='empty';await page.reload();await open('成片交付');await page.getByText('暂无成片交付资料。').waitFor();
  mode='error';await page.reload();await open('成片交付');await page.getByRole('button',{name:'重新读取',exact:true}).waitFor();mode='normal';await page.getByRole('button',{name:'重新读取',exact:true}).click();await categories.waitFor();
  mode='none';await page.reload();await page.getByRole('navigation',{name:'项目栏目',exact:true}).waitFor();assert.equal(await entry.count(),0);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(unexpected,[]);
  console.log(`${viewport.width}px: unified social navigation, episode files, pagination, empty/error and no writes passed`);await context.close();
 }
 console.log(`Screenshots: ${screenshots}`);
}finally{if(browser)await browser.close();await server.close();}
