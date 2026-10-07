"use strict";
const $ = id => document.getElementById(id);
const fields = [
  ["batch_size","每 Batch 节点数",1,100,1],["round_count","Round 次数",1,10,1],
  ["max_proxy_average_latency_ms","最大平均延迟（ms）",1,10000,1],
  ["max_proxy_loss_percent","最大请求丢失（%）",0,100,0.1],
  ["min_proxy_speed_mbps","最低速度（Mbps；16 = 2 MB/s）",0.01,100000,0.1],
  ["download_attempts","下载次数",1,10,1],["download_bytes","每次下载大小（MiB）",1,8,1],
  ["request_timeout_seconds","请求超时（秒）",0.1,60,0.1],["download_timeout_seconds","下载超时（秒）",0.1,120,0.1],
  ["delay_concurrency","延迟并发",1,100,1],["round_cooldown_seconds","轮间隔（秒）",0,2,0.1]];
let initialized = false, historyRows = null, lastTable = "";
async function post(action,payload={}){const response=await fetch(`/api/proxybench/${action}`,{method:"POST",headers:{"Content-Type":"application/json","X-ProxyBench":"1"},body:JSON.stringify(payload)});const value=await response.json();if(!response.ok)throw Error(value.error||"操作失败");return value;}
function feedback(message){$("feedback").textContent=message;}
function number(value){return value==null?"—":typeof value==="number"?value.toFixed(2):String(value);}
function table(rows){const signature=JSON.stringify(rows);if(signature===lastTable)return;lastTable=signature;
 const headers=["IP","来源","JP Hint",...['Google','Cloudflare','GitHub'].flatMap(site=>[`${site} R1`,`${site} R2`,`${site} R3`,`${site} Avg`]),"Round1 Avg","Round2 Avg","Round3 Avg","Final Avg","Proxy Loss %","Speed1 Mbps","Speed2 Mbps","Speed3 Mbps","Speed Avg MB/s","Speed Avg Mbps","出口","状态"];
 const head=document.createElement("tr");for(const text of headers){const th=document.createElement("th");th.scope="col";th.textContent=text;head.append(th);}$("thead").replaceChildren(head);
 const fragment=document.createDocumentFragment();for(const row of rows){const tr=document.createElement("tr");const cells=[`${row.ip}:${row.port}`,(row.source_names||[]).join(", "),row.jp_hint?"候选提示":"—"];
 for(const site of ["google","cloudflare","github"]){const values=row[`${site}_rounds_ms`]||(row.probes?.[site]||[]).map(probe=>probe.latency_ms);cells.push(...[0,1,2].map(i=>number(values[i])),number(row[`${site}_average_ms`]));}
 cells.push(...[0,1,2].map(i=>number(row.round_averages_ms?.[i])),number(row.proxy_average_latency_ms),number(row.proxy_loss_percent),...[0,1,2].map(i=>number(row.download_rounds_mbps?.[i])),number(row.proxy_download_average_mbytes),number(row.proxy_download_average_mbps),row.geo_country||"未验证",row.status||"Queued");for(const text of cells){const td=document.createElement("td");td.textContent=text;tr.append(td);}fragment.append(tr);}$("tbody").replaceChildren(fragment);}
function rules(values){if(initialized)return;initialized=true;for(const [key,label,min,max,step] of fields){const wrapper=document.createElement("label");wrapper.className="field";const span=document.createElement("span");span.textContent=label;const input=document.createElement("input");input.type="number";input.name=key;input.min=min;input.max=max;input.step=step;input.required=true;input.value=key==="download_bytes"?values[key]/1048576:values[key];input.addEventListener("blur",()=>input.reportValidity());wrapper.append(span,input);$("rulesForm").append(wrapper);}}
async function poll(){try{const response=await fetch("/api/proxybench/state");const value=await response.json();if(!response.ok)throw Error(value.error);const live=value.live||{},core=live.mihomo||{};
 const cloud=value.cloud||{};$("stage").textContent=(value.running&&cloud.stage?cloud.stage:live.stage)||"等待开始";$("status").textContent=(value.running&&cloud.status?cloud.status:live.status)||"Ready";$("counts").textContent=`${live.candidate_total||0} / ${live.tested_count||0}`;$("batch").textContent=`Batch ${live.batch_current||0} / ${live.batch_total||0}`;
 $("qualified").textContent=`${live.qualified_count||0} / ${Math.max(0,(live.tested_count||0)-(live.qualified_count||0))}`;$("core").textContent=`${core.version||"未安装"} · ${core.status||"Stopped"}`;$("coreDetail").textContent=`Rule Mode · ${core.loaded_proxies||0} Proxies · Controller ${core.controller_healthy?"Healthy":"Stopped"}`;
 $("profileState").textContent=value.profile.configured?`已配置：${value.profile.protocol.toUpperCase()} · ${value.profile.network} · Port ${value.profile.port}。鉴权参数仅保存在本机。`:"缺少可用代理协议配置。点击自动读取本机配置，或导入现有节点链接。";
 const sources=live.sources||{};$("sources").textContent=`Fixed A: ${sources.fixed_sources?.["fixed-source-a"]??"—"} · Fixed B: ${sources.fixed_sources?.["fixed-source-b"]??"—"} · Official: ${sources.cloudflare_official_count??"—"} · JP Supplemental: ${sources.jp_supplement_count??"—"} · Unique: ${sources.unique_candidate_count??"—"}`;
 const published=value.published||{};$("publishState").textContent=published.publish_gate_passed?`已通过发布门槛：General ${published.general_final_count} + JP ${published.jp_final_count}；110 个唯一 IP。`:`尚无本版本成功结果，或本轮需要补池。General ${published.general_final_count||0}/100 · JP ${published.jp_final_count||0}/10。`;
 $("actions").href=value.actions_url;rules(value.rules);table(historyRows||live.candidates||[]);
 if($("feedback").textContent==="正在读取本机状态…")feedback("已连接本机控制台。先完成路径验收，再开始正式优选。");
 }catch(error){feedback(error.message||"本地服务暂时无法连接");}finally{setTimeout(poll,2000);}}
for(const button of document.querySelectorAll("[data-action]"))button.addEventListener("click",async()=>{button.disabled=true;historyRows=null;feedback("正在提交操作…");try{const value=await post(button.dataset.action);feedback(value.started?"任务已启动，实测结果将自动更新。":"请求已保存，将在当前小步骤结束后执行。");}catch(error){feedback(error.message);}finally{button.disabled=false;}});
$("rulesForm").addEventListener("submit",async event=>{event.preventDefault();const values={speed_concurrency:1};for(const [key] of fields)values[key]=Number(new FormData(event.target).get(key));values.download_bytes*=1048576;try{const response=await post("rules",values);$("ruleFeedback").textContent=response.effective;}catch(error){$("ruleFeedback").textContent=error.message;}});
$("autoImport").addEventListener("click",async()=>{try{await post("import-existing",{auto:true});feedback("已从本机配置导入。点击完成路径验收即可。");}catch(error){feedback(error.message);}});
$("importProfile").addEventListener("click",async()=>{try{await post("import",{text:$("profileText").value});$("profileText").value="";feedback("代理配置已导入并验证格式，参数仅保存在本机。");}catch(error){feedback(error.message);}});
$("history").addEventListener("click",async()=>{try{const value=await post("results",{});historyRows=value.rows;table(historyRows);feedback(`已完成 ${value.total} 条，显示前 100 条。`);}catch(error){feedback(error.message);}});
setInterval(()=>fetch("/api/browser-presence",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({client:"proxybench",closed:false})}).catch(()=>{}),15000);
poll();
