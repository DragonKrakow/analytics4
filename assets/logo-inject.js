(function(){
  var LOGO='/assets/logo.svg';
  function swap(){
    document.querySelectorAll('.logo svg, .footer-logo svg, .hero-visual .logo-big, .logo-big').forEach(function(el){
      var img=document.createElement('img');
      img.src=LOGO;
      img.alt='Analytics 4';
      img.width=el.classList.contains('logo-big')?220:36;
      img.height=el.classList.contains('logo-big')?210:34;
      img.style.maxWidth='100%';
      if(el.classList.contains('logo-big')||(el.parentElement&&el.parentElement.classList.contains('hero-visual'))){
        img.style.filter='drop-shadow(0 20px 40px rgba(255,106,0,0.35))';
        img.style.width='220px';
        img.style.height='auto';
      }
      el.replaceWith(img);
    });
    document.querySelectorAll('.logo svg').forEach(function(el){
      var img=document.createElement('img');
      img.src=LOGO; img.alt='Analytics 4'; img.width=36; img.height=34;
      el.replaceWith(img);
    });
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',swap);
  else swap();
})();
