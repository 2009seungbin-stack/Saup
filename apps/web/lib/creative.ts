/** Deterministic product layouts. Only operator-supplied facts are rendered. */
export type CreativeDraft = {
  version: 1; title: string; subtitle: string; brand: string; sku: string;
  price: string; facts: string; description: string; notice: string;
  theme: 'sage' | 'sand' | 'ink'; thumbnailSize: number; detailWidth: number;
  showPrice: boolean; photos: string[];
};
export const emptyDraft: CreativeDraft = {
  version: 1, title: '', subtitle: '', brand: '', sku: '', price: '', facts: '',
  description: '', notice: '', theme: 'sage', thumbnailSize: 1000, detailWidth: 860,
  showPrice: false, photos: [],
};
export const themes = {
  sage: {name: '세이지 · 내추럴', background: '#eff3ed', accent: '#315e4e', ink: '#20332b'},
  sand: {name: '샌드 · 따뜻한', background: '#f5eee3', accent: '#855331', ink: '#392c22'},
  ink: {name: '잉크 · 모던', background: '#edf0f5', accent: '#334b78', ink: '#18263d'},
};
const MAX_IMAGE = 10 * 1024 * 1024;
export async function readPhoto(file: File): Promise<string> {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > MAX_IMAGE)
    throw new Error('사진은 JPG·PNG·WebP, 한 장당 10MB 이하로 선택하세요.');
  let bitmap: ImageBitmap;
  try { bitmap = await createImageBitmap(file); } catch { throw new Error('읽을 수 없는 이미지입니다.'); }
  try {
    if (bitmap.width * bitmap.height > 24000000) throw new Error('사진은 2,400만 화소 이하로 선택하세요.');
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', .9);
  } finally { bitmap.close(); }
}
export async function restoreDraft(file: File): Promise<CreativeDraft> {
  if (file.size > 25 * 1024 * 1024) throw new Error('편집 파일은 25MB 이하여야 합니다.');
  let raw: Record<string, unknown>;
  try { raw = JSON.parse(await file.text()); } catch { throw new Error('올바른 편집 파일이 아닙니다.'); }
  if (!raw || raw.version !== 1 || !Array.isArray(raw.photos) || raw.photos.length > 6)
    throw new Error('지원하지 않는 편집 파일입니다.');
  const draft = {...emptyDraft};
  const limits = {title: 80, subtitle: 120, brand: 40, sku: 80, price: 12, facts: 800, description: 1600, notice: 800};
  for (const [key, limit] of Object.entries(limits)) {
    if (typeof raw[key] !== 'string' || (raw[key] as string).length > limit) throw new Error('편집 파일의 텍스트 형식 또는 길이를 확인하세요.');
    Object.assign(draft, {[key]: raw[key]});
  }
  if (!['sage','sand','ink'].includes(String(raw.theme)) || ![800,1000,1200].includes(Number(raw.thumbnailSize)) || ![860,1000].includes(Number(raw.detailWidth)) || typeof raw.showPrice !== 'boolean')
    throw new Error('편집 파일의 디자인 설정을 확인하세요.');
  Object.assign(draft, {theme: raw.theme, thumbnailSize: Number(raw.thumbnailSize), detailWidth: Number(raw.detailWidth), showPrice: raw.showPrice});
  const photos: string[] = [];
  for (const value of raw.photos) {
    if (typeof value !== 'string' || value.length > 14 * 1024 * 1024 || !/^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(value))
      throw new Error('편집 파일에는 내장된 상품 사진만 사용할 수 있습니다.');
    const blob = await (await fetch(value)).blob();
    photos.push(await readPhoto(new File([blob], 'photo', {type: blob.type})));
  }
  draft.photos = photos; return draft;
}
type Context = CanvasRenderingContext2D;
function lines(ctx: Context, text: string, width: number) {
  const result: string[] = [];
  for (const paragraph of text.split('\n')) {
    let line = '';
    for (const char of Array.from(paragraph)) {
      if (line && ctx.measureText(line + char).width > width) { result.push(line); line = ''; }
      line += char;
    }
    result.push(line);
  }
  return result;
}
function text(ctx: Context, value: string, x: number, y: number, width: number, size: number, weight = 400) {
  ctx.font = `${weight} ${size}px Arial, "Noto Sans KR", sans-serif`;
  ctx.textBaseline = 'top';
  const wrapped = lines(ctx, value, width);
  wrapped.forEach((line, index) => ctx.fillText(line, x, y + index * size * 1.55));
  return y + wrapped.length * size * 1.55;
}
function fitted(ctx: Context, value: string, x: number, y: number, width: number, height: number, initial: number) {
  let size = initial;
  while (size > 15) { ctx.font = `700 ${size}px Arial, "Noto Sans KR", sans-serif`; if (lines(ctx, value, width).length * size * 1.55 <= height) break; size--; }
  return text(ctx, value, x, y, width, size, 700);
}
function photo(ctx: Context, image: HTMLImageElement, x: number, y: number, w: number, h: number) {
  const scale = Math.min(w / image.naturalWidth, h / image.naturalHeight);
  ctx.fillStyle = '#fff'; ctx.fillRect(x, y, w, h);
  ctx.drawImage(image, x + (w-image.naturalWidth*scale)/2, y + (h-image.naturalHeight*scale)/2, image.naturalWidth*scale, image.naturalHeight*scale);
}
function canvas(width: number, height: number) {
  const c = document.createElement('canvas'); c.width = width; c.height = height; return c;
}
async function png(c: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => c.toBlob(b => b ? resolve(b) : reject(new Error('이미지를 내보낼 수 없습니다.')), 'image/png'));
}
export type CreativeOutput = {name: string; blob: Blob; width: number; height: number};
export async function renderCreative(d: CreativeDraft): Promise<CreativeOutput[]> {
  if (!d.title.trim() || !d.photos.length) throw new Error('상품명과 사진 한 장 이상을 입력하세요.');
  if (d.showPrice && (!/^\d{1,10}$/.test(d.price) || Number(d.price) <= 0)) throw new Error('표시할 판매가는 양의 정수로 입력하세요.');
  await document.fonts.ready;
  const images = await Promise.all(d.photos.map(src => new Promise<HTMLImageElement>((resolve,reject) => {
    const i = new Image(); i.onload = () => resolve(i); i.onerror = () => reject(new Error('사진을 불러오지 못했습니다.')); i.src = src;
  })));
  const theme = themes[d.theme], output: CreativeOutput[] = [];
  for (const variant of ['clean','title','card']) {
    const c = canvas(d.thumbnailSize, d.thumbnailSize), ctx = c.getContext('2d')!;
    ctx.scale(d.thumbnailSize/1000,d.thumbnailSize/1000);
    ctx.fillStyle = variant === 'clean' ? '#fff' : theme.background; ctx.fillRect(0,0,1000,1000);
    if (variant === 'clean') photo(ctx, images[0], 40,40,920,920);
    if (variant === 'title') {
      photo(ctx,images[0],50,260,900,690); ctx.fillStyle=theme.ink;
      fitted(ctx,d.title,55,55,890,175,64);
    }
    if (variant === 'card') {
      photo(ctx,images[0],55,55,890,630);ctx.fillStyle=theme.ink;
      fitted(ctx,d.title,55,730,890,130,50);
      ctx.fillStyle=theme.accent;
      if (d.showPrice) text(ctx,Number(d.price).toLocaleString('ko-KR')+'원',55,900,890,40,700);
      else fitted(ctx,d.subtitle,55,885,890,85,26);
    }
    output.push({name:`thumbnail-${variant}.png`,blob:await png(c),width:c.width,height:c.height});
    c.width=1; c.height=1;
  }
  // Measure first, then allocate the exact canvas. No clipped long-form copy.
  const measure=canvas(d.detailWidth,1), ctx=measure.getContext('2d')!, w=d.detailWidth, pad=Math.round(w*.08), inner=w-2*pad;
  const draw = (ctx: Context) => {
    ctx.fillStyle=theme.background;ctx.fillRect(0,0,w,ctx.canvas.height); let y=pad;
    ctx.fillStyle=theme.accent;
    if(d.brand.trim()) y=text(ctx,d.brand,pad,y,inner,20,700)+28;
    ctx.fillStyle=theme.ink;y=text(ctx,d.title,pad,y,inner,48,700)+28;
    if(d.subtitle.trim()) y=text(ctx,d.subtitle,pad,y,inner,24)+28;
    photo(ctx,images[0],pad,y,inner,inner);y+=inner+40;
    ctx.fillStyle=theme.accent;
    if(d.showPrice) y=text(ctx,Number(d.price).toLocaleString('ko-KR')+'원',pad,y,inner,36,700)+35;
    const section=(heading:string,copy:string) => {
      if(!copy.trim())return;
      ctx.fillStyle=theme.accent;ctx.fillRect(pad,y,48,4);y+=30;
      ctx.fillStyle=theme.ink;y=text(ctx,heading,pad,y,inner,30,700)+22;
      y=text(ctx,copy,pad,y,inner,24)+55;
    };
    section('상품 정보', [d.sku.trim() ? `상품 코드  ${d.sku}` : '', d.facts].filter(Boolean).join('\n'));
    section('자세히 알아보기',d.description);
    for(const image of images.slice(1)) { const h=Math.min(inner*1.3,inner*image.naturalHeight/image.naturalWidth);photo(ctx,image,pad,y,inner,h);y+=h+35; }
    section('구매 전 확인',d.notice);
    return Math.ceil(y+pad);
  };
  const height=draw(ctx);
  if(height>14000)throw new Error('상세 이미지가 너무 깁니다. 설명이나 사진 수를 줄여 주세요.');
  const detail=canvas(w,height);draw(detail.getContext('2d')!);
  output.push({name:'detail.png',blob:await png(detail),width:w,height});detail.width=1;detail.height=1;
  return output;
}
export function download(blob: Blob, name: string) {
  const url=URL.createObjectURL(blob), a=document.createElement('a');a.href=url;a.download=name;a.click();
  window.setTimeout(()=>URL.revokeObjectURL(url),10000);
}
export function detailHtml(title: string, image: string) {
  const escaped=title.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
  return `<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escaped}</title><style>body{margin:0;background:#fff}img{display:block;width:100%;max-width:1000px;height:auto;margin:auto}</style><img src="${image}" alt="${escaped}"></html>`;
}
/** Small, dependency-free ZIP (stored entries, UTF-8 names, CRC-32). */
export async function zip(files: {name:string;blob:Blob}[]): Promise<Blob> {
  const chunks: Uint8Array<ArrayBuffer>[] = [], directory: Uint8Array<ArrayBuffer>[] = [];let offset=0;
  for(const file of files) {
    const bytes=new Uint8Array(await file.blob.arrayBuffer()), name=new TextEncoder().encode(file.name);
    let crc=0xffffffff;for(const byte of bytes){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}crc=(crc^0xffffffff)>>>0;
    const local=new Uint8Array(30+name.length), l=new DataView(local.buffer);
    l.setUint32(0,0x04034b50,true);l.setUint16(4,20,true);l.setUint16(6,0x800,true);l.setUint16(12,33,true);
    l.setUint32(14,crc,true);l.setUint32(18,bytes.length,true);l.setUint32(22,bytes.length,true);l.setUint16(26,name.length,true);local.set(name,30);
    const central=new Uint8Array(46+name.length), c=new DataView(central.buffer);
    c.setUint32(0,0x02014b50,true);c.setUint16(4,20,true);c.setUint16(6,20,true);c.setUint16(8,0x800,true);c.setUint16(14,33,true);
    c.setUint32(16,crc,true);c.setUint32(20,bytes.length,true);c.setUint32(24,bytes.length,true);c.setUint16(28,name.length,true);c.setUint32(42,offset,true);central.set(name,46);
    chunks.push(local,bytes);directory.push(central);offset+=local.length+bytes.length;
  }
  const end=new Uint8Array(22), e=new DataView(end.buffer);e.setUint32(0,0x06054b50,true);e.setUint16(8,files.length,true);e.setUint16(10,files.length,true);e.setUint32(12,directory.reduce((n,x)=>n+x.length,0),true);e.setUint32(16,offset,true);
  return new Blob([...chunks,...directory,end],{type:'application/zip'});
}
