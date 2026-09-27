"""Read local CLI login state and query subscription usage without running a model.
Protocol reference: farion1231/cc-switch subscription.rs and subscription_grok.rs.
Grok's undocumented wire schema is checked strictly; unknown responses stay unknown.
"""
from datetime import datetime,timezone
from pathlib import Path
import json, math, struct, time
from monitor_api import QueryError,request_bytes,number
from monitor_store import Quota,Window

def timestamp(value):
    if value is None:return None
    if isinstance(value,(int,float)):return int(value/1000 if value>100000000000 else value)
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp())
    except (ValueError,TypeError,AttributeError):return None

def credential_path(provider):
    return Path.home()/('.claude/.credentials.json' if provider=='claude' else '.grok/auth.json')

def credential(provider,manual=''):
    if manual:return manual
    try:root=json.loads(credential_path(provider).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):raise QueryError('未找到本机登录，请先在对应 Claude Code / Grok CLI 登录，或填写 OAuth Access Token') from None
    if not isinstance(root,dict):raise QueryError('本机登录文件格式不支持，请重新登录')
    if provider=='claude':
        entry=root.get('claudeAiOauth') or root.get('claude.ai_oauth') or {}
        token=entry.get('accessToken');expires=timestamp(entry.get('expiresAt'))
    else:
        entries=[v for k,v in root.items() if k.startswith('https://auth.x.ai::') and isinstance(v,dict) and v.get('key')]
        entry=next(iter(entries),root.get('https://accounts.x.ai/sign-in',{}))
        token=entry.get('key');expires=timestamp(entry.get('expires_at'))
    if expires and expires<=time.time():raise QueryError('本机登录已过期，请在对应 CLI 重新登录')
    if not isinstance(token,str) or not token:raise QueryError('本机登录中没有可用的 OAuth Access Token')
    return token

def normalize_claude(data,account):
    if not isinstance(data,dict):raise QueryError('Claude 用量响应格式不支持')
    windows=[]
    for key,label in [('five_hour','5小时'),('seven_day','7天'),('seven_day_opus','Opus 7天'),('seven_day_sonnet','Sonnet 7天')]:
        w=data.get(key)
        if not isinstance(w,dict):continue
        used=number(w.get('utilization'))
        if used is not None and not 0<=used<=100:raise QueryError('Claude 额度响应超出预期范围')
        windows.append(Window(label=label,remaining_percent=None if used is None else 100-used,resets_at=timestamp(w.get('resets_at'))))
    if not windows:raise QueryError('Claude 未返回订阅额度，请检查订阅登录')
    return Quota(provider='claude',account=account,fetched_at=time.time(),windows=windows)

def proto_fields(data):
    fields={};i=0
    def varint():
        nonlocal i
        n=0
        for shift in range(0,70,7):
            if i>=len(data):raise ValueError('truncated')
            b=data[i];i+=1;n|=(b&127)<<shift
            if not b&128:return n
        raise ValueError('varint')
    while i<len(data):
        key=varint();field=key>>3;wire=key&7
        if not field or field in fields:raise ValueError('unexpected field')
        if wire==0:value=varint()
        elif wire in (1,2,5):
            length=varint() if wire==2 else (8 if wire==1 else 4)
            if i+length>len(data):raise ValueError('truncated')
            value=data[i:i+length];i+=length
            if wire==5:value=struct.unpack('<f',value)[0]
        else:raise ValueError('wire')
        fields[field]=(wire,value)
    return fields

def normalize_grok(data,headers,account):
    try:
        if str({k.lower():v for k,v in headers.items()}.get('grpc-status','0'))!='0':raise ValueError('RPC error')
        frames=[];i=0
        while i<len(data):
            if len(data)-i<5:raise ValueError('frame')
            flag=data[i];length=int.from_bytes(data[i+1:i+5],'big');i+=5
            if i+length>len(data):raise ValueError('frame')
            payload=data[i:i+length];i+=length
            if flag==128:
                trailer=dict(line.split(':',1) for line in payload.decode().splitlines() if ':' in line)
                if trailer.get('grpc-status','0').strip()!='0':raise ValueError('RPC error')
            elif flag==0:frames.append(payload)
            else:raise ValueError('compression')
        if len(frames)!=1:raise ValueError('messages')
        root=proto_fields(frames[0]);wire,body=root[1]
        if wire!=2:raise ValueError('schema')
        fields=proto_fields(body);used=None;reset=None
        if 1 in fields:
            wire,used=fields[1]
            if wire!=5 or not math.isfinite(used) or not 0<=used<=100:raise ValueError('percentage')
        if 5 in fields:
            wire,raw=fields[5]
            if wire!=2:raise ValueError('timestamp')
            wire,reset=proto_fields(raw)[1]
            if wire!=0 or not 1577836800<reset<4102444800:raise ValueError('timestamp')
        if used is None and reset and 6 in fields and fields[6][0]==2 and proto_fields(fields[6][1]):used=0
        if used is None:raise ValueError('usage missing')
    except (ValueError,KeyError,TypeError,UnicodeError,struct.error):raise QueryError('Grok 订阅接口未返回可识别额度或拒绝登录；请检查 CLI 登录，接口变化时保留未知') from None
    return Quota(provider='grok',account=account,fetched_at=time.time(),windows=[Window(label='订阅额度',remaining_percent=100-used,resets_at=reset)])

def collect_subscription(provider,cfg):
    token=credential(provider,cfg.get('token',''));account=cfg.get('account','default')
    if provider=='claude':
        raw,_=request_bytes('https://api.anthropic.com/api/oauth/usage',token,{'anthropic-beta':'oauth-2025-04-20'})
        try:payload=json.loads(raw)
        except ValueError:raise QueryError('Claude 用量响应不是有效 JSON') from None
        return normalize_claude(payload,account)
    raw,headers=request_bytes('https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig',token,{'Origin':'https://grok.com','Referer':'https://grok.com/','Content-Type':'application/grpc-web+proto','x-grpc-web':'1','x-user-agent':'connect-es/2.1.1'},b'\0'*5)
    return normalize_grok(raw,headers,account)
