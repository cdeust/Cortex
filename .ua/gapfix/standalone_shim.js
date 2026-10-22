(function(){
  var files={};
  document.querySelectorAll('script[data-ua-file]').forEach(function(s){files[s.getAttribute('data-ua-file')]=s.textContent;});
  var impact=new URLSearchParams(location.search).get('impact');
  var realFetch=window.fetch.bind(window);
  window.fetch=function(input,init){
    var url=typeof input==='string'?input:(input&&input.url)||'';
    var name=url.split('?')[0].split('/').pop();
    if(name==='diff-overlay.json'){
      var key='diff-overlay-'+impact+'.json';
      if(impact&&files[key]) return Promise.resolve(new Response(files[key],{status:200,headers:{'Content-Type':'application/json'}}));
      return Promise.resolve(new Response('no impact view selected',{status:404}));
    }
    if(/\.json$/.test(name)){
      if(Object.prototype.hasOwnProperty.call(files,name)) return Promise.resolve(new Response(files[name],{status:200,headers:{'Content-Type':'application/json'}}));
      return Promise.resolve(new Response('not embedded',{status:404}));
    }
    if(location.protocol==='file:') return Promise.resolve(new Response('Source files are not embedded in this offline export.',{status:404}));
    return realFetch(input,init);
  };
  window.addEventListener('DOMContentLoaded',function(){
    var bar=document.createElement('div');
    bar.style.cssText='position:fixed;left:56px;bottom:12px;z-index:9999;background:#1a1a1a;color:#ddd;border:1px solid #c9a46a;border-radius:6px;padding:6px 8px;font:12px Inter,system-ui,sans-serif;max-width:calc(100vw - 80px)';
    bar.innerHTML='<label for="ua-impact" style="margin-right:6px">Impact view</label><select id="ua-impact" style="background:#111;color:#eee;border:1px solid #555;border-radius:4px;max-width:70vw"><option value="">none</option>__OPTIONS__</select>';
    document.body.appendChild(bar);
    var sel=document.getElementById('ua-impact'); sel.value=impact||'';
    sel.addEventListener('change',function(){ var q=new URLSearchParams(location.search); if(sel.value) q.set('impact',sel.value); else q.delete('impact'); location.search=q.toString(); });
  });
})();
