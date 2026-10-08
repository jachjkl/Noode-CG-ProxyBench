"use strict";
const $ = id => document.getElementById(id);
const fields = [
 ["batch_size","每批节点数",1,100,1],["round_count","每站连接次数（至少 5 次）",5,10,1],
 ["max_entry_latency_ms","入口延迟上限（毫秒）",1,10000,1],["max_proxy_average_latency_ms","三站统一延迟平均上限（毫秒）",1,10000,1],["max_proxy_loss_percent","最大请求失败率（%）",0,100,0.1],
 ["entry_timeout_seconds","入口连接超时（秒）",0.1,5,0.1],["entry_concurrency","入口初筛并发数",1,512,1],
 ["min_proxy_speed_mbps","最低网速（Mbps）",0.01,100000,0.01],["download_attempts","网速测量次数",1,10,1],
 ["download_bytes","测速样本（MiB）",0.5,8,0.5],["minimum_completion_ratio","最低正文完整度（%）",95,100,0.1],["maximum_download_seconds","正文计时上限（秒）",0.1,120,0.1],["request_timeout_seconds","网站超时（秒）",0.1,60,0.1],
 ["download_timeout_seconds","网速测量超时（秒）",0.1,120,0.1],["delay_concurrency","响应测试并发数",1,100,1],["speed_concurrency","网速测试并发数",1,8,1],
 ["round_cooldown_seconds","轮间隔（秒）",0,2,0.1]];
