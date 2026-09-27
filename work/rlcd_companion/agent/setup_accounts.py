import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
path=Path(__file__).with_name('config.json');cfg=json.loads(path.read_text(encoding='utf-8'))
root=tk.Tk();root.title('实验室账户额度采集');root.geometry('530x380')
tk.Label(root,text='可选：凭据留在这台实验室电脑，仅上报额度。\n账户标识需要与看板配置页一致。').pack(pady=12)
entries={}
for provider in ['glm','qoder']:
    tk.Label(root,text=provider.upper()+' 账户标识 / Key 或 Access Token').pack()
    account=tk.Entry(root,width=55);account.insert(0,cfg.get('accounts',{}).get(provider,{}).get('account','default'));account.pack()
    token=tk.Entry(root,width=55,show='*');token.pack(pady=4);entries[provider]=(account,token)
region=tk.StringVar(value=cfg.get('accounts',{}).get('qoder',{}).get('region','global'))
tk.Label(root,text='Qoder 账户地区').pack()
tk.Radiobutton(root,text='中国站 qoder.cn',variable=region,value='cn').pack()
tk.Radiobutton(root,text='国际站 qoder.com',variable=region,value='global').pack()

def save():
    for p,(account,token) in entries.items():
        if token.get(): cfg.setdefault('accounts',{})[p]={'enabled':True,'account':account.get(),'token':token.get()}
    if 'qoder' in cfg.get('accounts',{}): cfg['accounts']['qoder']['region']=region.get()
    path.write_text(json.dumps(cfg,indent=2,ensure_ascii=False),encoding='utf-8');messagebox.showinfo('已保存','下一次额度采集时生效。');root.destroy()
tk.Button(root,text='保存',command=save).pack(pady=15);root.mainloop()
