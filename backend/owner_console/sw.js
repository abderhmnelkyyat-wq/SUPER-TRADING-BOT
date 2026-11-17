const CACHE_NAME='stb-owner-shell-v1';
const SHELL=['/owner-console/','/owner-console/assets/owner.css','/owner-console/app.js','/owner-console/manifest.webmanifest'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE_NAME).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('stb-owner-')&&k!==CACHE_NAME).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const r=e.request,u=new URL(r.url);if(r.method!=='GET'||u.origin!==self.location.origin)return;if(u.pathname.startsWith('/api/')||!u.pathname.startsWith('/owner-console/'))return;if(r.mode==='navigate'){e.respondWith(fetch(r).then(res=>{if(res.ok){const copy=res.clone();caches.open(CACHE_NAME).then(c=>c.put('/owner-console/',copy));}return res;}).catch(()=>caches.match('/owner-console/')));return;}e.respondWith(caches.match(r).then(hit=>hit||fetch(r)));});
