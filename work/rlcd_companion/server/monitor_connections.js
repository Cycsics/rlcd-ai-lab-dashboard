/* Optional subscriptions and a separate API-balance screen. Keys never reappear in inputs. */
let connectionsReady=false;
const subscriptionChoices={codex:'Codex',glm:'GLM',qoder:'Qoder',claude:'Claude',grok:'Grok'};
const apiTemplates={deepseek:'DeepSeek',siliconflow:'硅基流动',openrouter:'OpenRouter',newapi:'New API 中转站',custom:'自定义 JSON 接口'};
function connectionSelect(parent,label,id,options,value){
  const l=el('label',label),s=el('select');s.id=id;
  for(const [v,t] of Object.entries(options)){const o=el('option',t);o.value=v;s.append(o)}
  s.value=value;l.append(s);parent.append(l);return s;
}
function updateConnections(data){
  if(!connectionsReady){
    const modes=el('section'),form=el('form');form.id='screen-mode-form';modes.append(el('h2','屏幕版本'),form);
    connectionSelect(form,'选择监控版本','screen-mode',{subscription:'订阅额度版',api:'API 余额版'},data.settings.display.mode);
    const slots=el('div');slots.className='grid';form.append(slots);
    data.settings.display.subscriptions.forEach((p,i)=>connectionSelect(slots,'订阅第 '+(i+1)+' 列','sub-slot-'+i,subscriptionChoices,p));
    form.append(el('p','订阅版显示所选三个平台；API 版显示下方三个 API 账户。固定单屏，手动切换，不轮播。'));
    const save=el('button','保存屏幕版本');form.append(save);
    form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await api('/api/settings','PUT',{display:{mode:document.getElementById('screen-mode').value,subscriptions:[0,1,2].map(i=>document.getElementById('sub-slot-'+i).value)}});msg('屏幕版本已保存，下次取图生效。');load()}catch(err){msg(err.message)}finally{save.disabled=false}};
    document.querySelector('.preview').after(modes);
    const section=el('section');section.append(el('h2','更多订阅与 API 账户'));
    section.append(el('p','参考 CC Switch 的连接模板。订阅登录与 API Key 分开使用；这里只读查询余额/额度，不发送模型请求。新增账户默认不启用。'));
    const grid=el('div');grid.className='grid';section.append(grid);
    document.getElementById('settings').closest('section').after(section);
    for(const p of ['claude','grok','api1','api2','api3']){
      const isApi=p.startsWith('api'),cfg=data.settings.accounts[p]||{},price=data.settings.prices[p]||{};
      const card=el('div');card.className='card';card.append(el('h2',isApi?'API 账户 '+p.slice(-1):subscriptionChoices[p]));
      const status=el('div');status.id=p+'-connection-status';card.append(status);
      const details=el('details');details.append(el('summary','连接设置'));const f=el('form');details.append(f);card.append(details);grid.append(card);
      field(f,'启用自动查询',p+'-connection-enabled','checkbox',cfg.enabled||false);
      field(f,'账户标识',p+'-connection-account','text',cfg.account||'default');
      if(isApi){
        field(f,'屏幕名称',p+'-connection-name','text',cfg.name||'').maxLength=20;
        connectionSelect(f,'查询模板',p+'-template',apiTemplates,cfg.template||'deepseek');
        connectionSelect(f,'硅基流动地区',p+'-api-region',{cn:'中国站',global:'国际站'},cfg.region||'cn');
      }
      const key=field(f,isApi?'API Key / 账户访问令牌（留空保留）':'OAuth Access Token（留空读取本机 CLI 登录）',p+'-connection-token','password');key.autocomplete='new-password';
      if(isApi){
        const custom=el('div');f.append(custom);
        field(custom,'完整余额查询地址（New API: /api/user/self）',p+'-query-url','url',cfg.query_url||'');
        field(custom,'New API 用户 ID',p+'-user-id','text',cfg.user_id||'');
        field(custom,'余额字段路径（例如 data.balance）',p+'-balance-path','text',cfg.balance_path||'balance');
        field(custom,'已用字段路径（可留空）',p+'-used-path','text',cfg.used_path||'');
        field(custom,'总额字段路径（可留空）',p+'-total-path','text',cfg.total_path||'');
        field(custom,'币种 / 单位',p+'-api-currency','text',cfg.currency||'USD');
        const divisor=field(custom,'数值除数（按站点单位填写）',p+'-divisor','number',cfg.divisor??1);divisor.min='0.000001';divisor.step='any';
        custom.append(el('small','New API 使用账户访问令牌和用户 ID，不是模型调用 Key；常见 USD 换算除数为 500000，以站点实际规则为准。自定义接口仅支持 GET + Bearer 认证与 JSON 字段路径，不执行脚本。'));
        const template=document.getElementById(p+'-template');
        const show=()=>{custom.hidden=!['newapi','custom'].includes(template.value);document.getElementById(p+'-api-region').parentElement.hidden=template.value!=='siliconflow'};
        template.onchange=()=>{if(template.value==='newapi'&&Number(divisor.value)===1)divisor.value=500000;show()};show();
      }else{
        f.append(el('small',p==='claude'?'在本机 Claude Code 登录后启用。读取本机 OAuth 凭据，过期后请重新登录。':'在本机 Grok CLI 登录后启用。查询 Grok Build / SuperGrok 账单接口；不保证普通网页订阅可查询。'));
        field(f,'订阅金额',p+'-extra-amount','number',price.amount??'').min=0;
        connectionSelect(f,'币种',p+'-extra-currency',{'¥':'¥','$':'$','€':'€'},price.currency||'$');
        connectionSelect(f,'周期',p+'-extra-period',{'月':'月','年':'年'},price.period||'月');
        field(f,'续费基准日期',p+'-extra-renewal','date',price.renewal_date||'');
        field(f,'自动滚动续费日期',p+'-extra-auto','checkbox',price.auto_renewal!==false);
      }
      const save=el('button','保存连接'),test=el('button','保存并测试');test.type='button';f.append(save,test);
      const submit=async testing=>{
        save.disabled=test.disabled=true;
        try{
          const v=s=>document.getElementById(p+'-'+s).value;
          const account={enabled:document.getElementById(p+'-connection-enabled').checked,account:v('connection-account')};
          if(key.value.trim())account.token=key.value.trim();
          const body={accounts:{[p]:account}};
          if(isApi)Object.assign(account,{name:v('connection-name'),template:v('template'),region:v('api-region'),query_url:v('query-url'),user_id:v('user-id'),balance_path:v('balance-path'),used_path:v('used-path'),total_path:v('total-path'),currency:v('api-currency'),divisor:Number(v('divisor'))});
          else body.prices={[p]:{amount:v('extra-amount')===''?null:Number(v('extra-amount')),currency:v('extra-currency'),period:v('extra-period'),renewal_date:v('extra-renewal')||null,auto_renewal:document.getElementById(p+'-extra-auto').checked}};
          await api('/api/settings','PUT',body);key.value='';
          if(testing){const result=await(await api('/api/connections/'+p+'/test','POST',{})).json();msg(result.error||'连接查询成功，已更新显示。')}
          else msg('连接已保存；启用后每 5 分钟自动查询。');
          load();
        }catch(e){msg(e.message)}finally{save.disabled=test.disabled=false}
      };
      f.onsubmit=e=>{e.preventDefault();submit(false)};test.onclick=()=>{if(f.reportValidity())submit(true)};
    }
    connectionsReady=true;
  }
  for(const p of ['claude','grok','api1','api2','api3']){
    const q=data.quotas[p],n=document.getElementById(p+'-connection-status');n.replaceChildren();
    if(!q){n.append(el('p',data.settings.accounts[p].configured?'凭据已就绪，启用或测试查询':'未配置'));continue}
    if(p.startsWith('api'))for(const b of q.balances||[])n.append(el('p',`${b.currency} 剩余 ${b.remaining??'未知'} · 已用 ${b.used??'未知'} · 总额 ${b.total??'未知'}`));
    else for(const w of q.windows||[])n.append(el('p',`${w.label}：${w.remaining_percent==null?'未知':w.remaining_percent.toFixed(0)+'%'}${w.resets_at?' · 重置 '+time(w.resets_at):''}`));
    if(q.error||q.stale){const e=el('p',q.error||'数据过期');e.className='error';n.append(e)}
    n.append(el('small','更新 '+time(q.fetched_at)));
    const price=data.settings.prices[p];if(price)n.append(el('small',(price.amount==null?'费用未设':price.currency+price.amount+'/'+price.period)+' · '+(price.next_renewal_date?'预计续费 '+price.next_renewal_date:'续费日期未设')));
  }
}