const states={Queued:"未测试",Ready:"准备就绪",Running:"正在测试",Paused:"已暂停",Stopped:"已停止",Failed:"未完成",Healthy:"正常",Preparing:"正在准备",Dispatching:"请求云端",Completed:"已完成",Qualified:"通过",Loading:"正在加载",completed:"已完成",needs_more:"继续补测",success:"已完成",failure:"未完成",in_progress:"正在运行",queued:"等待执行","Loading Proxy":"加载代理","Latency Passed":"响应通过","Speed Testing":"测量网速","Rejected Entry":"入口未通过初筛","Rejected Loss":"请求成功率不足","Rejected Latency":"响应时间不合格","Rejected Speed":"网速不合格","Validation Passed":"内核已就绪","Validation Failed":"内核检查未完成","Validation Required":"等待代理验收","Needs More":"继续补测"};
let initialized=false,listKind="candidates",pageNumber=1,totalPages=1,rowsOnPage=[],listRequest=0,lastTable="",resultKind="live-results",resultPage=1,resultPages=1,resultRequest=0,lastResults="";
Object.assign(states,{Local:"本地独立测速",Downloading:"多镜像下载中",Recovering:"正在恢复连接"});
states["Retest Required"]="旧规则结果，等待复测";
let lastCloudTable="",lastCloudRefreshRun="";
const ruleHelp={
 batch_size:"一个批次同时装入的独立代理节点数，最多 100 个。数量增加会提高本机资源占用。",
 round_count:"每个网站至少测 5 次，默认共测 15 次。每站去掉一次最高和一次最低延迟，取其余样本平均；5 次时保留中间 3 次。请求成功率仍统计全部请求。",
 max_entry_latency_ms:"本机连接候选 IP 端口的延迟上限。超过就淘汰，例如设置 200，240 毫秒不会通过；这不是网站访问延迟。",
 max_proxy_average_latency_ms:"先分别计算三个网站剔除最高和最低后的统一延迟平均值，再将三个均值相加除以 3。超过设定值就淘汰，默认上限 200 毫秒；单次响应仍单独显示。",
 max_proxy_loss_percent:"三个网站全部测试请求中允许失败的比例。设为 0 就必须全部成功，超过设定值就淘汰。",
 entry_timeout_seconds:"等待候选 IP 端口建立连接的最长时间，超时就淘汰。它是等待时限，与入口延迟上限分别判断。",
 entry_concurrency:"同时检查多少个 IP 的入口连接。提高可加快初筛，也会增加本机连接数量，最多 512。",
 min_proxy_speed_mbps:"开启候选代理后，下载小样本正文的平均网速最低值，低于该值就淘汰。单位 Mbps；8 Mbps 约等于 1 MB/秒。",
 download_attempts:"每个候选代理重复测量网速的次数。各次下载均须成功，再比较平均网速；次数增加会延长测试。",
 download_bytes:"每次用于测速的正文数据量，沿用旧安装包的小样本方法。可选 0.5、1、2、4、8 MiB，越大通常越耗时。",
 minimum_completion_ratio:"下载正文至少完成的百分比。设为 95%，收到的数据少于样本的 95% 就淘汰；发生超时仍按失败处理。",
 maximum_download_seconds:"开始接收正文后，允许传输正文的最长计时时间。超过就淘汰，网速按收到的正文大小和正文传输时间计算。",
 request_timeout_seconds:"每一次网站访问和出口地区查询的最长等待时间，超时算请求失败。三站统一延迟另按延迟上限判断。",
 download_timeout_seconds:"每次网速下载请求的 I/O 等待时限，包括连接和响应阶段。超时算下载失败，不得用不完整测量冒充通过。",
 delay_concurrency:"同时测试网站响应的代理数量。提高可加快网站测试，但也会增加连接压力，最多 100。",
 speed_concurrency:"同时下载测速样本的代理数量，最多 8。并发会共享本机可用网络容量，过高可能拉低每个 IP 的测量值。",
 round_cooldown_seconds:"两轮网站测试之间的等待时间，设为 0 就连续测试。用于控制测试节奏，不是允许的延迟。"
};
async function post(action,payload={}){const r=await fetch(`/api/proxybench/${action}`,{method:"POST",headers:{"Content-Type":"application/json","X-ProxyBench":"1"},body:JSON.stringify(payload)});const v=await r.json();if(!r.ok)throw Error(v.error||"操作未完成");return v;}
function feedback(message){$("feedback").textContent=message;}
function number(value){return value==null?"—":typeof value==="number"?value.toFixed(2):String(value);}
function label(value){if(states[value])return states[value];if(/^Round \d+$/.test(value))return `第 ${value.split(" ")[1]} 轮`;const round=/^Round (\d+): (google|cloudflare|github)$/.exec(value||"");if(round)return `第 ${round[1]} 轮 · ${({google:"谷歌",cloudflare:"Cloudflare",github:"GitHub"})[round[2]]}`;if((value||"").startsWith("Core Error"))return "内核异常，恢复未完成节点";return value&&/[\u4e00-\u9fff]/.test(value)?value:"等待更新";}
function sourceLabel(value){return (value||[]).map(name=>({"fixed-source-a":"链接一","fixed-source-b":"链接二","cloudflare-official":"边缘 IP 池","gslege-jp-hint":"日本补充池","last-good":"上次发布","unit-fixture":"测试样本"}[name]||(/jp/i.test(name)?"日本补充池":"补充来源"))).join("、")||"—";}
function country(value){return ({JP:"日本",US:"美国",HK:"中国香港",TW:"中国台湾",SG:"新加坡",KR:"韩国",DE:"德国",GB:"英国",FR:"法国",AU:"澳大利亚",CA:"加拿大",NL:"荷兰",CN:"中国",XX:"未确定"})[value]||(value?`地区代码 ${value}`:"待验证");}
function table(rows){const signature=JSON.stringify(rows);if(signature===lastTable)return;lastTable=signature;const fragment=document.createDocumentFragment();
 for(const row of rows){const tr=document.createElement("tr");for(const value of [`${row.ip}:${row.port}`,sourceLabel(row.source_names||row.sources),number(row.entry_latency_ms),label(row.status||"Queued")]){const cell=document.createElement("td");cell.textContent=value;tr.append(cell);}tr.firstChild.classList.add("ip-link");tr.firstChild.tabIndex=0;tr.firstChild.setAttribute("role","button");tr.firstChild.setAttribute("aria-label",`${row.ip} 详细数据`);tr.firstChild.addEventListener("click",()=>detail(row));tr.firstChild.addEventListener("keydown",e=>{if(e.key==="Enter")detail(row);});fragment.append(tr);}
 if(!rows.length){const tr=document.createElement("tr"),cell=document.createElement("td");cell.colSpan=4;cell.className="empty-list";cell.textContent="开始优选后，云端获取的候选 IP 会显示在左侧。";tr.append(cell);fragment.append(tr);}$("tbody").replaceChildren(fragment);
}
function resultTable(rows){const signature=JSON.stringify(rows);if(signature===lastResults)return;lastResults=signature;const fragment=document.createDocumentFragment();
 for(const row of rows){const tr=document.createElement("tr"),total=(row.rules?.round_count||3)*3,seen=row.completed_probe_count??row.proxy_probe_count??0;let progress=label(row.status||"Queued");if(/^Round/.test(row.status||""))progress=`${({google:"谷歌",cloudflare:"Cloudflare",github:"GitHub"})[row.active_site]||"网站"} 第 ${row.active_round||1} 轮 · ${seen}/${total}`;
  for(const text of [`${row.ip}:${row.port}`,progress,number(row.proxy_average_latency_ms??row.live_response_ms),number(row.proxy_download_average_mbps),country(row.geo_country||row.country)]){const cell=document.createElement("td");cell.textContent=text;tr.append(cell);}const cell=document.createElement("td"),button=document.createElement("button");button.className="button secondary detail-button";button.textContent="查看";button.addEventListener("click",()=>detail(row));cell.append(button);tr.append(cell);tr.classList.toggle("qualified-row",!!row.qualified);fragment.append(tr);
 }if(!rows.length){const tr=document.createElement("tr"),cell=document.createElement("td");cell.colSpan=6;cell.className="empty-list";cell.textContent="等待本地测试；正在测试的 IP 和每轮数据会实时显示在右侧。";tr.append(cell);fragment.append(tr);}$("resultBody").replaceChildren(fragment);
}
async function refreshResults(){const ticket=++resultRequest;const value=await post(resultKind,{page:resultPage});if(ticket!==resultRequest)return;resultPage=value.page;resultPages=value.pages;resultTable(value.rows);$("resultTotal").textContent=`共 ${value.total.toLocaleString("zh-CN")} 个 IP，每页 300 个`;$("resultPageInfo").textContent=`第 ${resultPage} / ${resultPages} 页`;$("resultPrevious").disabled=resultPage<=1;$("resultNext").disabled=resultPage>=resultPages;$("resultPageNumber").max=resultPages;if(document.activeElement!==$("resultPageNumber"))$("resultPageNumber").value=resultPage;}
function detail(row){$("detailTitle").textContent=`${row.ip}:${row.port} · 详细数据`;const box=$("detailBody");box.replaceChildren();const summary=document.createElement("p");summary.textContent=`${label(row.status||(row.qualified?"Qualified":"Queued"))} · 入口 ${number(row.entry_latency_ms)}毫秒 · 出口：${country(row.geo_country||row.country)} · 平均网速：${number(row.proxy_download_average_mbps)} Mbps`;box.append(summary);
 const grid=document.createElement("table"),head=document.createElement("tr");for(const text of ["测量项目","各次实测","平均值"]){const th=document.createElement("th");th.textContent=text;head.append(th);}grid.append(head);
 for(const [key,title] of [["google","谷歌"],["cloudflare","Cloudflare"],["github","GitHub"]]){const values=row[`${key}_rounds_ms`]||(row.probes?.[key]||[]).map(x=>x.latency_ms);const tr=document.createElement("tr");for(const text of [title,values.length?values.map((v,i)=>`第${i+1}轮：${v==null?"失败":`${number(v)}毫秒`}`).join("；"):"未测试",row[`${key}_average_ms`]==null?"—":`${number(row[`${key}_average_ms`])}毫秒`]){const td=document.createElement("td");td.textContent=text;tr.append(td);}grid.append(tr);}
 box.append(grid);const averages=document.createElement("p");averages.textContent=row.round_averages_ms?.length?`各轮平均：${row.round_averages_ms.map((v,i)=>`第${i+1}轮 ${number(v)}毫秒`).join("；")}。最终平均 ${number(row.proxy_average_latency_ms)}毫秒，抖动 ${number(row.latency_jitter_ms)}毫秒，请求失败率 ${number(row.proxy_loss_percent)}%。`:"尚未完成三网站响应测量。";box.append(averages);const downloads=document.createElement("p");downloads.textContent=row.download_rounds_mbps?.length?`网速测量：${row.download_rounds_mbps.map((v,i)=>`第${i+1}次 ${row.download_measurements?.[i]?.success===false?"失败":`${number(v)} Mbps`}`).join("；")}。平均 ${number(row.proxy_download_average_mbytes)} MB/s。`:"尚未完成网速测量。";box.append(downloads);if(row.jp_hint&&!row.geo_verified){const hint=document.createElement("p");hint.textContent="来源带有日本候选标记，真实出口仍需实测验证。";box.append(hint);}if(row.tested_at){const time=document.createElement("p");time.textContent=`测量时间：${new Date(row.tested_at).toLocaleString("zh-CN")}`;box.append(time);}$("detailDialog").showModal();}
