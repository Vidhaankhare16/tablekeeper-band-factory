import json, os, sys, urllib.request
os.environ['COMBO']='1'
src=open('/tmp/e2e/e2e.py').read().split("for w,t in ((375")[0]
exec(src)
EV='/home/user/tablekeeper-band-factory/evidence/stage-4'; os.makedirs(EV,exist_ok=True)
rest['manager_user_ids']=['u_mgr']
rest['opening_hours']=[{"weekday":"thu","opens":"18:00","closes":"23:00"}]
def mkfix():
    f=json.loads(json.dumps(FIX)); f['restaurants']=[rest]
    f['users'].append({"id":"u_mgr","email":"mgr@example.com","password":"manager pass","display_name":"Mia"})
    f['reservations']=[{"id":"res_a","reference":"SEAT01","user_id":"u_ada","restaurant_id":"r_anker","table_id":"t_2","party_size":3,"status":"confirmed",
      "starts_at_local":DATE+"T19:00","starts_at":DATE+"T19:00:00+02:00","ends_at":DATE+"T20:30:00+02:00","created_at":"2030-01-01T10:00:00+00:00"}]
    return f
def api(method,path,body=None,tok=None,key=None):
    h={'Content-Type':'application/json'}
    if tok: h['Authorization']='Bearer '+tok
    if key: h['Idempotency-Key']=key
    r=urllib.request.Request(BASE+path,json.dumps(body).encode() if body is not None else None,h,method=method)
    try: x=urllib.request.urlopen(r); return x.status, json.loads(x.read() or b'null')
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b'null')
def run(width):
    post('/_test/reset', mkfix())
    mt=api('POST','/auth/login',{'email':'mgr@example.com','password':'manager pass'})[1]['token']
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome'); p=b.new_context(viewport={'width':width,'height':900}).new_page()
        shot=lambda n: p.screenshot(path=f'{EV}/{width}-{n}.png', full_page=True)
        login(p); search(p,'2')
        check(f'{width} before closure t_2-19:30 cell state (booked 19:00 => false)', tid(p,'slot-t_2-19:30').get_attribute('data-available')=='false')
        check(f'{width} t_2-21:00 available before closure', tid(p,'slot-t_2-21:00').get_attribute('data-available')=='true')
        shot('30-before-closure')
        tid(p,'slot-t_2-21:00').click(); tid(p,'booking-form').wait_for()   # form open on t_2, stays through closure
        s,plan=api('POST','/restaurants/r_anker/replans',{'table_id':'t_2','from':DATE+'T18:00:00+02:00','to':DATE+'T23:00:00+02:00'},mt,'rp1'); check(f'{width} preview 201', s==201)
        s,ap=api('POST',f"/restaurants/r_anker/replans/{plan['plan_id']}/apply",{},mt,'ap1'); check(f'{width} apply 201', s==201)
        moved=ap['reservations'][0]; new_ids=moved.get('table_ids'); check(f'{width} booking moved off t_2 {new_ids}', 't_2' not in new_ids)
        # booking attempt on closed table, form preserved
        tid(p,'booking-party-size').fill('3'); tid(p,'booking-submit').click(); tid(p,'booking-error').wait_for()
        check(f'{width} closed-table booking -> booking-error, form kept, no confirmation', tid(p,'booking-form').count()==1 and tid(p,'booking-party-size').input_value()=='3' and tid(p,'confirmation').count()==0)
        p.wait_for_timeout(700); shot('31-closed-booking-error')
        # grid after closure
        search(p,'2')
        av=get(f'/availability?restaurant_id=r_anker&date={DATE}&party_size=2'); ok=True; n=0
        for s_ in av['slots']:
            t=s_['starts_at_local'][11:16]
            for tb in rest['tables']:
                exp='true' if tb['id'] in s_['available_table_ids'] else 'false'; ok&=tid(p,f"slot-{tb['id']}-{t}").get_attribute('data-available')==exp; n+=1
            opts={'+'.join(o['table_ids']) for o in s_['available_options'] if len(o['table_ids'])==2}
            for pr in rest['combinable']:
                k='+'.join(pr); ok&=tid(p,f"slot-{k}-{t}").get_attribute('data-available')==('true' if k in opts else 'false'); n+=1
        check(f'{width} grid matches server availability after apply ({n} cells)', ok)
        check(f'{width} every t_2 single and combo cell false during closure', all(
            tid(p,f"slot-{k}-{t}").get_attribute('data-available')=='false' for k in ('t_2','t_1+t_2','t_2+t_3') for t in ('18:00','19:00','20:00','21:00')))
        shot('32-grid-after-closure')
        # lookup of moved booking
        p.goto(BASE+'/lookup'); tid(p,'lookup-reference-input').fill('SEAT01'); tid(p,'lookup-submit').click(); tid(p,'reservation-detail').wait_for()
        labels=[ {t['id']:t['label'] for t in rest['tables']}[i] for i in new_ids]
        txt=tid(p,'reservation-tables').inner_text()
        check(f'{width} lookup shows new table labels {labels}: {txt!r}', all(l in txt for l in labels) and 'Window 2' not in txt and tid(p,'reservation-status').inner_text()=='confirmed')
        shot('33-lookup-moved')
        b.close()
for w in (375,1280): run(w)
bad=[n for n,o in results if not o]; print(len(results)-len(bad),'/',len(results)); sys.exit(1 if bad else 0)
