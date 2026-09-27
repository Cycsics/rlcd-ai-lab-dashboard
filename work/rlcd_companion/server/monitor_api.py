"""Read-only balance templates. No prompts, executable scripts or credential redirects."""
import ipaddress
import json
import math
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from monitor_store import Balance,Quota
import time

class QueryError(RuntimeError): pass

def valid_query_url(url):
    try:
        p=urlsplit(url);port=p.port
        if not p.hostname or p.username or p.password or p.query or p.fragment: return False
        if p.scheme=='https': return True
        ip=ipaddress.ip_address(p.hostname)
        return p.scheme=='http' and (ip.is_private or ip.is_loopback) and not ip.is_unspecified
    except ValueError: return False

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def request_bytes(url,token,headers=None,body=None):
    if not valid_query_url(url): raise QueryError('请使用 HTTPS 查询地址；本机或私有网络允许 HTTP，地址不能包含凭据或查询参数')
    req=urllib.request.Request(url,data=body,headers={'Authorization':'Bearer '+token,'Accept':'application/json',**(headers or {})})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=15) as r:
            data=r.read(2*1024*1024+1)
            if len(data)>2*1024*1024: raise QueryError('用量响应过大')
            return data,dict(r.headers)
    except urllib.error.HTTPError as e:
        if e.code in (401,403): raise QueryError('凭据被拒绝，请核对平台、权限或重新登录') from None
        if 300<=e.code<400: raise QueryError('查询地址发生重定向；为保护凭据已停止，请填写最终接口地址') from None
        if e.code==429: raise QueryError('查询过于频繁，请稍后重试') from None
        raise QueryError('用量接口暂不可用') from None
    except (urllib.error.URLError,TimeoutError): raise QueryError('用量查询连接失败，请检查网络') from None

def number(value):
    if value is None or isinstance(value,bool): return None
    try: result=float(value)
    except (ValueError,TypeError): return None
    return result if math.isfinite(result) else None

def extract(data,path):
    if not path:return None
    for part in path.split('.'):
        try:data=data[int(part)] if isinstance(data,list) else data[part]
        except (KeyError,ValueError,TypeError,IndexError):return None
    return number(data)

def normalize_api(payload,cfg):
    template=cfg.get('template','deepseek')
    if template=='deepseek':
        rows=[Balance(currency=x.get('currency','USD'),remaining=number(x.get('total_balance'))) for x in payload.get('balance_infos',[])[:8]]
    elif template=='siliconflow':
        if payload.get('code') not in (None,0,200): raise QueryError('余额接口返回失败状态')
        rows=[Balance(currency='CNY' if cfg.get('region')=='cn' else 'USD',remaining=extract(payload,'data.totalBalance'))]
    elif template=='openrouter':
        total=extract(payload,'data.total_credits');used=extract(payload,'data.total_usage')
        rows=[Balance(currency='USD',remaining=total-used if total is not None and used is not None else None,total=total,used=used)]
    else:
        if payload.get('success') is False: raise QueryError('余额接口返回失败状态')
        paths=('data.quota','data.used_quota','') if template=='newapi' else (cfg.get('balance_path','balance'),cfg.get('used_path',''),cfg.get('total_path',''))
        values=[extract(payload,path) for path in paths]
        divisor=cfg.get('divisor',1)
        values=[v/divisor if v is not None else None for v in values]
        balance,used,total=values
        if template=='newapi' and balance is not None and used is not None:total=balance+used
        rows=[Balance(currency=cfg.get('currency','USD'),remaining=balance,used=used,total=total)]
    if not rows or all(r.remaining is None for r in rows): raise QueryError('接口未返回余额，请检查查询模板或字段路径')
    return rows

def collect_api(provider,cfg):
    template=cfg.get('template','deepseek'); token=cfg.get('token','')
    if not token: raise QueryError('请在本机配置 API Key 或账户访问令牌')
    endpoints={'deepseek':'https://api.deepseek.com/user/balance','siliconflow':'https://api.siliconflow.'+('cn' if cfg.get('region')=='cn' else 'com')+'/v1/user/info','openrouter':'https://openrouter.ai/api/v1/credits'}
    url=endpoints.get(template) or cfg.get('query_url','')
    headers={}
    if template=='newapi': headers['New-Api-User']=cfg.get('user_id','')
    raw,_=request_bytes(url,token,headers)
    try:payload=json.loads(raw)
    except ValueError:raise QueryError('余额接口未返回有效 JSON') from None
    if not isinstance(payload,dict):raise QueryError('余额响应格式不支持')
    return Quota(provider=provider,account=cfg.get('account','default'),fetched_at=time.time(),kind='api',balances=normalize_api(payload,cfg),plan=template)