async function refreshRows(){const ticket=++listRequest;const value=await post(listKind,{page:pageNumber});if(ticket!==listRequest)return;pageNumber=value.page;totalPages=value.pages;table(value.rows);$("listTotal").textContent=`共 ${value.total.toLocaleString("zh-CN")} 个 IP，每页 300 个`;$("pageInfo").textContent=`第 ${pageNumber} / ${totalPages} 页`;$("previousPage").disabled=pageNumber<=1;$("nextPage").disabled=pageNumber>=totalPages;$("pageNumber").max=totalPages;if(document.activeElement!==$("pageNumber"))$("pageNumber").value=pageNumber;}
async function refreshCloudRows(){const value=await post("cloud-published-results"),signature=JSON.stringify(value.rows);if(signature===lastCloudTable)return;lastCloudTable=signature;const body=$("cloudPublishedBody");body.replaceChildren();for(const [index,row] of value.rows.entries()){const tr=document.createElement("tr");for(const text of [row.rank??index+1,`${row.ip}:${row.port}#${row.geo_country||row.country||"XX"}`,number(row.proxy_average_latency_ms),number(row.proxy_download_average_mbps),row.lane==="jp_append"?`日本追加 ${index-99}`:`普通 ${index+1}`,country(row.geo_country||row.country)]){const td=document.createElement("td");td.textContent=text;tr.append(td);}body.append(tr);}if(!value.rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=6;td.textContent="云端尚无已确认的发布名单，读取成功后会按原排名列在这里。";tr.append(td);body.append(tr);}}
function workflow(rows=[]){
 const names={pending:"等待前一步",running:"进行中",completed:"已完成",waiting:"等待补测或推送",paused:"已暂停 / 保存",failed:"失败，进度已保留"};
 let done=0,current="等待开始";
 for(const row of rows){
  const step=document.querySelector(`[data-step="${row.id}"]`);if(!step)continue;
  const state=Object.hasOwn(names,row.status)?row.status:"pending";
  step.className=`flow-step ${state}${step.classList.contains("motion-offscreen")?" motion-offscreen":""}`;
  step.querySelector(".flow-state").textContent=names[state];step.querySelector("small").textContent=row.detail||"";
  if(["running","paused","failed","waiting"].includes(state)){step.setAttribute("aria-current","step");current=`${row.title} · ${names[state]}`;}else step.removeAttribute("aria-current");
  if(state==="completed"){
   done++;
  }
 }
 $("flowProgress").value=done;
 const text=`${done===5?"本轮全部完成":current} · 已完成 ${done} / 5 步`;if($("flowStatus").textContent!==text)$("flowStatus").textContent=text;
}
function rules(values){if(initialized)return;initialized=true;for(const [key,title,min,max,step] of fields){const wrapper=document.createElement("label");wrapper.className="field";const span=document.createElement("span");span.textContent=title;const input=document.createElement(key==="download_bytes"?"select":"input");if(key==="download_bytes"){for(const size of [.5,1,2,4,8]){const option=document.createElement("option");option.value=size;option.textContent=`${size} MiB`;input.append(option);}}else{input.type="number";input.min=min;input.max=max;input.step=step;}input.name=key;input.required=true;input.value=key==="download_bytes"?values[key]/1048576:key==="minimum_completion_ratio"?values[key]*100:values[key];const help=document.createElement("small");help.className="field-help";help.id=`ruleHelp-${key}`;help.textContent=ruleHelp[key];input.setAttribute("aria-describedby",help.id);wrapper.append(span,input,help);$("rulesForm").append(wrapper);}}
async function poll(){try{const r=await fetch("/api/proxybench/state"),value=await r.json();if(!r.ok)throw Error(value.error);const live=value.live||{},core=live.mihomo||{},cloud=value.cloud||{},measuring=value.local_running||value.running&&["local-select","本地真实代理测速"].includes(cloud.stage);
 const publishedCloud=value.cloud_published||{};$("cloudPublishedCount").textContent=`云端共 ${publishedCloud.total||0} 个 IP · 普通 ${publishedCloud.general||0} 个 · 日本 ${publishedCloud.japan||0} 个`;$("cloudPublishedInfo").textContent=publishedCloud.message||"正在读取云端已发布 IP";if(cloud.status==="Completed"&&String(cloud.run_id)!==lastCloudRefreshRun){lastCloudRefreshRun=String(cloud.run_id);post("refresh-cloud-results").catch(()=>{});}
 const stage=measuring?live.stage:value.running&&cloud.stage?cloud.stage:live.stage;$("stage").textContent=stage?label(stage):"等待开始";$("status").textContent=label(measuring?live.status:live.status==="Paused"?"Paused":value.running&&cloud.status?cloud.status:live.status||"Ready");$("counts").textContent=`${live.candidate_total||0} / ${live.tested_count||0}`;$("batch").textContent=`第 ${live.batch_current||0} / ${live.batch_total||0} 批 · 初筛 ${live.entry_screened_count||0} 个 · 代理实测 ${live.proxy_tested_count||0} 个`;
 $("qualified").textContent=`${live.qualified_count||0} / ${Math.max(0,(live.tested_count||0)-(live.qualified_count||0))}`;$("core").textContent=core.version?`${core.version} · ${core.controller_healthy?"运行中":"已就绪"}`:"检查内核中";$("coreDetail").textContent=`规则代理 · 已加载 ${core.loaded_proxies||0} 个节点 · ${value.profile.configured?"代理已配置":"等待代理配置"}`;$("profileState").textContent=value.profile.configured?`代理配置已就绪，使用端口 ${value.profile.port}；${(live.profile_update||cloud.profile_update)?.status||"每次运行自动检查代理与内核更新"}。`:"本机尚无代理配置，可自动读取或导入现有节点。";
 if(cloud.network?.message)$("profileState").textContent+=` ${cloud.network.message}。`;
 const sources=live.sources||{},fixed=sources.fixed_fetched_this_round===false?"两个固定链接已在首轮获取，本轮不重复抓取":`链接一 ${sources.fixed_sources?.["fixed-source-a"]??"—"} 个 · 链接二 ${sources.fixed_sources?.["fixed-source-b"]??"—"} 个`;$("sources").textContent=`${fixed} · 边缘池 ${sources.cloudflare_official_count??"—"} 个 · 日本补充 ${sources.jp_supplement_count??"—"} 个`;
 const h=value.published||{};$("publishState").textContent=h.published?(value.workflow?.find(row=>row.id==="publish")?.status==="completed"?`本轮已推送 GitHub：普通 ${h.general_final_count} 个＋日本 ${h.jp_final_count} 个，共 110 个不同 IP。`:`本机保存了合格结果；本轮 GitHub 推送尚未确认。`):`本轮：普通 ${h.general_final_count||0}/100 · 日本 ${h.jp_final_count||0}/10。${h.last_good_count?`保留上次 ${h.last_good_count} 个已发布 IP。`:"等待首次成功发布。"}`;$("actions").href=value.actions_url;workflow(value.workflow);rules(value.rules);await Promise.all([refreshRows(),refreshResults()]);$("liveSelectionInfo").textContent=`当前项目：${label(live.stage)} · 实测 ${live.proxy_tested_count||0} 个 · 通过 ${live.qualified_count||0} 个`;if(cloud.monitor_warning)feedback(cloud.monitor_warning);if(cloud.status==="Failed")feedback(`${cloud.stage||"云端任务失败"}。${value.local_running?"本地测速仍在继续，结果正在保存。":"已保留异常断点，可继续测试。"}`);if($("feedback").textContent==="正在读取本机状态…")feedback("点击开始优选后，云端获取、下载、本地测速、复测和发布将自动进行。");
 }catch(error){feedback(error.message||"本地服务暂时无法连接");}finally{setTimeout(poll,2000);}}
