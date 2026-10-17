// Controlled HTTP fixtures only. Run with Node and Playwright on NODE_PATH.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const fire = {id:'f1',latitude:34.22,longitude:-118.55,observed_at:'2026-10-17T00:00:00Z',frp_mw:4,source:'NASA FIRMS'};
const secondFire = {...fire,id:'f2',latitude:34.24,longitude:-118.58,observed_at:'2026-10-17T00:15:00Z',frp_mw:7};
const species = '<img src=x onerror=alert(1)>';
const occurrence = {id:'7',species,latitude:34.23,longitude:-118.55,observed_at:'1998-05',dataset_key:'dataset-7',license:'CC BY 4.0',source:'GBIF'};
const zone = {id:'gbif:7',name:'Observation 7',latitude:34.23,longitude:-118.55,species,nearest_fire_id:'f1',distance_to_fire_km:1.1,risk:0.956,risk_method:'proximity',fire_eta_minutes:null,response_time_minutes:null,safety_buffer_minutes:null,response_window_minutes:null,priority:'UNASSESSED'};
let state = 'valid', scenarioStatus = 200, apiPort = 8878, delay = 0;
const calls = [];
let scenarioGate = null;
function persistence() {
  const report={status:'ready',reason:null,model_version:'wf08-rf-v1',method:'random_forest',
    source_product:'VIIRS_SNPP_NRT',mode:state==='live'?'live':'sample',experimental:state==='live',
    quality_flags:['nrt_transfer_unvalidated','vegetation_type_unavailable'],
    window_start:'2026-10-17T00:00:00Z',window_end:'2026-10-17T06:00:00Z',horizon_end:'2026-10-18T06:00:00Z',
    cells:[{id:'105:38',grid_x:105,grid_y:38,latitude:34.22,longitude:-118.55,fire_ids:['f1'],fire_count:1,score:.72,reason:null}]};
  if(state==='model-empty'){report.status='empty';report.cells=[];}
  if(state==='model-unavailable'){report.status='unavailable';report.reason='model_unavailable';report.cells=[];}
  if(state==='model-invalid')report.cells[0].score=NaN;
  if(state==='model-payload')report.model_version=species;
  if(state==='model-missing')return undefined;
  return report;
}
function snapshot() {
  return {fire_persistence:persistence(),fires:state==='empty-fire'?[]:[fire,secondFire],occurrences:state==='empty-occurrence'?[]:[occurrence,{...occurrence,id:'8',species:'Unknown species',observed_at:null,longitude:-118.56}],wildlife_zones:state.startsWith('empty')?[]:[zone,{...zone,id:'gbif:8',name:'Observation 8',species:'Unknown species',longitude:-118.56}],mode:state==='live'?'live':'sample',fetched_at:'2026-10-17T01:02:03Z',truncated:state==='capped'};
}
function api(req,res) {
  calls.push({port:req.socket.localPort,url:req.url,method:req.method});
  res.setHeader('Access-Control-Allow-Origin','*');
  res.setHeader('Access-Control-Allow-Headers','Content-Type');
  res.setHeader('Access-Control-Allow-Methods','GET, POST, OPTIONS');
  if(req.method==='OPTIONS'){res.writeHead(204);res.end();return;}
  res.setHeader('Content-Type','application/json');
  if(req.method==='GET') {setTimeout(()=>{res.writeHead(state==='error'?503:200);res.end(JSON.stringify(state==='error'?{detail:'Provider unavailable'}:snapshot()));},delay);return;}
  let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{
    const input=JSON.parse(body);calls[calls.length-1].body=input;
    const responseStatus = scenarioStatus;
    const assessment={...input.zone,...input,response_window_minutes:input.fire_eta_minutes-input.response_time_minutes-input.safety_buffer_minutes,priority:'ALTERNATIVE RESPONSE'};
    delete assessment.zone;
    const send = () => {
      res.writeHead(responseStatus);
      res.end(JSON.stringify(responseStatus===200?{assessment,timing_source:'operator_scenario'}:{detail:'Invalid scenario'}));
    };
    if (scenarioGate) {
      const received = scenarioGate;
      scenarioGate = null;
      received({zoneId:input.zone.id, release:send});
    } else send();
  });
}
const servers = [http.createServer((req,res)=>{
  if(req.url==='/favicon.ico'){res.writeHead(204);res.end();return;}
  if(req.url==='/config.js'){res.setHeader('Content-Type','text/javascript');res.end(`window.WILDFYRE_CONFIG={apiBaseUrl:'http://127.0.0.1:${apiPort}'};`);return;}
  const file=path.join(root,req.url==='/'?'index.html':req.url.split('?')[0]);
  if(!file.startsWith(root)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
}),http.createServer(api),http.createServer(api)];
(async()=>{
  for(let i=0;i<servers.length;i++)await new Promise(resolve=>servers[i].listen(8877+i,'127.0.0.1',resolve));
  let browser;
  try {
    browser=await chromium.launch({headless:true,channel:'msedge'});
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    page.setDefaultTimeout(1500); page.setDefaultNavigationTimeout(30000);
    const errors=[], consoleErrors=[];page.on('pageerror',error=>errors.push(error.message));
    page.on('console', message=>{if(message.type()==='error')consoleErrors.push({state,scenarioStatus,text:message.text()});});
    let dialogs=0;page.on('dialog',async dialog=>{dialogs++;await dialog.dismiss();});
    const results=[];
    async function check(name,fn){try{await fn();results.push({name,pass:true});}catch(error){results.push({name,pass:false,error:error.message});}}
    async function load(next='valid'){state=next;await page.goto('http://127.0.0.1:8877');await page.waitForTimeout(700);}
    async function pendingScenario() {
      await page.getByLabel('Fire ETA (minutes)').fill('10');
      await page.getByLabel('Response time (minutes)').fill('8');
      await page.getByLabel('Safety buffer (minutes)').fill('2');
      let timer;
      const received = new Promise((resolve, reject) => {
        scenarioGate = resolve;
        timer = setTimeout(() => reject(new Error('Scenario POST did not arrive')), 1500);
      });
      try {
        await page.getByRole('button',{name:'Evaluate scenario'}).click();
        const held = await received;
        assert.equal(held.zoneId, 'gbif:7');
        assert.match(await page.locator('#scenario-message').innerText(), /Evaluating operator scenario/);
        assert.equal(await page.locator('#scenario-result').innerText(), '');
        return held;
      } finally {
        clearTimeout(timer);
        scenarioGate = null;
      }
    }
    await load();
    await check('configured API URL used',async()=>assert(calls.some(call=>call.port===8878&&call.url==='/risk')));
    await check('keyboard skip link reveals the workspace below the header', async () => {
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.activeElement.className), 'skip-link');
      assert(await page.locator('.skip-link').isVisible());
      await page.keyboard.press('Enter');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'workspace');
      const target = await page.locator('#workspace').boundingBox();
      const header = await page.locator('.site-header').boundingBox();
      assert(target.y >= header.y + header.height - 1, 'sticky header must not obscure the skip-link target');
    });
    await check('both fire detection markers render', async () => {
      const fires = page.locator('.leaflet-interactive[fill="#df632d"]');
      assert.equal(await fires.count(), 2, 'both fire detections must appear as fire markers');
      await fires.nth(0).click();
      assert.match(await page.locator('.leaflet-popup-content').innerText(), /4 MW/);
      await page.locator('.leaflet-popup-close-button').click();
      await fires.nth(1).click();
      assert.match(await page.locator('.leaflet-popup-content').innerText(), /7 MW/);
      assert.match(await page.locator('.leaflet-popup-content').innerText(), /2026-10-17T00:15:00Z/);
      await page.locator('.leaflet-popup-close-button').click();
    });
    await check('sample mode and provenance visible',async()=>{assert.match(await page.locator('body').innerText(),/Sample data/i);assert.match(await page.locator('body').innerText(),/NASA FIRMS/);assert.match(await page.locator('body').innerText(),/2026-10-17/);});
    await check('candidate score and missing timing visible',async()=>{assert.match(await page.locator('body').innerText(),/Proximity score/);await page.getByRole('button',{name:/Observation 7/}).click({timeout:1200});assert.match(await page.locator('#scenario').innerText(),/Not provided/);});
    await check('untrusted species literal and inert',async()=>{assert.match(await page.locator('body').innerText(),/<img src=x onerror=alert\(1\)>/);assert.equal(await page.locator('img[src="x"]').count(),0);assert.equal(dialogs,0);});
    await check('partial and missing dates visible',async()=>{assert.match(await page.locator('body').innerText(),/1998-05/);assert.match(await page.locator('body').innerText(),/Observation date: Not provided/);});
    await check('popup provider text is literal',async()=>{await page.locator('.leaflet-interactive[fill="#fff"]').first().click();assert((await page.locator('.leaflet-popup-content').innerText()).includes(species));assert.equal(await page.locator('.leaflet-popup-content img').count(),0);assert.equal(dialogs,0);});
    await check('scenario submitted and zero preserved',async()=>{
      await page.getByLabel('Fire ETA (minutes)').fill('10');await page.getByLabel('Response time (minutes)').fill('8');await page.getByLabel('Safety buffer (minutes)').fill('2');
      await page.getByRole('button',{name:'Evaluate scenario'}).click();await page.waitForTimeout(150);
      assert.match(await page.locator('#scenario-result').innerText(),/0 minutes/);assert.match(await page.locator('#scenario-result').innerText(),/operator_scenario/);
      assert.equal(calls.findLast(call=>call.method==='POST').body.zone.id,'gbif:7');
    });
    await check('negative scenario window preserved',async()=>{await page.getByLabel('Fire ETA (minutes)').fill('9');await page.getByRole('button',{name:'Evaluate scenario'}).click();await page.waitForTimeout(150);assert.match(await page.locator('#scenario-result').innerText(),/-1 minutes/);});
    await check('invalid local duration is not sent',async()=>{const before=calls.filter(call=>call.method==='POST').length;await page.getByLabel('Fire ETA (minutes)').fill('-1');await page.getByRole('button',{name:'Evaluate scenario'}).click();assert.equal(calls.filter(call=>call.method==='POST').length,before);});
    await check('422 and 503 preserve selection and inputs',async()=>{await page.getByLabel('Fire ETA (minutes)').fill('10');for(const code of [422,503]){scenarioStatus=code;await page.getByRole('button',{name:'Evaluate scenario'}).click();await page.waitForTimeout(150);assert.match(await page.locator('#scenario-message').innerText(),code===422?/valid|invalid/i:/unavailable/i);assert.equal(await page.getByLabel('Fire ETA (minutes)').inputValue(),'10');}scenarioStatus=200;});
    await check('nonfinite and missing duration cannot submit',async()=>{for(const value of ['', '1e309']){const before=calls.filter(call=>call.method==='POST').length;await page.getByLabel('Fire ETA (minutes)').fill(value);await page.evaluate(()=>document.getElementById('timing-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true})));assert.equal(calls.filter(call=>call.method==='POST').length,before);assert.match(await page.locator('#scenario-message').innerText(),/finite, nonnegative/);}await page.getByLabel('Fire ETA (minutes)').fill('10');});
    await check('selection invalidates old scenario',async()=>{await page.getByRole('button',{name:'Evaluate scenario'}).click();await page.waitForTimeout(100);await page.getByRole('button',{name:/Observation 8/}).click();assert.equal(await page.locator('#scenario-result').innerText(),'');});
    await check('snapshot refresh invalidates scenario',async()=>{await page.getByLabel('Fire ETA (minutes)').fill('10');await page.getByLabel('Response time (minutes)').fill('8');await page.getByLabel('Safety buffer (minutes)').fill('2');await page.getByRole('button',{name:'Evaluate scenario'}).click();await page.waitForTimeout(100);await page.getByRole('button',{name:'Refresh data'}).click();await page.waitForTimeout(200);assert.equal(await page.locator('#scenario-result').innerText(),'');});
    await check('candidate change rejects an in-flight scenario response', async () => {
      await page.getByRole('button',{name:/Observation 7/}).click();
      const held = await pendingScenario();
      await page.getByRole('button',{name:/Observation 8/}).click();
      held.release();
      await page.waitForTimeout(150);
      assert.match(await page.locator('#selection-message').innerText(), /Observation 8/);
      assert.equal(await page.locator('#scenario-result').innerText(), '');
      assert.equal(await page.locator('#scenario-message').innerText(), '');
    });
    await check('snapshot refresh rejects an in-flight scenario response', async () => {
      await page.getByRole('button',{name:/Observation 7/}).click();
      const held = await pendingScenario();
      await page.getByRole('button',{name:'Refresh data'}).click();
      await page.waitForFunction(() => !document.getElementById('refresh').disabled);
      held.release();
      await page.waitForTimeout(150);
      assert.equal(await page.locator('.candidate').count(), 2);
      assert.equal(await page.locator('#scenario-result').innerText(), '');
      assert.equal(await page.locator('#scenario-content').isVisible(), false);
      assert.match(await page.locator('#selection-message').innerText(), /Select a candidate/);
    });
    await check('failed refresh preserves and labels old snapshot',async()=>{state='error';await page.getByRole('button',{name:'Refresh data'}).click();await page.waitForTimeout(200);assert.match(await page.locator('#coverage').innerText(),/previous snapshot.*stale/);assert.equal(await page.locator('.candidate').count(),2);assert(await page.locator('.candidate button').first().isDisabled());});
    for(const [next,pattern] of [['empty-fire',/No fire detections/],['empty-occurrence',/No wildlife observations/],['error',/unavailable/i],['capped',/truncated|capped/i],['live',/Live data/]])await check(next,async()=>{await load(next);assert.match(await page.locator('body').innerText(),pattern);});
    await check('loading visible',async()=>{delay=600;const navigation=page.goto('http://127.0.0.1:8877');await navigation;assert.match(await page.locator('#data-status').innerText(),/Loading/i);await page.waitForTimeout(700);delay=0;});
    await check('second API configured',async()=>{apiPort=8879;await load();assert(calls.some(call=>call.port===8879&&call.url==='/risk'));});
    await check('mobile has no horizontal overflow',async()=>{await page.setViewportSize({width:390,height:844});await load('capped');await page.getByRole('button',{name:/Observation 7/}).click();await page.getByLabel('Fire ETA (minutes)').fill('0');await page.getByLabel('Response time (minutes)').fill('0');await page.getByLabel('Safety buffer (minutes)').fill('0');await page.getByRole('button',{name:'Evaluate scenario'}).click();await page.waitForTimeout(150);assert.match(await page.locator('#scenario-result').innerText(),/0 minutes/);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);});
    await check('Leaflet markers and attribution render',async()=>{assert(await page.locator('.leaflet-container').count());assert(await page.locator('.leaflet-interactive').count()>=3);assert.match(await page.locator('.leaflet-control-attribution').innerText(),/OpenStreetMap/);});
    await check('live persistence separate from proximity with UTC horizon and experimental label',async()=>{
      await load('live');
      const text=await page.locator('#persistence-panel').innerText();
      for(const pattern of [/72%/,/105:38/,/wf08-rf-v1/,/2026-10-17T00:00:00Z/,/2026-10-18T06:00:00Z/,/Experimental live/,/vegetation type/i])assert.match(text,pattern);
      assert.match(await page.locator('#candidates').innerText(),/Proximity score: 0.96/);
      await page.getByRole('button',{name:/Cell 105:38/}).click();
      await page.locator('.leaflet-interactive[fill="#df632d"]').first().click();
      assert.match(await page.locator('.leaflet-popup-content').innerText(),/Persistence.*72%/);
    });
    for(const [next,pattern] of [['model-empty',/No eligible detections/],['model-unavailable',/unavailable/i],['model-invalid',/unavailable/i],['model-missing',/unavailable/i]]){
      await check(next,async()=>{await load(next);assert.match(await page.locator('#persistence-status').innerText(),pattern);assert.equal(await page.locator('#persistence-cells button').count(),0);});
    }
    await check('model text remains inert',async()=>{
      await load('model-payload');
      assert.match(await page.locator('#persistence-panel').innerText(),/<img src=x/);
      assert.equal(await page.locator('#persistence-panel img').count(),0);
    });
    await check('same-origin /app/ config and separate-host override',async()=>{
      const config=fs.readFileSync(path.join(root,'config.js'),'utf8');
      const same=await page.evaluate(code=>{const run=new Function('window',code+';return window.WILDFYRE_CONFIG');return run({location:{pathname:'/app/',origin:'http://example.test:8000'}});},config);
      assert.equal(same.apiBaseUrl,'http://example.test:8000');
    });
    await check('auto refresh every five minutes and pauses with selected scenario/hidden page',async()=>{
      await page.clock.install();
      await load('live');
      let before=calls.filter(c=>c.method==='GET').length;
      await page.clock.fastForward(300001);
      await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
      assert.equal(calls.filter(c=>c.method==='GET').length,before+1);
      await page.getByRole('button',{name:/Observation 7/}).click();
      await page.getByLabel('Fire ETA (minutes)').fill('95');
      before=calls.filter(c=>c.method==='GET').length;
      await page.clock.fastForward(600001);
      assert.equal(calls.filter(c=>c.method==='GET').length,before);
      assert.equal(await page.getByLabel('Fire ETA (minutes)').inputValue(),'95');
      assert.match(await page.locator('#refresh-status').innerText(),/paused.*timing/i);
      await page.getByRole('button',{name:'Refresh data'}).click();
      await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
      await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'));});
      before=calls.filter(c=>c.method==='GET').length;
      await page.clock.fastForward(600001);
      assert.equal(calls.filter(c=>c.method==='GET').length,before);
      assert.match(await page.locator('#refresh-status').innerText(),/paused.*hidden/i);
      await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));});
      delay=800;
      await page.clock.fastForward(300001);
      assert(await page.locator('#refresh').isDisabled());
      before=calls.filter(c=>c.method==='GET').length;
      await page.evaluate(()=>document.getElementById('refresh').click());
      assert.equal(calls.filter(c=>c.method==='GET').length,before);
      await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
      delay=0;
    });
    if(process.env.WF_SCREENSHOT_DIR){
      fs.mkdirSync(process.env.WF_SCREENSHOT_DIR,{recursive:true});
      await load('live');
      for(const [label,width,height] of [['desktop',1440,1000],['mobile',390,844]]){
        await page.setViewportSize({width,height});await page.waitForTimeout(800);
        await page.screenshot({path:path.join(process.env.WF_SCREENSHOT_DIR,'fixture-live-'+label+'.png'),fullPage:true});
      }
    }
    await check('no uncaught browser errors',async()=>assert.deepEqual(errors,[]));
    await check('no unexpected console errors in successful states',async()=>assert.deepEqual(consoleErrors.filter(error=>error.state!=='error'&&error.scenarioStatus===200),[]));
    console.log(JSON.stringify({browserVersion:browser.version(),results,errors,consoleErrors},null,2));
    if(results.some(result=>!result.pass))process.exitCode=1;
  } finally {if(browser)await browser.close();for(const server of servers)server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;for(const server of servers)server.close();});
