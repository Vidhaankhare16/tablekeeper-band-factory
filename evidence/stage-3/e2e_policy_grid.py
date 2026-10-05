import json, os, sys, urllib.request
os.environ['COMBO']='1'
src=open('/tmp/e2e/e2e.py').read().split("for w,t in ((375")[0]
exec(src)
rest['manager_user_ids']=['u_ada']
FIX['restaurants'][0]=rest
post('/_test/reset', FIX)
tok=json.load(urllib.request.urlopen(urllib.request.Request(BASE+'/auth/login',json.dumps({'email':'ada@example.com','password':'correct horse'}).encode(),{'Content-Type':'application/json'},method='POST')))['token']
pol={"effective_from":"2030-09-01","slot_minutes":60,"reservation_duration_minutes":120,"cancellation_cutoff_minutes":60,
 "opening_hours":[{"weekday":"thu","opens":"17:00","closes":"22:00"}],"capacities":{"t_1":6,"t_2":4,"t_3":3}}
r=urllib.request.Request(BASE+'/restaurants/r_anker/policies',json.dumps(pol).encode(),{'Content-Type':'application/json','Authorization':'Bearer '+tok,'Idempotency-Key':'p1'},method='POST'); print(urllib.request.urlopen(r).status)
for width in (375,1280):
  with sync_playwright() as pw:
    b=pw.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome'); p=b.new_context(viewport={'width':width,'height':900}).new_page()
    login(p); search(p,'5')
    av=get(f'/availability?restaurant_id=r_anker&date={DATE}&party_size=5')
    ok=True; n=0
    for s in av['slots']:
        t=s['starts_at_local'][11:16]
        for tb in rest['tables']:
            exp='true' if tb['id'] in s['available_table_ids'] else 'false'
            ok &= tid(p,f"slot-{tb['id']}-{t}").get_attribute('data-available')==exp; n+=1
        opts={'+'.join(o['table_ids']) for o in s['available_options'] if len(o['table_ids'])==2}
        for pr in rest['combinable']:
            k='+'.join(pr); exp='true' if k in opts else 'false'
            ok &= tid(p,f"slot-{k}-{t}").get_attribute('data-available')==exp; n+=1
    check(f'{width} grid matches policy availability ({n} cells, slots {[s["starts_at_local"][11:] for s in av["slots"]]})', ok)
    tid(p,'slot-t_1-17:00').click(); tid(p,'booking-submit').click(); tid(p,'confirmation').wait_for()
    ref=tid(p,'confirmation-reference').inner_text(); check(f'{width} book under policy', len(ref)>=6)
    p.goto(BASE+'/lookup'); tid(p,'lookup-reference-input').fill(ref); tid(p,'lookup-submit').click(); tid(p,'reservation-detail').wait_for()
    check(f'{width} lookup status exact', tid(p,'reservation-status').inner_text()=='confirmed')
    b.close()
    post('/_test/reset', FIX); post_pol=urllib.request.Request(BASE+'/restaurants/r_anker/policies',json.dumps(pol).encode(),{'Content-Type':'application/json','Authorization':'Bearer '+tok,'Idempotency-Key':'p1'},method='POST')
    tok=json.load(urllib.request.urlopen(urllib.request.Request(BASE+'/auth/login',json.dumps({'email':'ada@example.com','password':'correct horse'}).encode(),{'Content-Type':'application/json'},method='POST')))['token']
    urllib.request.urlopen(urllib.request.Request(BASE+'/restaurants/r_anker/policies',json.dumps(pol).encode(),{'Content-Type':'application/json','Authorization':'Bearer '+tok,'Idempotency-Key':'p2'},method='POST'))
bad=[n for n,o in results if not o]; print(len(results)-len(bad),'/',len(results)); sys.exit(1 if bad else 0)
