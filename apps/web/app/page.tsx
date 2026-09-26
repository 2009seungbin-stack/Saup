'use client';
import { FormEvent, useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import SupplierOperations from '../components/suppliers/SupplierOperations';
import OrderIntakePanel from '../components/orders/OrderIntakePanel';
import ReviewResolutionPanel from '../components/reviews/ReviewResolutionPanel';
import SetupPanel from '../components/operations/SetupPanel';
import WorkPanel from '../components/operations/WorkPanel';
import CreativeStudio from '../components/creative/CreativeStudio';

type User = {username:string;role:string;mode:string};
type Catalog = {id:string;title:string;sku:string;price:number;cost:number;shipping:number;stock:number|null;marketplace:string;desired_state:string;remote_state:string;safe_additional_order_capacity:number};
type Order = {id:string;external_id:string;marketplace:string;state:string;gross_sale:number;quantity:number;created_at:string};
type Review = {id:string;category:string;entity_id:string;status:string;details:Record<string,unknown>};
type Payment = {id:string;amount:number;status:string;destination_fingerprint:string};
type Profile = {id:string;name:string};
type Batch = {id:string;kind:string;status:string;accepted:number;rejected:number};
type Integration = {name:string;active:{status:string};production:{status:string}};
type Trail = {id:string;event:string;actor:string;created_at:string;reason:string};
type Overview = {mode:string;today:{orders:number;gross_sales:number;expected_contribution:number;claims:number};cash:{bank_balance:number;available_cash:number;bank_committed:number;refund_reserve:number;safety_reserve:number;marketplace_receivable:number};risk:{open_reviews:number;paused_listings:number;dead_jobs:number};automation:{production_rate:null}};
const won = (value:number) => new Intl.NumberFormat('ko-KR',{style:'currency',currency:'KRW',maximumFractionDigits:0}).format(value);
function Tag({value}:{value:string}) { return <span className={'tag '+(['ACTIVE','CLOSED','SUCCEEDED','COMPLETED'].includes(value)?'ok':['PAUSED','DEAD','FAILED','UNKNOWN'].includes(value)?'warn':'')}>{value}</span>; }

export default function Dashboard() {
  const [user,setUser]=useState<User|null>(null),[boot,setBoot]=useState(true),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [username,setUsername]=useState('admin'),[password,setPassword]=useState('');
  const [overview,setOverview]=useState<Overview|null>(null),[catalog,setCatalog]=useState<Catalog[]>([]),[orders,setOrders]=useState<Order[]>([]);
  const [reviews,setReviews]=useState<Review[]>([]),[payments,setPayments]=useState<Payment[]>([]),[profiles,setProfiles]=useState<Profile[]>([]);
  const [integrations,setIntegrations]=useState<Integration[]>([]),[batches,setBatches]=useState<Batch[]>([]),[profile,setProfile]=useState('');
  const [tab,setTab]=useState('상품'),[trail,setTrail]=useState<Trail[]>([]),[selectedOrder,setSelectedOrder]=useState('');
  const refresh=useCallback(async()=>{
    try {
      const [o,c,orders,r,p,i,b]=await Promise.all([api<Overview>('/v1/overview'),api<Catalog[]>('/v1/catalog'),api<Order[]>('/v1/orders'),api<Review[]>('/v1/reviews'),api<Profile[]>('/v1/profiles'),api<Integration[]>('/v1/integrations'),api<Batch[]>('/v1/imports')]);
      setOverview(o);setCatalog(c);setOrders(orders);setReviews(r);setProfiles(p);setIntegrations(i);setBatches(b);
      setProfile(current=>current||p[0]?.id||'');
      if(user?.role!=='viewer')setPayments(await api<Payment[]>('/v1/payments'));
      setError('');
    } catch(e) {setError(e instanceof Error?e.message:'조회 실패');}
  },[user?.role]);
  useEffect(()=>{api<User>('/auth/me').then(setUser).catch(()=>{}).finally(()=>setBoot(false));},[]);
  useEffect(()=>{if(user)void refresh();},[user,refresh]);
  async function action(fn:()=>Promise<unknown>){setBusy(true);setError('');try{await fn();await refresh();}catch(e){setError(e instanceof Error?e.message:'작업 실패');}finally{setBusy(false);}}
  async function signIn(e:FormEvent){e.preventDefault();setBusy(true);try{await api('/auth/login',{method:'POST',body:JSON.stringify({username,password})});setPassword('');setUser(await api<User>('/auth/me'));setError('');}catch(e){setError(e instanceof Error?e.message:'로그인 실패');}finally{setBusy(false);}}
  async function upload(file:File,kind:'price'|'shipment'){const form=new FormData();form.append('file',file);await action(()=>api(`/v1/imports/${profile}/${kind}`,{method:'POST',body:form}));setTab('파일');}
  async function demoOrder(){const item=catalog.find(x=>x.desired_state==='ACTIVE');if(!item)throw new Error('활성 데모 상품이 없습니다.');await api('/demo/orders',{method:'POST',body:JSON.stringify({marketplace:item.marketplace,external_id:'DEMO-'+crypto.randomUUID(),external_line_id:'1',listing_id:item.id,quantity:1,gross_sale:item.price,address:{recipient:'합성 고객',phone:'010-0000-0000',postal_code:'01234',address1:'가상시 테스트로 123',address2:'101호'}})});setTab('주문');}
  async function showTrail(order:Order){setSelectedOrder(order.external_id);try{setTrail(await api<Trail[]>(`/v1/orders/${order.id}/trail`));}catch(e){setError(String(e));}}
  if(boot)return <main className="login"><p>세션 확인 중…</p></main>;
  if(!user)return <main className="login"><form onSubmit={signIn}><div className="brand">S<span>au</span>p</div><h1>운영 콘솔</h1><p className="muted">관리자 계정으로 로그인하세요.</p><label>아이디<input autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)} required/></label><label>비밀번호<input autoComplete="current-password" type="password" value={password} onChange={e=>setPassword(e.target.value)} required/></label>{error&&<p role="alert" className="error">{error}</p>}<button className="primary" disabled={busy}>로그인</button><small>로컬 데모 계정은 bootstrap 명령에서 생성됩니다.</small></form></main>;
  return <main className="shell">
    <header><div className="brand">S<span>au</span>p</div><span className="muted">COMMERCE OPERATIONS</span><span className="mode">{user.mode.toUpperCase()} · 실결제 꺼짐</span><div className="grow"/><span>{user.username} <small>{user.role}</small></span><button title="새로고침" disabled={busy} onClick={()=>void refresh()}>↻</button><button onClick={()=>void api('/auth/logout',{method:'POST'}).then(()=>setUser(null))}>로그아웃</button></header>
    <div className="heading"><div><h1>운영 현황</h1><p className="muted">오늘 · 한국 시간 기준 <span>금액과 주문은 데이터베이스에서 조회합니다.</span></p></div><div className="actions">{user.mode!=='production'&&user.role!=='viewer'&&<button disabled={busy} onClick={()=>void action(demoOrder)}>＋ 모의 주문</button>}<button className="primary" onClick={()=>setTab('검토 큐')}>검토 큐 {overview?.risk.open_reviews??0}</button></div></div>
    {error&&<div className="error" role="alert">{error}<button onClick={()=>setError('')}>닫기</button></div>}
    <section className="stats" aria-label="오늘의 운영 지표"><article><label>총 주문액</label><strong>{won(overview?.today.gross_sales??0)}</strong><small>주문 {overview?.today.orders??0}건</small></article><article><label>예상 공헌이익</label><strong>{won(overview?.today.expected_contribution??0)}</strong><small>확정 손익 아님 · 클레임 조정 전</small></article><article><label>가용 은행 자금</label><strong>{won(overview?.cash.available_cash??0)}</strong><small>예치금은 공급사별 별도 계산</small></article><article><label>운영 예외</label><strong>{overview?.risk.open_reviews??0}<em>건</em></strong><small>판매중지 {overview?.risk.paused_listings??0} · 작업 실패 {overview?.risk.dead_jobs??0}</small></article></section>
    <section className="cashbar"><span>은행 잔액 <b>{won(overview?.cash.bank_balance??0)}</b></span><span>발주 예약 <b>{won(overview?.cash.bank_committed??0)}</b></span><span>환불 준비금 <b>{won(overview?.cash.refund_reserve??0)}</b></span><span>안전 준비금 <b>{won(overview?.cash.safety_reserve??0)}</b></span><span title="미정산 매출은 사용 가능한 현금이 아닙니다.">미정산 채권 <b>{won(overview?.cash.marketplace_receivable??0)}</b></span></section>
    <nav aria-label="운영 메뉴">{['초기 설정','상품','상품 제작','주문','주문 가져오기','공급사 운영','외부 처리 확인','클레임','정산','검토 큐','검토 해결','결제','파일','연동'].map(t=><button key={t} className={tab===t?'selected':''} onClick={()=>setTab(t)}>{t}{t==='검토 큐'&&reviews.length>0&&<i>{reviews.length}</i>}</button>)}</nav>
    <section className="panel">
      <div hidden={tab!=='상품 제작'}><CreativeStudio products={catalog} role={user.role}/></div>
      {tab==='초기 설정'&&<SetupPanel role={user.role} onFiles={()=>setTab('파일')} onIntake={()=>setTab('주문 가져오기')}/>}
      {(tab==='외부 처리 확인'||tab==='클레임'||tab==='정산')&&<WorkPanel role={user.role} section={tab}/>}
      {tab==='주문 가져오기'&&<OrderIntakePanel role={user.role} onSuppliers={()=>setTab('공급사 운영')}/>}
      {tab==='공급사 운영'&&<SupplierOperations role={user.role} mode={user.mode} onShipmentImport={()=>setTab('파일')}/>}
      {tab==='상품'&&<div className="tablewrap"><table><thead><tr><th>상품 / SKU</th><th>마켓</th><th>원가 + 배송</th><th>판매가</th><th>재고</th><th>자금 기준 추가 주문</th><th>내부 상태</th><th>마켓 확인</th></tr></thead><tbody>{catalog.map(x=><tr key={x.id}><td><b>{x.title}</b><small>{x.sku}</small></td><td>{x.marketplace}</td><td>{won(x.cost+x.shipping)}</td><td>{won(x.price)}</td><td>{x.stock??'미확인'}</td><td title="다른 SKU 주문과 동일 현금을 공유하는 개별 상한입니다. 합산하면 안 됩니다.">{x.safe_additional_order_capacity}건</td><td><Tag value={x.desired_state}/></td><td><Tag value={x.remote_state}/></td></tr>)}</tbody></table></div>}
      {tab==='주문'&&<><div className="tablewrap"><table><thead><tr><th>주문</th><th>마켓</th><th>수량</th><th>주문액</th><th>상태</th><th>이력</th></tr></thead><tbody>{orders.map(x=><tr key={x.id}><td>{x.external_id}<small>{new Date(x.created_at).toLocaleString('ko-KR')}</small></td><td>{x.marketplace}</td><td>{x.quantity}</td><td>{won(x.gross_sale)}</td><td><Tag value={x.state}/></td><td><button onClick={()=>void showTrail(x)}>거래 추적</button></td></tr>)}</tbody></table></div>{orders.length===0&&<p className="empty">수집된 주문이 없습니다.</p>}{selectedOrder&&<aside className="trail"><h3>{selectedOrder} · 감사 이력</h3>{trail.map(x=><div key={x.id}><time>{new Date(x.created_at).toLocaleTimeString('ko-KR')}</time><b>{x.event}</b><span>{x.reason} · {x.actor}</span></div>)}</aside>}</>}
      {tab==='검토 해결'&&<ReviewResolutionPanel role={user.role} onSaved={refresh}/>}
      {tab==='검토 큐'&&<><div className="tablewrap"><table><thead><tr><th>유형</th><th>대상</th><th>내용</th><th>상태</th></tr></thead><tbody>{reviews.map(x=><tr key={x.id}><td><b>{x.category}</b></td><td className="mono">{x.entity_id}</td><td className="details">{JSON.stringify(x.details)}</td><td><Tag value={x.status}/></td></tr>)}</tbody></table></div>{reviews.length===0&&<p className="empty">검토가 필요한 예외가 없습니다.</p>}</>}
      {tab==='결제'&&<div className="tablewrap"><table><thead><tr><th>결제 ID</th><th>금액</th><th>상태</th><th>작업</th></tr></thead><tbody>{payments.map(x=><tr key={x.id}><td className="mono">{x.id}</td><td>{won(x.amount)}</td><td><Tag value={x.status}/></td><td>{x.status==='MANUAL_APPROVAL'&&user.role==='admin'&&<button disabled={busy} onClick={()=>{if(confirm(`지급 준비 ${won(x.amount)}을 승인합니까? 이 승인은 실제 송금 확인이 아닙니다.`))void action(()=>api(`/v1/payments/${x.id}/approve`,{method:'POST',body:JSON.stringify({amount:x.amount,destination_fingerprint:x.destination_fingerprint})}));}}>승인</button>}{x.status==='UNKNOWN'&&user.role==='admin'&&<button onClick={()=>void action(()=>api(`/v1/payments/${x.id}/reconcile`,{method:'POST'}))}>거래 조회</button>}</td></tr>)}</tbody></table></div>}
      {tab==='파일'&&<><div className="toolbar"><select aria-label="공급사 엑셀 프로필" value={profile} onChange={e=>setProfile(e.target.value)}>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>{user.role!=='viewer'&&<>{(['price','shipment'] as const).map(kind=><label className="filebutton" key={kind}>{kind==='price'?'가격표 가져오기':'송장 가져오기'}<input type="file" accept=".xlsx" disabled={busy||!profile} onChange={e=>{const file=e.target.files?.[0];if(file)void upload(file,kind);e.target.value='';}}/></label>)}<button onClick={()=>setTab('공급사 운영')}>배치별 발주서 생성 / 다운로드</button></>}{user.mode!=='production'&&<a className="button" href="/api/demo/price-file">합성 샘플 가격표</a>}</div><p className="notice">발주서 내보내기는 공급사의 접수·결제 완료를 의미하지 않습니다.</p><table><thead><tr><th>가져오기</th><th>종류</th><th>상태</th><th>정상 행</th><th>오류 행</th></tr></thead><tbody>{batches.map(b=><tr key={b.id}><td className="mono">{b.id}</td><td>{b.kind}</td><td><Tag value={b.status}/></td><td>{b.accepted}</td><td>{b.rejected}</td></tr>)}</tbody></table></>}
      {tab==='연동'&&<div className="integrationgrid">{integrations.map(x=><article key={x.name}><h3>{x.name}</h3><label>현재 어댑터</label><Tag value={x.active.status}/><label>실서비스 연동</label><Tag value={x.production.status}/></article>)}<p className="notice">실제 계정 권한과 공식 API 검증 전에는 외부 판매·송금이 실행되지 않습니다. 운영 자동화율 95%는 목표이며 현재 측정된 수치가 아닙니다.</p></div>}
    </section><footer>SAUP · 로컬 검증용 운영 기반 <span>외부 마켓 실연동 / 실결제 미승인</span></footer>
  </main>;
}
