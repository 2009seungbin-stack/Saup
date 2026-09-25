const csrf = () => decodeURIComponent(document.cookie.split('; ').find(v=>v.startsWith('saup_csrf='))?.slice(10)||'');
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
  if (options.method && !['GET','HEAD'].includes(options.method)) headers.set('X-CSRF-Token',csrf());
  const response = await fetch('/api'+path,{...options,headers,credentials:'same-origin',cache:'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
  return data as T;
}