for(const button of document.querySelectorAll("[data-action]"))button.addEventListener("click",async()=>{button.disabled=true;feedback("正在提交操作…");try{const value=await post(button.dataset.action);feedback(value.started?"任务已启动，获取与实测结果会自动更新。":"请求已保存，将在当前步骤结束后执行。");}catch(error){feedback(error.message);}finally{button.disabled=false;}});
document.querySelector('[data-list="candidates"]').addEventListener("click",()=>{pageNumber=1;refreshRows().catch(e=>feedback(e.message));});
for(const button of document.querySelectorAll("[data-results]"))button.addEventListener("click",async()=>{resultKind=button.dataset.results;resultPage=1;for(const other of document.querySelectorAll("[data-results]")){other.classList.toggle("primary",other===button);other.classList.toggle("secondary",other!==button);other.setAttribute("aria-pressed",String(other===button));}try{await refreshResults();}catch(error){feedback(error.message);}});
$("resultPrevious").addEventListener("click",()=>{resultPage=Math.max(1,resultPage-1);refreshResults().catch(e=>feedback(e.message));});$("resultNext").addEventListener("click",()=>{resultPage=Math.min(resultPages,resultPage+1);refreshResults().catch(e=>feedback(e.message));});$("resultPageForm").addEventListener("submit",event=>{event.preventDefault();resultPage=Number($("resultPageNumber").value);refreshResults().catch(e=>feedback(e.message));});
$("previousPage").addEventListener("click",()=>{pageNumber=Math.max(1,pageNumber-1);refreshRows().catch(e=>feedback(e.message));});$("nextPage").addEventListener("click",()=>{pageNumber=Math.min(totalPages,pageNumber+1);refreshRows().catch(e=>feedback(e.message));});$("pageForm").addEventListener("submit",event=>{event.preventDefault();pageNumber=Number($("pageNumber").value);refreshRows().catch(e=>feedback(e.message));});$("closeDetail").addEventListener("click",()=>$("detailDialog").close());
$("rulesForm").addEventListener("submit",async event=>{event.preventDefault();const values={};for(const [key] of fields)values[key]=Number(new FormData(event.target).get(key));values.download_bytes*=1048576;values.minimum_completion_ratio/=100;try{const response=await post("rules",values);$("ruleFeedback").textContent=response.effective.replace("Batch","批次");}catch(error){$("ruleFeedback").textContent=error.message;}});
$("refreshCloud").addEventListener("click",()=>post("refresh-cloud-results").catch(error=>feedback(error.message)));
refreshCloudRows().catch(()=>{});setInterval(()=>refreshCloudRows().catch(()=>{}),4000);
$("autoImport").addEventListener("click",async()=>{try{await post("import-existing",{auto:true});feedback("本机代理已读取，开始优选时自动准备规则代理内核。");}catch(error){feedback(error.message);}});$("importProfile").addEventListener("click",async()=>{try{await post("import",{text:$("profileText").value});$("profileText").value="";feedback("代理配置已保存并检查格式，参数仅保存在本机。");}catch(error){feedback(error.message);}});
const browserClient=crypto.randomUUID();
const presence=closed=>fetch("/api/browser-presence",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({client:browserClient,closed})}).catch(()=>{});presence(false);setInterval(()=>presence(false),15000);window.addEventListener("pagehide",()=>navigator.sendBeacon("/api/browser-presence",JSON.stringify({client:browserClient,closed:true})));poll();

