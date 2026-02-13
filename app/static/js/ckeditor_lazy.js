// Lazy loader for CKEditor 4 (local self-hosted build).
// Loads CKEditor only when needed, while optionally preloading in idle time for better UX.

(function(){
  const CK_URL = window.__CKEDITOR_URL__ || "/static/vendor/ckeditor/ckeditor.js";
  let _loadingPromise = null;

  function loadScript(src){
    return new Promise((resolve, reject)=>{
      const s = document.createElement("script");
      s.src = src;
      s.async = true;
      s.onload = ()=>resolve();
      s.onerror = (e)=>reject(e);
      document.head.appendChild(s);
    });
  }

  async function ensureCkeditorLoaded(){
    if(window.CKEDITOR) return window.CKEDITOR;
    if(_loadingPromise) { await _loadingPromise; return window.CKEDITOR; }

    _loadingPromise = (async ()=>{
      try{
        // Preconnect hint (helps on some browsers even for same-origin if behind proxy/CDN)
        try{
          const link = document.createElement("link");
          link.rel = "preload";
          link.as = "script";
          link.href = CK_URL;
          document.head.appendChild(link);
        }catch(e){}
        await loadScript(CK_URL);
      } catch(e){
        // Fallback to CDN if local not present (e.g., offline build step failed)
        try{
          await loadScript("https://cdn.ckeditor.com/4.22.1/standard/ckeditor.js");
        }catch(_){}
      }
    })();

    await _loadingPromise;
    return window.CKEDITOR;
  }

  // Expose globally
  window.ensureCkeditorLoaded = ensureCkeditorLoaded;

  // Background preload (does not instantiate editors)
  function idlePreload(){
    ensureCkeditorLoaded().catch(()=>{});
  }
  if("requestIdleCallback" in window){
    window.requestIdleCallback(idlePreload, {timeout: 2000});
  }else{
    setTimeout(idlePreload, 1200);
  }
})();
