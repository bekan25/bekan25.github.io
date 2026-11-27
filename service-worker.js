"use strict";
const CACHE_NAME="dereje-portfolio-shell-v4";
const CORE_ASSETS=[
  "/",
  "/offline.html",
  "/manifest.webmanifest",
  "/assets/favicon.svg",
  "/assets/profile.jpg",
  "/assets/Dereje_Solomon_CV.pdf",
  "/assets/css/portfolio.css",
  "/assets/css/premium.css",
  "/assets/js/portfolio-enhancements.js",
  "/projects/merkato.html",
  "/projects/bdexpress.html",
  "/projects/high-school-management.html",
  "/projects/adwa-market.html",
  "/projects/nexoras.html",
  "/projects/barnootaai360.html"
];

self.addEventListener("install",event=>{
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache=>cache.addAll(CORE_ASSETS))
      .then(()=>self.skipWaiting())
  );
});

self.addEventListener("activate",event=>{
  event.waitUntil(
    caches.keys()
      .then(keys=>Promise.all(keys.filter(key=>key!==CACHE_NAME).map(key=>caches.delete(key))))
      .then(()=>self.clients.claim())
  );
});

self.addEventListener("fetch",event=>{
  const request=event.request;
  if(request.method!=="GET")return;
  const url=new URL(request.url);
  if(url.origin!==self.location.origin)return;

  if(request.mode==="navigate"){
    event.respondWith(
      fetch(request).then(response=>{
        if(response.ok){
          const copy=response.clone();
          caches.open(CACHE_NAME).then(cache=>cache.put(request,copy));
        }
        return response;
      }).catch(async()=>{
        return (await caches.match(request)) || (await caches.match("/offline.html")) || caches.match("/");
      })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(cached=>{
      if(cached)return cached;
      return fetch(request).then(response=>{
        if(response.ok){
          const copy=response.clone();
          caches.open(CACHE_NAME).then(cache=>cache.put(request,copy));
        }
        return response;
      });
    })
  );
});
