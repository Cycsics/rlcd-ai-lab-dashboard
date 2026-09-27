from datetime import datetime
from io import BytesIO
from pathlib import Path
from functools import lru_cache
from PIL import Image, ImageDraw
from monitor_periods import billing_periods
from monitor_billing import next_renewal_date
from pet import draw_pixel_pet
from renderer import _font, _draw_text, _pack_image, TZ

from monitor_catalog import NAMES,APIS,TASK_NAMES

def draw_api_column(text,x,q,width,now):
    rows=q.get('balances',[]) if q else []
    if not rows:
        text(x,58,'查询失败' if q and q.get('error') else '未连接',18,width)
        text(x,90,'请配置 API 余额',11,width)
    else:
        for index,b in enumerate(rows[:2]):
            y=54+index*43
            text(x,y,'剩余 '+b.get('currency',''),11,width)
            value=b.get('remaining')
            value=f'{value:,.2f}' if value is not None else '未知'
            size=20
            while size>10 and _font(size).getlength(value)>width:size-=1
            text(x,y+16,value,size,width)
        if len(rows)==1:
            b=rows[0];used=b.get('used');total=b.get('total')
            text(x,99,'已用 '+(f'{used:,.2f}' if used is not None else '未知'),11,width)
            text(x,118,'总额 '+(f'{total:,.2f}' if total is not None else '未知'),11,width)
    text(x,141,'按量计费 · '+('需更新' if q and (q.get('stale') or q.get('error')) else 'API 余额'),10,width)

def window_date_label(provider, window):
    if window.get('not_applicable'): return 'Pro · 无独立5h窗口'
    stamp=window.get('expires_at') if provider=='qoder' else window.get('resets_at')
    if stamp:
        when=datetime.fromtimestamp(stamp,TZ)
        return f'{when.month}月{when.day}日到期' if provider=='qoder' else f'{when.month}月{when.day}日 {when:%H:%M}重置'
    if provider=='qoder': return '到期日未返回'
    if window['label'] in ('5小时','300分钟','5h'): return '使用一次激活5h'
    return '重置时间未知'

def credit_ratio(window):
    def number(value): return f'{value:g}' if value is not None else '--'
    return f"{number(window.get('remaining'))}/{number(window.get('total'))}"

@lru_cache(maxsize=1)
def codex_pet_frame():
    source=Path(__file__).parent/'data/codex-pet.webp'
    if not source.exists(): return None
    with Image.open(source) as sheet:
        frame=sheet.convert('RGBA').crop((0,0,192,208))
    frame=frame.crop(frame.getbbox())
    frame.thumbnail((78,84),Image.Resampling.LANCZOS)
    canvas=Image.new('RGBA',frame.size,'white')
    canvas.alpha_composite(frame)
    return canvas.convert('L').point(lambda v:255 if v>=110 else 0,mode='1')