// Preserve the original page's decorative particles, card light and click ripples.
(()=>{
 const layer=document.getElementById("ambientParticles"),colors=["cyan","green","violet"];
 if(layer&&!layer.childElementCount)for(let index=0;index<30;index++){
  const particle=document.createElement("i");particle.className=`ambient-particle ${colors[index%colors.length]}`;
  for(const [name,value] of Object.entries({x:`${(index*37+11)%100}%`,drift:`${((index*29)%31)-15}vw`,size:`${2+index%4}px`,duration:`${14+(index%8)*2}s`,delay:`${-(index%12)*1.7}s`}))particle.style.setProperty(`--${name}`,value);
  layer.append(particle);
 }
 const observer=new IntersectionObserver(entries=>entries.forEach(entry=>entry.target.classList.toggle("motion-offscreen",!entry.isIntersecting)));
 for(const step of document.querySelectorAll(".flow-step"))observer.observe(step);
 const atmosphere=card=>{
  if(!card||card.querySelector(":scope > .card-atmosphere"))return;
  const glow=document.createElement("span");glow.className="card-atmosphere";glow.setAttribute("aria-hidden","true");
  for(let index=0;index<32;index++){
   const spark=document.createElement("i");
   for(const [name,value] of Object.entries({px:`${7+(index*31)%86}%`,pd:`${2.8+index%4*.4}s`,pl:`${-index*.31}s`,sway:`${index%2?24:-24}px`}))spark.style.setProperty(`--${name}`,value);
   glow.append(spark);
  }card.append(glow);observer.observe(card);
 };
 for(const step of document.querySelectorAll(".flow-step"))atmosphere(step);
 for(const event of ["pointerover","focusin"])document.addEventListener(event,e=>atmosphere(e.target.closest(".panel,.metric-card")));
 const visibility=()=>document.body.classList.toggle("page-hidden",document.hidden);
 document.addEventListener("visibilitychange",visibility);visibility();
 document.addEventListener("pointerdown",event=>{
  const button=event.target.closest(".button");if(!button||button.disabled)return;
  const rect=button.getBoundingClientRect(),ripple=document.createElement("span");ripple.className="ripple-ink";
  ripple.style.left=`${event.clientX-rect.left}px`;ripple.style.top=`${event.clientY-rect.top}px`;button.append(ripple);
  button.classList.add("button-pressed");setTimeout(()=>button.classList.remove("button-pressed"),460);
  ripple.addEventListener("animationend",()=>ripple.remove(),{once:true});
 });
 const select=()=>document.querySelectorAll("[data-list]").forEach(button=>button.setAttribute("aria-pressed",String(button.classList.contains("primary"))));
 document.addEventListener("click",event=>{if(event.target.closest("[data-list]"))select();});select();
})();
