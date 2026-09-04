import calendar, hashlib, json, sqlite3, os
from datetime import date, datetime, timedelta
from pathlib import Path
import flet as ft

APP_DATA = Path(os.getenv("FLET_APP_STORAGE_DATA") or Path(__file__).parent)
APP_DATA.mkdir(parents=True, exist_ok=True)
DB = APP_DATA / "maintenance_v6.db"
UNITS = ["周", "月", "年"]
FIELD_NAMES = {"equipment_no":"设备编号","equipment_name":"设备名称","location":"使用区域","status":"状态","frequency_value":"频率整数","frequency_unit":"频率单位","warning_days":"预警天数","next_date":"下次日期","enabled":"启用状态"}

def con():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def hp(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()
def add_months(d,n):
    y=d.year+(d.month-1+n)//12; m=(d.month-1+n)%12+1
    return date(y,m,min(d.day,calendar.monthrange(y,m)[1]))
def next_due(d,v,u):
    if u=="周": return d+timedelta(weeks=v)
    return add_months(d,v if u=="月" else v*12)
def freq_text(v,u): return f"{v}{u}保养"
def normalize_no(s): return s.strip().upper().replace(" ","")

def init_db():
    with con() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,display_name TEXT,password_hash TEXT,enabled INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS equipment(id INTEGER PRIMARY KEY,equipment_no TEXT UNIQUE,equipment_name TEXT,location TEXT,status TEXT DEFAULT 'active');
        CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY,equipment_id INTEGER,frequency_value INTEGER,frequency_unit TEXT,warning_days INTEGER DEFAULT 7,last_date TEXT,next_date TEXT,enabled INTEGER DEFAULT 1,UNIQUE(equipment_id,frequency_value,frequency_unit));
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,equipment_no TEXT,equipment_name TEXT,frequency_text TEXT,maintain_time TEXT,operator_name TEXT,next_date TEXT);
        CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY,operator_name TEXT,operation_type TEXT,object_type TEXT,object_code TEXT,before_data TEXT,after_data TEXT,operation_time TEXT);
        """)
        if not c.execute("SELECT 1 FROM users").fetchone():
            c.execute("INSERT INTO users(username,display_name,password_hash) VALUES(?,?,?)",("chu","Chu",hp("123456")))
        if not c.execute("SELECT 1 FROM equipment").fetchone():
            demos=[("P-0010","球面镜安装治具","流式池",[(1,"月",5),(3,"月",25),(1,"年",182)]),("P-0035","光学板调光治具","光学板测试",[(1,"月",-2)]),("P-0068","电脑切管机","Service Parts",[(2,"周",10)])]
            for no,name,loc,ps in demos:
                eid=c.execute("INSERT INTO equipment(equipment_no,equipment_name,location) VALUES(?,?,?)",(no,name,loc)).lastrowid
                for v,u,left in ps:
                    c.execute("INSERT INTO plans(equipment_id,frequency_value,frequency_unit,next_date) VALUES(?,?,?,?)",(eid,v,u,(date.today()+timedelta(days=left)).isoformat()))

def log_change(c,user,op,obj,code,before,after):
    c.execute("INSERT INTO logs(operator_name,operation_type,object_type,object_code,before_data,after_data,operation_time) VALUES(?,?,?,?,?,?,?)",(user,op,obj,code,json.dumps(before,ensure_ascii=False) if before else None,json.dumps(after,ensure_ascii=False) if after else None,datetime.now().isoformat(timespec="seconds")))

def main(page:ft.Page):
    init_db(); page.title="设备维护系统 V6"; page.padding=0; page.window_width=720; page.window_height=940; page.adaptive=True; page.bgcolor=ft.Colors.GREY_100
    state={"user":None}
    def rows(sql,args=()):
        with con() as c: return c.execute(sql,args).fetchall()
    def notify(text,color=ft.Colors.BLUE_700):
        page.show_dialog(ft.SnackBar(ft.Text(text,color=ft.Colors.WHITE),bgcolor=color))
    def bar(title,back=None):
        cs=[]
        if back: cs.append(ft.IconButton(icon=ft.Icons.ARROW_BACK,icon_color=ft.Colors.WHITE,on_click=lambda e:back()))
        cs.append(ft.Text(title,size=24,weight=ft.FontWeight.BOLD,color=ft.Colors.WHITE,expand=True))
        if state["user"]: cs.append(ft.Container(ft.Text(state["user"]["display_name"],color=ft.Colors.WHITE,weight=ft.FontWeight.BOLD),padding=8,border_radius=10,bgcolor=ft.Colors.BLUE_GREY_700))
        return ft.Container(ft.Row(cs),padding=14,bgcolor=ft.Colors.BLUE_GREY_900,shadow=ft.BoxShadow(blur_radius=8,color=ft.Colors.BLACK26))
    def button(text,icon,fn): return ft.Button(content=text,icon=icon,height=52,on_click=fn)
    def login():
        page.clean(); u=ft.TextField(label="用户名",autofocus=True); p=ft.TextField(label="密码",password=True,can_reveal_password=True)
        def go(e=None):
            found=rows("SELECT * FROM users WHERE username=? AND password_hash=? AND enabled=1",(u.value.strip(),hp(p.value)))
            if not found: notify("用户名或密码错误",ft.Colors.RED_600); return
            state["user"]=found[0]; home()
        p.on_submit=go
        page.add(ft.Container(ft.Column([ft.Text("设备维护系统",size=30,weight=ft.FontWeight.BOLD),u,p,button("登录",ft.Icons.LOGIN,go),ft.Text("演示账号：chu / 123456")]),padding=40,width=500))
    def search_devices(k="",all_=False):
        k=f"%{k.strip()}%"; sql="""SELECT e.*,MIN(julianday(p.next_date)-julianday(date('now','localtime'))) nearest FROM equipment e LEFT JOIN plans p ON p.equipment_id=e.id AND p.enabled=1 WHERE (e.equipment_no LIKE ? OR e.equipment_name LIKE ? OR e.location LIKE ?)"""
        if not all_: sql+=" AND e.status='active'"
        sql+=" GROUP BY e.id ORDER BY CASE WHEN nearest IS NULL THEN 1 ELSE 0 END,nearest,e.equipment_no"
        return rows(sql,(k,k,k))
    def home():
        page.clean(); q=ft.TextField(label="扫描或模糊查询",hint_text="扫码枪扫描，或输入设备编号、名称、区域",prefix_icon=ft.Icons.SEARCH); out=ft.Column(spacing=8)
        active=search_devices(""); overdue=sum(1 for x in active if x["nearest"] is not None and x["nearest"]<0); due7=sum(1 for x in active if x["nearest"] is not None and 0<=x["nearest"]<=7)
        def stat_card(title,value,color,icon):
            return ft.Container(ft.Row([ft.Icon(icon,color=color,size=34),ft.Column([ft.Text(str(value),size=28,weight=ft.FontWeight.BOLD,color=color),ft.Text(title,color=ft.Colors.GREY_700)])]),padding=16,bgcolor=ft.Colors.WHITE,border_radius=16,shadow=ft.BoxShadow(blur_radius=8,color=ft.Colors.BLACK12),expand=True)
        def refresh(e=None):
            out.controls.clear()
            for r in search_devices(q.value):
                n=r["nearest"]; text="未设频率" if n is None else (f"逾期 {-int(n)} 天" if n<0 else ("今天到期" if int(n)==0 else f"还有 {int(n)} 天")); color=ft.Colors.GREY_600 if n is None else (ft.Colors.RED_600 if n<=0 else (ft.Colors.ORANGE_700 if n<=7 else ft.Colors.GREEN_700))
                out.controls.append(ft.Card(content=ft.ListTile(leading=ft.Container(ft.Icon(ft.Icons.PRECISION_MANUFACTURING,color=ft.Colors.WHITE),padding=10,border_radius=12,bgcolor=ft.Colors.BLUE_GREY_700),title=ft.Text(f"{r['equipment_no']}  {r['equipment_name']}",weight=ft.FontWeight.BOLD,size=17),subtitle=ft.Text(r['location']),trailing=ft.Text(text,color=color,weight=ft.FontWeight.BOLD),on_click=lambda e,x=r:detail(x['id']))))
            page.update()
        q.on_change=refresh
        def scan_submit(e=None):
            code=normalize_no(q.value)
            exact=rows("SELECT id FROM equipment WHERE equipment_no=? AND status='active'",(code,))
            if exact: detail(exact[0]["id"])
            else: notify(f"未找到设备 {code}",ft.Colors.RED_600)
        q.on_submit=scan_submit
        page.add(bar("设备维护系统"),ft.Container(ft.Column([ft.Row([stat_card("激活设备",len(active),ft.Colors.BLUE_700,ft.Icons.INVENTORY_2),stat_card("已逾期",overdue,ft.Colors.RED_600,ft.Icons.WARNING),stat_card("7天内到期",due7,ft.Colors.ORANGE_700,ft.Icons.SCHEDULE)]),ft.Row([button("设备管理",ft.Icons.SETTINGS,lambda e:manage()),button("保养记录",ft.Icons.FACT_CHECK,lambda e:records_page()),button("修改记录",ft.Icons.HISTORY,lambda e:audit_page())],wrap=True),q,ft.Text("扫码枪设置为键盘模式并附加回车，即可自动打开设备",size=12,color=ft.Colors.GREY_600),ft.Text("待保养设备（按最近到期排序）",size=18,weight=ft.FontWeight.BOLD),out,button("退出登录",ft.Icons.LOGOUT,lambda e:login())],scroll=ft.ScrollMode.AUTO),padding=18,expand=True)); refresh()
    def detail(eid):
        r=rows("SELECT * FROM equipment WHERE id=?",(eid,))[0]; ps=rows("SELECT * FROM plans WHERE equipment_id=? AND enabled=1 ORDER BY next_date",(eid,)); picks=[]; cards=[]
        for p in ps:
            cb=ft.Checkbox(); picks.append((cb,p)); n=(date.fromisoformat(p["next_date"])-date.today()).days
            cards.append(ft.Card(content=ft.ListTile(leading=cb,title=ft.Text(freq_text(p["frequency_value"],p["frequency_unit"])),subtitle=ft.Text("下次："+p["next_date"]),trailing=ft.Text(f"逾期 {-n} 天" if n<0 else f"还有 {n} 天"))))
        def finish(e):
            selected=[p for cb,p in picks if cb.value]
            if not selected: notify("请至少勾选一个频率",ft.Colors.RED_600); return
            with con() as c:
                for p in selected:
                    nd=next_due(date.today(),p["frequency_value"],p["frequency_unit"]).isoformat()
                    c.execute("INSERT INTO records(equipment_no,equipment_name,frequency_text,maintain_time,operator_name,next_date) VALUES(?,?,?,?,?,?)",(r["equipment_no"],r["equipment_name"],freq_text(p["frequency_value"],p["frequency_unit"]),datetime.now().isoformat(timespec="seconds"),state["user"]["display_name"],nd))
                    c.execute("UPDATE plans SET last_date=?,next_date=? WHERE id=?",(date.today().isoformat(),nd,p["id"]))
            notify("保养完成"); detail(eid)
        page.clean(); page.add(bar("设备详情",home),ft.Container(ft.Column([ft.Container(ft.Column([ft.Text(r['equipment_no'],size=29,weight=ft.FontWeight.BOLD),ft.Text(r['equipment_name'],size=21),ft.Text("操作人："+state["user"]["display_name"])]),padding=18,bgcolor=ft.Colors.BLUE_50,border_radius=16),ft.Text("勾选本次完成的保养频率",size=18,weight=ft.FontWeight.BOLD),*cards,ft.Container(button("开始保养",ft.Icons.BUILD,finish),padding=ft.Padding(0,8,0,12))],scroll=ft.ScrollMode.AUTO),padding=18,expand=True))
    def manage():
        page.clean(); items=[ft.ListTile(title=ft.Text(f"{r['equipment_no']}  {r['equipment_name']}"),subtitle=ft.Text(f"{r['location']} · {'激活' if r['status']=='active' else '退役'}"),on_click=lambda e,x=r:edit_device(x['id'])) for r in search_devices("",True)]
        page.add(bar("设备管理",home),ft.Container(ft.Column([button("新增设备",ft.Icons.ADD,lambda e:edit_device(None)),*items],scroll=ft.ScrollMode.AUTO),padding=16,expand=True))
    def edit_device(eid):
        old=rows("SELECT * FROM equipment WHERE id=?",(eid,))[0] if eid else None
        no=ft.TextField(label="设备编号",value=old["equipment_no"] if old else "",disabled=bool(old))
        name=ft.TextField(label="设备名称",value=old["equipment_name"] if old else ""); loc=ft.TextField(label="使用区域",value=old["location"] if old else ""); status=ft.Dropdown(label="状态",value=old["status"] if old else "active",options=[ft.DropdownOption(key="active",text="激活"),ft.DropdownOption(key="retired",text="退役")])
        def save(e):
            code=old["equipment_no"] if old else normalize_no(no.value)
            if not code: notify("请输入设备编号",ft.Colors.RED_600); return
            if not name.value.strip(): notify("请输入设备名称",ft.Colors.RED_600); return
            try:
                with con() as c:
                    if old:
                        before=dict(c.execute("SELECT * FROM equipment WHERE id=?",(eid,)).fetchone())
                        c.execute("UPDATE equipment SET equipment_name=?,location=?,status=? WHERE id=?",(name.value.strip(),loc.value.strip(),status.value,eid))
                        after=dict(c.execute("SELECT * FROM equipment WHERE id=?",(eid,)).fetchone()); log_change(c,state["user"]["display_name"],"修改","设备",code,before,after); target=eid
                    else:
                        if c.execute("SELECT 1 FROM equipment WHERE equipment_no=?",(code,)).fetchone(): notify(f"设备编号 {code} 已存在",ft.Colors.RED_600); return
                        target=c.execute("INSERT INTO equipment(equipment_no,equipment_name,location,status) VALUES(?,?,?,?)",(code,name.value.strip(),loc.value.strip(),status.value)).lastrowid
                        after=dict(c.execute("SELECT * FROM equipment WHERE id=?",(target,)).fetchone()); log_change(c,state["user"]["display_name"],"新增","设备",code,None,after)
                notify("设备保存成功"); edit_device(target)
            except sqlite3.IntegrityError: notify(f"设备编号 {code} 已存在",ft.Colors.RED_600)
            except Exception: notify("设备保存失败，请检查输入",ft.Colors.RED_600)
        plan_items=[]
        if old:
            for p in rows("SELECT * FROM plans WHERE equipment_id=? ORDER BY next_date",(eid,)):
                plan_items.append(ft.ListTile(title=ft.Text(f"{freq_text(p['frequency_value'],p['frequency_unit'])} · {'启用' if p['enabled'] else '停用'}"),subtitle=ft.Text("下次："+p["next_date"]),on_click=lambda e,x=p:edit_plan(eid,x["id"])))
            plan_items.append(button("新增频率",ft.Icons.ADD,lambda e:edit_plan(eid,None)))
        page.clean(); page.add(bar("修改设备" if old else "新增设备",manage),ft.Container(ft.Column([no,ft.Text("设备编号创建后不可修改" if old else "设备编号保存后不可修改",size=12,color=ft.Colors.GREY_600),name,loc,status,button("保存设备",ft.Icons.SAVE,save),ft.Divider(),*plan_items],scroll=ft.ScrollMode.AUTO),padding=16,expand=True))
    def edit_plan(eid,pid):
        p=rows("SELECT * FROM plans WHERE id=?",(pid,))[0] if pid else None; code=rows("SELECT equipment_no FROM equipment WHERE id=?",(eid,))[0]["equipment_no"]
        value=ft.TextField(label="频率整数",value=str(p["frequency_value"]) if p else "1",keyboard_type=ft.KeyboardType.NUMBER); unit=ft.Dropdown(label="频率单位",value=p["frequency_unit"] if p else "月",options=[ft.DropdownOption(key=x,text=x) for x in UNITS]); warning=ft.TextField(label="预警天数",value=str(p["warning_days"]) if p else "7",keyboard_type=ft.KeyboardType.NUMBER); nd=ft.TextField(label="下次日期 YYYY-MM-DD",value=p["next_date"] if p else next_due(date.today(),1,"月").isoformat()); enabled=ft.Switch(label="启用",value=bool(p["enabled"]) if p else True); preview=ft.Text()
        def update(e=None): preview.value=f"显示：{value.value}{unit.value}保养"; page.update()
        value.on_change=update; unit.on_select=update
        def save(e):
            try:
                v=int(value.value); w=int(warning.value); date.fromisoformat(nd.value)
                if v<=0: notify("频率整数必须大于0",ft.Colors.RED_600); return
                if w<0: notify("预警天数不能小于0",ft.Colors.RED_600); return
                with con() as c:
                    duplicate=c.execute("SELECT 1 FROM plans WHERE equipment_id=? AND frequency_value=? AND frequency_unit=? AND id<>?",(eid,v,unit.value,pid or 0)).fetchone()
                    if duplicate: notify(f"{v}{unit.value}保养已存在",ft.Colors.RED_600); return
                    if p:
                        before=dict(c.execute("SELECT * FROM plans WHERE id=?",(pid,)).fetchone()); c.execute("UPDATE plans SET frequency_value=?,frequency_unit=?,warning_days=?,next_date=?,enabled=? WHERE id=?",(v,unit.value,w,nd.value,int(enabled.value),pid)); after=dict(c.execute("SELECT * FROM plans WHERE id=?",(pid,)).fetchone()); log_change(c,state["user"]["display_name"],"修改","频率",code,before,after)
                    else:
                        nid=c.execute("INSERT INTO plans(equipment_id,frequency_value,frequency_unit,warning_days,next_date,enabled) VALUES(?,?,?,?,?,?)",(eid,v,unit.value,w,nd.value,int(enabled.value))).lastrowid; after=dict(c.execute("SELECT * FROM plans WHERE id=?",(nid,)).fetchone()); log_change(c,state["user"]["display_name"],"新增","频率",code,None,after)
                notify("频率保存成功"); edit_device(eid)
            except ValueError: notify("请输入有效的整数和日期，日期格式为 YYYY-MM-DD",ft.Colors.RED_600)
            except sqlite3.IntegrityError: notify(f"{value.value}{unit.value}保养已存在",ft.Colors.RED_600)
            except Exception: notify("频率保存失败，请检查输入",ft.Colors.RED_600)
        page.clean(); page.add(bar("频率设置",lambda:edit_device(eid)),ft.Container(ft.Column([value,unit,preview,warning,nd,enabled,button("保存",ft.Icons.SAVE,save)]),padding=16)); update()
    def records_page():
        rs=rows("SELECT * FROM records ORDER BY maintain_time DESC"); items=[ft.Card(content=ft.Container(ft.Column([ft.Text(f"{r['equipment_no']}  {r['equipment_name']}",weight=ft.FontWeight.BOLD),ft.Text(f"{r['frequency_text']} · {r['maintain_time']}"),ft.Text(f"操作人：{r['operator_name']} · 下次：{r['next_date']}")]),padding=12)) for r in rs]
        page.clean(); page.add(bar("保养记录",home),ft.Container(ft.Column(items or [ft.Text("暂无记录")],scroll=ft.ScrollMode.AUTO),padding=16,expand=True))
    def audit_page():
        rs=rows("SELECT * FROM logs ORDER BY operation_time DESC"); items=[]
        for r in rs:
            b=json.loads(r["before_data"]) if r["before_data"] else {}; a=json.loads(r["after_data"]) if r["after_data"] else {}; changes=[]
            for k in sorted(set(b)|set(a)):
                if k in ("id","equipment_id") or b.get(k)==a.get(k): continue
                changes.append(ft.Text(f"{FIELD_NAMES.get(k,k)}：{b.get(k,'（无）')} → {a.get(k,'（无）')}"))
            items.append(ft.Card(content=ft.Container(ft.Column([ft.Text(f"{r['operation_type']} {r['object_type']} · {r['object_code']}",weight=ft.FontWeight.BOLD),ft.Text(f"{r['operation_time']} · {r['operator_name']}"),*changes]),padding=12)))
        page.clean(); page.add(bar("修改记录",home),ft.Container(ft.Column(items or [ft.Text("暂无记录")],scroll=ft.ScrollMode.AUTO),padding=16,expand=True))
    login()
if __name__=="__main__": ft.run(main)