def render_monitor(summary, environment, settings, fmt='png'):
    image=Image.new('1',(400,300),1)
    d=ImageDraw.Draw(image)
    def text(x,y,value,size=12,width=390):
        font=_font(size)
        # Position the visible glyph top, not the font's ascender origin.
        top=font.getbbox(str(value))[1]
        _draw_text(d,(x,y-top),str(value),font,max_width=width)
    now=summary['now']; dt=datetime.fromtimestamp(now,TZ)
    periods=billing_periods(now)
    weather=environment.get('weather','天气--')
    temp=environment.get('indoor_temperature_c'); humidity=environment.get('indoor_humidity_percent')
    indoor=f'室{temp:.0f}° {humidity:.0f}%' if temp is not None and humidity is not None else '室--'
    battery=environment.get('battery'); battery='--' if battery is None else str(battery)
    text(6,4,f'{dt:%H:%M} {dt.month}/{dt.day} {weather} {indoor} 电{battery}%',12)
    for y in (25,155,279): d.line((0,y,399,y),fill=0)
    for x in (133,266): d.line((x,26,x,155),fill=0)
    display=settings.get('display',{})
    providers=list(APIS) if display.get('mode')=='api' else display.get('subscriptions',['codex','glm','qoder'])
    for index,provider in enumerate(providers):
        x=index*133+7; q=summary['quotas'].get(provider); width=119
        d.rectangle((index*133+1,27,index*133+131,48),fill=0)
        title=settings.get('accounts',{}).get(provider,{}).get('name') or NAMES[provider]
        while _font(14).getlength(title)>86:title=title[:-1]
        d.text((x,30),title,font=_font(14),fill=1,anchor='lt')
        d.text((x+(94 if provider in APIS else 65),34),'API' if provider in APIS else periods[provider]['label'] if provider in periods else '剩余',font=_font(10),fill=1,anchor='lt')
        if provider in APIS:
            draw_api_column(text,x,q,width,now)
            continue
        windows=q.get('windows',[]) if q else []
        if provider=='codex' and windows:
            short=next((w for w in windows if w['label'] in ('5小时','300分钟','5h')),None)
            windows=[short or {'label':'5小时','remaining_percent':None,'unavailable':True,'not_applicable':q.get('plan','').lower()=='pro'}]+[w for w in windows if w is not short]
        if windows:
            for row,w in enumerate(windows[:2]):
                y=54+row*43
                label=w['label'].replace('小时','h')
                percent=w.get('remaining_percent')
                if provider=='qoder':
                    value=credit_ratio(w)
                    label+=' C'
                else: value='∞' if w.get('not_applicable') else f'{percent:.0f}%' if percent is not None else '--'
                text(x,y+4,label,10 if provider=='qoder' else 12,40 if provider=='qoder' else 62)
                value_left=x+40 if provider=='qoder' else x+64
                value_width=79 if provider=='qoder' else 55
                size=22 if value=='∞' else 18
                while size>9 and _font(size).getlength(value)>value_width: size-=1
                box=_font(size).getbbox(value)
                value_height=box[3]-box[1]
                value_x=value_left+(value_width-_font(size).getlength(value))/2
                text(value_x,y+(18-value_height)//2,value,size,value_width)
                d.rectangle((x,y+20,x+118,y+24),outline=0)
                if percent is not None:
                    fill=round(116*max(0,min(100,percent))/100)
                    if fill: d.rectangle((x+1,y+21,x+fill,y+23),fill=0)
                else:
                    for bx in range(x+3,x+117,6): d.point((bx,y+22),fill=0)
                text(x,y+29,window_date_label(provider,w),10,width)
        else:
            text(x,58,'未连接' if not q else '未知',20,width)
            text(x,88,'请在电脑端配置',11,width)
            text(x,111,'查询失败' if q and q.get('error') else '等待账户数据',11,width)
        price=settings.get('prices',{}).get(provider,{})
        cost=f"{price.get('currency','')}{price['amount']:g}/{price.get('period','月')}" if price.get('amount') is not None else '费用未设'
        renewal=price.get('next_renewal_date') or next_renewal_date(price,dt.date())
        renewal=f'{int(renewal[5:7])}/{int(renewal[8:10])}续费' if renewal else '续费待填'
        text(x,141,f'{cost} · {renewal}',10,width)
    tasks=summary.get('screen_tasks',summary['tasks']); machines=summary['machines']
    online=sum(m['online'] for m in machines)
    running=sum(t['display_status']=='running' for t in tasks)
    waiting=sum(t['display_status'].startswith('waiting') for t in tasks)
    done=sum(t['display_status']=='completed' for t in tasks)
    interrupted=sum(t['display_status'] in ('interrupted','failed') for t in tasks)
    unknown=sum(t['display_status'] in ('unknown','offline') for t in tasks)
    text(6,160,f'任务 · {"在线" if online else "离线"}',14,115)
    text(115,162,f'执行{running} 待办{waiting} 完成{done} 中断{interrupted}',10,179)
    if not machines:
        text(12,194,'本机采集正在启动',16)
        text(12,225,'请检查客户端与 Hooks',12,270)
    elif not tasks:
        text(12,197,'暂无任务事件',18)
        text(12,229,'客户端状态见电脑详情页',12)
    for i,t in enumerate(tasks[:3]):
        y=184+i*30
        text(6,y,f"{TASK_NAMES.get(t['tool'],t['tool'])} · {t['project'] or '未命名项目'}",12,174)
        text(190,y+3,t['status_label'],14,94)
        age=max(0,int(now-t['occurred_at']))
        text(6,y+16,f"{'本机' if t['machine_id'] in ('local-pc','local-chatgpt') else t['machine_id']}  {age//60}分钟前" if age>=60 else f"{'本机' if t['machine_id'] in ('local-pc','local-chatgpt') else t['machine_id']}  刚刚",10,174)
    d.line((295,163,295,271),fill=0)
    text(320,170,'Codex',13,74)
    pet_frame=codex_pet_frame()
    if pet_frame is not None:
        image.paste(pet_frame,(346-pet_frame.width//2,186))
    else:
        draw_pixel_pet(d,(304,190,394,266),'idle',1)
    freshest=max((m['last_seen'] for m in machines),default=None)
    footer=f'在线核对 {datetime.fromtimestamp(freshest,TZ):%H:%M:%S}' if freshest else '等待本机状态'
    stale=sum(q.get('stale',False) or bool(q.get('error')) for p,q in summary['quotas'].items() if p in providers)
    if stale: footer+=f' · {stale}项额度需更新'
    if len(tasks)>3: footer+=f' · 另{len(tasks)-3}项见网页'
    text(6,283,footer,11)
    if fmt=='bin': return _pack_image(image,None)
    result=BytesIO(); image.save(result,'PNG'); return result.getvalue()
