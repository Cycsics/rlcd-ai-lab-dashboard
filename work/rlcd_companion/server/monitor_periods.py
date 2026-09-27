"""Published billing windows, evaluated in Beijing time; not account eligibility."""
from datetime import datetime, date
from zoneinfo import ZoneInfo

GLM_SOURCE='https://docs.bigmodel.cn/cn/coding-plan/overview'
QODER_SOURCE='https://docs.qoder.cn/product-overview/qwen-3-7-series-model-staggering-discount'

def billing_periods(now):
    dt=datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai'))
    holiday=date(2026,9,25)<=dt.date()<=date(2026,10,7)
    peak=not holiday and dt.weekday()<5 and 14<=dt.hour<18
    night=dt.hour>=22 or dt.hour<8
    return {
        'glm':{'label':'高峰期' if peak else '非高峰','active':peak,
               'detail':'双节活动：2026/9/25–10/7 全天非高峰' if holiday else '北京时间周一至周五 14:00–18:00 为高峰，其余时段非高峰',
               'source':GLM_SOURCE},
        'qoder':{'label':'夜惠时段' if night else '非夜惠','active':night,
                 'detail':'个人账户：北京时间 22:00–次日08:00，限官方指定 Qwen 模型；时段提示不代表当前任务实际享受折扣',
                 'source':QODER_SOURCE}}
