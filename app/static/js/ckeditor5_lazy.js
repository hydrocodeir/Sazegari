// Lazy loader for CKEditor 5 (Classic build).
// Loads editor scripts only when needed; keeps a local self-hosted copy if available.

(function(){
  const CK5_URL = window.__CKEDITOR5_URL__ || "/static/vendor/ckeditor5/ckeditor.js";
  const CK5_FA_URL = window.__CKEDITOR5_FA_URL__ || "/static/vendor/ckeditor5/translations/fa.js";
  const FALLBACK_VER = window.__CKEDITOR5_FALLBACK_VER__ || "44.3.0";

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

  function preloadScript(src){
    try{
      const link = document.createElement("link");
      link.rel = "preload";
      link.as = "script";
      link.href = src;
      document.head.appendChild(link);
    }catch(e){}
  }

  async function ensureCkeditor5Loaded(){
    if(window.ClassicEditor) return window.ClassicEditor;
    if(_loadingPromise){
      await _loadingPromise;
      return window.ClassicEditor;
    }

    _loadingPromise = (async ()=>{
      // Prefer local (self-hosted) build
      preloadScript(CK5_URL);
      try{
        await loadScript(CK5_URL);
      }catch(e){
        // Fallback to jsDelivr (npm build)
        await loadScript(`https://cdn.jsdelivr.net/npm/@ckeditor/ckeditor5-build-classic@${FALLBACK_VER}/build/ckeditor.js`);
      }

      // Load Persian UI translation if available (optional)
      if(!(window.CKEDITOR_TRANSLATIONS && window.CKEDITOR_TRANSLATIONS.fa)){
        preloadScript(CK5_FA_URL);
        try{
          await loadScript(CK5_FA_URL);
        }catch(e){
          try{
            await loadScript(`https://cdn.jsdelivr.net/npm/@ckeditor/ckeditor5-build-classic@${FALLBACK_VER}/build/translations/fa.js`);
          }catch(_){ /* ignore */ }
        }
      }
    })();

    await _loadingPromise;
    return window.ClassicEditor;
  }

  // Expose globally
  window.ensureCkeditor5Loaded = ensureCkeditor5Loaded;

  // Background preload (does not instantiate editors)
  function idlePreload(){
    ensureCkeditor5Loaded().catch(()=>{});
  }

  if("requestIdleCallback" in window){
    window.requestIdleCallback(idlePreload, {timeout: 2000});
  }else{
    setTimeout(idlePreload, 1200);
  }
})();
